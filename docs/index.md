# QPUBench

**QPUBench is a benchmark framework for quantum computing that separates *what* you benchmark from *how* it runs and *where* the results go.**

You describe a circuit or problem once, as a typed [Pydantic v2](https://docs.pydantic.dev/) model. You run it against any registered backend — a local simulator, IBM or IQM hardware, an MBQC FPGA, or an algorithm library that builds its own circuits. Every run produces the same self-describing `BenchmarkRecord`, so results from different hardware, paradigms, and vendors are directly comparable and remain readable years later without any quantum SDK installed.

The core package depends only on `pydantic`. Every quantum SDK is an optional extra.

---

## The three ideas

QPUBench is built from three small, independent layers. Understanding them is enough to use the whole framework.

**1. Schemas — what you benchmark.**
`CircuitSpec` (a circuit or problem), `BackendSpec` (a machine), `ExecutionOptions` (how to run), and `QuantumResult` (what came back) are plain Pydantic models. They serialize to JSON, validate on construction, and never import a quantum SDK. A `BenchmarkRecord` bundles one circuit × one backend × one options set × one result, stamped with a schema version and a UUID.

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

This runs end-to-end with the bare install — no quantum SDK, no credentials. It prepares a Bell state, measures the ⟨ZZ⟩ correlation on a stub backend, and appends the record to an NDJSON file:

```python
import pathlib
from qpubench import (
    BenchmarkRunner, NDJSONStore, CircuitSpec,
    SparsePauliObservable, PauliTerm, PauliLabel, ComplexNumber,
)

# What to benchmark: a 2-qubit Bell circuit with one observable
bell_qasm = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0],q[1];"""

circuit = CircuitSpec(
    num_qubits=2,
    serialized=bell_qasm,
    observables=[
        SparsePauliObservable(num_qubits=2, terms=[
            PauliTerm(qubit_indices=(0, 1),
                      pauli_ops=(PauliLabel.Z, PauliLabel.Z),
                      coefficient=ComplexNumber(re=1.0))
        ])
    ],
)

# How to run it, and where results go
runner = BenchmarkRunner(store=NDJSONStore(pathlib.Path("results/bell.ndjson")))
runner.register(name="stub", seed=42)

record = runner.run(circuit, "stub", shots=4096)

ev = record.result.expectation_values[0]
print(f"<ZZ> = {ev.value:.4f} ± {ev.std_error:.4f}")
```

Registering with just a `name` and a `seed` creates a **`StubGateAdapter`** behind the scenes: a built-in placeholder backend that returns random, seed-reproducible values instead of simulating anything. It exists so you can build and test the full pipeline — circuit, runner, store — before installing a quantum SDK or touching real hardware. Likewise, `runner.run(..., shots=4096)` builds `ExecutionOptions(shots=4096)` for you; pass a full `ExecutionOptions` only when you need more detailed control (error mitigation, transpiler settings, algorithm hyperparameters).

To run the same circuit on a real simulator, change **one line**:

```python
from qpubench.backends import AerAdapter          # pip install "qpubench[qiskit]"

runner.register(AerAdapter(), name="aer")
record = runner.run(circuit, "aer", shots=4096)   # <ZZ> ≈ 1.0
```

That substitution — same circuit, same options, same record format, different machine — is the entire point of the framework.

### What got saved

Each line of `results/bell.ndjson` is one complete, versioned record:

```python
store = NDJSONStore(pathlib.Path("results/bell.ndjson"))
for r in store.query(backend__name="aer_statevector"):
    print(r.experiment_id, r.result.expectation_values[0].value)
```

Records embed the circuit source, backend description, options, timings, and results, so a stored file is a self-contained benchmark archive.

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
| Look up any model, field, or enum | [Schema reference](schemas.md) |
| See every backend and its status (real vs. stub) | [Backends & adapters](backends.md) |
| Store, query, and analyze results (incl. S3 / Hugging Face) | [Stores & persistence](persistence.md) |
| Run variational algorithms (VQE, ADAPT-VQE) | [VQA algorithms](vqa.md) |
| Run simulators on CPU / GPU, or MBQC programs on FPGA | [Compute architectures](compute_architectures.md) |
| Bridge an external framework's data (QForte, PySCF, QCSchema, GBS, …) | [Integrations](integrations.md) |
| Avoid cross-SDK convention traps (Pauli encodings, bit orders) | [Compatibility](compatibility.md) |
| Write your own adapter, step by step | [Integration guide](https://github.com/mqsdk/qpubench/blob/main/INTEGRATION_GUIDE.md) |
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

Two rules keep the ecosystem healthy: SDK imports live **inside** methods (so importing your adapter never requires the SDK), and recoverable failures return `status=FAILED` with an `error_message` rather than raising. Templates for both protocols are in [`integrations/template/`](https://github.com/mqsdk/qpubench/tree/main/integrations/template), and the [integration guide](https://github.com/mqsdk/qpubench/blob/main/INTEGRATION_GUIDE.md) walks through testing your adapter with the SDK mocked out.

---

## Beyond gate-based circuits

The same record format covers paradigms that most benchmark tools can't express side by side. `ComputingModel` (how a program is expressed: `GATE_BASED`, `MBQC`, `FUSION_BASED`, `ADIABATIC`, `ANNEALING`, `GBS`, `SAMPLING`) and `QubitModality` (what hardware realizes it: superconducting, trapped-ion, neutral-atom, photonic, silicon-spin) are independent axes on every circuit, backend, and result — so a gate-based run on photonic hardware and a Gaussian boson sampling run land in the same store and can be queried together.

Vendor- and framework-specific schemas (38 modules, from QForte and PySCF to QuEra's analog Hamiltonian simulation and Qedma's QESEM error mitigation) live in [`qpubench.schemas`](schemas.md). Modules that mirror a single external project are named `<maintainer>_<package>.py` so the filename tells you the upstream source; core record types and multi-source catalogues (basis sets, Hamiltonian metadata, the advantage tracker) stay unprefixed.

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

QPUBench is free software, released under the **GNU Lesser General Public License v3.0 or later** ([LGPL-3.0-or-later](https://www.gnu.org/licenses/lgpl-3.0.html)). You may use it in proprietary or differently-licensed applications; changes to QPUBench itself must be published under the LGPL. See [LICENSE](https://github.com/mqsdk/qpubench/blob/main/LICENSE) and [COPYING](https://github.com/mqsdk/qpubench/blob/main/COPYING) in the repository.
