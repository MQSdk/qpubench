---
title: "QPUBench"
subtitle: "Open Source Quantum Computing Benchmark Framework"
author: "MQS · mark@mqs.dk"
date: "2026"
institute: "Molecular Quantum Solutions"
theme: "metropolis"
fonttheme: "professionalfonts"
monofont: "DejaVu Sans Mono"
monofontoptions: "Scale=0.78"
aspectratio: 169
section-titles: true
toc: false
colorlinks: true
header-includes:
  - \metroset{block=fill}
  - \setbeamertemplate{navigation symbols}{}
  - \usepackage{booktabs}
  - \usepackage{amsmath,amssymb}
---

# Framework Overview

## What is QPUBench?

**Modality-agnostic quantum benchmark framework**

- Separates *what* you benchmark (schemas) from *how* execution happens (adapters) and *how results are stored* (stores)
- Typed **Pydantic v2** schema layer — zero quantum SDK dependencies in core
- Gate-based circuits, MBQC on FPGA, molecular VQE, evolutionary circuit search, and error-mitigated runs all share one `BenchmarkRecord`
- Schema **v1.12.0** — 21 modules, language-agnostic JSON output

\vspace{0.5em}
\begin{block}{Core invariant}
\texttt{qpubench} itself never imports from any quantum library. Only adapters do.
\end{block}

## Architecture

:::::: {.columns}
::: {.column width="50%"}
**Core layer** *(no SDK dependencies)*

- `schemas/` — 21 Pydantic v2 modules
- `runner.py` — `BenchmarkRunner`
- `store.py` — `NDJSONStore`, `ParquetStore`
:::
::: {.column width="50%"}
**Integration layer** *(your project)*

- `backends/` — adapter protocols + stubs
- `integrations/` — copy into your project
- `examples/` — runnable demos
:::
::::::

\vspace{0.5em}

```
CircuitSpec / Problem  ──▶  Adapter  ──▶  BenchmarkRecord  ──▶  Store
```

## Key Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Schema-first** | Pydantic v2 is the stable contract — all records are valid JSON |
| **No SDK lock-in** | Core never imports any quantum library |
| **Three adapter protocols** | `BackendAdapter` · `AlgorithmAdapter` · `ErrorMitigationAdapter` |
| **Append-only stores** | NDJSON and Parquet for reproducible sweeps |
| **Language-agnostic** | Any language can parse the NDJSON output |

## Installation

```bash
# Minimal — schemas + stubs, no quantum SDK required
pip install .

# With optional backends
pip install ".[qiskit]"     # Qiskit Aer + IBM Quantum Runtime V2
pip install ".[storage]"    # Parquet store (pyarrow + pandas)
pip install ".[all]"        # everything on PyPI
```

**Package managers**: `pip` · `uv` · `Poetry 2` · `conda`

**Credentials**: via `.env` file and `BackendSpec.auth` (never hardcoded)

# Schema Layer

## Core Schema Modules

| Module | Modality | Key types |
|--------|----------|-----------|
| `primitives` | all | `QPUModality`, `CircuitFormat`, `PauliLabel`, `ComplexNumber` |
| `circuit` | all | `CircuitSpec` — `from_openqasm3()`, `bind()`, `is_parametric()` |
| `observable` | all | `SparsePauliObservable`, `PauliTerm` |
| `backend` | all | `BackendSpec` — 27 factory constructors |
| `execution` | all | `ExecutionOptions`, `AlgorithmSpec`, `ZNEConfig` |
| `error_mitigation` | all | `ErrorMitigationStrategy`, provider configs, `QuantumAdvantageRecord` |
| `result` | all | `QuantumResult`, `ExpectationResult`, `ShotResult` |
| `record` | all | `BenchmarkRecord`, `VQAConfig` |

## Domain-Specific Schema Modules

| Module | Modality / Framework |
|--------|---------------------|
| `mbqc` | MBQC-FPGA — bit-exact 16-bit program word |
| `photonic` | Linear-optics chips, FBQC, HOM, photonic VQE/analog |
| `gbs` | Gaussian Boson Sampling — hafnian, vibronic, TDM/Borealis |
| `qdk_chemistry` | SCF → active space → QPE → resource estimation |
| `qse` | Krylov Quantum Diagonalization (KQD / SQD) |
| `qesem` | QESEM (Qedma) — noise scaling, QET, device characterisation |
| `qcschema` | QCSchema / QCElemental / PennyLane interoperability |
| `neutral_atom` | Bloqade / Aquila AHS, Rydberg atom arrangement |
| `slowquant` | SlowQuant UCC/VQE — ansatz, SCF, linear response |
| `error_mitigation` | Q-CTRL · Mitiq · Haiqu · ParityQC · QMatter · Quantum Motion · IBM V2 · Advantage Tracker |

