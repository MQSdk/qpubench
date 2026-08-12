# Kubeflow Pipelines (kfp) integration

Worked example showing qpubench algorithmic steps run as **kfp components**,
visible in the Kubeflow Central Dashboard as a real pipeline graph — the
Cebule SDK task chain (`MOL_MAP -> TN_QC_OPT -> QASM_GEN -> circuit
execution`) as DAG nodes.

This is **Path 1** of the qpubench/Kubeflow integration analysis: kfp owns
the DAG and the dashboard. The unified Kubeflow SDK (`TrainerClient`,
`OptimizerClient`) is deliberately *not* used here — see
[docs/integrations/kubeflow.md](../../docs/integrations/kubeflow.md) for why,
and for the narrower cases (multi-node distributed simulation, Katib
hyperparameter search) where it's worth reaching for inside a component
body.

## Four pipelines, one per (`Mapper`, `Method`) pair

[`data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv`](../../data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv)
(see [the campaign README](../../data/benchmarks/ibm_tn-vqe_qesem/README.md)) crosses two `Mapper`
values with two `Method` values, and each of the four pairs gets its own
`@dsl.pipeline` — that pair is the one axis that changes which components
exist (a component change), so it's the one thing that gets its own DAG:

| Pipeline | Mapper | Method | Components |
|---|---|---|---|
| `cebule_molecular_vqe_pipeline` | `mol_map` | `TN-VQE` | `mol_map_component -> tn_qc_opt_component -> qasm_gen_component -> execute_circuits_component` |
| `cebule_tn_vqe_pipeline` | `JW` | `TN-VQE` | `jw_map_component -> tn_qc_opt_component -> qasm_gen_component -> execute_circuits_component` |
| `mol_map_measurement_pipeline` | `mol_map` | `VQE` | `mol_map_component -> execute_static_hamiltonian_component` |
| `jw_baseline_pipeline` | `JW` | `VQE` | `jw_map_component -> execute_static_hamiltonian_component` |

Every other benchmark dimension — `TN_Layers_Network`, `TN_Layers_Circuit`,
`TN_Ansatz`, `Measurement_Method`, `Shots`, `Optimization_Mode` — is a
**parameter value**, not a different pipeline: it's resolved *inside* one
of the four DAGs above via `dsl.ParallelFor` (the Cebule-task-level knobs)
and `BenchmarkRunner.sweep()` inside the Execution components (the
execution-option knobs). One run of one pipeline, however many sweep
points it fans out to, is one graph in the dashboard — not one DAG per CSV
row. See `components.py`'s and `pipelines.py`'s module docstrings for the
full reasoning.

The two `VQE` pipelines measure the fixed Hartree-Fock reference state
rather than an optimized one; see `execute_static_hamiltonian_component`'s
docstring. That is a limitation of these components, not of the matrix:
`data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv` names a real `Ansatz` and `Ansatz_Reps`
on every row, including the `VQE` ones, and nothing here consumes them
yet.

## Files

| File | Purpose |
|------|---------|
| `components.py` | `@dsl.component` functions — the DAG nodes, shared across the four pipelines where the same step applies |
| `pipelines.py` | The four `@dsl.pipeline` functions wiring components together, one per (`Mapper`, `Method`) pair |

## Component kinds

| Component | Kind | Backend calls |
|---|---|---|
| `jw_map_component` | Transform | None — local PySCF/OpenFermion (`hamiltonian_sources/ab_initio.py`) |
| `mol_map_component` | Transform | Cebule cloud API (MOL_MAP) |
| `tn_qc_opt_component` | Transform (one job, whole optimizer loop inside) | Cebule cloud API (TN_QC_OPT) |
| `qasm_gen_component` | Transform | Cebule cloud API (QASM_GEN) |
| `execute_circuits_component` | Execution | qpubench `BenchmarkRunner` against a registered `BackendAdapter` (stub by default) — the two `TN-VQE` pipelines |
| `execute_static_hamiltonian_component` | Execution | qpubench `BenchmarkRunner`, plus Cebule QASM_GEN for the `grouped` branch only — the two `VQE` pipelines |

## Setup

```sh
pip install kfp kfp-kubernetes
```

Build and publish container images with `qpubench` + `mqsdk` installed
(referenced as `_QPUBENCH_IMAGE`/`_QPUBENCH_SIM_IMAGE` in `components.py` —
replace the placeholder tags with your own registry), plus a separate image
with `qpubench[openfermion]` for `jw_map_component` (`_QPUBENCH_CHEM_IMAGE`
— PySCF/OpenFermion, no Cebule credentials needed):

```dockerfile
FROM python:3.11-slim
RUN pip install qpubench mqsdk
```

```dockerfile
FROM python:3.11-slim
RUN pip install "qpubench[openfermion]"
```

Create the Cebule credentials secret once per cluster/namespace:

```sh
kubectl create secret generic cebule-credentials \
  --from-literal=email="$CEBULE_EMAIL" \
  --from-literal=password="$CEBULE_PASSWORD"
```

## Compile and run

```python
from kfp import compiler
from pipelines import cebule_molecular_vqe_pipeline

compiler.Compiler().compile(cebule_molecular_vqe_pipeline, "cebule_pipeline.yaml")
```

