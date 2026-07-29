"""Kubeflow Pipelines (kfp) components wrapping the Cebule SDK task chain.

Each function below is one DAG node, wired together in pipelines.py and
compiled by kfp.compiler.Compiler() into a pipeline visible in the Kubeflow
Central Dashboard (graph, per-step logs, artifacts, caching).

Two kinds of component, per the design notes in docs/integrations/kubeflow.md:

  Transform  — pydantic-in, pydantic-out, no qpubench BackendAdapter involved
               (jw_map_component, mol_map_component, tn_qc_opt_component,
               qasm_gen_component)
  Execution  — drives a qpubench BenchmarkRunner against a registered
               BackendAdapter (execute_circuits_component,
               execute_static_hamiltonian_component)

TN_QC_OPT's n_iterations optimizer loop runs entirely inside
tn_qc_opt_component — it is one job, never exploded into one DAG node per
iteration. Likewise, the Shots x Qiskit_Opt_Level execution-option sweep
(see data/README.md) runs entirely inside the Execution components via
BenchmarkRunner.sweep() — it is one job, not one DAG node per (shots,
opt_level) pair. Only the `Mapper` axis (JW / mol_map / tn_qc_opt /
tn_qc_opt+mol_map — see data/README.md) changes which components exist;
everything else in the benchmark matrix (TN_Layers_Network,
TN_Layers_Circuit, Rotation_Type, Measurement_Method, Shots,
Qiskit_Opt_Level) is a parameter value swept via dsl.ParallelFor /
BenchmarkRunner.sweep() inside a *single* pipeline definition — see
pipelines.py and docs/integrations/kubeflow.md.

Vendor imports (mqsdk, qpubench) are deferred to inside each function body
so this module can be *parsed* by the kfp compiler in an environment that has
neither package installed — only the container image named in base_image
needs them at run time (mirrors the "import qforte inside the method, not at
module level" rule in docs/backends.md).

No `from __future__ import annotations` here (unlike the rest of this
repo): kfp's component decorator inspects live type objects at decoration
time and misparses stringified (PEP 563) annotations — confirmed by
actually compiling this module against kfp 2.16.1.
"""
from kfp import dsl
from kfp.dsl import Dataset, Input, Output

# Placeholder image tags — build and publish these yourself; see README.md
# for the (trivial) Dockerfile. Swap _QPUBENCH_SIM_IMAGE for a
# qpubench[qiskit]/qpubench[qrack] image + the matching adapter to move off
# the stub in execute_circuits_component.
_QPUBENCH_IMAGE = "ghcr.io/mqsdk/qpubench-slim:latest"
_QPUBENCH_SIM_IMAGE = "ghcr.io/mqsdk/qpubench-slim:latest"
# jw_map_component is the only component that needs a real quantum-chemistry
# stack (PySCF/OpenFermion) rather than just qpubench+mqsdk — it is the one
# Mapper category (`JW`) that never calls Cebule at all (see data/README.md).
_QPUBENCH_CHEM_IMAGE = "ghcr.io/mqsdk/qpubench-chem:latest"


@dsl.component(base_image=_QPUBENCH_IMAGE, packages_to_install=["qpubench", "mqsdk"])
def mol_map_component(
    geometry: list[float],
    symbols: list[str],
    basis: str,
    email_env: str,
    password_env: str,
    mol_map_result: Output[Dataset],
) -> None:
    """Cebule MOL_MAP: molecular geometry -> qubit Hamiltonian.

    email_env/password_env name the environment variables holding Cebule
    credentials — injected via kfp.kubernetes.use_secret_as_env in
    pipelines.py, never passed as plain pipeline parameters (those get
    recorded in the run's parameter history in the dashboard).
    """
    import os

    import mqsdk

    from qpubench.schemas import MolecularGeometry, MolMapInput, MolMapResult

    session = mqsdk.Cebule(os.environ[email_env], os.environ[password_env])
    inp = MolMapInput(molecule=MolecularGeometry(geometry=geometry, symbols=symbols, basis=basis))
    # NOTE: confirm mqsdk.TaskType's import path against your installed
    # mqsdk version — docs/integrations/cebule.md shows the create_task
    # call shape but not TaskType's own import.
    task = session.cebule.create_task("qpubench-mol-map", mqsdk.TaskType.MOL_MAP, inp.model_dump())
    result = MolMapResult.model_validate(task.result)

    with open(mol_map_result.path, "w") as f:
        f.write(result.model_dump_json())


