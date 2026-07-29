# Backends & adapters

An **adapter** is the piece of code that connects qpubench to something that can execute quantum programs — a simulator, real hardware behind a cloud API, or an algorithm library. Adapters translate between qpubench's SDK-neutral schemas (`CircuitSpec` in, `QuantumResult` out) and whatever the underlying SDK speaks natively. You register adapters with a `BenchmarkRunner` under a name of your choice, and every run through the runner produces the same `BenchmarkRecord` regardless of which adapter executed it.

There are two adapter protocols, because there are two fundamentally different kinds of execution engine:

- A **backend** (simulator or QPU) executes a circuit *you* wrote — you hand it a finished `CircuitSpec` and get results back. This is the `BackendAdapter` protocol.
- An **algorithm library** (QForte, an ADAPT-VQE engine, …) does not accept a pre-written circuit at all. It takes a *problem specification* (a molecule, a Hamiltonian), generates circuits internally, and drives its own optimization loop. This is the `AlgorithmAdapter` protocol.

Both register with the same `BenchmarkRunner` and both produce `BenchmarkRecord`s — that is why they live side by side: the runner is the single entry point for "run this and store a comparable record", whether "this" is one circuit or a whole algorithm run. The runner dispatches automatically based on which protocol the registered adapter satisfies (an `isinstance()` check against the runtime-checkable protocols); you never tell it which path to take.

Note the distinction between a **backend** and an **algorithm**: VQE, QPE, and KQD are algorithms, not backends. A variational algorithm like plain VQE runs *through* a `BackendAdapter` (each energy evaluation is one circuit run — see [VQA algorithms](vqa.md)); a self-driving implementation like QForte's ADAPT-VQE is wrapped as an `AlgorithmAdapter`; and QPE/KQD are currently schema-only (they describe runs, but no adapter executes them — see the [known gaps](../README.md#known-gaps--open-todos)).

---

## Protocols

### `BackendAdapter` — circuit-driven

```
validate(circuit: CircuitSpec) → list[str]
run(circuit: CircuitSpec, options: ExecutionOptions) → QuantumResult
spec: BackendSpec
```

Use this when **you** provide the circuit and the backend executes it.  
Examples: Qiskit Aer, PennyLane Lightning, IBM Quantum Runtime, IQM, AWS Braket, Quantinuum, Qibo, MBQC-FPGA.

The three members:

- **`spec`** — a static `BackendSpec` describing the machine (name, provider, simulator or hardware, computing model, qubit modality). It is copied into every `BenchmarkRecord`, so stored records identify the machine without the adapter present.
- **`validate(circuit)`** — a pre-flight check the runner calls before `run()`. It returns a list of human-readable *warnings* (empty list = nothing to flag) for recoverable concerns — unsupported gate names, qubit count near the limit, unbound parameters — and raises `ValueError` only for hard errors that make execution meaningless (wrong computing model, malformed circuit). Warnings don't abort the run; they are surfaced so a benchmark sweep can proceed while telling you which runs are questionable.
- **`run(circuit, options)`** — transpiles (if the backend needs it), executes, and returns a `QuantumResult`. Recoverable failures (a cloud job that errored) come back as `status=FAILED` with an `error_message` rather than an exception, so one failed point doesn't kill a sweep.

### `AlgorithmAdapter` — algorithm-driven

```
validate_problem(circuit: CircuitSpec) → list[str]
run_algorithm(circuit: CircuitSpec, options: ExecutionOptions) → tuple[QuantumResult, VQAConfig, VQAResult]
spec: BackendSpec
```

Use this when the **library generates its own circuit** from a problem specification and drives its own execution loop.  
Examples: QForte (ADAPT-VQE, UCCNVQE), OpenFermion VQE stacks.

The `CircuitSpec` argument here carries a *problem*, not gates: `format=CircuitFormat.MOLECULE_JSON` with `serialized` holding a molecule JSON dict or file path. Which algorithm to run is specified in `options.algorithm_spec`, and its hyperparameters in the family-specific config (e.g. `options.adapt_vqe_run_config`). The two protocol methods mirror `BackendAdapter`'s:

- **`validate_problem(circuit)`** — same contract as `validate()`, but checks the problem specification (does the file exist, is the molecule dict well-formed) instead of a gate list.
- **`run_algorithm(circuit, options)`** — runs the full algorithm and returns three objects instead of one: the `QuantumResult` (execution outcome), a `VQAConfig` (the experiment inputs as the library understood them), and a `VQAResult` (computed outputs — final energy, convergence history). An algorithm run produces all three, whereas a single circuit run only produces a result.