## QPU Modalities

QPUBench natively covers **9 quantum computing paradigms**:

:::::: {.columns}
::: {.column width="50%"}
- `GATE_BASED` — qubit circuits (QASM2/3)
- `MBQC` — measurement-based QC on FPGA
- `PHOTONIC_LINEAR_OPTICS` — Fock-state chips
- `FUSION_BASED` — FBQC resource states + fusion
- `QPE` — Quantum Phase Estimation / IQPE
:::
::: {.column width="50%"}
- `GBS` — Gaussian Boson Sampling
- `KQD` — Krylov Quantum Diagonalization
- `NEUTRAL_ATOM` — AHS on Rydberg atoms
- `ANNEALING` — quantum annealing
:::
::::::

\vspace{0.3em}
All modalities share the same `BenchmarkRecord` schema.

## CircuitSpec — One Type for All Circuits

```python
# Gate-based (QASM2)
circuit = CircuitSpec(
    num_qubits=2,
    serialized='OPENQASM 2.0;\ninclude "qelib1.inc";\n...',
    observables=[SparsePauliObservable(num_qubits=2, terms=[
        PauliTerm(qubit_indices=(0, 1),
                  pauli_ops=(PauliLabel.Z, PauliLabel.Z),
                  coefficient=ComplexNumber(re=1.0))
    ])],
)

# OpenQASM 3.0 helper
circuit = CircuitSpec.from_openqasm3(source, num_qubits=2)

# Parametric VQE — bind() returns a new copy
ansatz = CircuitSpec(num_qubits=2, parameters=["theta"], ...)
bound  = ansatz.bind({"theta": 1.2566})

# Algorithm-driven (chemistry)
mol = CircuitSpec(format=CircuitFormat.MOLECULE_JSON,
                  serialized="/path/to/He-ccpvdz.json", num_qubits=0)
```

# Adapters

## Three Adapter Protocols

:::::: {.columns}
::: {.column width="33%"}
**`BackendAdapter`**
*Circuit in, result out*

```
CircuitSpec
    ↓ run()
QuantumResult
```

Aer · Qrack · IBM
IQM · MBQC-FPGA
:::
::: {.column width="33%"}
**`AlgorithmAdapter`**
*Problem spec in*

```
CircuitSpec
 (problem)
    ↓ run_algorithm()
(Result, VQAConfig)
```

QForte · OpenFermion
:::
::: {.column width="33%"}
**`ErrorMitigationAdapter`**
*Wraps a BackendAdapter*

```
inner adapter
    ↓ run()
mitigate/suppress
    ↓
QuantumResult
```

Fire Opal · Mitiq
Haiqu · ParityQC
:::
::::::

\vspace{0.3em}
`BenchmarkRunner` dispatches automatically — `ErrorMitigationAdapter` registers like any `BackendAdapter`.

## BackendAdapter — Estimator vs Sampler

```python
class MyBackendAdapter:
    @property
    def spec(self) -> BackendSpec: ...          # hardware description

    def validate(self, circuit: CircuitSpec) -> list[str]: ...

    def run(self, circuit: CircuitSpec,
            options: ExecutionOptions) -> QuantumResult:
        if circuit.observables:
            # Estimator path → expectation_values (VQE, QAOA)
            evs = [measure_expectation(circuit, obs) for obs in circuit.observables]
            return QuantumResult(expectation_values=evs, ...)
        else:
            # Sampler path → shot counts / bitstrings
            counts = sample_bitstrings(circuit, options.shots)
            return QuantumResult(shots=ShotResult(..., counts=counts), ...)
```

**Rule**: SDK imports go inside the method that uses them — never at module level.

## AlgorithmAdapter (QForte example)