@dsl.component(base_image=_QPUBENCH_CHEM_IMAGE, packages_to_install=["qpubench[openfermion]"])
def jw_map_component(
    geometry: list[float],
    symbols: list[str],
    basis: str,
    charge: int,
    multiplicity: int,
    active_electrons: int,
    active_orbitals: int,
    jw_map_result: Output[Dataset],
) -> None:
    """Plain Jordan-Wigner mapping: molecular geometry -> qubit Hamiltonian.

    The `JW` Mapper category (data/README.md) never calls Cebule at all —
    this is the one component in the whole integration with no MQS
    credentials involved, computed entirely locally via
    `qpubench.hamiltonian_sources.ab_initio.build_qubit_hamiltonian`
    (real PySCF HF + OpenFermion Jordan-Wigner, not a stub).

    active_electrons/active_orbitals: pass 0/0 for "full space, no
    active-space reduction" (build_qubit_hamiltonian treats that the same
    as None — see its docstring); anything else requests a frozen-core
    active-space reduction. kfp component parameters can't be `int | None`
    cleanly, hence the 0-means-unset convention here.

    Output JSON keys deliberately mirror MolMapResult's own field names
    (`num_qubits`, `hf_state`) so downstream components
    (tn_qc_opt_component, qasm_gen_component,
    execute_static_hamiltonian_component) can read either a mol_map_result
    or a jw_map_result the same generic way — see their `mapper_result`
    docstrings.
    """
    import json

    from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian

    geom = [
        (symbols[i], (geometry[3 * i], geometry[3 * i + 1], geometry[3 * i + 2]))
        for i in range(len(symbols))
    ]
    observable, record = build_qubit_hamiltonian(
        geom,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
        active_electrons=active_electrons or None,
        active_orbitals=active_orbitals or None,
    )

    # Standard JW/occupation-number Hartree-Fock reference: the
    # lowest-index `num_electrons` spin-orbitals occupied, the rest empty
    # (same convention OpenFermion's own MolecularData/HF machinery uses,
    # and what build_qubit_hamiltonian's `occupied_indices` maps onto) —
    # not a fabricated ordering.
    num_electrons = record.num_electrons or 0
    hf_state = [1] * num_electrons + [0] * (record.num_qubits - num_electrons)

    with open(jw_map_result.path, "w") as f:
        json.dump(
            {
                "num_qubits": record.num_qubits,
                "hf_state": hf_state,
                "hf_energy": record.hf_energy,
                "observable": observable.model_dump(mode="json"),
            },
            f,
        )


