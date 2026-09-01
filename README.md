# QPUBench

[![Python ≥ 3.11](https://img.shields.io/badge/python-≥3.11-blue)](https://python.org)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-green)](LICENSE)
[![Schema v6.6.0](https://img.shields.io/badge/schema-v6.6.0-orange)](docs/schemas.md)
[![Docs](https://img.shields.io/badge/docs-qpubench.org-blue)](https://qpubench.org)

**QPUBench is a framework for running quantum benchmarks and recording every
result in one common format, so runs from different SDKs, machines, and even
different quantum computing paradigms can be compared side by side.**

You describe what to run as plain typed data, execute it through a pluggable
backend adapter, and every run is stored as the same self-describing
`BenchmarkRecord`, readable years later without any quantum SDK installed.
It is a framework for running *your own* benchmark campaigns, not a fixed
suite of standard benchmark circuits with a leaderboard.

## What would you use it for?

| Scenario | Supported? |
|---|---|
| Absolute performance of a quantum algorithm (accuracy / cost) | **Yes.** Expectation values with error bars, energy error against a stored classical reference (FCI / exact diagonalization), timings, and QPU-cost estimates. See the note below on what "reference" means here. |
| Comparing implementations of the same algorithm | **Yes, a core design goal.** E.g. one ADAPT-VQE configuration runs unchanged against three different engines, producing directly comparable records. |
| Comparing different algorithms | **Yes.** Records are tagged with a package-agnostic algorithm family, so different algorithms on the same problem stay comparable in one store. |
| Comparing different hardware | **Yes.** Register several backends (Aer, IBM, IQM, Braket, Quantinuum, Qibo, …) and sweep the same circuits across all of them. |
| Comparing different quantum computing modalities | **Yes, this is the "modality-agnostic" in the tagline.** The record format covers gate-based, MBQC, boson sampling, neutral-atom analog, and more. Runnable adapters today are mostly gate-based; other modalities enter via schemas and integrations. |
| Comparing a quantum algorithm to a classical algorithm | **Partially.** Classical reference values (FCI / exact diagonalization) are computed and stored so quantum results are judged against them, but classical algorithms are not benchmarked as first-class runs. |
| Modelling noise | **No.** Backends bring their own noise models (e.g. pass a Qiskit Aer noise model to the Aer adapter); QPUBench records what ran, it does not define noise models. |
| Measuring noise | **No.** It can *store* device-characterization results produced by external tools (e.g. Qedma's QESEM), but it does not perform characterization itself. |

> **A note on "chemical accuracy".** QPUBench reports an *energy error*, the
> gap between a run's result and a **classically computed** reference (FCI or
> exact diagonalization), and flags whether that gap is below 1.6 mHartree.
> This is a numerical-convergence check against a computed value; it is **not**
> the same as "chemical accuracy" in the strict sense many chemists mean, which
> is agreement with an **experimentally measured** quantity from reality. A
> result within 1.6 mHartree of a computed FCI reference can still be far from
> the true physical value if the model (basis set, active space, Hamiltonian)
> is itself an approximation. Treat the stored reference as a computed baseline,
> not as ground truth from experiment.

## Installation

```sh
pip install .                # minimal; pydantic is the only dependency
pip install ".[qiskit]"      # + Qiskit Aer simulator backend
```

Other extras and full instructions for uv, Poetry 2, and conda:
[docs/installation.md](docs/installation.md)

## Quick start

Copy, paste, run; it works on the minimal install, no quantum SDK or
credentials needed. It prepares a two-qubit Bell state, measures the ⟨ZZ⟩
correlation, and appends the result record to an NDJSON file:

```python
from qpubench import BenchmarkRunner, CircuitSpec, Pauli

bell_qasm = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0],q[1];"""

circuit = CircuitSpec(
    num_qubits=2,
    serialized=bell_qasm,
    observables=[Pauli("Z0 Z1")],   # ⟨ZZ⟩; Pauli() builds a SparsePauliObservable
)

runner = BenchmarkRunner(store="results/bell.ndjson")   # str path → NDJSONStore
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

That is the whole loop: describe → run → record. Everything else, from VQE to
sweeps across backends, real hardware and other paradigms, is the same loop
with different pieces. Continue with the [user guide](docs/index.md).

## Plain VQE in a dozen lines

Plain VQE is *not* a special object or an algorithm adapter; it is exactly
that same describe → run → record loop wrapped in a classical optimizer. You
keep one unbound parametrized ansatz (with its Hamiltonian attached as an
observable), and each energy evaluation binds the current parameters into a
copy and runs it as an ordinary circuit. Here a one-qubit `Ry(θ)` ansatz is
driven to the ground state of `H = Z` (minimum ⟨Z⟩ = −1 at θ = π):

```python
import numpy as np
from scipy.optimize import minimize
from qpubench import BenchmarkRunner, CircuitSpec, Pauli, VQAConfig
from qpubench.backends import AerAdapter        # pip install "qpubench[qiskit]"
from qpubench.schemas.primitives import CircuitFormat

ansatz = CircuitSpec(                            # the unbound master copy, reused every step
    num_qubits=1,
    format=CircuitFormat.QASM3,
    serialized='OPENQASM 3.0; include "stdgates.inc"; input float[64] theta; qubit[1] q; ry(theta) q[0];',
    parameters=["theta"],
    observables=[Pauli("Z0")],                   # H = Z, the thing we minimize
)

runner = BenchmarkRunner()
runner.register(AerAdapter(), name="aer")        # swap for hardware here; nothing else changes

def energy(theta: np.ndarray) -> float:
    bound = ansatz.bind({"theta": float(theta[0])})   # .bind() never mutates the master
    # VQAConfig only *labels* the run for the record; it sets no parameters.
    record = runner.run(bound, "aer",
        vqa=VQAConfig(problem_type="chemistry", ansatz="ry", optimizer="COBYLA"))
    return record.result.expectation_values[0].value

res = minimize(energy, x0=[0.1], method="COBYLA")
print(f"ground-state energy ≈ {res.fun:.4f}")   # → -1.0000
```

qpubench ships no optimizer of its own; the loop is a few lines and any
optimizer works. Every evaluation is persisted as a full `BenchmarkRecord`, so
the stored history *is* the convergence trace. The full guide (real chemistry
Hamiltonians, QAOA, the interchangeable ADAPT-VQE engines) is in
[VQA algorithms](docs/vqa.md).

## How it works

Three layers, three responsibilities:

- **Schemas** describe: circuits, backends, options, and results are plain
  [Pydantic v2](https://docs.pydantic.dev/) models with no quantum SDK imports.
- **Adapters** execute: a `BackendAdapter` runs a circuit you provide; an
  `AlgorithmAdapter` wraps a library that generates its own circuits from a
  problem (e.g. the ground state energy calculation of a molecule) and drives
  its own loop. Both register with the same `BenchmarkRunner`.
- **Stores** persist: every record lands in NDJSON, Parquet, or S3 through
  one `save`/`load`/`query` interface.

## What is a "schema" here?

Just typed Python classes (Pydantic models) that you **import and
instantiate**; `CircuitSpec` in the quick start is one. You pick them from
the library; there is nothing to design or register yourself. The library
ships **48 schema modules** at the current schema version (see the badge
above), split into three groups: core record format, cross-cutting
catalogues, and per-project mirrors.

- The **core modules** (`circuit`, `backend`, `execution`, `result`,
  `record`, …) define the record format every benchmark uses. For most
  work this is all you touch; the quick start used nothing else.
- The remaining modules are **optional add-ons**, each mirroring one
  external project (`microsoft_qdk.py`, `qedma_qesem.py`, …) or a shared
  catalogue (basis sets, Hamiltonian metadata, …). You only need one if
  your benchmark involves that specific tool, and its results attach to the
  same `BenchmarkRecord` (via dedicated fields or the `vendor_data` dict);
  there is no assembly of multiple schema files required.

Full model-by-model reference: [docs/schemas.md](docs/schemas.md)

## Credentials

**No credential is ever written in code.** Not in `src/`, not in an example,
not in a notebook, not in a test. Put them in a `.env` file, which is
gitignored:

```sh
cp .env.example .env     # then fill in your tokens
```

Adapters do not accept a token as an argument. They accept the **name of the
environment variable** to read it from, and read it only at the moment they
connect:

```python
IBMAdapter("ibm_torino")                        # reads $IBM_QUANTUM_TOKEN
IBMAdapter("ibm_torino", token_ref="MY_TOKEN")  # reads $MY_TOKEN instead
```

That name is what `BackendSpec.auth` stores, so a saved `BenchmarkRecord`
never contains a secret and can be shared as-is. `S3Store` goes further and
raises if you pass `aws_secret_access_key=` at all.

Settings that are account-specific but not secret (`IBM_QUANTUM_INSTANCE`,
`AWS_REGION`) have no built-in default either; an adapter tells you which
variable to set rather than guessing one that happens to work on someone
else's machine. `.env.example` lists every variable, grouped by adapter.

## Documentation

| | |
|---|---|
| [User guide](docs/index.md) | The three layers, first benchmark, sweeps, hooks, writing an adapter |
| [Installation](docs/installation.md) | pip · uv · Poetry 2 · conda |
| [Developer guide](docs/developer_guide.md) | Why the code looks like it does: protocols, `super()`, `bind()`, decorators, naming |
| [Schema reference](docs/schemas.md) | Every Pydantic model, field, and enum |
| [Schema review](docs/schema_review.md) | Known gaps in the core record format, and what the mirror layer revealed about them |
| [Roadmap](docs/roadmap.md) | Planned schema work, phased; tracked in git-bug under the `schema-review` label |
| [Backends & adapters](docs/backends.md) | Available backends and their status; adapter protocols |
| [Stores & persistence](docs/persistence.md) | NDJSON · Parquet · S3; querying results |
| [VQA algorithms](docs/vqa.md) | VQE and ADAPT-VQE, including the interchangeable engines |
| [Algorithms & `AlgorithmSpec`](docs/algorithm_spec.md) | Algorithm identity vs. hyperparameters, the family dispatch model, vanilla VQE vs. ADAPT |
| [Integrations](docs/integrations.md) | Bridges to external frameworks (QForte, PySCF, QCSchema, GBS, …) |
| [Examples](examples/README.md) | Runnable guides, demos, and tutorials |

## Development

```sh
pytest tests/       # full schema test suite, no quantum SDK required
```

Known gaps and follow-ups are tracked in-repo with
[git-bug](https://github.com/git-bug/git-bug) (`git bug bug` to list them);
see [docs/feedback_workflow.md](docs/feedback_workflow.md).

## License

QPUBench has a single license: **LGPL-3.0-or-later**. It is not dual-licensed.

| File | Contents | Role |
| --- | --- | --- |
| [`LICENSE`](LICENSE) | LGPLv3 | The license QPUBench is under |

In short: you may use QPUBench in proprietary or differently-licensed
applications; modifications to QPUBench itself must be released under the LGPL.