```python
class QForteAlgorithmAdapter:
    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        if circuit.format != CircuitFormat.MOLECULE_JSON:
            return [f"Expected MOLECULE_JSON, got {circuit.format!r}"]
        return []

    def run_algorithm(self, circuit: CircuitSpec,
                      options: ExecutionOptions
                      ) -> tuple[QuantumResult, VQAConfig]:
        import qforte as qf                   # ← deferred SDK import
        mol = qf.system_factory(...)
        alg = qf.ADAPTVQE(mol, ...)
        alg.run(pool_type="SD", optimizer="BFGS", ...)
        energy = float(alg.get_gs_energy())
        result = QuantumResult(expectation_values=[
            ExpectationResult(observable_index=0, value=energy, std_error=0.0)
        ], status=JobStatus.SUCCEEDED)
        return result, VQAConfig(problem_type="chemistry",
                                 final_eigenvalue=energy, ...)
```

## Energy Evaluator Hook

Advanced: QForte drives the ansatz; a qpubench backend evaluates $\langle H \rangle$

```
QForte optimizer  -->  energy_feval(params)
                              |
                    EnergyEvaluatorHook.evaluate()
                              |
                    qpubench BackendAdapter.run()
                              |
                    QuantumResult  -->  <H> (float)
```

- Enables ADAPT-VQE on **Aer, Qrack GPU, IBM hardware**, or any adapter
- Gradient computation automatically routed through the hook
- Falls back to QForte's internal C++ simulator on error
- Available in `integrations/qforte/energy_hook.py`

## Error Mitigation Providers

`error_mitigation.py` — one schema module, seven provider integrations:

| Provider | Schema types | Technique |
|---|---|---|
| **Q-CTRL Fire Opal** | `FireOpalConfig`, `FireOpalResult` | Closed-box noise suppression; `fo.execute()` API |
| **Mitiq** | `MitiqConfig` + 5 configs, `MitiqResult` | ZNE · PEC · CDR · REM · DDD |
| **Haiqu Rivet** | `HaiquRivetConfig`, `HaiquTranspilationResult` | Hardware-aware transpilation caching |
| **ParityQC** | `ParityQCConfig`, `ParityQCResult` | Parity encoding for QUBO / HCBO / Ising |
| **QMatter** | `QMatterConfig`, `QMatterCompressionResult` | Quantum problem compression |
| **Quantum Motion** | `QuantumMotionDeviceSpec` | Silicon CMOS spin-qubit characterisation |

\vspace{0.3em}
`ErrorMitigationStrategy` enum extended: `FIRE_OPAL` · `MITIQ_ZNE/PEC/CDR/REM/DDD` · `HAIQU` · `PARITY_QC` · `QMATTER`

## IQM Hardware — Star Topology

:::::: {.columns}
::: {.column width="55%"}
**IQM Resonance cloud** (`iqm-client` + `qiskit-iqm`)

```python
# Star architecture: all qubits via COMPR1 resonator
backend = BackendSpec.iqm_resonance(
    "garnet",       # 20Q IQM Garnet
    api_token_ref="IQM_TOKEN",
)
# BackendSpec.iqm_resonance("deneb")   # 6Q
# BackendSpec.iqm_resonance("sirius")  # 24Q Star

adapter = IQMAdapter("garnet", token=os.environ["IQM_TOKEN"])
```

Calibration via `IQMClient.get_dynamic_quantum_architecture()`:
T1 ~28 µs · T2* ~17 µs · PRX ~99.79% · CZ ~98.42%
:::
::: {.column width="45%"}
**Native gate set**

| Gate | Parameters | Notes |
|------|-----------|-------|
| `PRX` | $\theta$, $\varphi$ | Angles in **fractions of turns** — $\theta$=0.5 $\rightarrow$ $\pi$ rotation |
| `CZ` | — | Controlled-Z, symmetric |
| `MOVE` | — | Qubit $\leftrightarrow$ resonator swap (Star only) |

Hub-and-spoke topology gives effective all-to-all connectivity without SWAP routing.
:::
::::::

## IBM Quantum Runtime V2

:::::: {.columns}
::: {.column width="50%"}
**EstimatorV2 PUB**
`(circuit, observables, params?, precision?)`

```python
# precision replaces fixed shot count
estimator.run([(qc, obs, params, 1e-2)])
result[i].data.evs   # expectation value
result[i].data.stds  # statistical error
```

