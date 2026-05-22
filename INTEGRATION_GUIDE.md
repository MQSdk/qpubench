# QPUBench Integration Guide

How to connect an external quantum library or hardware backend to qpubench.

---

## Core principle

qpubench itself never imports from any quantum library or hardware SDK.
**Your integration code is the only place that imports from both.**

```
your_project/
├── my_qforte_adapter.py    ← imports qpubench + imports qforte
├── my_ibm_adapter.py       ← imports qpubench + imports qiskit_ibm_runtime
└── benchmark.py            ← imports qpubench + imports your adapters
```

qpubench exposes two protocols (abstract interfaces). You implement one.

---

## Which protocol do you need?

| Situation | Protocol |
|-----------|----------|
| Your library accepts a circuit and runs it | `BackendAdapter` |
| Your library generates its own circuit from a problem spec and runs it | `AlgorithmAdapter` |

**BackendAdapter** — the circuit-driven path:
```
qpubench provides circuit → adapter executes it → returns QuantumResult
```

Examples: Qiskit Aer, Qrack GPU simulator, IBM Quantum Runtime, IQM,
MBQC-FPGA, any custom statevector simulator.

**AlgorithmAdapter** — the algorithm-driven path:
```
qpubench provides problem spec → adapter runs algorithm (generates
circuit internally, executes it) → returns (QuantumResult, VQAConfig)
```

Examples: QForte (UCCNVQE, ADAPT-VQE), OpenFermion VQE,
any ADAPT/CISD/FCI implementation that manages its own loop.

---

## 1. Implementing BackendAdapter

Copy `integrations/template/backend_adapter_template.py` into your project
and fill the TODOs.  The minimum you must implement:

```python
from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.result import QuantumResult

class MyBackendAdapter:
    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(name="my_backend", provider="my_provider", simulator=True)

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings = []
        if circuit.num_qubits > 32:
            warnings.append("backend supports at most 32 qubits")
        return warnings

    def run(self, circuit: CircuitSpec, options: ExecutionOptions) -> QuantumResult:
        # 1. Transpile circuit.serialized (QASM2 string) to your gate set
        # 2. Execute
        # 3. Collect results
        ...
```

Register it with the runner and use it immediately:

```python
from qpubench import BenchmarkRunner, ExecutionOptions
from my_project.my_adapter import MyBackendAdapter

runner = BenchmarkRunner()
runner.register(MyBackendAdapter(), name="my_backend")
record = runner.run(circuit, "my_backend", ExecutionOptions(shots=1024))
```

### Two execution paths inside run()

When `circuit.observables` is non-empty → **Estimator path**: return
`QuantumResult.expectation_values`.

When `circuit.observables` is empty → **Sampler path**: return
`QuantumResult.shots` with bitstring counts.

```python
def run(self, circuit, options):
    if circuit.observables:
        # measure ⟨H⟩ for each observable
        evs = [measure_expectation(circuit, obs, options) for obs in circuit.observables]
        return QuantumResult(modality=circuit.modality, expectation_values=evs, ...)
    else:
        # sample bitstrings
        counts = sample_counts(circuit, options.shots)
        return QuantumResult(modality=circuit.modality,
                             shots=ShotResult(..., counts=counts), ...)
```

### Parametric circuits (VQE sweeps)

If your backend supports pre-compilation (Qrack's `.qgc` files, Qiskit's
transpiler pass manager), implement the optional `TranspilableBackend` protocol
and the runner will call `transpile()` once before the sweep:

```python
from qpubench.backends.base import TranspilableBackend
from qpubench.schemas.result import TranspileLayout

class MyTranspilableBackend:
    def transpile(self, circuit, options) -> tuple[CircuitSpec, TranspileLayout | None]:
        transpiled_qasm = my_transpiler.run(circuit.serialized)
        gate_counts     = count_gates(transpiled_qasm)
        return circuit.model_copy(update={
            "serialized":  transpiled_qasm,
            "gate_counts": gate_counts,
        }), None
```

---

## 2. Implementing AlgorithmAdapter (worked example: QForte)

Copy `integrations/template/algorithm_adapter_template.py` into your project.
The QForte integration in `integrations/qforte/` is the reference implementation.

### Step 1 — Represent the problem as a CircuitSpec

For chemistry, use `format=MOLECULE_JSON`:

```python
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.primitives import CircuitFormat

mol_spec = CircuitSpec(
    num_qubits=0,                        # fill after building the system
    format=CircuitFormat.MOLECULE_JSON,
    serialized="/path/to/He-ccpvdz.json",   # or inline JSON
)
```

The `serialized` field carries whatever your library needs to build the system:
a file path, an inline JSON dict, a SMILES string, a graph adjacency matrix, etc.

