"""Four kfp DAGs — one per (`Mapper`, `Method`) pair in
data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv (see data/benchmarks/ibm_tn-vqe_qesem/README.md's "Mapper and method
are separate columns" section):

    cebule_molecular_vqe_pipeline  -- mol_map, TN-VQE
    cebule_tn_vqe_pipeline         -- JW, TN-VQE (no mol_map)
    mol_map_measurement_pipeline   -- mol_map, VQE (Hartree-Fock reference)
    jw_baseline_pipeline           -- JW, VQE (no Cebule call at all)

That pair is the *only* axis that gets its own pipeline/DAG here: it's the one
dimension in the benchmark matrix that changes which components run (a
component change, per docs/integrations/kubeflow.md's Transform/Execution
taxonomy). Every other benchmark dimension --
TN_Layers_Network/TN_Layers_Circuit/TN_Ansatz/Measurement_Method/Shots/
Qiskit_Opt_Level -- is a parameter value, resolved *inside* one pipeline via
dsl.ParallelFor (for the Cebule-task-level knobs) and
BenchmarkRunner.sweep() inside the Execution components (for the
Shots x Qiskit_Opt_Level execution-option knobs, see components.py). A run
of any one of these four pipelines shows as one graph in the dashboard, no
matter how many sweep points it fans out to.

Compile once, submit many times:

    from kfp import compiler
    from pipelines import cebule_molecular_vqe_pipeline
    compiler.Compiler().compile(cebule_molecular_vqe_pipeline, "cebule_pipeline.yaml")

Then either upload cebule_pipeline.yaml through the Kubeflow Central
Dashboard's Pipelines UI, or submit programmatically:

    import kfp
    client = kfp.Client(host="https://<your-kubeflow-endpoint>")
    client.create_run_from_pipeline_package(
        "cebule_pipeline.yaml",
        arguments={
            "geometry": [0.0, 0.0, 0.0, 0.0, 0.0, 0.7414],
            "symbols": ["H", "H"],
            "tn_layers_network_values": [0, 1, 2, 3],
            "tn_layers_circuit_values": [1, 2, 3, 4],
            "measurement_methods": ["pauli", "grouped"],
        },
    )

Either path shows the run — graph, per-step logs, artifacts, caching status —
in the dashboard immediately, with every sweep point as one fanned-out branch
of the same graph.

Nothing here calls TrainerClient/OptimizerClient: every step is a Transform
or an Execution node (see components.py docstrings). Reach for the
Kubeflow Trainer/Optimizer SDK only *inside* a component body that
specifically needs multi-node distributed launch or Katib hyperparameter
search — see docs/integrations/kubeflow.md for when that trade-off is worth
it. Keeping that vocabulary out of this file is deliberate: nothing here
trains a model, so nothing here should look like it does.

No `from __future__ import annotations` here (unlike the rest of this
repo) — kfp's decorators need live type objects at decoration time; see the
same note in components.py.
"""
from typing import Any

from kfp import dsl, kubernetes

from .components import (
    execute_circuits_component,
    execute_static_hamiltonian_component,
    jw_map_component,
    mol_map_component,
    qasm_gen_component,
    tn_qc_opt_component,
)

# kubectl create secret generic cebule-credentials \
#   --from-literal=email=... --from-literal=password=...
_CEBULE_SECRET = "cebule-credentials"
_EMAIL_ENV = "CEBULE_EMAIL"
_PASSWORD_ENV = "CEBULE_PASSWORD"


def _with_cebule_credentials(task: Any) -> Any:
    """Inject Cebule credentials as env vars from a Kubernetes Secret.

    Never pass credentials as plain pipeline parameters — those are stored
    in the run's recorded parameter history in the dashboard. Requires the
    kfp-kubernetes package in addition to kfp.
    """
    return kubernetes.use_secret_as_env(
        task,
        secret_name=_CEBULE_SECRET,
        secret_key_to_env={"email": _EMAIL_ENV, "password": _PASSWORD_ENV},
    )


