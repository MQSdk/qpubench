# `IBM_VQE_Test_Benchmark.csv`

VQE benchmark scenario matrix: one row per (molecule, basis, mapper,
TN-VQE sweep point, measurement method) combination — 2,436 rows.
Restructured 2026-07-09 from an earlier draft that relied on blank cells
implicitly inheriting the value above them (fragile for anything reading
the file programmatically); extended the same day to add Cebule TN-VQE
(`tn_qc_opt`) benchmark cases (with and without `mol_map`), then extended
again to add Cebule's QASM_GEN measurement method as an independent
with/without dimension across the whole matrix. Every row is
self-contained — no implicit inheritance from the row above.

## Running this as a real campaign — see `batches/`

[`data/batches/`](batches/) splits this CSV into sequential files sized to
each IBM access plan's QPU-time budget — a first tranche that fits the
Open Plan's free 10 minutes, a next tranche sized to a fresh 400-minute
Flex Plan purchase, and a third sized to a fresh 5,200-minute Premium
Plan annual minimum — using real transpile-based per-row QPU-time
estimates (see [`batches/README.md`](batches/README.md) for the full
methodology and assumptions). Regenerate with
`python examples/guides/split_benchmark_batches.py`.

## Four `Mapper` categories

| Mapper | Meaning |
|---|---|
| `JW` | Plain Jordan-Wigner mapped Hamiltonian, `2 x num_spatial_orbitals` qubits |
| `mol_map` | Cebule's MQS constraint-based encoding (`qpubench.schemas.mqsdk_cebule.MolMapInput`/`MolMapResult`), `< 2N` qubits |
| `tn_qc_opt` | Cebule TN-VQE (`schemas.mqsdk_cebule.TNQCOptInput`) applied to the **JW**-mapped Hamiltonian — no `mol_map` |
| `tn_qc_opt+mol_map` | Cebule TN-VQE applied to the **`mol_map`**-encoded Hamiltonian — "combine the mapping, measurement and MPS encoding for the VQE routine," per Cebule's own docs |

## Columns