**SamplerV2 PUB**
`(circuit, params?, shots?)`

```python
sampler.run([(qc, params, 4096)])
bit_array = result[0].data.meas
counts = bit_array.get_counts()
```

`BitArray.shape` = `(num_shots,)` or `(num_params, num_shots)`
:::
::: {.column width="50%"}
**Execution modes** (`IBMExecutionMode`)

| Mode | When to use |
|------|-------------|
| `SESSION` | VQE / adaptive — exclusive QPU hold |
| `BATCH` | Sweeps — parallel independent jobs |
| `SINGLE` | One-shot run (default) |

```python
adapter = IBMAdapter(
    "ibm_torino",
    execution_mode=IBMExecutionMode.SESSION,
)
```

**`IBMRuntimeRecord`** on `QuantumResult`:
job\_id · session\_id · resilience\_level · `ExecutionSpan` timestamps

\vspace{0.3em}
**CUDA-Q**: `cudaq.observe()` $\approx$ EstimatorV2; `cudaq.sample()` $\approx$ SamplerV2 — same `BackendAdapter` protocol.
:::
::::::

## Quantum Advantage Tracker

`BenchmarkRecord.advantage` holds a `QuantumAdvantageRecord`:

```python
record = runner.run(circuit, "ibm_torino", options)
record = record.model_copy(update={"advantage": QuantumAdvantageRecord(
    experiment_type=AdvantageExperimentType.OBSERVABLE_ESTIMATION,
    circuit_name="Loschmidt-echo-70q",
    num_qubits=70,
    backend_name="ibm_boston",
    floquet_layers=20,
    observable_value=0.327,
    observable_error_bound=0.012,
    classical_method=ClassicalComparisonMethod.TENSOR_NETWORK,
    coupling_params={"b": 1.0, "delta": 0.5},
    submission_url="https://github.com/quantum-advantage-tracker/...",
)})
```

\begin{block}{Quantum Advantage Tracker}
Community registry co-initiated by IBM, Flatiron Institute, BlueQubit, Algorithmiq.
Three experiment categories: observable estimation · variational · classically verifiable.
\end{block}

# Execution & Storage

## BenchmarkRunner

```python
runner = BenchmarkRunner(store=NDJSONStore(Path("results.ndjson")))
runner.register(AerAdapter(), name="aer")
runner.register(QForteAlgorithmAdapter(), name="qforte")

# Single run
record = runner.run(circuit, "aer", ExecutionOptions(shots=4096))

# Cartesian product sweep: circuits × backends × options
records = runner.sweep(
    circuits=[circuit_h2, circuit_lih],
    backend_names=["aer", "qforte"],
    options_list=[ExecutionOptions(shots=1024),
                  ExecutionOptions(shots=8192)],
    run_id="vqe-sweep-001",
)

# Post-execution hooks
runner.add_hook(lambda rec: log_energy(rec.vqa.final_eigenvalue))
```

## Data Persistence

**NDJSONStore** — zero dependencies, append-only, grep-able

```python
store = NDJSONStore(Path("results/run1.ndjson"))
store.save(record)

record  = store.load(experiment_id)           # by UUID
records = store.query(                        # dot-path filters
    backend__name="aer_statevector",
    result__status="succeeded",
)
```

**ParquetStore** — columnar analytics (`pip install ".[storage]"`)

```python
store = ParquetStore(Path("results/run1.parquet"))
df = store.to_dataframe()                     # → pandas DataFrame
```

Every record is one JSON line — stream-able, pandas-ready, archive-safe.

# Integrations

## Integration Ecosystem (1/3)

| Integration | Schema module | Protocol |
|-------------|--------------|---------|
| Cebule SDK | `cebule` | `BackendAdapter` |
| Xenakis GA circuit search | `xenakis` | `AlgorithmAdapter` |
| ExcitationSolve (Fourier VQE) | `excitation_solve` | `AlgorithmAdapter` |
| GSOpt (ground-state benchmark) | `gsopt` | `AlgorithmAdapter` |
| Photochipsim / FBQC | `photonic` | `BackendAdapter` |
| QDK / QuNorth chemistry | `qdk_chemistry` | `AlgorithmAdapter` |

## Integration Ecosystem (2/3)