### Step 2 — Specify the algorithm via AlgorithmSpec

```python
from qpubench import AlgorithmSpec, ExecutionOptions

options = ExecutionOptions(
    algorithm_spec=AlgorithmSpec(
        name="ADAPTVQE",
        pool_type="SD",
        optimizer="BFGS",
        avqe_thresh=1.0e-4,
        adapt_maxiter=20,
    )
)
```

`AlgorithmSpec.extra_params` is an escape hatch for any algorithm-specific
keyword arguments your library needs that are not covered by the standard fields.

### Step 3 — Implement the adapter

```python
# my_qforte_adapter.py
import json
from pathlib import Path
import qforte as qf                      # ← only import here
from qpubench.backends.base import AlgorithmAdapter
from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.primitives import CircuitFormat, JobStatus, QPUModality
from qpubench.schemas.record import VQAConfig
from qpubench.schemas.result import ExpectationResult, QuantumResult

class QForteAdapter:
    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(name="qforte_statevector", provider="qforte", simulator=True)

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        if circuit.format != CircuitFormat.MOLECULE_JSON:
            return [f"Expected MOLECULE_JSON, got {circuit.format.value!r}"]
        return []

    def run_algorithm(
        self, circuit: CircuitSpec, options: ExecutionOptions
    ) -> tuple[QuantumResult, VQAConfig]:
        # 1. Build system
        mol = qf.system_factory(
            system_type="molecule",
            build_type="external",
            basis="",
            filename=circuit.serialized,
        )
        # 2. Run algorithm
        alg_spec = options.algorithm_spec
        alg = getattr(qf, alg_spec.name)(mol, print_summary_file=False)
        alg.run(
            pool_type=alg_spec.pool_type,
            optimizer=alg_spec.optimizer,
            opt_thresh=alg_spec.opt_thresh,
        )
        # 3. Extract results
        energy = float(alg.get_gs_energy())
        result = QuantumResult(
            modality=QPUModality.GATE_BASED,
            expectation_values=[ExpectationResult(observable_index=0,
                                                  value=energy, std_error=0.0)],
            status=JobStatus.SUCCEEDED,
        )
        vqa = VQAConfig(
            problem_type="chemistry",
            algorithm=alg_spec.name,
            final_eigenvalue=energy,
            ground_truth=float(getattr(mol, "fci_energy", 0.0)) or None,
        )
        return result, vqa
```

### Step 4 — Register and run

The runner detects `AlgorithmAdapter` automatically via `isinstance()`:

```python
from qpubench import BenchmarkRunner, NDJSONStore
runner = BenchmarkRunner(store=NDJSONStore("results.ndjson"))
runner.register(QForteAdapter(), name="qforte")
record = runner.run(mol_spec, "qforte", options)
print(record.vqa.chemical_accuracy)
```

### Complete QForte integration

`integrations/qforte/` contains a production-ready version covering:
- `QForteAlgorithmAdapter` — uses QForte's internal C++ statevector
- `ExternalEvalAlgorithmAdapter` — overrides `energy_feval()` to forward each
  energy evaluation to any qpubench `BackendAdapter` (Aer, Qrack GPU, IBM, …)
- `AdaptVQERunner` — compare optimizers, pool types, and algorithms
- `ExternalEvalAdaptVQERunner` — same comparisons on an external backend
- QASM2 converter, HF state prep, convergence table helpers

---

## 3. The energy evaluator hook (advanced)

When using an `AlgorithmAdapter`, the library runs on its own internal simulator.
To instead use a qpubench backend for *each individual energy evaluation* inside
the optimizer loop, override the library's energy callback:

```python
# The library's optimizer calls energy_feval(params) → float.
# We subclass and override it to call our qpubench backend instead.

class HookedQForteADAPT(qf.ADAPTVQE):
    def __init__(self, *args, hook, **kwargs):
        super().__init__(*args, **kwargs)
        self._hook = hook

    def energy_feval(self, params):
        self._tamps = list(params)
        try:
            circuit = self.build_Uvqc()   # QForte builds the current circuit
            return self._hook.evaluate(circuit)
        except Exception:
            return super().energy_feval(params)   # fall back on error
```

`integrations/qforte/energy_hook.py` provides `EnergyEvaluatorHook` and
`make_hooked_class()` which do exactly this — see that file for the complete
implementation.

This pattern applies to any library where:
1. The optimizer loop is in Python (`scipy.minimize`, `numpy`, or custom)
2. The energy callback is an overridable Python method

---

## 4. Accessing qpubench types in your adapter

All public types are importable from the top-level package:

