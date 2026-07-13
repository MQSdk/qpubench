# QESEM integration

qpubench models the [Qedma QESEM](https://docs.qedma.io/) quantum error suppression and mitigation service in `src/qpubench/schemas/qedma_qesem.py`.

QESEM is available through two interfaces:
- **Native client**: `pip install qedma-api` → `qedma_api.Client`
- **IBM Qiskit Function**: `QiskitFunctionsCatalog.load("qedma/qesem")` on the IBM Quantum platform

QESEM wraps any IBM gate-based backend with:
1. **Device characterization** — noise-learning protocol builds a tailored noise model
2. **Noise-aware transpilation** — maps circuit to physical qubits minimising QPU time
3. **Quasi-probabilistic Error Tuning (QET)** — runs circuits at multiple noise scale factors
4. **Classical post-processing** — extrapolates to a zero-noise unbiased estimate with error bar

Error mitigation strategy in qpubench: `ErrorMitigationStrategy.QESEM`

---

## Quick start

```python
from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.primitives import ComputingModel, ErrorMitigationStrategy, QubitModality
from qpubench.schemas.qedma_qesem import (
    QESEMJobSpec, QESEMObservableSpec, QESEMCircuitOptions,
    QESEMJobOptions, QESEMExecutionMode,
)

backend = BackendSpec.qesem("ibm_fez", api_token_ref="QEDMA_TOKEN")

options = ExecutionOptions(
    shots=10_000,
    error_mitigation=ErrorMitigationStrategy.QESEM,
    qesem_circuit_options=QESEMCircuitOptions(parallel_execution=True),
    qesem_job_options=QESEMJobOptions(execution_mode=QESEMExecutionMode.BATCH),
)
```

---

## Observables

QESEM uses Qedma's Pauli string dict format: comma-separated qubit-indexed Pauli operators mapped to real coefficients.

```python
from qpubench.schemas.qedma_qesem import QESEMObservableSpec

# Average magnetization over 5 qubits
avg_mag = QESEMObservableSpec(
    pauli_terms={"Z0": 0.2, "Z1": 0.2, "Z2": 0.2, "Z3": 0.2, "Z4": 0.2},
    description="average magnetization",
)

# Two-body correlation
zz_corr = QESEMObservableSpec(
    pauli_terms={"Z0,Z1": 1.0},
    description="ZZ correlation (0,1)",
)

# Hamiltonian fragment with non-commuting Paulis
ham_obs = QESEMObservableSpec(
    pauli_terms={"Z0,Z3": 1.0, "X1,Y2": 0.5, "Z2": -0.3},
    description="Hamiltonian observable",
)
```

---

## Job specification

```python
from qpubench.schemas.qedma_qesem import (
    QESEMJobSpec, QESEMObservableSpec, QESEMCircuitOptions,
    QESEMTranspilationLevel, QESEMPrecisionMode,
)

spec = QESEMJobSpec(
    circuit_qasm='OPENQASM 2.0;\nqreg q[5];\nh q[0];\ncx q[0],q[1];\ncx q[1],q[2];',
    num_qubits=5,
    observables=[avg_mag, zz_corr],
    precision=0.05,                                 # target 1-σ = 0.05 for all observables
    precision_mode=QESEMPrecisionMode.CIRCUIT,       # applied per circuit instance
    backend_name="ibm_fez",
    circuit_options=QESEMCircuitOptions(
        transpilation_level=QESEMTranspilationLevel.STANDARD,
        parallel_execution=False,
        error_suppression_only=False,
    ),
    description="GHZ circuit magnetization",
)
```

### Parameterized circuits

```python
# Two circuit instances with different parameter bindings
spec_param = QESEMJobSpec(
    circuit_qasm='OPENQASM 2.0;\nqreg q[4];\n...',  # circuit with rx(param0), rx(param1)
    num_qubits=4,
    observables=[avg_mag],
    precision=0.1,
    backend_name="ibm_fez",
    parameterized_values={
        "param0": [0.5, 0.0],
        "param1": [0.1, 0.6],
    },
    precision_mode=QESEMPrecisionMode.CIRCUIT,
)
```

### QPU time estimation

```python
spec_estimate = QESEMJobSpec(
    circuit_qasm='...',
    observables=[avg_mag],
    precision=0.05,
    backend_name="ibm_fez",
    empirical_time_estimation=True,   # pilot run to estimate cost before full execution
)
```

---

## Quasi-probabilistic Error Tuning (QET)

QET runs the circuit at multiple noise scale factors and extrapolates to the zero-noise limit.

```python
from qpubench.schemas.qedma_qesem import QESEMPrecisionPerFactor

spec_qet = QESEMJobSpec(
    circuit_qasm='...',
    observables=[avg_mag],
    backend_name="ibm_fez",
    # Different precision targets per noise scale
    precision_per_factor=QESEMPrecisionPerFactor(
        scale_precision_map={
            "0.0": 0.10,   # zero-noise extrapolated result
            "1.0": 0.15,   # physical device noise
            "2.0": 0.20,   # 2× noise amplification
        }
    ),
)
```

---

## Results

### Mitigated expectation values

```python
from qpubench.schemas.qedma_qesem import (
    QESEMJobRecord, QESEMCircuitResult, QESEMObservableResult,
    QESEMExpectationValue, QESEMScaleExpectationValue, QESEMNoiseScalingResult,
    QESEMHeuristicResult,
)

# Noise-scaling results from QET
ns = QESEMNoiseScalingResult(
    scaling_method="QESEM",
    results_per_scale=[
        QESEMScaleExpectationValue(value=-0.81, error_bar=0.05, scale=0.0),  # zero-noise
        QESEMScaleExpectationValue(value=-0.56, error_bar=0.04, scale=1.0),  # physical
        QESEMScaleExpectationValue(value=-0.32, error_bar=0.04, scale=2.0),  # amplified
    ]
)
print(f"Scale factors used: {ns.scale_factors}")         # [0.0, 1.0, 2.0]
print(f"Zero-noise result: {ns.zero_noise_result.value}")  # -0.81

# Heuristic extrapolation (QESEM's final best estimate)
heuristic = QESEMHeuristicResult(
    value=-0.80, error_bar=0.05,
    extrapolation="linear",
    scale_factors=[0.0, 1.0, 2.0],
)

# Full observable result
obs_result = QESEMObservableResult(
    unmitigated=QESEMExpectationValue(value=-0.42, error_bar=0.08),  # raw noisy
    noise_scaling=ns,
    qesem_heuristic=[heuristic],
)
print(f"Best mitigated: {obs_result.mitigated.value}")  # -0.80 (uses heuristic)
```

### Circuit result — accessing mitigated values

```python
from qpubench.schemas.qedma_qesem import QESEMCircuitResult, QESEMCircuitObservableResult

circuit_result = QESEMCircuitResult(
    parameter_index=0,
    observable_results=[
        QESEMCircuitObservableResult(observable=avg_mag, result=obs_result),
        QESEMCircuitObservableResult(observable=zz_corr, result=obs_result_2),
    ],
)

print(circuit_result.mitigated_evs)   # [-0.80, -0.31]
print(circuit_result.mitigated_stds)  # [0.05, 0.04]
print(circuit_result.noisy_evs)       # [-0.42, -0.22]
```

---

## Execution details

```python
from qpubench.schemas.qedma_qesem import (
    QESEMExecutionDetails, QESEMTranspiledCircuit,
)

tc = QESEMTranspiledCircuit(
    circuit_qasm="OPENQASM 2.0; ...",
    qubit_maps=[{"0": 12, "1": 13, "2": 14, "3": 15, "4": 16}],
    num_measurement_bases=6,        # distinct Pauli bases needed for observables
)

details = QESEMExecutionDetails(
    total_shots=120_000,            # calibration + characterization + mitigation
    mitigation_shots=30_000,        # purely mitigation allocation
    gate_fidelities={
        "CNOT":  0.9901,            # from QESEM's noise-learning characterization
        "ID1Q":  0.9989,
    },
    transpiled_circuits=[tc],
)
```

---

## Device characterization

```python
from qpubench.schemas.qedma_qesem import (
    QESEMCharacterizationResult, QESEMGateInfidelity,
)

char = QESEMCharacterizationResult(
    qpu_name="ibm_fez",
    measurement_errors={
        12: 0.012,   # qubit 12: 1.2% readout error
        13: 0.009,
        14: 0.015,
        15: 0.011,
        16: 0.008,
    },
    gate_infidelities=[
        QESEMGateInfidelity(gate_name="CNOT", qubits=(12, 13), infidelity=0.0099),
        QESEMGateInfidelity(gate_name="CNOT", qubits=(13, 14), infidelity=0.0087),
        QESEMGateInfidelity(gate_name="CNOT", qubits=(14, 15), infidelity=0.0112),
    ],
    qubit_map={0: 12, 1: 13, 2: 14, 3: 15, 4: 16},
)
```

---

## Full job record

```python
from qpubench.schemas.qedma_qesem import QESEMJobRecord, QESEMJobStatus, QESEMExecutionMode
from qpubench.schemas.result import QuantumResult
from qpubench.schemas.primitives import ComputingModel, QubitModality

record = QESEMJobRecord(
    job_id="qesem-fez-abc123",
    status=QESEMJobStatus.SUCCEEDED,
    qpu_name="ibm_fez",
    spec=spec,
    execution_mode=QESEMExecutionMode.BATCH,
    analytical_qpu_time_s=187.3,
    total_execution_time_s=241.8,
    circuit_results=[circuit_result],
    execution_details=details,
    characterization=char,
)

result = QuantumResult(
    computing_model=ComputingModel.GATE_BASED,
    qubit_modality=QubitModality.SUPERCONDUCTING,
    vendor_results={"qesem_result": record},
)
```

---

## IBM Qiskit Function interface

When using the IBM Qiskit Functions catalog, set `via_qiskit_function=True` and use Qiskit's PUB (Primitive Unified Bloc) format in your adapter:

```python
# Backend spec for Qiskit Function path
backend = BackendSpec.qesem("ibm_fez", via_qiskit_function=True)

# Map QESEMJobSpec back to Qiskit Function run() call:
#   qesem_function.run(
#       pubs=[(circuit, [avg_mag_sparse_pauli_op, zz_sparse_pauli_op])],
#       backend_name="ibm_fez",
#   )
#
# Map results back to QESEMJobRecord:
#   results[0].data.evs          → mitigated_evs
#   results[0].data.stds         → mitigated_stds
#   results[0].metadata["noisy_results"].evs  → noisy_evs
#   results[0].metadata["total_qpu_time"]     → total_execution_time_s
#   results[0].metadata["gate_fidelities"]    → execution_details.gate_fidelities
#   results[0].metadata["total_shots"]        → execution_details.total_shots
#   results[0].metadata["mitigation_shots"]   → execution_details.mitigation_shots
```

---

## Backend

```python
from qpubench.schemas.backend import BackendSpec

# Native qedma-api client
BackendSpec.qesem("ibm_fez",    api_token_ref="QEDMA_TOKEN")
BackendSpec.qesem("ibm_torino", api_token_ref="QEDMA_TOKEN")

# Via IBM Qiskit Functions catalog
BackendSpec.qesem("ibm_fez", via_qiskit_function=True)
```
