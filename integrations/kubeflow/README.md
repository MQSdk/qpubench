# Kubeflow Pipelines (kfp) integration

Worked example showing qpubench algorithmic steps run as **kfp components**,
visible in the Kubeflow Central Dashboard as a real pipeline graph — the
Cebule SDK task chain (`MOL_MAP -> TN_QC_OPT -> QASM_GEN -> circuit
execution`) as four DAG nodes.

This is **Path 1** of the qpubench/Kubeflow integration analysis: kfp owns
the DAG and the dashboard. The unified Kubeflow SDK (`TrainerClient`,
`OptimizerClient`) is deliberately *not* used here — see
[docs/integrations/kubeflow.md](../../docs/integrations/kubeflow.md) for why,
and for the narrower cases (multi-node distributed simulation, Katib
hyperparameter search) where it's worth reaching for inside a component
body.

## Files

| File | Purpose |
|------|---------|
| `components.py` | Four `@dsl.component` functions — the DAG nodes |
| `pipelines.py` | `cebule_molecular_vqe_pipeline` — the `@dsl.pipeline` wiring them together |

## Component kinds

| Component | Kind | Backend calls |
|---|---|---|
| `mol_map_component` | Transform | Cebule cloud API (MOL_MAP) |
| `tn_qc_opt_component` | Transform (one job, whole optimizer loop inside) | Cebule cloud API (TN_QC_OPT) |
| `qasm_gen_component` | Transform | Cebule cloud API (QASM_GEN) |
| `execute_circuits_component` | Execution | qpubench `BenchmarkRunner` against a registered `BackendAdapter` (stub by default) |

## Setup

```sh
pip install kfp kfp-kubernetes
```

Build and publish a container image with `qpubench` + `mqsdk` installed
(referenced as `_QPUBENCH_IMAGE`/`_QPUBENCH_SIM_IMAGE` in `components.py` —
replace the placeholder tags with your own registry):

```dockerfile
FROM python:3.11-slim
RUN pip install qpubench mqsdk
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

Upload `cebule_pipeline.yaml` through the dashboard's Pipelines UI, or
submit programmatically:

```python
import kfp

client = kfp.Client(host="https://<your-kubeflow-endpoint>")
client.create_run_from_pipeline_package(
    "cebule_pipeline.yaml",
    arguments={
        "geometry": [0.0, 0.0, 0.0, 0.0, 0.0, 0.7414],
        "symbols": ["H", "H"],
    },
)
```

The run appears immediately in the dashboard: graph, per-step logs,
artifacts, and caching status.

Verified against `kfp==2.16.1` by actually compiling this pipeline, not just
reading it — see the note below on `from __future__ import annotations`,
which surfaced from that test.

## Known placeholders (read before running against real Cebule credentials)

- `qasm_gen_component` needs a Pauli-term → dense-Hermitian-matrix
  conversion that qpubench doesn't ship yet (`schemas/observable.py` only
  implements the reverse direction, `from_cebule_operators`). It's a marked
  `TODO` in `components.py`, not silently fabricated math.
- `mqsdk.TaskType`'s exact import path isn't pinned down by
  `docs/integrations/cebule.md`'s existing session-pattern example — confirm
  it against your installed `mqsdk` version.
- Swapping `execute_circuits_component`'s `StubGateAdapter` for a real
  backend (Aer/Qrack/IBM) means changing that one component's `base_image`
  and adapter registration, and its resource request in `pipelines.py`
  (`.set_cpu_limit(...)` / `.set_accelerator_type("nvidia.com/gpu")...` for a
  GPU simulator) — no other component changes.
- Neither `components.py` nor `pipelines.py` uses
  `from __future__ import annotations`, unlike the rest of this repo — kfp's
  `@dsl.component`/`@dsl.pipeline` decorators inspect live type objects at
  decoration time and misparse stringified (PEP 563) annotations. If you add
  a component here, don't add that import.