Or compile all four at once: `python -m integrations.kubeflow.pipelines`
(writes `<pipeline_name>.yaml` for each of the four).

Upload the YAML through the dashboard's Pipelines UI, or submit
programmatically — e.g. running the full `TN_Layers_Network x
TN_Layers_Circuit x TN_Ansatz x Measurement_Method` sweep from
`data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv` as **one** pipeline run:

```python
import kfp

client = kfp.Client(host="https://<your-kubeflow-endpoint>")
client.create_run_from_pipeline_package(
    "cebule_molecular_vqe_pipeline.yaml",
    arguments={
        "geometry": [0.0, 0.0, 0.0, 0.0, 0.0, 0.7414],
        "symbols": ["H", "H"],
        "tn_layers_network_values": [0, 1, 2, 3],
        "tn_layers_circuit_values": [1, 2, 3, 4],
        "tn_ansatz_values": ["givens", "rotation_3param"],
        "measurement_methods": ["pauli", "grouped"],
        "shots_values": [1024],
        "optimization_levels": [1],
    },
)
```

The run appears immediately in the dashboard: one graph (fanned out by
`dsl.ParallelFor` into every sweep-point branch above), per-step logs,
artifacts, and caching status.

Verified against `kfp==2.16.1` by actually compiling all four pipelines,
not just reading them (nested 4-deep `dsl.ParallelFor` included) — see the
note below on `from __future__ import annotations`, which surfaced from
that test. The pure-Python logic inside each component body (JSON
artifact reads, the pauli/Estimator vs grouped/Sampler branch,
`jw_map_component`'s real PySCF/OpenFermion call, `BenchmarkRunner.sweep()`
against `StubGateAdapter`) was also run directly (outside a container,
calling each `@dsl.component`'s `.python_func`) — real, not just
compile-checked. Only the actual Cebule `create_task` calls
(`mol_map_component`, `tn_qc_opt_component`, `qasm_gen_component`, and
`execute_static_hamiltonian_component`'s `grouped` branch) are
untested here, same as before this change — they need real Cebule
credentials this environment doesn't have.

## Dense <-> sparse Hamiltonian conversion (formerly "Known placeholders")

The three `NotImplementedError` gaps documented here previously are closed:
`SparsePauliObservable.to_dense_matrix()` (sparse -> dense Pauli tensor
expansion) and `SparsePauliObservable.from_dense_matrix()` (dense -> sparse
Pauli decomposition, `coeff_P = Tr(P @ H) / 2**n`) now ship in
`schemas/observable.py`, verified against Qiskit's `SparsePauliOp` for both
directions plus round-trips. All four pipelines' Execution components use
them, so every (hamiltonian_kind, measurement_method) combination runs:

| Component | Conversion used |
|---|---|
| `qasm_gen_component` (the two `TN-VQE` pipelines) | TN_QC_OPT sparse terms -> `to_dense_matrix()` -> `QASMGenInput.operator` |
| `execute_static_hamiltonian_component(hamiltonian_kind="dense", measurement_method="pauli")` | `mol_map` dense matrix -> `from_dense_matrix()` -> Estimator observable |
| `execute_static_hamiltonian_component(hamiltonian_kind="sparse", measurement_method="grouped")` | JW sparse terms -> `to_dense_matrix()` -> `QASMGenInput.operator` |

Both conversions are exponential by nature (the dense side is already a
`2**n x 2**n` matrix), matched to this benchmark's small `mol_map`/JW qubit
counts and guarded by an explicit `max_qubits=` parameter — do not reuse
them for large observables without raising the guard deliberately.

Still open, unchanged by this: the actual Cebule `create_task` calls have
only been verified against the stub backend + compile-checked DAG structure
— re-verify all four pipelines' Execution components against real Cebule
credentials before relying on them (see "Compile and run" above for exactly
what has and hasn't been run).

Other things to know before a real run:

- `mqsdk.TaskType`'s exact import path isn't pinned down by
  `docs/integrations/cebule.md`'s existing session-pattern example — confirm
  it against your installed `mqsdk` version.
- Swapping either Execution component's `StubGateAdapter` for a real
  backend (Aer/Qrack/IBM) means changing that one component's `base_image`
  and adapter registration, and its resource request in `pipelines.py`
  (`.set_cpu_limit(...)` / `.set_accelerator_type("nvidia.com/gpu")...` for a
  GPU simulator) — no other component changes.
- `execute_static_hamiltonian_component`'s one-hot `state_vector` for the
  HF reference state, and `jw_map_component`'s HF occupation-number
  `hf_state` convention, both scale as `2**num_qubits`/are only meaningful
  for the small qubit counts this benchmark's `mol_map`/`JW` rows actually
  use — not a general-purpose statevector builder.
- Neither `components.py` nor `pipelines.py` uses
  `from __future__ import annotations`, unlike the rest of this repo — kfp's
  `@dsl.component`/`@dsl.pipeline` decorators inspect live type objects at
  decoration time and misparse stringified (PEP 563) annotations. If you add
  a component here, don't add that import.
