# Integrations

Example adapters showing how to connect external libraries to qpubench.

These files are **not part of the qpubench package** — they are reference
implementations you copy into your own project and adapt.

| Directory | What it shows |
|-----------|--------------|
| `template/` | Bare-bones templates with every TODO marked |
| `qforte/` | Complete QForte integration: UCCNVQE, ADAPT-VQE, external energy backend |
| `slowquant/` | Real SlowQuant UCC/UPS VQE adapter (not on PyPI — git-only install, see `slowquant/README.md`) |
| `kubeflow/` | Cebule task chain as a Kubeflow Pipelines (kfp) DAG — algorithmic steps as dashboard-visible components |

Read `../INTEGRATION_GUIDE.md` first for the design principles and step-by-step
recipes. The files here are the code that corresponds to the guide.

## Quick decision tree

```
Do you have a quantum circuit to run?
  YES → copy template/backend_adapter_template.py
        Fill: _run_estimator() and _run_sampler()

Does your library generate circuits from a problem spec (molecule, graph)?
  YES → copy template/algorithm_adapter_template.py
        Fill: run_algorithm() — parse spec, run library, extract results

Do you want QForte's ADAPT-VQE to evaluate energies on a qpubench backend?
  YES → copy integrations/qforte/ entirely
        Use ExternalEvalAlgorithmAdapter(energy_backend=YourBackend())
```
