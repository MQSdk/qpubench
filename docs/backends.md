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

### Real adapters (SDK required)

`aer_adapter.py`, `ibm_adapter.py`, `iqm_adapter.py`, and `braket_adapter.py`
in `src/qpubench/backends/` are real, working implementations (no TODOs) —
verified against the installed SDKs (`qiskit-aer` 0.17.x, `qiskit-ibm-runtime`
0.47.x, `iqm-client[qiskit]` 34.x, `amazon-braket-sdk` + `qiskit-braket-provider`
0.17.x):

| File | Backend | Provider string | Tested how |
|---|---|---|---|
| `aer_adapter.py` | Qiskit Aer statevector + QASM (EstimatorV2/SamplerV2) | `"aer"` | Fully executed — no credentials needed |
| `braket_adapter.py` | AWS Braket (via `qiskit-braket-provider`'s `BraketSampler`/`BraketEstimator`) | `"aws_braket"` | Fully executed via `BraketLocalBackend` (`device_arn="local"`) — no AWS account needed |
| `ibm_adapter.py` | IBM Quantum Runtime V2 (Session/Batch/Single, TREX/ZNE/PEC resilience) | `"ibm"` | Transpile/run logic fully executed against `qiskit_ibm_runtime.fake_provider.FakeManilaV2`; only the credential-fetching `QiskitRuntimeService` call needs a real account |
| `iqm_adapter.py` | IQM hardware (Sampler path only — no Estimator; see below) | `"iqm"` | Transpile/run logic fully executed against `iqm.qiskit_iqm.fake_backends.IQMFakeAdonis`; only the credential-fetching `IQMProvider` call needs a real account |

`qrack_adapter.py` remains a stub (`raise NotImplementedError`, TODOs in the
docstring) — out of scope for the pass that made the other four real.

IQM's Estimator path (`circuit.observables` populated) still raises
`NotImplementedError` — this is a real, current upstream limitation
(`iqm-client[qiskit]` exposes no `EstimatorV2`-equivalent as of 34.x), not
an unfinished stub. Use the Sampler path and reconstruct expectation values
classically from counts.

**Package-name change**: the standalone `qiskit-iqm`/`qiskit_on_iqm`
packages are now obsolete (importing raises
`RuntimeError: The qiskit-iqm package is obsolete ... use iqm-client[qiskit]
instead`, confirmed empirically). Install `pip install 'qpubench[iqm]'`
(`iqm-client[qiskit]`), which bundles the same functionality under the
`iqm.qiskit_iqm` / `iqm.iqm_client` namespace.

**Dependency note**: `iqm-client[qiskit]` and the `qiskit`/`braket` extras
were verified to coexist in one environment (`qiskit>=2.2`, `qiskit-aer`
>=0.17, `numpy<2.5` for `numba`/`braket`'s default simulator) — install
`pip install 'qpubench[qiskit,braket,iqm]'` together without conflict.

### Resource / cost estimation (before you submit anything)

`ibm_cost_estimator.py` estimates what a circuit/study will cost on real
IBM Quantum hardware *before* running it — real ALAP-scheduled
transpilation against `qiskit_ibm_runtime.fake_provider` (no credentials
needed) plus IBM's own documented usage formula, then a dollar breakdown
across all four IBM access plans (`schemas/ibm_cost_estimator.py`). Full
documentation → [docs/integrations/ibm_cost_estimator.md](integrations/ibm_cost_estimator.md).

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
from qpubench.schemas.primitives import ComputingModel, JobStatus
from qpubench.schemas.result import ExpectationResult, QuantumResult, ShotResult

class MyBackendAdapter:

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(name="my_backend", provider="my_provider",
                           simulator=True, computing_model=ComputingModel.GATE_BASED)

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
                computing_model=circuit.computing_model,
                qubit_modality=circuit.qubit_modality,
                expectation_values=[
                    ExpectationResult(observable_index=0, value=energy, std_error=0.0)
                ],
                status=JobStatus.SUCCEEDED,
            )
        else:
            # Sampler path
            counts = my_sdk.sample(circuit.serialized, shots=options.shots)
            return QuantumResult(
                computing_model=circuit.computing_model,
                qubit_modality=circuit.qubit_modality,
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

### Gate-based

| Backend | Provider | Computing model | Qubit modality | Adapter | Status |
|---|---|---|---|---|---|
| Qiskit Aer (statevector + QASM) | `"aer"` | `GATE_BASED` | — (simulator) | `AerAdapter` | Real, tested — EstimatorV2/SamplerV2 |
| IBM Quantum Runtime V2 | `"ibm"` | `GATE_BASED` | `SUPERCONDUCTING` | `IBMAdapter` | Real, tested against a fake backend — implements `TranspilableBackend`; needs real credentials for live hardware |
| IQM hardware | `"iqm"` | `GATE_BASED` | `SUPERCONDUCTING` | `IQMAdapter` | Real, tested against a fake backend — implements `TranspilableBackend`; Sampler path only (no Estimator — real upstream limitation); `BackendSpec.iqm()` / `.iqm_resonance()` / `.iqm_local_server()` |
| Qrack GPU/CPU simulator | `"qrack"` | `GATE_BASED` | — (simulator) | `QrackAdapter` | Stub — fill TODOs in `qrack_adapter.py` |
| AWS Braket (Rigetti/IonQ/OQC/SV1/DM1/TN1) | `"aws_braket"` | `GATE_BASED` | configurable | `BraketAdapter` | Real, tested via `BraketLocalBackend` — implements `TranspilableBackend`; `BackendSpec.braket(device_arn)`; via `qiskit-braket-provider` |
| Qibo cloud | `"qibo"` | `GATE_BASED` | — | Copy `backend_adapter_template.py` | |
| PennyLane `lightning.qubit` | `"pennylane"` | `GATE_BASED` | — (simulator) | Copy template | `BackendSpec.lightning_qubit()` |
| CUDA-Q | `"cudaq"` | `GATE_BASED` | — (simulator) | Copy template | `BackendSpec.cudaq()` |
| Cebule cloud | `"cebule"` | `GATE_BASED` | — (heterogeneous) | Copy template | `BackendSpec.cebule()` |
| Quantum Motion CMOS spin-qubit | `"quantum_motion"` | `GATE_BASED` | `SILICON_SPIN` | Copy template | `BackendSpec.quantum_motion(device_name)` |
| Stub gate simulator | — | `GATE_BASED` | — (simulator) | `StubGateAdapter` | Fully functional, no SDK |
| Stub MBQC simulator | — | `MBQC` | — | `StubMBQCAdapter` | Fully functional, no SDK |
| MBQC-FPGA | `"mbqc"` | `MBQC` | — (FPGA control logic) | Copy `backend_adapter_template.py` | Schemas complete; COE + CSV round-trip |

### Photonic (linear-optics / FBQC)

`ComputingModel` and `QubitModality` are independent — all four factories below set `qubit_modality=PHOTONIC`; the paradigm running on that hardware is `GATE_BASED` for linear-optics circuits (MZI/permanent-based), or set `computing_model=FUSION_BASED` explicitly for FBQC resource-state + fusion-gate circuits.

| Backend | Provider | Computing model | Qubit modality | Factory | Notes |
|---|---|---|---|---|---|
| photochipsim | `"photochipsim"` | `GATE_BASED` | `PHOTONIC` | `BackendSpec.photochipsim(num_modes)` | thewalrus permanent engine |
| Strawberry Fields Fock | `"strawberry_fields"` | `GATE_BASED` | `PHOTONIC` | `BackendSpec.strawberry_fields(backend, num_modes, cutoff_dim)` | Fock-basis; also `"gaussian"` or `"tf"` backend |
| Quandela Perceval | `"perceval"` | `GATE_BASED` | `PHOTONIC` | `BackendSpec.perceval(backend, num_modes)` | SLOS / MPS / Naive |
| Photonic chip hardware | `"photonic_hardware"` | `GATE_BASED` | `PHOTONIC` | `BackendSpec.photonic_chip_hardware(chip_id, platform, num_modes)` | SiN, SOI, InP, LN platforms |

### GBS (Gaussian Boson Sampling)

| Backend | Provider | Computing model | Qubit modality | Factory | Notes |
|---|---|---|---|---|---|
| Xanadu X8 | `"xanadu"` | `GBS` | `PHOTONIC` | `BackendSpec.xanadu_x8(num_modes=8)` | 8-mode PNR hardware; Xanadu Cloud |
| Xanadu Borealis | `"xanadu"` / `"aws_braket"` | `GBS` | `PHOTONIC` | `BackendSpec.xanadu_borealis(via_braket=False)` | 216-mode TDM; `via_braket=True` for AWS |
| Strawberry Fields Gaussian | `"strawberry_fields"` | `GBS` | `PHOTONIC` | `BackendSpec.strawberry_fields_gaussian(num_modes)` | Covariance-matrix + thewalrus hafnian |

### QPE / QDK chemistry

QPE/IQPE is an algorithmic technique on top of gate-based circuits (see `QPEMethod` in `microsoft_qdk`), not a separate paradigm.

| Backend | Provider | Computing model | Qubit modality | Factory | Notes |
|---|---|---|---|---|---|
| QDK simulator | `"qdk_chemistry"` | `GATE_BASED` | — (simulator) | `BackendSpec.qdk_chemistry_simulator(executor, num_qubits)` | Sparse / full state vector |
| Azure Quantum | `"azure_quantum"` | `GATE_BASED` | `TRAPPED_ION` (Quantinuum/IonQ hardware) or — (simulator/estimator) | `BackendSpec.azure_quantum(target, *, resource_id_ref, location_ref, qubit_modality)` | Hardware + resource estimator; QPU modality inferred from `target` or pass explicitly |

### KQD / QSE

KQD is an algorithmic technique on top of gate-based circuits (see `KQDMethod` in `mqsdk_qse`), not a separate paradigm.

| Backend | Provider | Computing model | Qubit modality | Factory | Notes |
|---|---|---|---|---|---|
| Qiskit Aer (KQD) | `"aer"` | `GATE_BASED` | — (simulator) | `BackendSpec.qiskit_aer(method="statevector", num_qubits)` | statevector / MPS / stabilizer |

### QESEM (Qedma)

| Backend | Provider | Computing model | Qubit modality | Factory | Notes |
|---|---|---|---|---|---|
| QESEM native client | `"qedma"` | `GATE_BASED` + `QESEM` | `SUPERCONDUCTING` | `BackendSpec.qesem(backend_name, *, api_token_ref, via_qiskit_function=False)` | Wraps any IBM backend with noise-aware QET mitigation |
| QESEM via Qiskit Function | `"qedma"` | `GATE_BASED` + `QESEM` | `SUPERCONDUCTING` | `BackendSpec.qesem(backend_name, via_qiskit_function=True)` | Submitted through IBM Qiskit Functions catalog |

### Neutral atom (Rydberg / AHS)

| Backend | Provider | Computing model | Qubit modality | Factory | Notes |
|---|---|---|---|---|---|
| QuEra Aquila 256-qubit QPU | `"quera"` | `ADIABATIC` | `NEUTRAL_ATOM` | `BackendSpec.aquila(aws_region="us-east-1")` | Analog Hamiltonian Simulation; submitted via AWS Braket |
| Bloqade Python emulator | `"bloqade"` | `ADIABATIC` | `NEUTRAL_ATOM` | `BackendSpec.bloqade_emulator(num_qubits)` | Local exact state-vector; no credentials; practical up to ~20 atoms |

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