@dsl.pipeline(
    name="cebule-molecular-vqe",
    description=(
        "MOL_MAP -> TN_QC_OPT -> QASM_GEN -> circuit execution, following the "
        "Cebule SDK task chain documented in schemas/mirrors/mqsdk_cebule.py. "
        "Mapper `mol_map` + Method `TN-VQE` in data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv."
    ),
)
def cebule_molecular_vqe_pipeline(
    geometry: list[float],
    symbols: list[str],
    basis: str = "sto3g",
    h_coeff_values: list[float] = [],  # noqa: B006 — kfp pipeline params, not a mutable default trap
    h_operators: list[str] = [],  # noqa: B006
    n_iterations: int = 100,
    # TN_Layers_Network / TN_Layers_Circuit / TN_Ansatz / Measurement_Method
    # sweep points (data/benchmarks/ibm_tn-vqe_qesem/README.md) — resolved by dsl.ParallelFor below, all
    # inside this one pipeline/DAG, not one pipeline per combination.
    tn_layers_network_values: list[int] = [3],
    tn_layers_circuit_values: list[int] = [3],
    # TNAnsatz values as plain strings (kfp params must be primitives):
    # rotation_1param | rotation_3param | givens | number_preserving.
    # A list[bool] cannot express a four-valued sweep, which is why the
    # older three_para_tn spelling is gone.
    tn_ansatz_values: list[str] = ["givens"],
    measurement_methods: list[str] = ["pauli"],  # "pauli" | "grouped"
    opt_method: str = "COBYLA",   # the task's own default (parsers.py, checked 2026-08-08)
    optimization_mode: str = "both",   # the task's own default (parsers.py, checked 2026-08-08)
    # The task's own default. get_backend dispatches on the string: the
    # four named simulators, "fake*" and "ibm*" route to Qiskit, and
    # everything else falls through to qml.device -- so "aer_simulator"
    # is the local Qiskit option and "ibm*" the hardware one.
    tn_backend: str = "default.qubit",
    # Needed downstream for the "pauli" measurement_method branch
    # (execute_circuits_component reads qasm_gen_result.state_circuit) —
    # always requested regardless of Cebule's own raw default.
    include_state_circuit: bool = True,
    # Shots / Qiskit_Opt_Level sweep points — resolved inside
    # execute_circuits_component via BenchmarkRunner.sweep(), not by
    # dsl.ParallelFor, since these are execution options, not different
    # Cebule task calls (see components.py).
    shots_values: list[int] = [1024],
    optimization_levels: list[int] = [1],
) -> None:
    mol_map_task = _with_cebule_credentials(
        mol_map_component(
            geometry=geometry,
            symbols=symbols,
            basis=basis,
            email_env=_EMAIL_ENV,
            password_env=_PASSWORD_ENV,
        )
    )

    with dsl.ParallelFor(items=tn_layers_network_values) as n_layers_network:
        with dsl.ParallelFor(items=tn_layers_circuit_values) as n_layers_circuit:
            with dsl.ParallelFor(items=tn_ansatz_values) as tn_ansatz:
                with dsl.ParallelFor(items=measurement_methods) as measurement_method:
                    tn_qc_opt_task = _with_cebule_credentials(
                        tn_qc_opt_component(
                            mapper_result=mol_map_task.outputs["mol_map_result"],
                            h_coeff_values=h_coeff_values,
                            h_operators=h_operators,
                            n_iterations=n_iterations,
                            n_layers_network=n_layers_network,
                            n_layers_circuit=n_layers_circuit,
                            tn_ansatz=tn_ansatz,
                            opt_method=opt_method,
                            measurement_method=measurement_method,
                            optimization_mode=optimization_mode,
                            backend=tn_backend,
                            email_env=_EMAIL_ENV,
                            password_env=_PASSWORD_ENV,
                        )
                    )
                    # TN_QC_OPT's n_iterations optimizer loop is the expensive
                    # step here — request more CPU than the default. Still
                    # one job per sweep point, not one per iteration.
                    tn_qc_opt_task.set_cpu_request("2").set_cpu_limit("4").set_memory_limit("4Gi")

                    qasm_gen_task = _with_cebule_credentials(
                        qasm_gen_component(
                            mapper_result=mol_map_task.outputs["mol_map_result"],
                            tn_qc_opt_result=tn_qc_opt_task.outputs["tn_qc_opt_result"],
                            include_state_circuit=include_state_circuit,
                            email_env=_EMAIL_ENV,
                            password_env=_PASSWORD_ENV,
                        )
                    )

                    # No credentials needed past this point — execution runs
                    # against a qpubench-registered BackendAdapter (stub by
                    # default), not Cebule's API.
                    execute_circuits_component(
                        mapper_result=mol_map_task.outputs["mol_map_result"],
                        qasm_gen_result=qasm_gen_task.outputs["qasm_gen_result"],
                        tn_qc_opt_result=tn_qc_opt_task.outputs["tn_qc_opt_result"],
                        measurement_method=measurement_method,
                        shots_values=shots_values,
                        optimization_levels=optimization_levels,
                    )


