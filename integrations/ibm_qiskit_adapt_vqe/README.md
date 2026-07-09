# IBM/Qiskit ADAPT-VQE integration

`AlgorithmFamily.ADAPT_VQE` via a from-scratch, Qiskit-circuit-convention
implementation — a thin `AlgorithmAdapter` wrapper over
`integrations/generic_adapt_vqe/`. Registered under a different name than
`integrations/qforte/`, it lets you run the exact same `AdaptVQEConfig`
against a different implementation and compare the resulting
`BenchmarkRecord`s directly.

No Qiskit installation is required for the algorithm logic itself — circuits
are emitted as standard OpenQASM 3.0 (same convention `AerAdapter` /
`IBMAdapter` already speak) and executed via whichever qpubench
`BackendAdapter` you register as the energy oracle. Only that backend (e.g.
a real Qiskit/Aer-backed adapter) needs Qiskit installed.

## Setup

```sh
pip install 'qpubench[adapt_vqe]'   # scipy + numpy (classical optimizer + test verification)
```

Copy this directory *and* `integrations/generic_adapt_vqe/` into your
project — this adapter depends on the shared engine there.

## Quick start

```python
from qpubench import BenchmarkRunner, ExecutionOptions, AlgorithmSpec, AdaptVQEConfig
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.primitives import AlgorithmFamily, CircuitFormat
from ibm_qiskit_adapt_vqe.adapter import IBMQiskitAdaptVQEAdapter
from qpubench.backends.aer_adapter import AerAdapter   # fill the TODOs first

runner = BenchmarkRunner()
runner.register(IBMQiskitAdaptVQEAdapter(energy_backend=AerAdapter()), name="ibm_qiskit")

# Problem: pre-built qubit Hamiltonian, not raw molecular geometry —
# see the adapter docstring for the exact CircuitSpec.serialized JSON shape.
problem = CircuitSpec(num_qubits=0, format=CircuitFormat.MOLECULE_JSON, serialized=problem_json)
options = ExecutionOptions(
    algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
    adapt_vqe_config=AdaptVQEConfig(pool_type="SD", optimizer="BFGS"),
)
record = runner.run(problem, "ibm_qiskit", options)
```

See `../generic_adapt_vqe/README.md` for the engine internals and how its
Jordan-Wigner / circuit-synthesis math is verified.
