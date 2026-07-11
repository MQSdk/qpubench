# Classiq integration

Self-contained example showing how to run Classiq's synthesize → execute
pipeline via qpubench, and how to compare a Classiq-synthesized circuit
against a Xenakis GA-searched one for the same problem.

## Files

| File | Purpose |
|------|---------|
| `adapter.py` | `ClassiqAlgorithmAdapter` |
| `converters.py` | Classiq ↔ qpubench type conversions; problem-spec helpers |

## Setup

```sh
pip install qpubench
pip install classiq
classiq login   # device-code auth against the Classiq cloud
```

Copy this directory into your project:

```sh
cp -r integrations/classiq/ my_project/classiq_adapter/
```

## Quick start

Building the `@qfunc`-decorated functional model is inherent Classiq SDK
usage and is not something qpubench can generate for you — see
[docs.classiq.io](https://docs.classiq.io/) for the current chemistry /
combinatorial-optimization application helpers (these have moved across SDK
versions; check the installed version's docs). Once you have a model:

```python
import classiq
from qpubench import BenchmarkRunner, NDJSONStore, ExecutionOptions

from classiq_adapter.adapter import ClassiqAlgorithmAdapter
from classiq_adapter.converters import problem_spec_from_qmod
from qpubench.schemas.classiq_classiq import ClassiqConstraints, ClassiqOptimizationParameter

@classiq.qfunc
def main(q: classiq.QArray[classiq.QBit]) -> None:
    classiq.allocate(3, q)
    classiq.H(q[0])
    # ... rest of your functional model

qmod_source = classiq.create_model(main)

spec = problem_spec_from_qmod(
    qmod_source,
    constraints=ClassiqConstraints(max_width=3, optimization_parameter=ClassiqOptimizationParameter.DEPTH),
)

runner = BenchmarkRunner(store=NDJSONStore("results.ndjson"))
runner.register(ClassiqAlgorithmAdapter(), name="classiq")
record = runner.run(spec, "classiq", ExecutionOptions(shots=2000))

print(record.result.metadata["classiq_synthesis_id"], record.result.metadata["classiq_depth"])
```

## Hybrid execution: synthesize with Classiq, run on any qpubench backend

Because synthesis and execution are separate Classiq calls, you can
synthesize once, convert straight to a `CircuitSpec`, and hand it to Aer,
Qrack, IBM, or IQM instead of Classiq's own `execute()`:

```python
import classiq
from classiq_adapter.converters import synthesis_result_from_quantum_program
from qpubench.backends.aer_adapter import AerAdapter

quantum_program = classiq.synthesize(model)
synthesis = synthesis_result_from_quantum_program(quantum_program)
circuit_spec = synthesis.to_circuit_spec()

runner.register(AerAdapter(), name="aer")
record = runner.run(circuit_spec, "aer", ExecutionOptions(shots=2000))
```

This isolates *synthesis quality* (does Classiq's engine find a shallower
circuit?) from *execution quality* (does Classiq's own backend run it
faster/more accurately than Aer?) — useful when comparing against a
Xenakis-searched circuit, since Xenakis circuits also convert to the exact
same `CircuitSpec` type (`GARunResult.best_circuit_spec()`).

## Comparing against a Xenakis GA search

```python
from qpubench.schemas.classiq_classiq import CircuitOptimizationComparison

comparison = CircuitOptimizationComparison(
    problem_label="H2 UCCSD ansatz, sto-3g",
    ga_result=ga_run_result,           # from your Xenakis GA run
    classiq_result=synthesis,          # from synthesis_result_from_quantum_program() above
)
print(comparison.depth_delta, comparison.search_cost_label)
```

See `../../docs/integrations/classiq.md` for the full schema reference and
`../../docs/integrations/xenakis.md` for the GA-search side, and
`../../INTEGRATION_GUIDE.md` for why the adapter is structured this way.
