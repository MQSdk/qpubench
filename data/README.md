# `IBM_VQE_Test_Benchmark.csv`

VQE benchmark scenario matrix: one row per (molecule, basis, mapper, TN-VQE
sweep point, measurement method) combination — 2,436 self-contained rows (no
implicit inheritance from the row above).

To run it as a real campaign, [`batches/`](batches/) splits the matrix into
tranches sized to IBM's Open / Flex / Premium plan QPU-time budgets, with
real transpile-based per-row estimates — methodology in
[`batches/README.md`](batches/README.md). Regenerate with
`python examples/guides/split_benchmark_batches.py`.

## Mapper categories

| Mapper | Meaning |
|---|---|
| `JW` | Jordan-Wigner mapped Hamiltonian, `2 × num_spatial_orbitals` qubits |
| `mol_map` | Cebule's constraint-based encoding (`< 2N` qubits) |
| `tn_qc_opt` | Cebule TN-VQE on the JW-mapped Hamiltonian |
| `tn_qc_opt+mol_map` | Cebule TN-VQE on the `mol_map`-encoded Hamiltonian |

## Columns

| Column | Meaning |
|---|---|
| `Case_ID` | Row index |
| `Molecule`, `Charge`, `Multiplicity`, `Num_Electrons` | `H2`, `Li2`, `H2O` — all neutral closed-shell singlets |
| `Basis`, `Basis_Source` | 6 [Basis Set Exchange](https://www.basissetexchange.org/) names or `qvSZP` — see [docs/integrations/basis_sets.md](../docs/integrations/basis_sets.md) |
| `Mapper` | See table above |
| `N_Qubit`, `N_Qubit_Verified` | Input-Hamiltonian qubit count; `mol_map`-derived values need a real `MOL_MAP` run and are blank (870 rows — see `batches/batch0_unestimable_needs_mol_map_run.csv`) |
| `Ansatz`, `Optimizer` | Filled for TN-VQE rows (`TN_QC_OPT (Cebule)` / `COBYLA`); blank otherwise |
| `TN_Layers_Network`, `TN_Layers_Circuit` | TN-VQE sweep: θ (classical TN side, 0–3; 0 = "circuit only" baseline) and φ (quantum circuit side, 1–4). Ranges match the reference paper ([arXiv:2402.12105](https://arxiv.org/abs/2402.12105)) |
| `Rotation_Type` | `full` (3-parameter) or `phase` (1-parameter) TN rotation |
| `Measurement_Method` | `pauli` or `qasm_gen_grouped` (Cebule's QASM_GEN basis-state-pair grouping), swept across all rows |
| `Num_Opt_Params_Phi` | `3 × TN_Layers_Circuit × N_Qubit` (PennyLane `StronglyEntanglingLayers` shape) |
| `Num_Opt_Params_Theta`, `Num_ExpVals_Per_Iter` | Blank — outputs of a real run, not derivable from inputs |
| `Qiskit_Opt_Level`, `Shots` | Blank — open campaign decisions (see below) |
| `Notes` | Per-row caveat, if any |

## Known limitations

- **Cost estimates treat `pauli` and `qasm_gen_grouped` rows as identical.**
  QASM_GEN's circuit-count reduction is an output of a real run, so the
  [IBM cost estimator](../docs/integrations/ibm_cost_estimator.md) and
  `batches/` cannot account for it.
- **`TN_Layers_Network` is classical compute, not QPU time.** Only
  `TN_Layers_Circuit` affects IBM billing; the two costs move independently.
- **qvSZP qubit counts are computed offline** via
  `hamiltonian_sources.qvszp` (a `34 → 36` Li2 error in an earlier draft was
  caught this way); `mol_map` counts cannot be, and are blank pending a real
  run.

Sources: Cebule docs ([docs.mqs.dk](https://docs.mqs.dk/sections/section_014_quantum_computing/),
checked 2026-07-09) and [arXiv:2402.12105](https://arxiv.org/abs/2402.12105),
cross-checked against `schemas/mqsdk_cebule.py`.

## Open campaign decisions

Unresolved choices (geometries, active spaces, `Shots`/`Qiskit_Opt_Level`
values, whether to fill `mol_map` gaps with real runs, possible pruning of
the 2,436-row sweep) are tracked as a git-bug item — run
`git bug bug --status open` and look for "IBM VQE campaign".
