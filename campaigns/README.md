# `campaigns/`

One folder per benchmarking campaign. Each is self-contained: the code
that generates its matrix, the matrix itself, the data it runs on, the
circuits it pins, its results and the notebooks that analyse them.
Nothing a campaign decides -- which molecules, axes, shots, optimizer
settings or budgets -- lives outside its folder.

What campaigns share is in [`utils/`](../utils/): building and pinning
ansatz circuits, budgeting optimizers, submitting runs to Cebule and
costing a matrix on IBM hardware. Those tools take a campaign as an
argument and read what they need from its `campaign.py`.

## Campaigns

| Campaign | What it compares |
|---|---|
| [`ibm_tn-vqe_qesem/`](ibm_tn-vqe_qesem/) | Tensor-network VQE (Cebule TN_QC_OPT) against plain VQE, on a targeted set of axes (mapper, ansatz, optimizer, TN-layers) rather than a full factorial, with a Qedma QESEM error-mitigation stage generated on demand. Read its [README](ibm_tn-vqe_qesem/README.md) first; the folder name reads *vendor, method, mitigation* |

## What a campaign folder holds

| Path | Holds |
|---|---|
| `README.md` | What the campaign is for and how its matrix is built |
| `campaign.py` | What the shared tools need to know: the matrix path, the circuit and results folders, and how to find a row's Hamiltonian. See [`utils/_campaign.py`](../utils/_campaign.py) for the full list |
| a matrix builder | Generates the campaign's CSV; the source of truth for what each row is |
| `*.csv` | The matrix: one row per run |
| `hamiltonian_data/` | The committed Hamiltonians the runs optimise |
| `qasm/` | The exact circuits the matrix pins, as OpenQASM 3.0, written by [`pin_qasm_ansatz.py`](../utils/pin_qasm_ansatz.py). Each campaign has its own, because pinning deletes files no row of that campaign runs |
| `results/` | Run results and checkpoints, written by [`run_campaign.py`](../utils/run_campaign.py). Gitignored |

Circuits for variational campaigns are dumped with their parameters
**free**, carried by OpenQASM 3's `input` declarations, because the file
has to say which parameters the optimisation varies. A matrix records each
circuit's path and a SHA-256 prefix, so a silently edited circuit stops
matching the campaign that runs it.

## Starting a new campaign

1. Create `campaigns/<name>/` with a `campaign.py` defining at least
   `CSV`, `QASM_DIR`, `RESULTS_DIR` and `hamiltonian_file(run)`.
2. Write a matrix builder that produces the CSV, using `utils/_matrix_io.py`,
   `utils/_ansatz_builders.py` and `utils/_optimizer_budget.py` for the
   parts every campaign needs.
3. Generate, pin, regenerate (the matrix picks up the circuits' hashes on
   the second pass), then run with `utils/run_campaign.py --campaign <name>`.

## Regenerating `ibm_tn-vqe_qesem`

```sh
PYTHONPATH=src python campaigns/ibm_tn-vqe_qesem/build_matrix.py --stage targeted  # the matrix
PYTHONPATH=src python utils/pin_qasm_ansatz.py --campaign ibm_tn-vqe_qesem        # the circuits
```

Run them in that order after a change to the matrix, then run the builder
again so it picks up the circuits' hashes. Neither needs credentials or a
network. `PYTHONPATH=src` (or a `pip install -e .`) is required.
`tests/test_docs_consistency.py` fails the build if the committed CSV
stops matching what its builder produces, or if a row count stated in
prose stops matching the data.
