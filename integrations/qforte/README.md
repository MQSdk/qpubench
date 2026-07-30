# QForte integration

Self-contained example showing how to run QForte VQE algorithms via qpubench.
QForte's pybind11 object model (Circuit, Gate, QubitOperator, ...) and its
Algorithm/AnsatzAlgorithm/ADAPTVQE attribute surface are modeled as typed
schemas in `schemas/mirrors/evangelistalab_qforte.py` — no more ad hoc `getattr()`
scraping of private attributes with an untyped contract.

> **See [docs/vqa.md](../../docs/vqa.md) for the overall VQA picture** — how
> VQE and ADAPT-VQE relate, the package-agnostic `AdaptVQERunConfig` contract,
> and how this QForte engine compares to the other two `ADAPT_VQE`
> implementations. This README covers the QForte adapter specifically.

This is one of three implementations of `AlgorithmFamily.ADAPT_VQE` in this
repo — `integrations/ibm_qiskit_adapt_vqe/` and
`integrations/microsoft_qdk_adapt_vqe/` implement the same family without
requiring QForte, sharing a package-agnostic engine
(`integrations/generic_adapt_vqe/`). Register any of the three under a
different name and drive them with the same `AdaptVQERunConfig`.

## Files

| File | Purpose |
|------|---------|
| `adapter.py` | `QForteAlgorithmAdapter` + `ExternalEvalAlgorithmAdapter` |
| `converters.py` | QForte ↔ qpubench type conversions; molecule spec helpers |
| `circuit_utils.py` | QForte `QuantumCircuit` → QASM2 string |
| `energy_hook.py` | `EnergyEvaluatorHook` + `make_hooked_class` |
| `adapt_vqe.py` | `AdaptVQERunner` + `ExternalEvalAdaptVQERunner` |
| `benchmark_example.py` | Full benchmark: compare optimizers, pool types, algorithms |

## Setup

```sh
pip install qpubench
pip install qforte          # C++ extension, needs a compiler
# or from source:
git clone https://github.com/evangelistalab/qforte && cd qforte && pip install -e .
```

Copy this directory into your project:

```sh
cp -r integrations/qforte/ my_project/qforte_adapter/
```

## Quick start

```python
from qpubench import BenchmarkRunner, NDJSONStore, AlgorithmSpec, ExecutionOptions

# Import the adapter code you copied
from qforte_adapter.adapter import QForteAlgorithmAdapter
from qforte_adapter.converters import molecule_spec_from_file
from qforte_adapter.adapt_vqe import AdaptVQERunner

runner = BenchmarkRunner(store=NDJSONStore("results.ndjson"))
runner.register(QForteAlgorithmAdapter(), name="qforte")

adapt = AdaptVQERunner(runner)
mol   = molecule_spec_from_file("path/to/He-ccpvdz.json")
# or let converters.find_molecule_json("He-ccpvdz.json") locate it — see below

# Compare BFGS vs jacobi
records = adapt.compare_optimizers(mol, pool_type="SD")
table   = AdaptVQERunner.summary_table(records)
```

## Finding QForte's test molecules

`He-ccpvdz.json` and the other molecule files live in QForte's `tests/` directory, and QForte's `setup.py` does not install it — neither `pip install .` nor `python setup.py develop` puts those files inside the installed package. `converters.find_molecule_json(name, env_var=...)` handles that: it checks the environment variable you name, the installed package, the checkout the package came from (parent directories, plus the source path pip records in `direct_url.json`), and the working directory. If it still comes up empty it raises with the searched paths and the `curl` command for the single file.

## Running on an external backend (Aer, Qrack, IBM)

```python
from qpubench import AdaptVQERunConfig, AlgorithmFamily
from qpubench.backends.aer_adapter import AerAdapter   # fill the TODOs first
from qforte_adapter.adapter import ExternalEvalAlgorithmAdapter
from qforte_adapter.adapt_vqe import ExternalEvalAdaptVQERunner

runner.register(
    ExternalEvalAlgorithmAdapter(energy_backend=AerAdapter()),
    name="qforte+aer",
)
ext = ExternalEvalAdaptVQERunner(runner, "qforte+aer")
record = ext.run(
    mol,
    AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
    AdaptVQERunConfig(pool_type="SD"),
)
print(record.result.metadata["hook_call_count"])
```

See [`docs/backends.md`](../../docs/backends.md) for the full explanation of why this
is structured the way it is.