@dsl.component(base_image=_QPUBENCH_IMAGE, packages_to_install=["qpubench", "mqsdk"])
def tn_qc_opt_component(
    mapper_result: Input[Dataset],
    h_coeff_values: list[float],
    h_operators: list[str],
    n_iterations: int,
    n_layers_network: int,
    n_layers_circuit: int,
    three_para_tn: bool,
    opt_method: str,
    measurement_method: str,
    optimization_mode: str,
    backend: str,
    email_env: str,
    password_env: str,
    tn_qc_opt_result: Output[Dataset],
) -> None:
    """Cebule TN_QC_OPT: hybrid tensor-network + circuit VQE, run as a
    documented follow-up to MOL_MAP or a plain JW mapping (see
    MolMapResult.to_sparse_pauli_observable in schemas/mirrors/mqsdk_cebule.py).

    The entire n_iterations optimizer loop executes inside this one
    component/pod — it is not decomposed into per-iteration DAG nodes.

    mapper_result is whichever upstream mapping produced the Hamiltonian
    this call optimizes (mol_map_component's MolMapResult for the
    `tn_qc_opt+mol_map` Mapper category, or jw_map_component's JSON for the
    plain `tn_qc_opt` category) — read here only for DAG lineage/caching,
    not parsed into a specific schema, since h_coeff_values/h_operators
    are supplied directly by the caller either way (qpubench does not ship
    a dense-matrix -> Pauli-term decomposition utility, so neither
    upstream result can be auto-converted into TN_QC_OPT's input shape).

    n_layers_network/n_layers_circuit/three_para_tn/measurement_method
    sweep over data/README.md's TN_Layers_Network / TN_Layers_Circuit /
    Rotation_Type / Measurement_Method columns — resolved by
    dsl.ParallelFor in pipelines.py, not by separate pipeline
    definitions, since none of these change which components run.
    """
    import os

    import mqsdk

    from qpubench.schemas import TNQCOptInput, TNQCOptResult

    with open(mapper_result.path) as f:
        f.read()  # validated to exist for DAG lineage; not otherwise used here

    session = mqsdk.Cebule(os.environ[email_env], os.environ[password_env])
    inp = TNQCOptInput(
        h_coeff_values=h_coeff_values,
        h_operators=list(h_operators),
        n_iterations=n_iterations,
        n_layers_network=n_layers_network,
        n_layers_circuit=n_layers_circuit,
        three_para_tn=three_para_tn,
        opt_method=opt_method,
        measurement_method=measurement_method,
        optimization_mode=optimization_mode,
        backend=backend,
    )
    task = session.cebule.create_task(
        "qpubench-tn-qc-opt", mqsdk.TaskType.TN_QC_OPT, inp.model_dump()
    )
    result = TNQCOptResult.model_validate(task.result)

    with open(tn_qc_opt_result.path, "w") as f:
        f.write(result.model_dump_json())


@dsl.component(base_image=_QPUBENCH_IMAGE, packages_to_install=["qpubench", "mqsdk"])
def qasm_gen_component(
    mapper_result: Input[Dataset],
    tn_qc_opt_result: Input[Dataset],
    include_state_circuit: bool,
    email_env: str,
    password_env: str,
    qasm_gen_result: Output[Dataset],
) -> None:
    """Cebule QASM_GEN: generate hardware-verification measurement circuits
    for the operator TN_QC_OPT converged on.

    Runs once per (tn_layers_network, tn_layers_circuit, three_para_tn,
    measurement_method) combination from the enclosing dsl.ParallelFor in
    pipelines.py, regardless of which measurement_method that combination
    uses — execute_circuits_component decides whether to consume this
    result's `circuit_files` (Measurement_Method=qasm_gen_grouped) or just
    its `state_circuit` (Measurement_Method=pauli, Estimator path against
    tn_qc_opt_result's own sparse Pauli terms directly). That split is a
    plain Python branch inside one Execution component, not a DAG
    conditional, since it doesn't change which components run.
    """
    import json
    import os

    import mqsdk

    from qpubench.schemas import QASMGenInput, QASMGenResult, TNQCOptResult

    with open(mapper_result.path) as f:
        mapper_data = json.load(f)
    num_qubits = mapper_data.get("num_qubits")
    with open(tn_qc_opt_result.path) as f:
        tn_qc_opt = TNQCOptResult.model_validate_json(f.read())

    if num_qubits is None:
        num_qubits = len(mapper_data.get("hf_state", []))
    observable = tn_qc_opt.to_sparse_pauli_observable(num_qubits=num_qubits)

    # Sparse Pauli terms -> the dense Hermitian matrix QASMGenInput.operator
    # expects. Exponential by construction (the operator matrix is
    # 2**n x 2**n), guarded inside to_dense_matrix() via max_qubits.
    dense_operator: list[list[float]] = observable.to_dense_matrix()

    session = mqsdk.Cebule(os.environ[email_env], os.environ[password_env])
    inp = QASMGenInput(operator=dense_operator, include_state_circuit=include_state_circuit)
    task = session.cebule.create_task(
        "qpubench-qasm-gen", mqsdk.TaskType.QASM_GEN, inp.model_dump()
    )
    result = QASMGenResult.model_validate(task.result)

    with open(qasm_gen_result.path, "w") as f:
        f.write(result.model_dump_json())


