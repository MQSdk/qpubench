# Backends & adapters

qpubench uses two adapter protocols that the `BenchmarkRunner` dispatches automatically based on `isinstance()` checks.

---

## Protocols

### `BackendAdapter` — circuit-driven

```
validate(circuit: CircuitSpec) → list[str]
run(circuit: CircuitSpec, options: ExecutionOptions) → QuantumResult
spec: BackendSpec
```

Use this when **you** provide the circuit and the backend executes it.  
Examples: Qiskit Aer, Qrack, IBM Quantum Runtime, IQM, Qibo, MBQC-FPGA.

### `AlgorithmAdapter` — algorithm-driven

```
validate_problem(circuit: CircuitSpec) → list[str]
run_algorithm(circuit: CircuitSpec, options: ExecutionOptions) → tuple[QuantumResult, VQAConfig]
spec: BackendSpec
```

Use this when the **library generates its own circuit** from a problem specification and drives its own execution loop.  
Examples: QForte (ADAPT-VQE, UCCNVQE), OpenFermion VQE stacks.

### `TranspilableBackend` — optional extension

```
transpile(circuit: CircuitSpec, options: ExecutionOptions) → tuple[CircuitSpec, TranspileLayout]
```

Implement this on a `BackendAdapter` to expose transpilation before execution. The runner will call it automatically if present.

---

## Built-in adapters

### Stub adapters (no SDK required)

| Class | Protocol | Description |
|---|---|---|
| `StubGateAdapter` | `BackendAdapter` | Returns random expectation values and shot counts. Accepts `seed` for reproducibility. |
| `StubMBQCAdapter` | `BackendAdapter` | Returns random MBQC round results with configurable `fidelity`. |

```python
from qpubench import StubGateAdapter, StubMBQCAdapter

runner.register(StubGateAdapter(seed=42), name="stub_gate")
runner.register(StubMBQCAdapter(seed=7, fidelity=0.97), name="stub_mbqc")
```

### Partial adapters (fill TODOs)

These live in `src/qpubench/backends/` and have the correct schema wiring in place; the SDK-specific call sites are marked with `# TODO`.

| File | Backend | Provider string |
|---|---|---|
| `aer_adapter.py` | Qiskit Aer statevector + QASM | `"aer"` |
| `ibm_adapter.py` | IBM Quantum Runtime V2 | `"ibm"` |
| `qrack_adapter.py` | PyQrack GPU/CPU (ctypes) | `"qrack"` |

### Integration examples (copy into your project)

From `integrations/`:

| Path | Backend | Notes |
|---|---|---|
| `integrations/qforte/adapter.py` | QForte UCCNVQE / ADAPT-VQE | `AlgorithmAdapter`; also `ExternalEvalAlgorithmAdapter` |
| `integrations/template/backend_adapter_template.py` | Any circuit backend | Start here |
| `integrations/template/algorithm_adapter_template.py` | Any algorithm library | Start here |

---

## Writing a new `BackendAdapter`

Copy `integrations/template/backend_adapter_template.py` and fill the TODOs:

```python
from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.primitives import JobStatus, QPUModality
from qpubench.schemas.result import ExpectationResult, QuantumResult, ShotResult

class MyBackendAdapter:

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(name="my_backend", provider="my_provider",
                           simulator=True, qpu_modality=QPUModality.GATE_BASED)

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings = []
        if circuit.num_qubits > 32:
            warnings.append("backend supports at most 32 qubits")
        return warnings

    def run(self, circuit: CircuitSpec, options: ExecutionOptions) -> QuantumResult:
        if circuit.observables:
            # Estimator path
            energy = my_sdk.expectation(circuit.serialized, ...)
            return QuantumResult(
                modality=circuit.modality,
                expectation_values=[
                    ExpectationResult(observable_index=0, value=energy, std_error=0.0)
                ],
                status=JobStatus.SUCCEEDED,
            )
        else:
            # Sampler path
            counts = my_sdk.sample(circuit.serialized, shots=options.shots)
            return QuantumResult(
                modality=circuit.modality,
                shots=ShotResult(num_qubits=circuit.num_qubits,
                                 num_shots=options.shots, counts=counts),
                status=JobStatus.SUCCEEDED,
            )
```

