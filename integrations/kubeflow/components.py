"""Kubeflow Pipelines (kfp) components wrapping the Cebule SDK task chain.

Each function below is one DAG node, wired together in pipelines.py and
compiled by kfp.compiler.Compiler() into a pipeline visible in the Kubeflow
Central Dashboard (graph, per-step logs, artifacts, caching).

Two kinds of component, per the design notes in docs/integrations/kubeflow.md:

  Transform  — pydantic-in, pydantic-out, no qpubench BackendAdapter involved
               (mol_map_component, tn_qc_opt_component, qasm_gen_component)
  Execution  — drives a qpubench BenchmarkRunner against a registered
               BackendAdapter (execute_circuits_component)

TN_QC_OPT's n_iterations optimizer loop runs entirely inside
tn_qc_opt_component — it is one job, never exploded into one DAG node per
iteration.

Vendor imports (mqsdk, qpubench) are deferred to inside each function body
so this module can be *parsed* by the kfp compiler in an environment that has
neither package installed — only the container image named in base_image
needs them at run time (mirrors the "import qforte inside the method, not at
module level" rule in INTEGRATION_GUIDE.md).

No `from __future__ import annotations` here (unlike the rest of this repo):
kfp's component decorator inspects live type objects at decoration time and
misparses stringified (PEP 563) annotations — confirmed by actually
compiling this module against kfp 2.16.1.
"""
from kfp import dsl
from kfp.dsl import Dataset, Input, Output

# Placeholder image tags — build and publish these yourself; see README.md
# for the (trivial) Dockerfile. Swap _QPUBENCH_SIM_IMAGE for a
# qpubench[qiskit]/qpubench[qrack] image + the matching adapter to move off
# the stub in execute_circuits_component.
_QPUBENCH_IMAGE = "ghcr.io/mqsdk/qpubench-slim:latest"
_QPUBENCH_SIM_IMAGE = "ghcr.io/mqsdk/qpubench-slim:latest"


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


@dsl.component(base_image=_QPUBENCH_IMAGE, packages_to_install=["qpubench", "mqsdk"])
def tn_qc_opt_component(
    mol_map_result: Input[Dataset],
    h_coeff_values: list[float],
    h_operators: list[str],
    n_iterations: int,
    n_layers_network: int,
    n_layers_circuit: int,
    opt_method: str,
    backend: str,
    email_env: str,
    password_env: str,
    tn_qc_opt_result: Output[Dataset],
) -> None:
    """Cebule TN_QC_OPT: hybrid tensor-network + circuit VQE, run as a
    documented follow-up to MOL_MAP (see MolMapResult.to_sparse_pauli_observable
    in schemas/mqsdk_cebule.py).

    The entire n_iterations optimizer loop executes inside this one
    component/pod — it is not decomposed into per-iteration DAG nodes.

    h_coeff_values/h_operators are the qubit-operator decomposition of
    MolMapResult.mapped_hamiltonian. qpubench does not ship a dense-matrix
    -> Pauli-term decomposition utility, so the caller supplies this
    directly (from whatever produced the geometry, or a future qpubench
    helper) rather than this component inventing one.
    """
    import os

    import mqsdk

    from qpubench.schemas import MolMapResult, TNQCOptInput, TNQCOptResult

    with open(mol_map_result.path) as f:
        MolMapResult.model_validate_json(f.read())  # validated, not otherwise used here

    session = mqsdk.Cebule(os.environ[email_env], os.environ[password_env])
    inp = TNQCOptInput(
        h_coeff_values=h_coeff_values,
        h_operators=list(h_operators),
        n_iterations=n_iterations,
        n_layers_network=n_layers_network,
        n_layers_circuit=n_layers_circuit,
        opt_method=opt_method,
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
    mol_map_result: Input[Dataset],
    tn_qc_opt_result: Input[Dataset],
    include_state_circuit: bool,
    email_env: str,
    password_env: str,
    qasm_gen_result: Output[Dataset],
) -> None:
    """Cebule QASM_GEN: generate hardware-verification measurement circuits
    for the operator TN_QC_OPT converged on.
    """
    import os

    import mqsdk

    from qpubench.schemas import MolMapResult, QASMGenInput, QASMGenResult, TNQCOptResult

    with open(mol_map_result.path) as f:
        mol_map = MolMapResult.model_validate_json(f.read())
    with open(tn_qc_opt_result.path) as f:
        tn_qc_opt = TNQCOptResult.model_validate_json(f.read())

    num_qubits = mol_map.num_qubits or len(mol_map.hf_state)
    tn_qc_opt.to_sparse_pauli_observable(num_qubits=num_qubits)  # validated, not otherwise used here

    # TODO: convert the sparse Pauli-term observable above into the dense
    # Hermitian matrix QASMGenInput.operator expects. qpubench has no
    # Pauli-term -> dense-matrix utility (schemas/observable.py only
    # implements the reverse direction via from_cebule_operators) — wire in
    # your own conversion or a future qpubench helper here.
    dense_operator: list[list[float]] = []  # placeholder — see TODO above

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
    mol_map_result: Input[Dataset],
    qasm_gen_result: Input[Dataset],
    shots: int,
    records: Output[Dataset],
) -> None:
    """Execution-kind component: runs each QASM_GEN circuit through a
    registered qpubench BackendAdapter via BenchmarkRunner.

    Uses StubGateAdapter as the always-available default so this pipeline
    compiles and runs without any quantum SDK installed. Swap in
    AerAdapter / QrackAdapter / IBMAdapter (and the matching base_image,
    e.g. a qpubench[qiskit] image with a GPU/CPU resource request set on
    this task in pipelines.py) for a real run — this is the one node in the
    pipeline whose resource profile changes per backend; nothing else in
    the DAG needs to change.
    """
    from qpubench import BenchmarkRunner, ExecutionOptions, NDJSONStore, StubGateAdapter
    from qpubench.schemas import MolMapResult, QASMGenResult

    with open(mol_map_result.path) as f:
        mol_map = MolMapResult.model_validate_json(f.read())
    with open(qasm_gen_result.path) as f:
        qasm_gen = QASMGenResult.model_validate_json(f.read())

    num_qubits = mol_map.num_qubits or len(mol_map.hf_state)
    circuits = qasm_gen.to_circuit_specs(num_qubits=num_qubits)

    runner = BenchmarkRunner(store=NDJSONStore(records.path))
    runner.register(StubGateAdapter(), name="stub")
    for circuit in circuits:
        runner.run(circuit, "stub", ExecutionOptions(shots=shots), tags=["cebule", "qasm_gen"])
