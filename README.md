# QPUBench

[![Python ≥ 3.11](https://img.shields.io/badge/python-≥3.11-blue)](https://python.org)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-green)](LICENSE)
[![Schema v3.1.0](https://img.shields.io/badge/schema-v3.1.0-orange)](docs/schemas.md)

**QPUBench is a framework for running quantum benchmarks and recording every
result in one common format, so runs from different SDKs, machines, and even
different quantum computing paradigms can be compared side by side.**

You describe what to run as plain typed data, execute it through a pluggable
backend adapter, and every run is stored as the same self-describing
`BenchmarkRecord` — readable years later without any quantum SDK installed.
It is a framework for running *your own* benchmark campaigns, not a fixed
suite of standard benchmark circuits with a leaderboard.

## What would you use it for?

| Scenario | Supported? |
|---|---|
| Absolute performance of a quantum algorithm (accuracy / cost) | **Yes.** Expectation values with error bars, energy error against computed classical references (chemical accuracy), timings, and QPU-cost estimates. |
| Comparing implementations of the same algorithm | **Yes — a core design goal.** E.g. one ADAPT-VQE configuration runs unchanged against three different engines, producing directly comparable records. |
| Comparing different algorithms | **Yes.** Records are tagged with a package-agnostic algorithm family, so different algorithms on the same problem stay comparable in one store. |
| Comparing different hardware | **Yes.** Register several backends (Aer, IBM, IQM, Braket, …) and sweep the same circuits across all of them. |
| Comparing different quantum computing modalities | **Yes — this is the "modality-agnostic" in the tagline.** The record format covers gate-based, MBQC, boson sampling, neutral-atom analog, and more. Runnable adapters today are mostly gate-based; other modalities enter via schemas and integrations. |
| Comparing a quantum algorithm to a classical algorithm | **Partially.** Classical reference values (FCI / exact diagonalization) are computed and stored so quantum results are judged against them, but classical algorithms are not benchmarked as first-class runs. |
| Modelling noise | **No.** Backends bring their own noise models (e.g. pass a Qiskit Aer noise model to the Aer adapter); QPUBench records what ran, it does not define noise models. |
| Measuring noise | **No.** It can *store* device-characterization results produced by external tools (e.g. Qedma's QESEM), but it does not perform characterization itself. |

## Installation

```sh
pip install .                # minimal — pydantic is the only dependency
pip install ".[qiskit]"      # + Qiskit Aer simulator backend
```

Other extras and full instructions for uv, Poetry 2, and conda:
[docs/installation.md](docs/installation.md)

## Quick start

Copy, paste, run — works on the minimal install, no quantum SDK or
credentials needed. It prepares a two-qubit Bell state, measures the ⟨ZZ⟩
correlation, and appends the result record to an NDJSON file:

```python
import pathlib
from qpubench import (
    BenchmarkRunner, NDJSONStore, CircuitSpec,
    SparsePauliObservable, PauliTerm, PauliLabel, ComplexNumber,
)

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

runner = BenchmarkRunner(store=NDJSONStore(pathlib.Path("results/bell.ndjson")))
runner.register(name="stub", seed=42)
record = runner.run(circuit, "stub", shots=4096)

ev = record.result.expectation_values[0]
print(f"<ZZ> = {ev.value:.4f} ± {ev.std_error:.4f}")
```

`"stub"` is a built-in placeholder backend that returns random but
seed-reproducible numbers, so you can try the full pipeline with nothing
installed. For real numbers, install `".[qiskit]"` and change one line:

```python
from qpubench.backends import AerAdapter
runner.register(AerAdapter(), name="aer")
record = runner.run(circuit, "aer", shots=4096)   # <ZZ> ≈ 1.0 for a Bell state
```

That is the whole loop: describe → run → record. Everything else — VQE,
sweeps across backends, real hardware, other paradigms — is the same loop
with different pieces. Continue with the [user guide](docs/index.md).

## How it works

Three layers, three responsibilities:

- **Schemas** describe — circuits, backends, options, and results are plain
  [Pydantic v2](https://docs.pydantic.dev/) models with no quantum SDK imports.
- **Adapters** execute — a `BackendAdapter` runs a circuit you provide; an
  `AlgorithmAdapter` wraps a library that generates its own circuits from a
  problem (e.g. a molecule) and drives its own loop. Both register with the
  same `BenchmarkRunner`.
- **Stores** persist — every record lands in NDJSON, Parquet, or S3 through
  one `save`/`load`/`query` interface.

## What is a "schema" here?

Just typed Python classes (Pydantic models) that you **import and
instantiate** — `CircuitSpec` in the quick start is one. You pick them from
the library; there is nothing to design or register yourself.

- The **core modules** (`circuit`, `backend`, `execution`, `result`,
  `record`, …) define the record format every benchmark uses. For most
  work this is all you touch — the quick start used nothing else.
- The remaining modules are **optional add-ons**, each mirroring one
  external project (`microsoft_qdk.py`, `qedma_qesem.py`, …) or a shared
  catalogue (basis sets, Hamiltonian metadata, …). You only need one if
  your benchmark involves that specific tool, and its results attach to the
  same `BenchmarkRecord` (via dedicated fields or the `vendor_data` dict) —
  there is no assembly of multiple schema files required.

Full model-by-model reference: [docs/schemas.md](docs/schemas.md)

## Documentation

| | |
|---|---|
| [User guide](docs/index.md) | The three layers, first benchmark, sweeps, hooks, writing an adapter |
| [Installation](docs/installation.md) | pip · uv · Poetry 2 · conda |
| [Schema reference](docs/schemas.md) | Every Pydantic model, field, and enum |
| [Backends & adapters](docs/backends.md) | Available backends and their status; adapter protocols |
| [Stores & persistence](docs/persistence.md) | NDJSON · Parquet · S3; querying results |
| [VQA algorithms](docs/vqa.md) | VQE and ADAPT-VQE, including the interchangeable engines |
| [Integrations](docs/integrations.md) | Bridges to external frameworks (QForte, PySCF, QCSchema, GBS, …) |
| [Examples](examples/README.md) | Runnable guides, demos, and tutorials |

## Development

```sh
pytest tests/       # full schema test suite, no quantum SDK required
```

Known gaps and follow-ups are tracked in-repo with
[git-bug](https://github.com/git-bug/git-bug) (`git bug bug` to list them) —
see [docs/feedback_workflow.md](docs/feedback_workflow.md).

## License

LGPL-3.0-or-later. Two license files are normal for the LGPL: the LGPL
([LICENSE](LICENSE)) is a set of extra permissions on top of the GPL
([COPYING](COPYING)), which it incorporates by reference, so the FSF asks
projects to ship both texts. In short: you may use QPUBench in proprietary
or differently-licensed applications; modifications to QPUBench itself must
be released under the LGPL.