### `TranspilableBackend` — optional extension

```
transpile(circuit: CircuitSpec, options: ExecutionOptions) → tuple[CircuitSpec, TranspileLayout]
```

Implement this on a `BackendAdapter` to expose transpilation as a separate, callable step. The runner does **not** call it automatically — adapters that need transpilation (IBM, IQM, Braket) invoke it themselves inside `run()`; call `adapter.transpile(...)` directly if you want the transpiled circuit or layout beforehand.

---

## Built-in adapters

### Adapter index

This table is the **authoritative list** of every adapter that ships in `src/qpubench/backends/`. Code does not duplicate it — docstrings in `runner.py` and `base.py` point here instead, so there is one place to update when an adapter is added.

| Class | File | Protocol | Kind | Estimator path | Status |
|---|---|---|---|---|---|
| `StubGateAdapter` | `stub.py` | `BackendAdapter` | stub | yes (synthetic) | complete |
| `StubMBQCAdapter` | `stub.py` | `BackendAdapter` | stub | — (MBQC) | complete |
| `AerAdapter` | `aer_adapter.py` | `BackendAdapter` + `TranspilableBackend` | simulator | **yes** | complete |
| `PennyLaneLightningAdapter` | `pennylane_lightning_adapter.py` | `BackendAdapter` | simulator | **yes** | complete |
| `QrackAdapter` | `qrack_adapter.py` | `BackendAdapter` | simulator | **yes** | complete |
| `IBMAdapter` | `ibm_adapter.py` | `BackendAdapter` + `TranspilableBackend` | hardware (cloud) | **yes** | complete |
| `BraketAdapter` | `braket_adapter.py` | `BackendAdapter` + `TranspilableBackend` | hardware (cloud) | **yes** | complete |
| `IQMAdapter` | `iqm_adapter.py` | `BackendAdapter` + `TranspilableBackend` | hardware (cloud) | no — sampler only | complete |
| `QuantinuumAdapter` | `quantinuum_adapter.py` | `BackendAdapter` + `TranspilableBackend` | hardware (cloud) | no — sampler only | complete |
| `QiboAdapter` | `qibo_adapter.py` | `BackendAdapter` | simulator + hardware | no — sampler only | complete |
| `MitiqZNEAdapter` | `unitaryfund_mitiq_adapter.py` | `ErrorMitigationAdapter` | wrapper | **yes** (required) | complete |

