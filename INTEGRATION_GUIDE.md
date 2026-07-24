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
Quantinuum H-Series, Qibo (simulator / Qibolab / cloud), MBQC-FPGA, any
custom statevector simulator.

**AlgorithmAdapter** — the algorithm-driven path:
```
qpubench provides problem spec → adapter runs algorithm (generates
circuit internally, executes it) → returns (QuantumResult, VQAConfig, VQAResult)
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
`integrations/qforte/` is one worked example of an `AlgorithmAdapter` — not
the only one. `AlgorithmFamily.ADAPT_VQE` (see `AlgorithmSpec.family`) is
implemented three ways in this repo: QForte's native C++ engine
(`integrations/qforte/`), a from-scratch Qiskit-circuit-convention engine
(`integrations/ibm_qiskit_adapt_vqe/`), and a QDK/Azure Quantum-flavored
one (`integrations/microsoft_qdk_adapt_vqe/`) — the latter two share a
single package-agnostic engine (`integrations/generic_adapt_vqe/`) and
differ only in `BackendSpec` naming. Register any of the three under
different names and switch between them with the same `AdaptVQEConfig`:

```python
runner.register(QForteAlgorithmAdapter(), name="qforte")
runner.register(IBMQiskitAdaptVQEAdapter(energy_backend=aer), name="ibm_qiskit")
config = AdaptVQEConfig(pool_type="SD", optimizer="BFGS")
record = runner.run(mol, "qforte", ExecutionOptions(adapt_vqe_config=config))       # or:
record = runner.run(mol, "ibm_qiskit", ExecutionOptions(adapt_vqe_config=config))   # same config, different implementation
```

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

### Step 2 — Specify the algorithm via AlgorithmSpec + a hyperparameter config

`AlgorithmSpec` only carries identity (`name` + `family`); hyperparameters
live in a family-specific config so they aren't duplicated per adapter.
`AlgorithmFamily.ADAPT_VQE` uses the package-agnostic `AdaptVQEConfig`,
shared by every ADAPT-VQE-family adapter:

```python
from qpubench import AdaptVQEConfig, AlgorithmFamily, AlgorithmSpec, ExecutionOptions

options = ExecutionOptions(
    algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
    adapt_vqe_config=AdaptVQEConfig(
        pool_type="SD",
        optimizer="BFGS",
        gradient_threshold=1.0e-4,
        max_macro_iterations=20,
    ),
)
```

`AlgorithmSpec.extra_params` is an escape hatch for adapter-specific kwargs
not covered by the typed config (e.g. QForte-only knobs like
`diis_max_dim` — see `evangelistalab_qforte.QForteAlgorithmConfig`).

### Step 3 — Implement the adapter

```python
# my_qforte_adapter.py
import json
from pathlib import Path
import qforte as qf                      # ← only import here
from qpubench.backends.base import AlgorithmAdapter
from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import AdaptVQEConfig, ExecutionOptions
from qpubench.schemas.primitives import CircuitFormat, ComputingModel, JobStatus
from qpubench.schemas.record import VQAConfig, VQAResult
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
    ) -> tuple[QuantumResult, VQAConfig, VQAResult]:
        # 1. Build system
        mol = qf.system_factory(
            system_type="molecule",
            build_type="external",
            basis="",
            filename=circuit.serialized,
        )
        # 2. Run algorithm
        alg_spec = options.algorithm_spec
        cfg      = options.adapt_vqe_config or AdaptVQEConfig()
        alg = getattr(qf, alg_spec.name)(mol, print_summary_file=False)
        alg.run(
            pool_type=cfg.pool_type,
            optimizer=cfg.optimizer,
            opt_thresh=cfg.energy_threshold,
        )
        # 3. Extract results
        energy = float(alg.get_gs_energy())
        result = QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=[ExpectationResult(observable_index=0,
                                                  value=energy, std_error=0.0)],
            status=JobStatus.SUCCEEDED,
        )
        vqa = VQAConfig(
            problem_type="chemistry",
            algorithm=alg_spec.name,
        )
        vqa_result = VQAResult(
            final_eigenvalue=energy,
            ground_truth=float(getattr(mol, "fci_energy", 0.0)) or None,
        )
        return result, vqa, vqa_result
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
- `QForteAlgorithmAdapter` — uses QForte's internal C++ statevector; results
  are captured as a typed `evangelistalab_qforte.QForteRunResult` (both the
  pybind11 object layer — `QForteCircuitSpec`, `QForteQubitOperatorSpec` —
  and the algorithm-attribute layer are modeled in `schemas/evangelistalab_qforte.py`)