@dsl.component(base_image=_QPUBENCH_SIM_IMAGE, packages_to_install=["qpubench"])
def execute_circuits_component(
    mapper_result: Input[Dataset],
    qasm_gen_result: Input[Dataset],
    tn_qc_opt_result: Input[Dataset],
    measurement_method: str,
    shots_values: list[int],
    optimization_levels: list[int],
    records: Output[Dataset],
) -> None:
    """Execution-kind component: runs the TN_QC_OPT-converged circuit(s)
    through a registered qpubench BackendAdapter via BenchmarkRunner.

    measurement_method ("pauli" | "qasm_gen_grouped") picks which of
    qasm_gen_result's outputs to execute:
      - "qasm_gen_grouped": qasm_gen_result.circuit_files, one CircuitSpec
        per Pauli grouping (Sampler path — counts, no .observables).
      - "pauli": a single CircuitSpec built from qasm_gen_result's
        state_circuit with tn_qc_opt_result's own sparse Pauli terms
        attached as .observables (Estimator path — every registered
        BackendAdapter already branches on `if circuit.observables:`,
        see e.g. backends/aer_adapter.py).

    shots_values x optimization_levels (data/README.md's Shots /
    Qiskit_Opt_Level columns) is resolved here via
    BenchmarkRunner.sweep()'s cartesian product — one component/job, not
    one DAG node per (shots, opt_level) pair, matching the same
    "n_iterations stays inside one component" principle TN_QC_OPT already
    follows.

    Uses StubGateAdapter as the always-available default so this pipeline
    compiles and runs without any quantum SDK installed. Swap in
    AerAdapter / QrackAdapter / IBMAdapter (and the matching base_image,
    e.g. a qpubench[qiskit] image with a GPU/CPU resource request set on
    this task in pipelines.py) for a real run — this is the one node in the
    pipeline whose resource profile changes per backend; nothing else in
    the DAG needs to change.
    """
    import json

    from qpubench import BenchmarkRunner, ExecutionOptions, NDJSONStore, StubGateAdapter
    from qpubench.schemas import CircuitFormat, CircuitSpec, QASMGenResult, TNQCOptResult

    with open(mapper_result.path) as f:
        mapper_data = json.load(f)
    num_qubits = mapper_data.get("num_qubits") or len(mapper_data.get("hf_state", []))
    with open(qasm_gen_result.path) as f:
        qasm_gen = QASMGenResult.model_validate_json(f.read())
    with open(tn_qc_opt_result.path) as f:
        tn_qc_opt = TNQCOptResult.model_validate_json(f.read())

    if measurement_method == "qasm_gen_grouped":
        circuits = qasm_gen.to_circuit_specs(num_qubits=num_qubits)
    else:
        observable = tn_qc_opt.to_sparse_pauli_observable(num_qubits=num_qubits)
        circuits = [
            CircuitSpec(
                num_qubits=num_qubits,
                format=CircuitFormat.QASM2,
                serialized=qasm_gen.state_circuit,
                observables=[observable],
            )
        ]

    options_list = [
        ExecutionOptions(shots=shots, optimization_level=opt_level)
        for shots in shots_values
        for opt_level in optimization_levels
    ]

    runner = BenchmarkRunner(store=NDJSONStore(records.path))
    runner.register(StubGateAdapter(), name="stub")
    runner.sweep(
        circuits,
        ["stub"],
        options_list,
        tags=["cebule", "tn_qc_opt", measurement_method],
    )


