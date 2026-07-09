"""cebule_molecular_vqe_pipeline — the kfp DAG wiring components.py together.

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
        arguments={"geometry": [0.0, 0.0, 0.0, 0.0, 0.0, 0.7414], "symbols": ["H", "H"]},
    )

Either path shows the run — graph, per-step logs, artifacts, caching status —
in the dashboard immediately.

Nothing here calls TrainerClient/OptimizerClient: every step is a Transform
or the one Execution node (see components.py docstrings). Reach for the
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
        "Cebule SDK task chain documented in schemas/mqsdk_cebule.py."
    ),
)
def cebule_molecular_vqe_pipeline(
    geometry: list[float],
    symbols: list[str],
    basis: str = "sto3g",
    h_coeff_values: list[float] = [],  # noqa: B006 — kfp pipeline params, not a mutable default trap
    h_operators: list[str] = [],  # noqa: B006
    n_iterations: int = 100,
    n_layers_network: int = 3,
    n_layers_circuit: int = 3,
    opt_method: str = "COBYLA",   # Cebule's own current default (docs.mqs.dk, checked 2026-07-09)
    tn_backend: str = "lightning.qubit",
    include_state_circuit: bool = False,   # Cebule's own current default (docs.mqs.dk, checked 2026-07-09)
    shots: int = 1024,
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

    tn_qc_opt_task = _with_cebule_credentials(
        tn_qc_opt_component(
            mol_map_result=mol_map_task.outputs["mol_map_result"],
            h_coeff_values=h_coeff_values,
            h_operators=h_operators,
            n_iterations=n_iterations,
            n_layers_network=n_layers_network,
            n_layers_circuit=n_layers_circuit,
            opt_method=opt_method,
            backend=tn_backend,
            email_env=_EMAIL_ENV,
            password_env=_PASSWORD_ENV,
        )
    )
    # TN_QC_OPT's n_iterations optimizer loop is the expensive step here —
    # request more CPU than the default. Still one job, not one per iteration.
    tn_qc_opt_task.set_cpu_request("2").set_cpu_limit("4").set_memory_limit("4Gi")

    qasm_gen_task = _with_cebule_credentials(
        qasm_gen_component(
            mol_map_result=mol_map_task.outputs["mol_map_result"],
            tn_qc_opt_result=tn_qc_opt_task.outputs["tn_qc_opt_result"],
            include_state_circuit=include_state_circuit,
            email_env=_EMAIL_ENV,
            password_env=_PASSWORD_ENV,
        )
    )

    # No credentials needed past this point — execution runs against a
    # qpubench-registered BackendAdapter (stub by default), not Cebule's API.
    execute_circuits_component(
        mol_map_result=mol_map_task.outputs["mol_map_result"],
        qasm_gen_result=qasm_gen_task.outputs["qasm_gen_result"],
        shots=shots,
    )


def compile_pipeline(output_path: str = "cebule_molecular_vqe_pipeline.yaml") -> None:
    """Compile the pipeline to a kfp YAML package for the dashboard's upload UI."""
    from kfp import compiler

    compiler.Compiler().compile(cebule_molecular_vqe_pipeline, output_path)


if __name__ == "__main__":
    compile_pipeline()
