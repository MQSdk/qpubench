# `data/`

This folder contains benchmark **inputs** — the specifications that say
what to run, not the results of running it. A benchmark scenario is a set
of cases to be executed, together with a real per-case estimate of what
each one would cost on the hardware it targets. Results live outside this
folder.

## What is in here

| Path | Holds |
|---|---|
| [`benchmarks/`](benchmarks/) | One folder per benchmark scenario — the matrix of cases, the tranches it is split into, and a README explaining that campaign |
| [`qasm/`](qasm/) | The exact circuits the scenarios pin, as OpenQASM 3.0, written by [`pin_qasm_ansatz.py`](../examples/guides/pin_qasm_ansatz.py) and shared across scenarios |

### Benchmark scenarios

| Scenario | What it compares |
|---|---|
| [`benchmarks/ibm_tn-vqe_qesem/`](benchmarks/ibm_tn-vqe_qesem/) | Tensor-network VQE (Cebule TN_QC_OPT) against plain VQE on IBM hardware, across 7 basis sets and 2 mappers, with a Qedma QESEM error-mitigation refinement arm. Read its [README](benchmarks/ibm_tn-vqe_qesem/README.md) first — the folder name reads *vendor · method · mitigation* |

### `qasm/`

Each scenario that runs a named circuit pins that circuit here as a file,
and records the path and a SHA-256 prefix in its matrix, so a silently
edited circuit stops matching the scenario that runs it.

The circuits for variational scenarios are dumped with their parameters
**free** — OpenQASM 3's `input` declarations carry them — because the
file has to say which parameters the optimisation varies. A circuit
dumped with its parameters bound describes one fixed state instead, which
is a different thing to run.

## Regenerating

Everything here is generated, and the generators are the source of truth:

```sh
PYTHONPATH=src python examples/guides/build_benchmark_matrix.py   # the matrix
PYTHONPATH=src python examples/guides/pin_qasm_ansatz.py          # the circuits
PYTHONPATH=src python examples/guides/split_benchmark_batches.py  # the tranches
```

Run them in that order after a change to the matrix: the circuits are
pinned from the shapes the matrix names, the matrix then picks up their
hashes on a second pass, and the tranches are cut from the result. None
of the three needs credentials or a network.

`PYTHONPATH=src` (or a `pip install -e .`) is required: the scripts add
the repo root to `sys.path`, not `src/`. `tests/test_docs_consistency.py`
fails the build if a committed file stops matching what its generator
produces, or if a row count stated in prose stops matching the data.