@dsl.component(base_image=_QPUBENCH_SIM_IMAGE, packages_to_install=["qpubench", "mqsdk"])
def execute_static_hamiltonian_component(
    mapper_result: Input[Dataset],
    hamiltonian_kind: str,
    measurement_method: str,
    shots_values: list[int],
    optimization_levels: list[int],
    email_env: str,
    password_env: str,
    records: Output[Dataset],
) -> None:
    """Execution-kind component for the two Mapper categories that carry no
    VQE ansatz at all — plain `JW` and `mol_map`-only (see data/README.md,
    where `Ansatz` is blank for both). There is no optimized state to
    measure, so the "circuit" here is a fixed Hartree-Fock reference-state
    preparation (X gates on the occupied qubits of mapper_result's own
    `hf_state`) — not a fabricated ansatz, the standard HF baseline.

    hamiltonian_kind says which representation mapper_result carries:
      - "dense": mol_map_component's MolMapResult.mapped_hamiltonian — a
        real 2-D Hermitian matrix, usable directly as
        QASMGenInput.operator.
      - "sparse": jw_map_component's SparsePauliObservable — usable
        directly as CircuitSpec.observables for the Estimator path.

    measurement_method picks the execution path; all four
    (hamiltonian_kind, measurement_method) combinations run:
      - dense  + qasm_gen_grouped -> QASM_GEN called directly with the
        dense operator, no conversion needed.
      - sparse + pauli            -> Estimator path, no conversion needed.
      - dense  + pauli            -> SparsePauliObservable.from_dense_matrix()
        (Pauli decomposition, coeff_P = Tr(P@H)/2**n) feeds the Estimator.
      - sparse + qasm_gen_grouped -> SparsePauliObservable.to_dense_matrix()
        (Pauli tensor expansion) feeds QASM_GEN's dense operator.
    Both conversions are exponential by nature — matched to this
    benchmark's small mol_map/JW qubit counts and size-guarded inside the
    schema methods via max_qubits.

    shots_values x optimization_levels is resolved here via
    BenchmarkRunner.sweep(), same as execute_circuits_component.
    """
    import json

    from qpubench import BenchmarkRunner, ExecutionOptions, NDJSONStore, StubGateAdapter
    from qpubench.schemas import CircuitFormat, CircuitSpec, SparsePauliObservable

    with open(mapper_result.path) as f:
        mapper_data = json.load(f)
    num_qubits = mapper_data["num_qubits"]
    hf_state = mapper_data["hf_state"]

    hf_prep_qasm = "OPENQASM 2.0;\ninclude \"qelib1.inc\";\n" + f"qreg q[{num_qubits}];\n"
    hf_prep_qasm += "".join(f"x q[{i}];\n" for i, bit in enumerate(hf_state) if bit)

    if measurement_method == "pauli":
        if hamiltonian_kind == "sparse":
            observable = SparsePauliObservable.model_validate(mapper_data["observable"])
        else:  # "dense" — mol_map's mapped_hamiltonian, Pauli-decomposed
            observable = SparsePauliObservable.from_dense_matrix(
                mapper_data["mapped_hamiltonian"], num_qubits
            )
        circuits = [
            CircuitSpec(
                num_qubits=num_qubits,
                format=CircuitFormat.QASM2,
                serialized=hf_prep_qasm,
                observables=[observable],
            )
        ]
    else:  # "qasm_gen_grouped"
        if hamiltonian_kind == "dense":
            dense_operator = mapper_data["mapped_hamiltonian"]
        else:  # "sparse" — JW's Pauli terms, tensor-expanded
            dense_operator = SparsePauliObservable.model_validate(
                mapper_data["observable"]
            ).to_dense_matrix()
        import os

        import mqsdk

        from qpubench.schemas import QASMGenInput, QASMGenResult

        # One-hot statevector for the fixed HF computational basis state —
        # real and exact for this small, already-exponential (mol_map's own
        # mapped_hamiltonian is a dense 2**n x 2**n matrix) representation,
        # not an approximation.
        index = int("".join(str(b) for b in hf_state), 2) if hf_state else 0
        state_vector = [0.0] * (2 ** num_qubits)
        state_vector[index] = 1.0

        session = mqsdk.Cebule(os.environ[email_env], os.environ[password_env])
        inp = QASMGenInput(
            operator=dense_operator,
            state_vector=state_vector,
            include_state_circuit=False,
        )
        task = session.cebule.create_task(
            "qpubench-qasm-gen-static", mqsdk.TaskType.QASM_GEN, inp.model_dump()
        )
        result = QASMGenResult.model_validate(task.result)
        circuits = result.to_circuit_specs(num_qubits=num_qubits)

    options_list = [
        ExecutionOptions(shots=shots, optimization_level=opt_level)
        for shots in shots_values
        for opt_level in optimization_levels
    ]

    runner = BenchmarkRunner(store=NDJSONStore(records.path))
    runner.register(StubGateAdapter(), name="stub")
    runner.sweep(
        circuits,
        ["stub"],
        options_list,
        tags=["cebule", hamiltonian_kind, measurement_method],
    )