- `ExternalEvalAlgorithmAdapter` — overrides `energy_feval()` to forward each
  energy evaluation to any qpubench `BackendAdapter` (Aer, Qrack GPU, IBM, …)
- `AdaptVQERunner` — compare optimizers, pool types, and algorithms
- `ExternalEvalAdaptVQERunner` — same comparisons on an external backend
- QASM2 converter, HF state prep, convergence table helpers

### Other AlgorithmFamily.ADAPT_VQE implementations

Two more adapters implement the same family without needing QForte
installed at all — `integrations/generic_adapt_vqe/` is a pure-Python
(+ scipy) ADAPT-VQE engine (fermionic singles+doubles pool, Jordan-Wigner
mapping, Pauli-exponential circuit synthesis, finite-difference gradient
screening — all independently verified against dense-matrix ground truth
in `tests/test_generic_adapt_vqe.py`) that any qpubench `BackendAdapter`
can drive:
- `integrations/ibm_qiskit_adapt_vqe/` — Qiskit-style OpenQASM 3.0 circuits
- `integrations/microsoft_qdk_adapt_vqe/` — QDK / Azure Quantum defaults

Register any of the three under different names and pass the same
`AdaptVQEConfig` to compare them directly in the same `BenchmarkRecord` format.

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
    ComputingModel,       # GATE_BASED, MBQC, GBS, ADIABATIC, ...
    QubitModality,        # SUPERCONDUCTING, TRAPPED_ION, NEUTRAL_ATOM, PHOTONIC, SILICON_SPIN
    QuantumResult,        # top-level execution result
    ShotResult,           # bitstring counts + optional per-shot memory
    SparsePauliObservable,
    TranspileLayout,      # virtual → physical qubit mapping
    TranspilerConfig,     # layout_method, routing_method, approx_degree
    VQAConfig,            # VQE inputs: molecule, ansatz, optimizer
    VQAResult,            # VQE computed outputs: energy, convergence
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
    assert record.vqa_result.final_eigenvalue == -2.9003
```

Use `pytest` with no extra dependencies — the test suite in `tests/test_schemas.py`
shows 61 tests that run entirely without any quantum SDK.

---

## 6. Common pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| `PauliLabel.Z.to_qrack_int()` returns 2, not 3 | Qrack uses Q# convention: I=0, X=1, **Z=2**, **Y=3** | Always use `PauliLabel.to_qrack_int()`, never raw integers |
| Qiskit C API gets wrong amplitudes | `QkComplex64` is two `float32`, not `float64` | Use `numpy.complex64`, not Python `complex` |
| MBQC byproduct update is wrong | `ops` register: **bit 0 = Z, bit 1 = X** (reversed from gate-based convention) | See `schemas/johnrscott_mbqc_fpga.py` |
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
| `src/qpubench/backends/braket_adapter.py` | AWS Braket (Rigetti/IonQ/OQC/SV1/DM1/TN1) | `BackendAdapter` (fill TODOs) |
| `src/qpubench/backends/quantinuum_adapter.py` | Quantinuum H-Series (trapped-ion, via pytket) | `BackendAdapter` + `TranspilableBackend` (fill TODOs) |
| `src/qpubench/backends/qibo_adapter.py` | Qibo (local simulator / Qibolab hardware / Qibo cloud) | `BackendAdapter` (fill TODOs) |
| `integrations/template/backend_adapter_template.py` | Generic gate-based | `BackendAdapter` template |
| `integrations/template/algorithm_adapter_template.py` | Generic algorithm library | `AlgorithmAdapter` template |
| `integrations/qforte/adapter.py` | QForte (UCCNVQE, ADAPT-VQE) | `AlgorithmAdapter` — complete implementation |
| `integrations/qforte/energy_hook.py` | QForte + external backend | Energy evaluator hook — complete implementation |
