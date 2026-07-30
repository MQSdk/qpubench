# QPUBench

**QPUBench is a benchmark framework for quantum computing paradigms and quantum computers (QPUs) that separates *what* you benchmark from *how* it runs and *where* the results go.**

You describe a circuit or problem once, as a typed [Pydantic v2](https://docs.pydantic.dev/) model. You run it against any registered backend — a local simulator, IBM or IQM hardware, or an algorithm library that builds its own circuits. Every run produces the same self-describing `BenchmarkRecord`, so results from different hardware, paradigms, and vendors are directly comparable and remain readable years later without any quantum SDK installed.

The core package depends only on `pydantic`. Every quantum SDK is an optional extra.

---

## The three ideas

QPUBench is built from three small, independent layers. Understanding them is enough to use the whole framework.

**1. Schemas — what you benchmark.**
`CircuitSpec` (a circuit or problem), `BackendSpec` (a machine), `ExecutionOptions` (how to run), and `QuantumResult` (what came back) are plain Pydantic models. They serialize to JSON, validate on construction, and never import a quantum SDK. A `BenchmarkRecord` bundles one circuit × one backend × one options set × one result, stamped with a schema version, a UUID (`experiment_id`), and a UTC `timestamp` recording when the run was created.

**2. Adapters — how execution happens.**
An adapter is any object with three members: `spec`, `validate(circuit)`, and `run(circuit, options)` (the `BackendAdapter` protocol). Libraries that generate their *own* circuits from a problem description — ADAPT-VQE engines, for example — implement the sibling `AlgorithmAdapter` protocol instead, and the runner dispatches automatically. No base class to inherit; protocols are structural.

**3. Stores — where results go.**
`NDJSONStore` (zero-dependency, append-only), `ParquetStore` (columnar, for analysis with pandas), and `S3Store` (one object per record, safe for distributed sweeps). All share the same `save` / `load` / `query` interface, and the runner persists every record automatically.

```
CircuitSpec ──▶ BenchmarkRunner ──▶ BackendAdapter / AlgorithmAdapter
                     │                        │
                     ◀── BenchmarkRecord ◀────┘
                     │
                     ▶ hooks (logging, live monitoring)
                     ▶ ResultStore (NDJSON / Parquet / S3)
```

---

## Installation

```sh
pip install .              # schemas + runner + stubs — pydantic is the only dependency
pip install ".[qiskit]"    # + Qiskit Aer and IBM Quantum Runtime backends
pip install ".[storage]"   # + Parquet store
pip install ".[all]"       # everything on PyPI
```

Works identically with `uv`, Poetry 2, and conda — see the [installation guide](installation.md).

---

## Your first benchmark

This runs end-to-end with the bare install — no quantum SDK, no credentials. It prepares a 3-qubit GHZ state, measures two observables on a stub backend, and appends the record to an NDJSON file. Compared with the README's minimal Bell example, this one deliberately reaches for a few more knobs — multiple observables, an explicit `ExecutionOptions` (reproducibility seed, transpiler tier), and record tags/notes — so you meet them early:

```python
from qpubench import (
    BenchmarkRunner, CircuitSpec, ExecutionOptions,
    SparsePauliObservable, PauliTerm, PauliLabel, ComplexNumber,
)

# What to benchmark: a 3-qubit GHZ circuit with TWO observables
ghz_qasm = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[3];
h q[0];
cx q[0],q[1];
cx q[1],q[2];"""

zzz = SparsePauliObservable(num_qubits=3, terms=[
    PauliTerm(qubit_indices=(0, 1, 2),
              pauli_ops=(PauliLabel.Z, PauliLabel.Z, PauliLabel.Z),
              coefficient=ComplexNumber(re=1.0))])
xxx = SparsePauliObservable(num_qubits=3, terms=[
    PauliTerm(qubit_indices=(0, 1, 2),
              pauli_ops=(PauliLabel.X, PauliLabel.X, PauliLabel.X),
              coefficient=ComplexNumber(re=1.0))])

circuit = CircuitSpec(num_qubits=3, serialized=ghz_qasm, observables=[zzz, xxx])

# How to run it, and where results go.  A plain string path becomes an
# append-only NDJSONStore — no pathlib, no store import needed.
runner = BenchmarkRunner(store="results/ghz.ndjson")
runner.register(name="stub", seed=42)

# An explicit ExecutionOptions exposes settings runner.run(..., shots=) hides:
# a reproducibility seed and the transpiler optimization tier (0–3).
options = ExecutionOptions(shots=4096, seed=7, optimization_level=2)

record = runner.run(
    circuit, "stub", options,
    tags=["tutorial", "ghz"],          # queryable labels on the record
    notes="first GHZ benchmark",       # free-text provenance
)

for ev in record.result.expectation_values:
    label = "".join(p.name for p in circuit.observables[ev.observable_index].terms[0].pauli_ops)
    print(f"<{label}> = {ev.value:.4f} ± {ev.std_error:.4f}")
print("created at:", record.timestamp)          # UTC timestamp, auto-stamped
```

Registering with just a `name` and a `seed` creates a **`StubGateAdapter`** behind the scenes: a built-in placeholder backend that returns random, seed-reproducible values instead of simulating anything. It exists so you can build and test the full pipeline — circuit, runner, store — before installing a quantum SDK or touching real hardware. `runner.run(..., shots=4096)` would build `ExecutionOptions(shots=4096)` for you; here we pass a full `ExecutionOptions` to reach the extra settings (`seed`, `optimization_level`, and later error mitigation, transpiler settings, or algorithm hyperparameters). When a circuit carries observables the stub takes the estimator path and returns expectation values; drop the observables and it samples bitstrings into `record.result.shots` instead (set `memory=True` for per-shot data).

To run the same circuit on a real simulator, change **one line**:

```python
from qpubench.backends import AerAdapter          # pip install "qpubench[qiskit]"

runner.register(AerAdapter(), name="aer")
record = runner.run(circuit, "aer", options)      # <ZZZ> ≈ 0, <XXX> ≈ 1 for GHZ
```

That substitution — same circuit, same options, same record format, different machine — is the entire point of the framework.

### Simulators you can drop in

Every backend below is a **real, credential-free simulator** that swaps into that one line the same way. The stub needs nothing installed; the rest need only their extra:

| Simulator | Install extra | Register it with |
|---|---|---|
| Stub (random, seeded — no SDK) | *(built-in)* | `runner.register(name="stub", seed=42)` |
| Stub MBQC (random round results) | *(built-in)* | `runner.register(StubMBQCAdapter(seed=7), name="mbqc")` |
| Qiskit Aer (statevector + QASM) | `[qiskit]` | `runner.register(AerAdapter(), name="aer")` |
| PennyLane `lightning.qubit` | `[pennylane]` | `runner.register(PennyLaneLightningAdapter(), name="pennylane")` |
| AWS Braket local (`LocalSimulator`) | `[braket]` | `runner.register(BraketAdapter(device_arn="local"), name="braket")` |
| Qibo local (`numpy` / `qibojit`) | `[qibo]` | `runner.register(QiboAdapter(platform="numpy"), name="qibo")` |
| Qrack (GPU/CPU statevector) | `[qrack]` | `runner.register(QrackAdapter(2, gpu=False), name="qrack")` |
| Mitiq ZNE (wraps another simulator) | `[mitiq]` | `runner.register(MitiqZNEAdapter(AerAdapter()), name="mitiq")` |

All adapter classes import from `qpubench.backends`. Fake-noise hardware backends (IBM `FakeManilaV2`, IQM `IQMFakeAdonis`, Quantinuum `machine_debug=True`) also run without credentials — see [Backends & adapters](backends.md) for those and for real-hardware access.

### What got saved

Each line of `results/ghz.ndjson` is one complete, versioned record. A plain string path opens the store for reading too:

```python
from qpubench import NDJSONStore

store = NDJSONStore("results/ghz.ndjson")
for r in store.query(backend__name="aer_statevector"):
    print(r.experiment_id, r.timestamp, r.tags, r.result.expectation_values[0].value)
```

Records embed the circuit source, backend description, options, timings, tags, notes, and results, so a stored file is a self-contained benchmark archive.

---

## Sweeps, VQE metadata, and hooks

Benchmarking rarely means one run. `sweep()` takes the Cartesian product of circuits × backends × options and groups the records under one `run_id`:

```python
records = runner.sweep(
    circuits=[circuit],
    backend_names=["stub", "aer"],
    options_list=[ExecutionOptions(shots=s) for s in (512, 2048, 8192)],
    run_id="bell_shots_sweep",
)
```

For variational algorithms, attach a `VQAConfig` describing what you ran; the computed outputs arrive in `record.vqa_result`:

```python
from qpubench import VQAConfig

record = runner.run(bound_ansatz, "aer", shots=4096,
    vqa=VQAConfig(problem_type="chemistry", molecule="H2", basis="sto-3g"))
record.vqa_result.final_eigenvalue   # derived from the measured expectation values
record.vqa_result.energy_error       # |final − reference|, when a reference is present
record.vqa_result.chemical_accuracy  # True (< 1.6 mHa)
```

`VQAConfig` is input metadata, not configuration — it changes nothing about execution and never carries computed values. `problem_type` (the only required field) labels the problem domain (`"chemistry"`, `"optimization"`, `"ml"`) so records can be filtered by domain in the store. The computed side (`VQAResult`) is produced by the run itself: algorithm adapters return the converged energy, convergence history, and computed references (FCI / exact diagonalisation); for estimator-path circuit runs the runner derives `final_eigenvalue` from the result's expectation values. `energy_error` and `chemical_accuracy` are derived whenever a computed reference is present.

Hooks fire on every completed record before persistence — use them for live progress lines or structured logging (`BenchmarkLogger` ships with a JSON formatter):

```python
runner.add_hook(lambda r: print(r.backend.name, r.result.status.value))
```

---

## Where to go next

| If you want to… | Read |
|---|---|
| Install with uv / Poetry / conda, set up credentials | [Installation](installation.md) |
| Understand why the code is written the way it is | [Developer guide](developer_guide.md) |
| Look up any model, field, or enum | [Schema reference](schemas.md) |
| See what the core record format still lacks | [Schema review](schema_review.md) |
| See what is planned, and pick something up | [Roadmap](roadmap.md) · `git bug bug --status open` |
| See every backend and its status (real vs. stub) | [Backends & adapters](backends.md) |
| Store, query, and analyze results (incl. S3 / Hugging Face) | [Stores & persistence](persistence.md) |
| Run variational algorithms (VQE, ADAPT-VQE) | [VQA algorithms](vqa.md) |
| Understand algorithm identity, families, and configs | [Algorithms & `AlgorithmSpec`](algorithm_spec.md) |
| Run simulators on CPU / GPU, or MBQC programs on FPGA | [Compute architectures](compute_architectures.md) |
| Bridge an external framework's data (QForte, PySCF, QCSchema, GBS, …) | [Integrations](integrations.md) |
| Load pre-defined QUBO Hamiltonians (OR-Library, MQLib, BQPJSON) | [`hamiltonian_sources/qubo.py`](../src/qpubench/hamiltonian_sources/qubo.py) and the [generator roadmap](qubo_generator_roadmap.md) |
| Avoid cross-SDK convention traps (Pauli encodings, bit orders) | [Compatibility](compatibility.md) |
| Write your own adapter, step by step | [Backends & adapters](backends.md) and the [integrations directory](https://github.com/mqsdk/qpubench/tree/main/integrations) |
| Learn from runnable code | [examples/](https://github.com/mqsdk/qpubench/tree/main/examples) — guides, demos, and full tutorials |

The examples directory follows a three-tier layout: `guides/` are focused how-tos (one concept each), `demos/` are self-contained showcases, and `tutorials/` are multi-step scientific workflows such as a bond-dissociation curve or an SN2 reaction path.

---

## Plugging in your own backend

An adapter is a plain class — no registration machinery, no inheritance:

```python
from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.primitives import JobStatus
from qpubench.schemas.result import QuantumResult, ShotResult

class MySimulatorAdapter:
    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(name="my_sim", provider="me", simulator=True)

    def validate(self, circuit: CircuitSpec) -> list[str]:
        return [] if circuit.num_qubits <= 30 else ["max 30 qubits"]

    def run(self, circuit: CircuitSpec, options: ExecutionOptions) -> QuantumResult:
        import my_sdk                    # SDK imports stay inside methods
        counts = my_sdk.sample(circuit.serialized, shots=options.shots)
        return QuantumResult(
            computing_model=circuit.computing_model,
            shots=ShotResult(num_qubits=circuit.num_qubits,
                             num_shots=options.shots, counts=counts),
            status=JobStatus.SUCCEEDED,
        )
```

Two rules keep the ecosystem healthy: SDK imports live **inside** methods (so importing your adapter never requires the SDK), and recoverable failures return `status=FAILED` with an `error_message` rather than raising. Templates for both protocols are in [`integrations/template/`](https://github.com/mqsdk/qpubench/tree/main/integrations/template), and [Backends & adapters](backends.md) walks through testing your adapter with the SDK mocked out.

---

## Beyond gate-based circuits

The same record format covers paradigms that most benchmark tools can't express side by side. `ComputingModel` (how a program is expressed: `GATE_BASED`, `MBQC`, `FUSION_BASED`, `ADIABATIC`, `ANNEALING`, `GBS`, `SAMPLING`) and `QubitModality` (what hardware realizes it: superconducting, trapped-ion, neutral-atom, photonic, silicon-spin) are independent axes on every circuit, backend, and result — so a gate-based run on photonic hardware and a Gaussian boson sampling run land in the same store and can be queried together.

Vendor- and framework-specific schemas (41 modules, from QForte and PySCF to QuEra's analog Hamiltonian simulation and Qedma's QESEM error mitigation) live in [`qpubench.schemas`](schemas.md). They are split three ways by directory: `schemas/` holds the core record types, `schemas/mirrors/` one module per external project (named `<maintainer>_<package>.py`, so the filename tells you the upstream source), and `schemas/catalogs/` the cross-cutting catalogues that draw on several upstreams at once (basis sets, Hamiltonian metadata, the advantage tracker).

---

## Development

```sh
uv sync              # install package + dev tools (pytest, ruff, mypy)
pytest tests/        # full suite runs without any quantum SDK
ruff check src/ tests/
mypy src/
```

Contributions follow two hard constraints: no quantum SDK imports inside `src/qpubench/`, and schema changes are append-only (add optional fields; never rename or retype existing ones without bumping the schema version).

---

## License

QPUBench is free software under a single license: the **GNU Lesser General Public License v3.0 or later** ([LGPL-3.0-or-later](https://www.gnu.org/licenses/lgpl-3.0.html)). It is not dual-licensed. You may use it in proprietary or differently-licensed applications; changes to QPUBench itself must be published under the LGPL.

Following the FSF's naming convention, the repository ships the LGPLv3 text as [`COPYING.LESSER`](https://github.com/mqsdk/qpubench/blob/main/COPYING.LESSER) (duplicated as [`LICENSE`](https://github.com/mqsdk/qpubench/blob/main/LICENSE) so GitHub detects it) and the GPLv3 text as [`COPYING`](https://github.com/mqsdk/qpubench/blob/main/COPYING). The GPLv3 file is the base that the LGPLv3 incorporates by reference, not a second license offer.
