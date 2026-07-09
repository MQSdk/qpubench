# QDK / Azure Quantum ADAPT-VQE integration

`AlgorithmFamily.ADAPT_VQE` targeting QDK / Azure Quantum simulators and
hardware (`BackendSpec.qdk_chemistry_simulator()` / `BackendSpec.azure_quantum(...)`,
see `src/qpubench/schemas/backend.py`) — a thin `AlgorithmAdapter` wrapper
over `integrations/generic_adapt_vqe/`, identical in every respect to
`integrations/ibm_qiskit_adapt_vqe/` except its `BackendSpec` defaults.

## Why this exists alongside `schemas/microsoft_qdk.py`

`schemas/microsoft_qdk.py` models the Microsoft QDK chemistry-course
pipeline (SCF → active-space selection → QPE/IQPE resource estimation) — a
phase-estimation workflow, not ADAPT-VQE. QDK's Quantum Chemistry Library
and Azure Quantum both support UCC-style variational algorithms too, so
`AlgorithmFamily.ADAPT_VQE` "via microsoft_qdk" is a legitimate, separate
thing to run. Build the qubit Hamiltonian with `microsoft_qdk.py`'s
`QChemPipelineSpec` (SCF through fermionic-to-qubit mapping), then hand it
to this adapter instead of continuing on to `QPEConfig`.

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
from microsoft_qdk_adapt_vqe.adapter import MicrosoftQDKAdaptVQEAdapter

runner = BenchmarkRunner()
runner.register(
    MicrosoftQDKAdaptVQEAdapter(energy_backend=my_qdk_backend),
    name="microsoft_qdk",
)

problem = CircuitSpec(num_qubits=0, format=CircuitFormat.MOLECULE_JSON, serialized=problem_json)
options = ExecutionOptions(
    algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
    adapt_vqe_config=AdaptVQEConfig(pool_type="SD", optimizer="BFGS"),
)
record = runner.run(problem, "microsoft_qdk", options)
```

See `../generic_adapt_vqe/README.md` for the engine internals and how its
Jordan-Wigner / circuit-synthesis math is verified.