Register and run:

```python
runner.register(MyBackendAdapter(), name="my_backend")
record = runner.run(circuit, "my_backend", ExecutionOptions(shots=1024))
```

---

## Writing a new `AlgorithmAdapter`

Copy `integrations/template/algorithm_adapter_template.py`:

```python
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.record import VQAConfig
from qpubench.schemas.result import QuantumResult

class MyAlgorithmAdapter:

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(name="my_library", provider="my_provider", simulator=True)

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        # Check that circuit.serialized points to a valid problem file
        return []

    def run_algorithm(
        self, circuit: CircuitSpec, options: ExecutionOptions,
    ) -> tuple[QuantumResult, VQAConfig]:
        alg = options.algorithm_spec
        # Parse problem, run algorithm, return (result, vqa_metadata)
        ...
```

The runner dispatches to `run_algorithm()` automatically when it detects `AlgorithmAdapter`. No configuration needed — just register the adapter normally.

---

## Backend support matrix

| Backend | Provider | Adapter | Status |
|---|---|---|---|
| Qiskit Aer (statevector + QASM) | `"aer"` | `AerAdapter` | Stub — fill TODOs in `aer_adapter.py` |
| IBM Quantum Runtime V2 | `"ibm"` | `IBMAdapter` | Stub — fill TODOs in `ibm_adapter.py` |
| Qrack GPU/CPU simulator | `"qrack"` | `QrackAdapter` | Stub — fill TODOs in `qrack_adapter.py` |
| IQM hardware | `"iqm"` | Copy `backend_adapter_template.py` | |
| Qibo cloud | `"qibo"` | Copy `backend_adapter_template.py` | |
| MBQC-FPGA (photonic) | `"mbqc"` | Copy `backend_adapter_template.py` | Schemas complete; COE + CSV round-trip |
| PennyLane `lightning.qubit` | `"pennylane"` | Copy template | `BackendSpec.lightning_qubit()` |
| CUDA-Q | `"cudaq"` | Copy template | `BackendSpec.cudaq()` |
| Cebule cloud | `"cebule"` | Copy template | `BackendSpec.cebule()` |
| Stub gate simulator | — | `StubGateAdapter` | Fully functional, no SDK |
| Stub MBQC simulator | — | `StubMBQCAdapter` | Fully functional, no SDK |

### Algorithm libraries

| Library | Adapter | Algorithms | Location |
|---|---|---|---|
| QForte (internal eval) | `QForteAlgorithmAdapter` | UCCNVQE, ADAPTVQE, UCCNPQE, SPQE | `integrations/qforte/adapter.py` |
| QForte (external backend) | `ExternalEvalAlgorithmAdapter` | Same + any BackendAdapter as oracle | `integrations/qforte/adapter.py` |
| Any library | Copy template | Your algorithms | `integrations/template/` |

---

## Error mitigation

| `ErrorMitigationStrategy` | IBM `resilience_level` | Description |
|---|---|---|
| `NONE` | 0 | Raw |
| `DD` | — | Dynamical decoupling |
| `TREX` | 1 | Twirled readout error extinction |
| `ZNE` | 2 | Zero-noise extrapolation + gate twirling |
| `PEC` | 3 | Probabilistic error cancellation |
| `QESEM` | — | Quantum error suppression and mitigation |

When `error_mitigation=ZNE` is set and `zne_config=None`, a default `ZNEConfig(noise_factors=(1.0, 3.0, 5.0), extrapolator="linear")` is populated automatically.

---

## Hooks

Hooks receive every `BenchmarkRecord` after execution and before persistence.

```python
def log_record(record):
    ev  = record.result.expectation_values
    val = ev[0].value if ev else "n/a"
    print(f"[{record.backend.name}] E={val}  status={record.result.status.value}")

runner.add_hook(log_record)
```

Hooks are called in registration order. Exceptions in hooks are logged but do not abort the run.