@dsl.pipeline(
    name="cebule-tn-vqe",
    description=(
        "JW mapping -> TN_QC_OPT -> QASM_GEN -> circuit execution — TN-VQE "
        "applied to the plain JW-mapped Hamiltonian, no MOL_MAP. Mapper "
        "category `tn_qc_opt` in data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv."
    ),
)
def cebule_tn_vqe_pipeline(
    geometry: list[float],
    symbols: list[str],
    basis: str = "sto-3g",
    charge: int = 0,
    multiplicity: int = 1,
    active_electrons: int = 0,   # 0 = full space, no active-space reduction
    active_orbitals: int = 0,    # 0 = full space, no active-space reduction
    h_coeff_values: list[float] = [],  # noqa: B006
    h_operators: list[str] = [],  # noqa: B006
    n_iterations: int = 100,
    tn_layers_network_values: list[int] = [3],
    tn_layers_circuit_values: list[int] = [3],
    tn_ansatz_values: list[str] = ["givens"],   # see the mol_map pipeline above
    measurement_methods: list[str] = ["pauli"],
    opt_method: str = "COBYLA",
    optimization_mode: str = "both",
    tn_backend: str = "default.qubit",
    include_state_circuit: bool = True,
    shots_values: list[int] = [1024],
    optimization_levels: list[int] = [1],
) -> None:
    # Local computation, no Cebule credentials — the plain JW mapping never
    # touches the Cebule API (see jw_map_component's docstring).
    jw_map_task = jw_map_component(
        geometry=geometry,
        symbols=symbols,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
        active_electrons=active_electrons,
        active_orbitals=active_orbitals,
    )

    with dsl.ParallelFor(items=tn_layers_network_values) as n_layers_network:
        with dsl.ParallelFor(items=tn_layers_circuit_values) as n_layers_circuit:
            with dsl.ParallelFor(items=tn_ansatz_values) as tn_ansatz:
                with dsl.ParallelFor(items=measurement_methods) as measurement_method:
                    tn_qc_opt_task = _with_cebule_credentials(
                        tn_qc_opt_component(
                            mapper_result=jw_map_task.outputs["jw_map_result"],
                            h_coeff_values=h_coeff_values,
                            h_operators=h_operators,
                            n_iterations=n_iterations,
                            n_layers_network=n_layers_network,
                            n_layers_circuit=n_layers_circuit,
                            tn_ansatz=tn_ansatz,
                            opt_method=opt_method,
                            measurement_method=measurement_method,
                            optimization_mode=optimization_mode,
                            backend=tn_backend,
                            email_env=_EMAIL_ENV,
                            password_env=_PASSWORD_ENV,
                        )
                    )
                    tn_qc_opt_task.set_cpu_request("2").set_cpu_limit("4").set_memory_limit("4Gi")

                    qasm_gen_task = _with_cebule_credentials(
                        qasm_gen_component(
                            mapper_result=jw_map_task.outputs["jw_map_result"],
                            tn_qc_opt_result=tn_qc_opt_task.outputs["tn_qc_opt_result"],
                            include_state_circuit=include_state_circuit,
                            email_env=_EMAIL_ENV,
                            password_env=_PASSWORD_ENV,
                        )
                    )

                    execute_circuits_component(
                        mapper_result=jw_map_task.outputs["jw_map_result"],
                        qasm_gen_result=qasm_gen_task.outputs["qasm_gen_result"],
                        tn_qc_opt_result=tn_qc_opt_task.outputs["tn_qc_opt_result"],
                        measurement_method=measurement_method,
                        shots_values=shots_values,
                        optimization_levels=optimization_levels,
                    )


