# QPUBench

[![Python ≥ 3.11](https://img.shields.io/badge/python-≥3.11-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Schema v1.3.0](https://img.shields.io/badge/schema-v1.3.0-orange)](docs/schemas.md)

Modality-agnostic quantum benchmark framework with a typed [Pydantic v2](https://docs.pydantic.dev/) schema layer.

qpubench separates **what you benchmark** (schemas) from **how execution happens** (adapters) and **how results are stored** (stores). The schema layer is the stable core — gate-based circuits, MBQC on FPGA, molecular VQE problems, and evolutionary circuit search all share the same `BenchmarkRecord` format, independent of any quantum SDK.

---

## Documentation

| | |
|---|---|
| **[Installation](docs/installation.md)** | pip · uv · Poetry 2 · conda |
| **[Schema reference](docs/schemas.md)** | Every Pydantic model, field, and enum |
| **[Backends & adapters](docs/backends.md)** | BackendAdapter / AlgorithmAdapter protocols, writing a new adapter |
| **[Integrations](docs/integrations.md)** | Cebule SDK · Xenakis · ExcitationSolve · GSOpt |
| **[MBQC FPGA](docs/mbqc.md)** | 16-bit program word, COE files, byproduct registers |
| **[Persistence](docs/persistence.md)** | NDJSONStore · ParquetStore · hooks |
| **[Compatibility](docs/compatibility.md)** | Pauli encoding, complex precision, MBQC bit conventions |
| **[Integration guide](INTEGRATION_GUIDE.md)** | Writing adapters, energy hooks, testing pattern |

---

## Installation

```sh
# Minimal (schemas + stubs only — no quantum SDK needed)
pip install .

# With optional backends
pip install ".[qiskit]"      # Qiskit Aer + IBM Quantum Runtime V2
pip install ".[storage]"     # Parquet store (pyarrow + pandas)
pip install ".[all]"         # everything on PyPI
```

Full instructions for **uv**, **Poetry 2**, and **conda** → [docs/installation.md](docs/installation.md)

---

## Architecture

```mermaid
classDiagram
    class BenchmarkRunner {
        +register(adapter, name)
        +add_hook(fn)
        +run(circuit, backend_name, options) BenchmarkRecord
        +sweep(circuits, backends, options_list) list[BenchmarkRecord]
    }
    class BackendAdapter {
        <<Protocol — circuit-driven>>
        +spec() BackendSpec
        +validate(circuit) list[str]
        +run(circuit, options) QuantumResult
    }
    class AlgorithmAdapter {
        <<Protocol — algorithm-driven>>
        +spec() BackendSpec
        +validate_problem(circuit) list[str]
        +run_algorithm(circuit, options) tuple[QuantumResult, VQAConfig]
    }
    class BenchmarkRecord {
        +schema_version str
        +circuit CircuitSpec
        +backend BackendSpec
        +options ExecutionOptions
        +result QuantumResult
        +vqa VQAConfig
    }
    class ResultStore {
        <<Protocol>>
        +save(record)
        +load(experiment_id) BenchmarkRecord
        +query(**filters) list[BenchmarkRecord]
    }
    BenchmarkRunner --> BackendAdapter
    BenchmarkRunner --> AlgorithmAdapter
    BenchmarkRunner --> ResultStore
    BenchmarkRunner --> BenchmarkRecord
```

| Protocol | When to use | Examples |
|---|---|---|
| `BackendAdapter` | You provide the circuit; backend executes it | Aer, Qrack, IBM, IQM, MBQC-FPGA |
| `AlgorithmAdapter` | Library generates its own circuit from a problem spec | QForte (ADAPT-VQE, UCCNVQE) |

---

## Quick start

### Gate-based (Bell state + ZZ expectation)

```python
import pathlib
from qpubench import (
    BenchmarkRunner, NDJSONStore, StubGateAdapter,
    CircuitSpec, ExecutionOptions,
    SparsePauliObservable, PauliTerm, PauliLabel, ComplexNumber,
)

circuit = CircuitSpec(
    num_qubits=2,
    serialized='OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];',
    observables=[
        SparsePauliObservable(num_qubits=2, terms=[
            PauliTerm(qubit_indices=(0, 1),
                      pauli_ops=(PauliLabel.Z, PauliLabel.Z),
                      coefficient=ComplexNumber(re=1.0))
        ])
    ],
)

runner = BenchmarkRunner(store=NDJSONStore(pathlib.Path("results/bell.ndjson")))
runner.register(StubGateAdapter(seed=42), name="stub")
record = runner.run(circuit, "stub", ExecutionOptions(shots=4096))
ev = record.result.expectation_values[0]
print(f"⟨ZZ⟩ = {ev.value:.4f} ± {ev.std_error:.4f}")
```

### OpenQASM 3.0 circuit

```python
from qpubench import CircuitSpec

circuit = CircuitSpec.from_openqasm3(
    'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nh q[0];\ncx q[0], q[1];',
    num_qubits=2,
)
print(circuit.openqasm3)          # → the source string
print(circuit.format)             # → CircuitFormat.QASM3
```

### Parametric VQE circuit

```python
from qpubench import CircuitSpec, VQAConfig

ansatz = CircuitSpec(num_qubits=2, parameters=["theta"], serialized="OPENQASM 2.0; ...")
bound  = ansatz.bind({"theta": 1.2566})

record = runner.run(bound, "stub", ExecutionOptions(shots=4096),
    vqa=VQAConfig(problem_type="chemistry", molecule="H2", basis="sto-3g",
                  final_eigenvalue=-1.137, ground_truth=-1.1373))
print(f"Chemical accuracy: {record.vqa.chemical_accuracy}")
```

### Algorithm library (QForte ADAPT-VQE)

```python
from qpubench import BenchmarkRunner, ExecutionOptions, AlgorithmSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.primitives import CircuitFormat

mol = CircuitSpec(num_qubits=0, format=CircuitFormat.MOLECULE_JSON,
                  serialized="/path/to/He-ccpvdz.json")
options = ExecutionOptions(algorithm_spec=AlgorithmSpec(
    name="ADAPTVQE", pool_type="SD", optimizer="BFGS",
    avqe_thresh=1e-4, adapt_maxiter=20,
))
# register QForteAlgorithmAdapter from integrations/qforte/
record = runner.run(mol, "qforte", options)
```

→ Full examples: [examples/](examples/) · QForte adapter: [integrations/qforte/](integrations/qforte/)

---

## Schema overview

Schema version **1.3.0** — 13 modules, zero quantum SDK dependencies.

| Module | Key types |
|---|---|
| `primitives` | `QPUModality`, `CircuitFormat`, `PauliLabel`, `CebuleTaskType`, all enums |
| `circuit` | `CircuitSpec` (`from_openqasm3`, `openqasm3`, `bind`), `ParameterBinding` |
| `observable` | `SparsePauliObservable`, `PauliTerm`, `from_cebule_operators` |
| `backend` | `BackendSpec` (`.aer_statevector()`, `.ibm()`, `.qrack()`, `.cudaq()`, `.cebule()`, …) |
| `execution` | `ExecutionOptions`, `AlgorithmSpec`, `ZNEConfig`, `TranspilerConfig` |
| `result` | `QuantumResult`, `ExpectationResult`, `ShotResult`, `FidelityResult`, `AdaptIteration`, `TranspileLayout` |
| `record` | `BenchmarkRecord`, `VQAConfig` |
| `mbqc` | `MBQCPattern`, `MBQCProgramWord`, `MBQCExecutionResult` — bit-exact 16-bit FPGA word |
| `cebule` | `MolMapResult`, `QASMGenResult`, `TNQCOptResult`, `COVOResult`, `MolecularGeometry` |
| `xenakis` | `LayerGenome`, `BitstringGenome`, `QNEATGenome`, `GARunResult`, `XenakisRunConfig` |
| `excitation_solve` | `ExcitationSolveResult`, `ExcitationSolveSweep`, `ExcitationAdaptResult` |
| `gsopt` | `GSOptBenchmarkResult`, `ActiveSpaceSpec`, `REFERENCE_ENERGIES`, `VQERunConfig` |

→ Full field-level reference: [docs/schemas.md](docs/schemas.md)

---

## Repository layout

```
qpubench/
├── src/qpubench/
│   ├── schemas/           ← Pydantic schema layer (13 modules, schema v1.3.0)
│   ├── backends/          ← BackendAdapter/AlgorithmAdapter protocols + stubs
│   ├── runner.py          ← BenchmarkRunner (run, sweep, hooks, dual-protocol dispatch)
│   └── store.py           ← NDJSONStore, ParquetStore, ResultStore protocol
│
├── integrations/          ← NOT installed; copy into your project
│   ├── template/          ← BackendAdapter + AlgorithmAdapter starter templates
│   └── qforte/            ← Complete QForte integration (ADAPT-VQE, UCCNVQE)
│
├── examples/              ← Runnable examples (gate-based, MBQC, QForte VQE)
├── tests/                 ← 61 schema tests, no quantum SDK required
├── docs/                  ← Detailed documentation
├── conda-recipe/          ← conda-build recipe (meta.yaml)
├── environment.yml        ← conda development environment
├── pyproject.toml         ← pip / uv / Poetry 2 / conda-build entry point
└── INTEGRATION_GUIDE.md   ← Step-by-step adapter guide
```

---

## Tests

```sh
pytest tests/       # 61 tests, no quantum SDK required
```

---

## License

MIT — see [LICENSE](LICENSE).
