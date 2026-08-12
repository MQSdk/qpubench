# `data/`

Benchmark **inputs** — the specifications that say what to run, not the
results of running it. A benchmark scenario here is a set of chemistry
problems (molecule, basis set, active space, fermion-to-qubit mapper,
circuit ansatz) together with a real per-row estimate of what each one
would cost in QPU time. Results live outside this folder.

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

A circuit pinned as a file rather than a CSV cell, because a multi-line
QASM program does not belong in one. Each scenario records the path and a
SHA-256 prefix, so a silently edited circuit stops matching its matrix.
The circuits are dumped with their parameters **free** — OpenQASM 3's
`input` declarations carry them — because a consumer derives the
circuit's parameter count from the file, and a circuit dumped with its
parameters bound reads as having none.

## New to tensor-network VQE?

TN-VQE wraps a classical tensor-network optimisation around a quantum
circuit: a network of two-qubit gates rotates the Hamiltonian (θ,
contracted classically) while a circuit prepares a state on hardware (φ,
measured on the QPU), and the two can be optimised jointly or one at a
time. Background and the task's own documentation are on
[docs.mqs.dk](https://docs.mqs.dk/sections/section_014_quantum_computing/);
the method paper is [arXiv:2402.12105](https://arxiv.org/abs/2402.12105).
The schema mirror in
[`schemas/mirrors/mqsdk_cebule.py`](../src/qpubench/schemas/mirrors/mqsdk_cebule.py)
documents every field with file:line citations into the implementation.

## Regenerating

Everything here is generated, and the generators are the source of truth:

```sh
PYTHONPATH=src python examples/guides/build_benchmark_matrix.py   # the matrix
PYTHONPATH=src python examples/guides/pin_qasm_ansatz.py          # the circuits
PYTHONPATH=src python examples/guides/split_benchmark_batches.py  # the tranches
```

`PYTHONPATH=src` (or a `pip install -e .`) is required: the scripts add
the repo root to `sys.path`, not `src/`. `tests/test_docs_consistency.py`
fails the build if a committed file stops matching what its generator
produces, or if a row count stated in prose stops matching the data.
