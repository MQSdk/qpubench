# QForte integration

Self-contained example showing how to run QForte VQE algorithms via qpubench.

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

# Compare BFGS vs jacobi
records = adapt.compare_optimizers(mol, pool_type="SD")
table   = AdaptVQERunner.summary_table(records)
```

## Running on an external backend (Aer, Qrack, IBM)

```python
from qpubench.backends.aer_adapter import AerAdapter   # fill the TODOs first
from qforte_adapter.adapter import ExternalEvalAlgorithmAdapter
from qforte_adapter.adapt_vqe import ExternalEvalAdaptVQERunner

runner.register(
    ExternalEvalAlgorithmAdapter(energy_backend=AerAdapter()),
    name="qforte+aer",
)
ext = ExternalEvalAdaptVQERunner(runner, "qforte+aer")
record = ext.run(mol, AlgorithmSpec(name="ADAPTVQE", pool_type="SD"))
print(record.result.metadata["hook_call_count"])
```

See `../../INTEGRATION_GUIDE.md` for the full explanation of why this is structured
the way it is.