| Column | Meaning | Status |
|---|---|---|
| `Case_ID` | Row index, for cross-referencing | — |
| `Molecule` | `H2`, `Li2`, or `H2O` | fixed |
| `Charge`, `Multiplicity`, `Num_Electrons` | All three molecules are neutral closed-shell singlets | fixed |
| `Basis` | One of 6 [Basis Set Exchange](https://www.basissetexchange.org/) names or `qvSZP` ([grimme-lab/qvSZP](https://github.com/grimme-lab/qvSZP)) | fixed |
| `Basis_Source` | `basis_set_exchange` or `grimme_qvszp` — see [docs/integrations/basis_sets.md](../docs/integrations/basis_sets.md) | fixed |
| `Mapper` | See table above | fixed |
| `N_Qubit` | Qubit count for this case — for `tn_qc_opt`/`tn_qc_opt+mol_map` rows this is the *input* Hamiltonian's qubit count (TN-VQE doesn't change it) | see verification below |
| `N_Qubit_Verified` | `yes` (real, cross-checked), `n/a` (`mol_map`-derived, not a formula-derivable quantity, or blank if unknown) | see below |
| `Ansatz` | `TN_QC_OPT (Cebule)` for the two TN-VQE mappers; blank for `JW`/`mol_map` (still open, see "Still needed") | partial |
| `Optimizer` | `COBYLA` for TN-VQE rows (Cebule's own `TNQCOptInput.opt_method` default, corrected 2026-07-09 — was documented as `BFGS` before the docs.mqs.dk revision this was re-checked against); blank otherwise | partial |
| `TN_Layers_Network` | `n_layers_network` (θ, the classical tensor-network side) — `0,1,2,3`. `0` = Cebule/paper's own "circuit only" baseline (no TN preprocessing at all) | TN-VQE rows only |
| `TN_Layers_Circuit` | `n_layers_circuit` (φ, the quantum-circuit side) — `1,2,3,4`, independent of `TN_Layers_Network` | TN-VQE rows only |
| `Rotation_Type` | `full` (`three_para_tn=True`, 3-parameter arbitrary rotation) or `phase` (`three_para_tn=False`, 1-parameter phase gate); `n/a (no TN layers)` when `TN_Layers_Network=0` (no TN block exists to parameterize) | TN-VQE rows only |
| `Measurement_Method` | `pauli` (standard per-Pauli-string measurement) or `qasm_gen_grouped` (Cebule's QASM_GEN basis-state-pair-grouping scheme) — see "QASM_GEN" section below | **all rows** |
| `Num_Opt_Params_Phi` | Real: `3 x TN_Layers_Circuit x N_Qubit` (PennyLane `StronglyEntanglingLayers` parameter shape, confirmed installed) | TN-VQE rows only, when `N_Qubit` known |
| `Num_Opt_Params_Theta`, `Num_ExpVals_Per_Iter` | Not predictable in advance — see "TN-VQE: what could and couldn't be computed" below | **blank, all rows** |
| `Qiskit_Opt_Level`, `Shots` | Experiment sweep parameters | **blank — still open, see "Still needed"** |
| `Notes` | Per-row caveat, if any | — |

## TN-VQE: what could and couldn't be computed

Sourced from Cebule's own docs
([docs.mqs.dk, TN-VQE/`tn_qc_opt` section](https://docs.mqs.dk/sections/section_014_quantum_computing/#efficient_quantum_computing_with_parameterized_tensor_networks_as_matrix_product_states_mps_and_operators_mpo))
and the reference preprint
([arXiv:2402.12105](https://arxiv.org/abs/2402.12105), same MQS authors),
cross-checked directly against the real `TNQCOptInput`/`TNQCOptResult`
schema already in this repo (`schemas/mqsdk_cebule.py`):

- **Real, computed**: `Num_Opt_Params_Phi` — the quantum-circuit-side
  parameter count follows PennyLane's `StronglyEntanglingLayers` shape
  convention (`n_layers x n_wires x 3`), confirmed against the installed
  PennyLane in this session (`qml.StronglyEntanglingLayers.shape(3, 4) ==
  (3, 4, 3)`). Whether Cebule's *productized* `tn_qc_opt` circuit ansatz is
  identical to the reference paper's choice of `StronglyEntanglingLayers`
  is inferred from shared authorship/lineage (paper: "Molecular Quantum
  Solutions ApS" — the same company as the Cebule SDK), not explicitly
  confirmed identical in the docs — worth double-checking against a real
  job if exact reproducibility matters.
- **NOT computed — genuinely not predictable in advance**:
  - `Num_Opt_Params_Theta` (TN/θ-side parameter count). The paper's own
    worked example (4 qubits, 1 TN layer) uses 5 tensor blocks x
    (3 or 1 params each) = 15 or 5 parameters, but no general formula
    for N qubits is given in either source, and Cebule's docs list
    `theta` only as an **output** of a real run, not something derivable
    from `n_layers_network` alone.
  - `Num_ExpVals_Per_Iter`. The paper's own Section 3.1 states each Pauli
    string's expectation value is measured independently, but how many
    *distinct* Pauli terms result from the TN-optimized Hamiltonian
    (`h_tn_opt_qubit`/`qubit_operators`) is explicitly an **output**, not
    an input-derivable count — it may differ from (and is expected to be
    smaller than) the original Hamiltonian's raw term count, which is the
    whole point of the MPO compression.
- **`TN_Layers_Network=0` rows**: per the paper's own "circuit only"
  baseline (tested directly alongside 1/2/3-layer TN in Figures 11–12),
  this is equivalent to plain VQE on the same input Hamiltonian encoding
  — included explicitly (rather than assuming the reader cross-references
  the `JW`/`mol_map` rows) so every row stays self-contained.
- **Sweep ranges** (`TN_Layers_Network` 0–3, `TN_Layers_Circuit` 1–4) match
  the paper's own tested values exactly (Figures 11 and 12 each show a
  1/2/3/4-layer-circuit x 4-panel grid, with "circuit only" as the 0-TN
  baseline in every panel) — not arbitrarily chosen.
- **Scope**: applied to all 7 bases (up to Li2/cc-pVTZ's 120 qubits) per
  your explicit choice — note neither the paper (a 4-qubit toy Ising
  chain) nor Cebule's docs give any indication these larger sizes are
  practically tractable for the *tensor-network* side specifically; only
  the smaller bases have any precedent.

## QASM_GEN: the with/without-measurement-method dimension

Sourced from Cebule's own docs
([docs.mqs.dk, checked 2026-07-09](https://docs.mqs.dk/sections/section_014_quantum_computing/)),
which the SDK's maintainers describe as recently updated — this revision
now documents QASM_GEN with a full parameter table for the first time
(previously flagged in `schemas/mqsdk_cebule.py` as "unconfirmed against
current SDK source," which remains true for TaskType-enum membership
specifically, but the method itself is now fully documented):

> "The measurement method efficiently evaluates the expectation value of
> the mapped Hamiltonian using a novel circuit generation scheme that
> groups terms by computational basis state pairs rather than Pauli
> string decomposition."

Applied as an independent `Measurement_Method` dimension across the
**whole** matrix (your choice, not scoped to TN-VQE only) because
QASM_GEN's own docs describe it as "compatible with outputs from MOL_MAP
or TN_QC_OPT" — a general measurement strategy for any mapped
Hamiltonian, not something tied to one Hamiltonian source:

- **`tn_qc_opt`/`tn_qc_opt+mol_map` rows**: maps directly onto the real
  `TNQCOptInput.measurement_method` field (`"pauli"` vs `"grouped"` —
  confirmed real, newly documented alongside `optimization_mode`, both
  added to `schemas/mqsdk_cebule.py` this session).
- **`JW`/`mol_map` rows**: represents applying the standalone `QASM_GEN`
  task as a separate measurement-circuit-generation step on top of that
  Hamiltonian — structural, not a literal field on a schema those rows
  already carry (they don't call `TN_QC_OPT` at all).

**Not computed**: the actual circuit-count difference between the two
methods. QASM_GEN's whole purpose is grouping Pauli terms sharing a
measurement basis into fewer circuits than naive per-term measurement, so
`qasm_gen_grouped` rows should need fewer-or-equal real circuit
submissions per iteration than `pauli` rows for the *same* Hamiltonian —
but the exact count is an **output** of a real QASM_GEN/TN_QC_OPT run
(`circuit_files` length), not derivable from the inputs alone. This means
the [IBM cost estimator](../docs/integrations/ibm_cost_estimator.md) and
[`batches/`](batches/) currently estimate `pauli` and `qasm_gen_grouped`
variants of the same row as **identical cost** (same ansatz, same
qubits, same shots) — a known simplification, not a claim that the two
methods really cost the same on real hardware.

## Cost implication: `TN_Layers_Network` is classical, not QPU time

Per the paper's own pipeline diagram (Figure 10): the TN/θ evaluation runs
on a "Classical Computational Processing Unit (CPU) or Graphical
Processing Unit (GPU)," while only the quantum-circuit/φ evaluation runs
on the "Quantum Processing Unit (QPU)." That means, for the
[IBM cost estimator](../docs/integrations/ibm_cost_estimator.md):
**`TN_Layers_Network` affects your own classical compute cost, not IBM
QPU-seconds billing** — only `TN_Layers_Circuit` (via the real ansatz
depth it produces) changes what you pay IBM. A high-`TN_Layers_Network`,
low-`TN_Layers_Circuit` configuration could be the cheapest *IBM* option
in this matrix while being the most classically expensive — the two costs
don't move together.

## Two things this file cannot verify offline

**`mol_map` qubit counts** (also gates `tn_qc_opt+mol_map`'s `N_Qubit`).
Cebule's `MOL_MAP` task produces a molecule-specific constraint-based
encoding (`num_qubits < 2N`, per `MolMapResult`'s own docstring) — it
isn't a formula over basis-set size, so only the six values already
present in the original draft (H2 × 4 bases, Li2/H2O × sto-3g) are known;
the rest are blank pending a real `MOL_MAP` run (1,176 `tn_qc_opt+mol_map`
rows — doubled by the `Measurement_Method` dimension — inherit this gap;
870 rows total have no known `N_Qubit`, see `batches/
batch0_unestimable_needs_mol_map_run.csv`).

**qvSZP qubit counts — corrected, not just unverifiable.** qvSZP's
`q-vSZP_basis/basisq` (and the independently-generated CP2K-format file)
are static, per-element shell tables — only the *contraction coefficients*
are charge-dependent, not the function count, so it's fully computable
offline via `hamiltonian_sources.qvszp` (no ORCA needed). This caught a
real error in the original draft: its Li2/qvSZP value (`34`) was
physically impossible for a homonuclear diatomic. Corrected to `36`; H2
(`16`) and H2O (`34`) were already correct. See
[docs/integrations/basis_sets.md](../docs/integrations/basis_sets.md).

## Still needed from you

1. **Geometries.** `N_Qubit` doesn't depend on bond length, but actually
   *running* any of these cases does. Fixed experimental/literature bond
   length per molecule, or a basis-specific CCSD(T)/MP2-optimized geometry?
2. **Active space.** Full space for all three molecules, or a frozen-core
   / active-space reduction for the larger bases (up to 120 qubits) to
   keep them classically checkable?
3. **`Qiskit_Opt_Level` / `Shots`.** Still blank for every row — apply
   uniformly across the whole matrix, or sweep them too?
4. **`mol_map` gaps.** Want me to wire up a real `MOL_MAP` call (via
   `qpubench.schemas.mqsdk_cebule.MolMapInput`, needs Cebule SDK
   credentials) to fill in the remaining blank `mol_map`/`tn_qc_opt+mol_map`
   `N_Qubit` values, or are those out of scope for now?
5. **`n_iterations`.** `TNQCOptInput.n_iterations` (max optimizer
   iterations) has no documented default and isn't a column here — worth
   adding once you've picked a value, since it directly affects total QPU
   time in the [IBM cost estimator](../docs/integrations/ibm_cost_estimator.md).
6. **2,436 rows is a lot.** If the full `tn_qc_opt`/`tn_qc_opt+mol_map`
   x `Measurement_Method` sweep across all 7 bases turns out to be more
   than you actually intend to run, say which subset (bases / layer
   ranges / rotation types / measurement methods) to prune back to —
   happy to trim it down.
7. **`optimization_mode`.** `TNQCOptInput.optimization_mode`
   (`"circuit"`/`"network"`/`"both"`, added to the schema this session
   alongside `measurement_method`) isn't a column here yet — want it swept
   too, or held at Cebule's own `"both"` default (jointly optimize θ/φ,
   matching the reference paper's own approach)?