| Integration | Schema module | Protocol |
|-------------|--------------|---------|
| DTU-GBS / photonic\_QC | `gbs` | `BackendAdapter` |
| QSE / KQD | `qse` | `AlgorithmAdapter` |
| QESEM (Qedma) | `qesem` | `BackendAdapter` |
| QCSchema / PennyLane | `qcschema` | cross-format interop |
| Bloqade / Aquila | `neutral_atom` | `BackendAdapter` |
| SlowQuant UCC/VQE | `slowquant` | `AlgorithmAdapter` |

## Integration Ecosystem (3/3) — Error Mitigation & Hardware

| Integration | Schema module | Protocol |
|-------------|--------------|---------|
| Q-CTRL Fire Opal | `error_mitigation` | `ErrorMitigationAdapter` |
| Mitiq (ZNE · PEC · CDR · REM · DDD) | `error_mitigation` | `ErrorMitigationAdapter` |
| Haiqu Rivet transpiler | `error_mitigation` | `ErrorMitigationAdapter` |
| ParityQC parity encoding | `error_mitigation` | `ErrorMitigationAdapter` |
| QMatter problem compression | `error_mitigation` | `ErrorMitigationAdapter` |
| IQM Resonance (garnet · deneb · sirius) | — | `BackendAdapter` |
| Quantum Motion CMOS spin-qubit | `error_mitigation` | `BackendAdapter` |

## Cross-Framework Compatibility

**Pauli encoding** — explicit converters prevent silent convention bugs:

```python
# Qrack Q# convention: I=0, X=1, Z=2, Y=3  (non-sequential!)
PauliLabel.Z.to_qrack_int()           # → 2  (not 3)
PauliLabel.Y.to_qrack_int()           # → 3  (not 2)

# Qiskit C API QkBitTerm bit-packed encoding
PauliLabel.X.to_qiskit_c_bit_term()   # → 0b0010

# MBQC byproduct register: bit 0 = Z, bit 1 = X  (reversed vs gate-based!)
```

**Complex numbers**: stored as `{"re": 1.0, "im": 0.5}` — valid JSON without Python eval

**QCSchema / QCElemental / PennyLane** interoperability via the `qcschema` module

# Code Quality

## Python Quality Toolchain

```bash
ruff check src/ tests/    # lint (line-length 100, target py311)
ruff format src/ tests/   # format
mypy src/                 # static types (strict = true)
pytest tests/ -q          # 156 tests — no quantum SDK required
```

| Tool | Role |
|------|------|
| **Pydantic v2** | Runtime-validated schemas — field types enforced at parse time |
| **ruff** | Linting + auto-formatting, replaces flake8/isort/black |
| **mypy strict** | Full type coverage — `Any` only where unavoidable |
| **pytest** | Schema-only test suite runs with `pip install .` alone |
| **ponytail** | Agent code-quality enforcement via decision ladder |

# Summary

## Getting Started

```python
from qpubench import (
    BenchmarkRunner, NDJSONStore, StubGateAdapter,
    CircuitSpec, ExecutionOptions,
    SparsePauliObservable, PauliTerm, PauliLabel, ComplexNumber,
)
import pathlib

circuit = CircuitSpec(
    num_qubits=2,
    serialized='OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];',
    observables=[SparsePauliObservable(num_qubits=2, terms=[
        PauliTerm(qubit_indices=(0, 1),
                  pauli_ops=(PauliLabel.Z, PauliLabel.Z),
                  coefficient=ComplexNumber(re=1.0))
    ])],
)
runner = BenchmarkRunner(store=NDJSONStore(pathlib.Path("results.ndjson")))
runner.register(StubGateAdapter(seed=42), name="stub")
record = runner.run(circuit, "stub", ExecutionOptions(shots=4096))
print(f"<ZZ> = {record.result.expectation_values[0].value:.4f}")
```

## Roadmap & Links

**Repository**: `github.com/mqsdk/qpubench`

**Schema v1.12.0** — 21 modules · 9 QPU modalities · zero quantum SDK deps in core

\vspace{0.5em}

**Contributing** — writing an adapter takes \~30 lines:

```bash
cp integrations/template/backend_adapter_template.py  my_adapter.py
# fill the three TODOs: spec, validate(), run()
```

See `INTEGRATION_GUIDE.md` and `AGENTS.md` for the full development workflow.

\vspace{0.5em}

**Contact**: `contact@mqs.dk`