@dsl.pipeline(
    name="mol-map-measurement",
    description=(
        "MOL_MAP -> measurement of the fixed Hartree-Fock reference state "
        "(no VQE ansatz — Ansatz is blank for this Mapper category in "
        "data/benchmarks/ibm_tn-vqe_qesem/README.md). Mapper category `mol_map` in "
        "data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv."
    ),
)
def mol_map_measurement_pipeline(
    geometry: list[float],
    symbols: list[str],
    basis: str = "sto3g",
    measurement_methods: list[str] = ["grouped"],
    shots_values: list[int] = [1024],
    optimization_levels: list[int] = [1],
) -> None:
    mol_map_task = _with_cebule_credentials(
        mol_map_component(
            geometry=geometry,
            symbols=symbols,
            basis=basis,
            email_env=_EMAIL_ENV,
            password_env=_PASSWORD_ENV,
        )
    )

    with dsl.ParallelFor(items=measurement_methods) as measurement_method:
        _with_cebule_credentials(
            execute_static_hamiltonian_component(
                mapper_result=mol_map_task.outputs["mol_map_result"],
                hamiltonian_kind="dense",
                measurement_method=measurement_method,
                shots_values=shots_values,
                optimization_levels=optimization_levels,
                email_env=_EMAIL_ENV,
                password_env=_PASSWORD_ENV,
            )
        )


@dsl.pipeline(
    name="jw-baseline",
    description=(
        "Plain Jordan-Wigner mapping -> measurement of the fixed "
        "Hartree-Fock reference state. No Cebule call at all (no VQE "
        "ansatz — Ansatz is blank for this Mapper category in "
        "data/benchmarks/ibm_tn-vqe_qesem/README.md). Mapper category `JW` in "
        "data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv."
    ),
)
def jw_baseline_pipeline(
    geometry: list[float],
    symbols: list[str],
    basis: str = "sto-3g",
    charge: int = 0,
    multiplicity: int = 1,
    active_electrons: int = 0,
    active_orbitals: int = 0,
    measurement_methods: list[str] = ["pauli"],
    shots_values: list[int] = [1024],
    optimization_levels: list[int] = [1],
) -> None:
    jw_map_task = jw_map_component(
        geometry=geometry,
        symbols=symbols,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
        active_electrons=active_electrons,
        active_orbitals=active_orbitals,
    )

    with dsl.ParallelFor(items=measurement_methods) as measurement_method:
        # Credentials only actually used by the grouped branch
        # (execute_static_hamiltonian_component calls Cebule QASM_GEN for
        # that branch only) — harmless no-op env vars for the pauli branch.
        _with_cebule_credentials(
            execute_static_hamiltonian_component(
                mapper_result=jw_map_task.outputs["jw_map_result"],
                hamiltonian_kind="sparse",
                measurement_method=measurement_method,
                shots_values=shots_values,
                optimization_levels=optimization_levels,
                email_env=_EMAIL_ENV,
                password_env=_PASSWORD_ENV,
            )
        )


_PIPELINES = {
    "cebule_molecular_vqe_pipeline": cebule_molecular_vqe_pipeline,
    "cebule_tn_vqe_pipeline": cebule_tn_vqe_pipeline,
    "mol_map_measurement_pipeline": mol_map_measurement_pipeline,
    "jw_baseline_pipeline": jw_baseline_pipeline,
}


def compile_pipeline(name: str = "cebule_molecular_vqe_pipeline", output_path: str | None = None) -> None:
    """Compile one of the four pipelines to a kfp YAML package.

    `name` is one of _PIPELINES' keys (also the four Mapper-category
    pipeline function names above).
    """
    from kfp import compiler

    pipeline_fn = _PIPELINES[name]
    compiler.Compiler().compile(pipeline_fn, output_path or f"{name}.yaml")


if __name__ == "__main__":
    for _name in _PIPELINES:
        compile_pipeline(_name)