`ibm_cost_estimator.py` is not in this table because it is not an adapter — it estimates resources and cost without executing anything. See [Resource / cost estimation](#resource--cost-estimation-before-you-submit-anything).

Algorithm adapters (`AlgorithmAdapter`) ship as copyable examples under `integrations/`, not inside the package — see [Integration examples](#integration-examples-copy-into-your-project) and [Algorithm libraries](#algorithm-libraries-algorithmadapter).

### Does a missing Estimator path matter?

Four adapters implement both execution paths; three implement only the sampler path. The split is not an oversight, and it does have consequences worth knowing.

**Why the split exists.** The Estimator path asks a backend for an *expectation value* ⟨ψ|O|ψ⟩ directly. A simulator can compute that exactly from the statevector, and IBM's and Braket's cloud services expose a server-side `EstimatorV2` primitive that does the observable grouping, twirling and error mitigation for you. IQM, Quantinuum and Qibo's hardware stacks return measurement samples and nothing else — there is no `EstimatorV2`-equivalent in their SDKs to delegate to. Those adapters raise a clear `ValueError` naming the limitation rather than silently doing something else.

**What you lose on a sampler-only backend.**

- `circuit.observables` is not usable directly. You must add basis-change gates yourself, sample, and reconstruct ⟨O⟩ from the counts — for a Hamiltonian with many non-commuting Pauli terms that means one circuit per commuting group.
- Anything that consumes `QuantumResult.expectation_values` gets nothing: `MitiqZNEAdapter` cannot wrap the backend (ZNE extrapolates expectation values), and the runner's automatic `VQAResult.final_eigenvalue` derivation has no input. A circuit-driven VQE therefore does not run unmodified on these backends.
- Error mitigation that lives inside a vendor's Estimator (IBM's TREX/ZNE/PEC resilience levels) has no counterpart.

**What you do not lose.** The record format is unaffected — a sampler-only run produces the same `BenchmarkRecord`, so results stay comparable across backends on everything except expectation values. Nothing about the framework prevents a future Estimator path: it is a per-SDK capability question, not a design limit. The practical answer is that comparing a VQE across an IBM QPU and a Quantinuum QPU needs an explicit classical estimator layer on top, not a different framework.

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

Shorthand: `runner.register(name="stub_gate", seed=42)` — when no adapter object is passed, the runner creates a `StubGateAdapter` for you. Similarly, `runner.run(circuit, "stub_gate", shots=1024)` builds `ExecutionOptions(shots=1024)` automatically when you don't need any other execution option.

### Real adapters (SDK required)

`aer_adapter.py`, `ibm_adapter.py`, `iqm_adapter.py`, `braket_adapter.py`,
`quantinuum_adapter.py`, `qibo_adapter.py`, `pennylane_lightning_adapter.py`,
`qrack_adapter.py` and `unitaryfund_mitiq_adapter.py` in
`src/qpubench/backends/` are real,
working implementations (no TODOs) — verified against the installed SDKs
(`qiskit-aer` 0.17.x, `qiskit-ibm-runtime` 0.47.x, `iqm-client[qiskit]` 34.x,
`amazon-braket-sdk` + `qiskit-braket-provider` 0.17.x, `pytket-quantinuum`
0.59.x + `pytket-qiskit` 0.77.x, `qibo` 0.2.x + `qibo-cloud-backends` 0.0.x,
`pennylane-lightning`, `mitiq`):

| File | Backend | Provider string | Tested how |
|---|---|---|---|
| `aer_adapter.py` | Qiskit Aer statevector + QASM (EstimatorV2/SamplerV2) | `"aer"` | Fully executed — no credentials needed |
| `braket_adapter.py` | AWS Braket (via `qiskit-braket-provider`'s `BraketSampler`/`BraketEstimator`) | `"aws_braket"` | Fully executed via `BraketLocalBackend` (`device_arn="local"`) — no AWS account needed |
| `ibm_adapter.py` | IBM Quantum Runtime V2 (Session/Batch/Single, TREX/ZNE/PEC resilience) | `"ibm"` | Transpile/run logic fully executed against `qiskit_ibm_runtime.fake_provider.FakeManilaV2`; only the credential-fetching `QiskitRuntimeService` call needs a real account |
| `iqm_adapter.py` | IQM hardware (Sampler path only — no Estimator; see below) | `"iqm"` | Transpile/run logic fully executed against `iqm.qiskit_iqm.fake_backends.IQMFakeAdonis`; only the credential-fetching `IQMProvider` call needs a real account |
| `quantinuum_adapter.py` | Quantinuum H-Series (Sampler path only — no Estimator; see below) | `"quantinuum"` | Transpile compiled offline via `QuantinuumBackend(machine_debug=True)` (real native-gate compilation); sampler plumbing executed against a local pytket simulator; only the credential-fetching `QuantinuumBackend` login needs a real account |
| `qibo_adapter.py` | Qibo — local simulator / Qibolab hardware / Qibo cloud (Sampler path only — no Estimator; see below) | `"qibo"` | Local `numpy` simulator fully executed (no credentials); only the Qibolab (`set_backend("qibolab", …)`) and cloud (`set_backend("qibo-cloud-backends", …)`) paths need a real lab / account |
| `pennylane_lightning_adapter.py` | PennyLane `lightning.qubit` simulator (Estimator + Sampler) | `"pennylane"` | Fully executed — no credentials needed |
| `qrack_adapter.py` | Qrack GPU/CPU statevector simulator via PyQrack (Estimator + Sampler) | `"qrack"` | Fully executed on the CPU simulator — no credentials, no GPU needed |
| `unitaryfund_mitiq_adapter.py` | Mitiq ZNE error-mitigation wrapper around another adapter | — | Fully executed around `AerAdapter` |

`qrack_adapter.py` remains a stub (`raise NotImplementedError`) — the
implementation plan lives in `integrations/qrack/IMPLEMENTATION_NOTES.md`.

IQM's Estimator path (`circuit.observables` populated) still raises
`NotImplementedError` — this is a real, current upstream limitation
(`iqm-client[qiskit]` exposes no `EstimatorV2`-equivalent as of 34.x), not
an unfinished stub. Use the Sampler path and reconstruct expectation values
classically from counts. The Quantinuum and Qibo adapters raise the same way:
Quantinuum exposes no server-side expectation-value primitive, and real Qibo
hardware (Qibolab / cloud) returns measurement samples, not expectation values.

**Quantinuum access path**: unlike the IBM/IQM/Braket adapters, Quantinuum
has no Qiskit `BackendV2`/PUB-primitive interface — the official Python route
is `pytket-quantinuum`'s `QuantinuumBackend` (submitting through Quantinuum
Nexus). `quantinuum_adapter.py` therefore converts the CircuitSpec's QASM into
a pytket `Circuit` (`pytket-qiskit`'s `qiskit_to_tk`), compiles with the
device's own `get_compiled_circuit`, and serialises the transpiled circuit
back to OpenQASM 3.0 via `tk_to_qiskit` + `qasm3.dumps`. Authentication is
through the Quantinuum Nexus credential store — run `QuantinuumBackend.login()`
(or `qnexus.login()`) once to cache a token. See Quantinuum's
[API options](https://docs.quantinuum.com/systems/trainings/h2/getting_started/api_options.html).

**Qibo access paths**: one `QiboAdapter` covers Qibo's three execution
surfaces, selected by `execution=`: `"local"` runs a local simulator
(`qibo.set_backend("numpy")` / `"qibojit"` — no credentials); `"qibolab"`
drives a self-hosted lab QPU by compiling to pulse sequences
([Qibolab](https://qibo.science/qibolab/stable/)); `"cloud"` submits to a
remote QPU through
[qibo-cloud-backends](https://qibo.science/qibo-cloud-backends/stable/)
(`client="qibo-client"` for the TII cloud, `"qiskit-client"` for IBM servers,
token from `QIBO_CLIENT_TOKEN` / `IBMQ_TOKEN`). Qibo's `Circuit.from_qasm`
reads OpenQASM 2.0, so QASM3 CircuitSpecs are converted via Qiskit first
(the `[qiskit]` extra); QASM2 CircuitSpecs need no Qiskit. Note Qibo is
big-endian (qubit 0 leftmost); the adapter reverses bitstrings to the Qiskit
little-endian convention used everywhere else in the framework.

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
across all four IBM access plans (`schemas/mirrors/ibm_cost_estimator.py`). Full
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
from qpubench.schemas.record import VQAConfig, VQAResult
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
    ) -> tuple[QuantumResult, VQAConfig, VQAResult]:
        alg = options.algorithm_spec
        # Parse problem, run algorithm, return (result, inputs, computed outputs)
        ...
```

The runner dispatches to `run_algorithm()` automatically when it detects `AlgorithmAdapter`. No configuration needed — just register the adapter normally.

---

## Backend support matrix

The tables below are organized along the same independent axes the schema layer uses:

- **Computing model** (`ComputingModel`) — the paradigm the program is expressed in. Each subsection covers one computing model (gate-based, MBQC, photonic linear optics, GBS, neutral-atom AHS).
- **Qubit modality** (`QubitModality`) — the hardware technology realizing it; "—" for simulators, where no physical modality applies.
- **Algorithms are not backends** and do not get rows here: QPE, KQD/QSE, and VQE run *on* the gate-based backends below and are identified by `AlgorithmFamily` (see [VQA algorithms](vqa.md)). The one exception is the final table — self-driving **algorithm libraries**, which register as `AlgorithmAdapter`s.

Where a **Factory** is listed, it names a `BackendSpec` classmethod that pre-fills the descriptive spec for that device (provider string, modality, device defaults) so you don't have to construct it field by field. A factory builds only the *description* — executing still requires an adapter, and the Adapter/Status columns say whether one exists (real implementation, stub, or copy-the-template).

### Gate-based

| Backend | Provider | Computing model | Qubit modality | Adapter | Status |
|---|---|---|---|---|---|
| Qiskit Aer (statevector + QASM) | `"aer"` | `GATE_BASED` | — (simulator) | `AerAdapter` | Real, tested — EstimatorV2/SamplerV2; `BackendSpec.qiskit_aer(method, num_qubits)` factory (statevector / MPS / stabilizer) |
| IBM Quantum Runtime V2 | `"ibm"` | `GATE_BASED` | `SUPERCONDUCTING` | `IBMAdapter` | Real, tested against a fake backend — implements `TranspilableBackend`; needs real credentials for live hardware |
| IQM hardware | `"iqm"` | `GATE_BASED` | `SUPERCONDUCTING` | `IQMAdapter` | Real, tested against a fake backend — implements `TranspilableBackend`; Sampler path only (no Estimator — real upstream limitation); `BackendSpec.iqm()` / `.iqm_resonance()` / `.iqm_local_server()` |
| Quantinuum H-Series (H2-1/H2-1E/H2-1SC, H1) | `"quantinuum"` | `GATE_BASED` | `TRAPPED_ION` | `QuantinuumAdapter` | Real, tested offline via `machine_debug` + local pytket sim — implements `TranspilableBackend`; Sampler path only (no Estimator — real upstream limitation); via `pytket-quantinuum`; `BackendSpec.quantinuum(device_name)` |
| Qrack GPU/CPU simulator | `"qrack"` | `GATE_BASED` | — (simulator) | `QrackAdapter` | Stub — see `integrations/qrack/IMPLEMENTATION_NOTES.md` |
| AWS Braket (Rigetti/IonQ/OQC/SV1/DM1/TN1) | `"aws_braket"` | `GATE_BASED` | configurable | `BraketAdapter` | Real, tested via `BraketLocalBackend` — implements `TranspilableBackend`; `BackendSpec.braket(device_arn)`; via `qiskit-braket-provider` |
| Qibo (local simulator / Qibolab hardware / Qibo cloud) | `"qibo"` | `GATE_BASED` | `SUPERCONDUCTING` (hardware) or — (simulator) | `QiboAdapter` | Real, tested — local `numpy` simulator fully executed (no credentials); Sampler path only (no Estimator — hardware returns samples); `BackendSpec.qibo_simulator()` / `.qibolab(platform)` / `.qibo_cloud(platform)` |
| PennyLane `lightning.qubit` | `"pennylane"` | `GATE_BASED` | — (simulator) | `PennyLaneLightningAdapter` | Real, tested — Estimator + Sampler; `BackendSpec.lightning_qubit()` |
| CUDA-Q | `"cudaq"` | `GATE_BASED` | — (simulator) | Copy template | `BackendSpec.cudaq()` |
| Cebule cloud | `"cebule"` | `GATE_BASED` | — (heterogeneous) | Copy template | `BackendSpec.cebule()` |
| Quantum Motion CMOS spin-qubit | `"quantum_motion"` | `GATE_BASED` | `SILICON_SPIN` | Copy template | `BackendSpec.quantum_motion(device_name)` |
| QDK statevector simulator | `"qdk_chemistry"` | `GATE_BASED` | — (simulator) | Copy template | `BackendSpec.qdk_chemistry_simulator(executor, num_qubits)` — sparse / full statevector; commonly paired with the QDK chemistry pipeline schemas (`schemas/mirrors/microsoft_qdk.py`) |
| Azure Quantum | `"azure_quantum"` | `GATE_BASED` | `TRAPPED_ION` (Quantinuum/IonQ hardware) or — (simulator/estimator) | Copy template | `BackendSpec.azure_quantum(target, *, resource_id_ref, location_ref, qubit_modality)` — hardware + resource estimator; QPU modality inferred from `target` or passed explicitly |
| Stub gate simulator | — | `GATE_BASED` | — (simulator) | `StubGateAdapter` | Fully functional, no SDK |

Note on algorithms vs. backends: the QDK simulator and Azure Quantum rows are ordinary gate-based backends. QPE is one algorithm frequently run on them (via the QDK chemistry pipeline, `schemas/mirrors/microsoft_qdk.py`) — but the QDK is a general package, and these backends run any gate-based circuit. Likewise KQD/QSE (`schemas/mirrors/mqsdk_qse.py`) runs on plain Aer, and VQE drives any backend in this table as its energy oracle.

### MBQC (measurement-based)

| Backend | Provider | Computing model | Qubit modality | Adapter | Status |
|---|---|---|---|---|---|
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

### QESEM (Qedma) — error-mitigation service over gate-based backends

| Backend | Provider | Computing model | Qubit modality | Factory | Notes |
|---|---|---|---|---|---|
| QESEM native client | `"qedma"` | `GATE_BASED` + `QESEM` | `SUPERCONDUCTING` | `BackendSpec.qesem(backend_name, *, api_token_ref, via_qiskit_function=False)` | Wraps any IBM backend with noise-aware QET mitigation |
| QESEM via Qiskit Function | `"qedma"` | `GATE_BASED` + `QESEM` | `SUPERCONDUCTING` | `BackendSpec.qesem(backend_name, via_qiskit_function=True)` | Submitted through IBM Qiskit Functions catalog |

### Neutral atom (Rydberg / AHS)

| Backend | Provider | Computing model | Qubit modality | Factory | Notes |
|---|---|---|---|---|---|
| QuEra Aquila 256-qubit QPU | `"quera"` | `ADIABATIC` | `NEUTRAL_ATOM` | `BackendSpec.aquila(aws_region="us-east-1")` | Analog Hamiltonian Simulation; submitted via AWS Braket |
| Bloqade Python emulator | `"bloqade"` | `ADIABATIC` | `NEUTRAL_ATOM` | `BackendSpec.bloqade_emulator(num_qubits)` | Local exact state-vector; no credentials; practical up to ~20 atoms |

### Algorithm libraries (`AlgorithmAdapter`)

These register with the same runner as the backends above, but take a problem specification instead of a circuit and drive their own execution loop. The `AlgorithmFamily` column is the package-agnostic identity that lets you compare runs of the same algorithm across different implementations — `ADAPT_VQE` currently has three interchangeable implementations sharing one `AdaptVQERunConfig` (see [VQA algorithms](vqa.md)).

| Library | Adapter | Algorithms (`AlgorithmFamily`) | Location |
|---|---|---|---|
| QForte (internal eval) | `QForteAlgorithmAdapter` | `ADAPT_VQE`, `VQE` (UCCNVQE), `UCC_PQE`, `SPQE` | `integrations/qforte/adapter.py` |
| QForte (external backend) | `ExternalEvalAlgorithmAdapter` | Same, with any `BackendAdapter` as the energy oracle | `integrations/qforte/adapter.py` |
| Generic engine, Qiskit-flavored | `IBMQiskitAdaptVQEAdapter` | `ADAPT_VQE` | `integrations/ibm_qiskit_adapt_vqe/` |
| Generic engine, QDK/Azure-flavored | `MicrosoftQDKAdaptVQEAdapter` | `ADAPT_VQE` | `integrations/microsoft_qdk_adapt_vqe/` |
| Any library | Copy template | Your algorithms | `integrations/template/` |

Plain VQE (fixed ansatz) is deliberately **not** in this table: it needs no `AlgorithmAdapter`, because a VQE run is a sequence of ordinary circuit runs — a classical optimizer binding parameters and calling a `BackendAdapter` for each energy evaluation. See [VQA algorithms — running plain VQE](vqa.md#running-plain-vqe) for the worked loop. QPE and KQD/QSE currently have schema modules but no runnable adapter (see the [known gaps](../README.md#known-gaps--open-todos)).

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

### Vendor coverage: which are executable, which are schema-only

Two different things go by "error mitigation support" here, and it is worth being explicit about which each vendor has.

- **Executable** — an `ErrorMitigationAdapter` you can register and run.
- **Schema-only** — a Pydantic module that models the vendor's config and result formats, so a run performed *outside* qpubench can be recorded and compared. No code in this repo calls the vendor.

| Vendor | Schema module | Adapter | Status |
|---|---|---|---|
| Mitiq (Unitary Fund) | `unitaryfund_mitiq.py` | `MitiqZNEAdapter` | **executable** — ZNE only; PEC/CDR/REM/DDD are modelled but not wrapped |
| Qedma QESEM | `qedma_qesem.py` | — | schema-only; runs execute through Qedma's own Qiskit Function |
| Q-CTRL Fire Opal | `qctrl_fire_opal.py` | — | schema-only |
| Haiqu Rivet | `haiqu_rivet.py` | — | schema-only |
| ParityQC | `parityqc_parityqc.py` | — | schema-only |
| QMatter | `qmatter_qmatter.py` | — | schema-only |
| IBM resilience levels | `ibm_runtime_v2.py` | via `IBMAdapter` | **executable** — set `ExecutionOptions.error_mitigation`; runs server-side |

The gap between the two columns is tracked as an open issue in this repo's git-bug tracker (`Fire Opal / Haiqu Rivet / ParityQC / QMatter have schema modules but no ErrorMitigationAdapter`); several of these vendors are commercial products whose SDKs need a paid account, which is why the schema landed first.

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