```python
from qpubench import (
    AlgorithmSpec,        # algorithm name + hyperparameters
    BackendSpec,          # hardware/simulator description
    BenchmarkRecord,      # one execution record
    BenchmarkRunner,      # orchestrator
    CircuitFormat,        # QASM2, QGC, MOLECULE_JSON, …
    CircuitSpec,          # circuit or problem specification
    ComplexNumber,        # JSON-safe complex: {re, im}
    ErrorMitigationStrategy,
    ExecutionOptions,     # shots, mitigation, transpiler, algorithm_spec
    ExpectationResult,    # value + std_error for one observable
    FidelityMetric,
    FidelityResult,
    JobStatus,
    NDJSONStore,          # append-only result store
    PauliLabel,           # I/X/Y/Z with Qrack/Qiskit-C converters
    PauliTerm,            # one term in a sparse Pauli sum
    QPUModality,          # GATE_BASED or MBQC
    QuantumResult,        # top-level execution result
    ShotResult,           # bitstring counts + optional per-shot memory
    SparsePauliObservable,
    TranspileLayout,      # virtual → physical qubit mapping
    TranspilerConfig,     # layout_method, routing_method, approx_degree
    VQAConfig,            # VQE metadata: molecule, energy, convergence
    ZNEConfig,            # zero-noise extrapolation parameters
    AdaptIteration,       # per-ADAPT-iteration metrics
)
```

The backend protocols are in `qpubench.backends.base`:

```python
from qpubench.backends.base import (
    BackendAdapter,        # circuit-driven: spec, validate(), run()
    AlgorithmAdapter,      # algorithm-driven: spec, validate_problem(), run_algorithm()
    TranspilableBackend,   # optional: transpile() returns (CircuitSpec, TranspileLayout)
)
```

---

## 5. Testing your adapter (no real hardware required)

Write mock-based unit tests that replace the external library with `MagicMock`.
The pattern from `tests/test_schemas.py`:

```python
from unittest.mock import MagicMock, patch
from qpubench import BenchmarkRunner, AlgorithmSpec, ExecutionOptions
from qpubench.schemas.primitives import JobStatus

def test_my_adapter_succeeds():
    # Arrange: mock the external library
    mock_lib = MagicMock()
    mock_lib.solve.return_value = -2.9003

    # Act: patch the import inside your adapter module
    with patch("my_adapter.my_library", mock_lib):
        from my_adapter import MyAlgorithmAdapter
        runner = BenchmarkRunner()
        runner.register(MyAlgorithmAdapter(), name="mine")
        record = runner.run(mol_spec, "mine", ExecutionOptions())

    # Assert
    assert record.result.status == JobStatus.SUCCEEDED
    assert record.vqa.final_eigenvalue == -2.9003
```

Use `pytest` with no extra dependencies — the test suite in `tests/test_schemas.py`
shows 61 tests that run entirely without any quantum SDK.

---

## 6. Common pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| `PauliLabel.Z.to_qrack_int()` returns 2, not 3 | Qrack uses Q# convention: I=0, X=1, **Z=2**, **Y=3** | Always use `PauliLabel.to_qrack_int()`, never raw integers |
| Qiskit C API gets wrong amplitudes | `QkComplex64` is two `float32`, not `float64` | Use `numpy.complex64`, not Python `complex` |
| MBQC byproduct update is wrong | `ops` register: **bit 0 = Z, bit 1 = X** (reversed from gate-based convention) | See `schemas/mbqc.py` |
| Algorithm adapter not detected | `AlgorithmAdapter` check uses `isinstance()` | Your class must have `validate_problem` and `run_algorithm` methods |
| Tests fail without QForte installed | Adapter imports qforte at module level | Move the `import qforte` inside the method that uses it |

---

## 7. Reference implementations

| Directory | Backend / Library | Protocol |
|-----------|-------------------|----------|
| `src/qpubench/backends/stub.py` | Stub (no deps, random results) | `BackendAdapter` |
| `src/qpubench/backends/aer_adapter.py` | Qiskit Aer | `BackendAdapter` + `TranspilableBackend` (fill TODOs) |
| `src/qpubench/backends/ibm_adapter.py` | IBM Quantum Runtime V2 | `BackendAdapter` + `TranspilableBackend` (fill TODOs) |
| `src/qpubench/backends/qrack_adapter.py` | PyQrack GPU simulator | `BackendAdapter` (fill TODOs) |
| `integrations/template/backend_adapter_template.py` | Generic gate-based | `BackendAdapter` template |
| `integrations/template/algorithm_adapter_template.py` | Generic algorithm library | `AlgorithmAdapter` template |
| `integrations/qforte/adapter.py` | QForte (UCCNVQE, ADAPT-VQE) | `AlgorithmAdapter` — complete implementation |
| `integrations/qforte/energy_hook.py` | QForte + external backend | Energy evaluator hook — complete implementation |
