# TN-VQE vs VQE: a targeted simulator study

## Objective

This campaign measures how much a tensor-network based VQE method
(TN-VQE) improves molecular ground-state energies over a conventional
VQE treatment of the same system. In TN-VQE part of the variational work
is carried out classically: a tensor-network transformation `U(θ)` is
contracted on CPU and optimised jointly with a parameterised quantum
circuit `U(φ)`. The method under test is Cebule's `TN_QC_OPT`, following
the hybrid tensor-network and circuit construction of [1].

Plain VQE is the reference treatment. The campaign is built around one
baseline run and a set of named axes, each varying exactly one thing off
it, so a question has one row to point to rather than a slice of a large
crossing:

1. **Mapper**: Jordan-Wigner (JW) against Cebule's `mol_map` constraint
   encoding, reindexed for circuit efficiency (`MolMap_sb` —
   see [Mappers](#mappers)).
2. **Ansatz**: two hardware-efficient families (`RealAmplitudes`,
   `rzryrz`) at several repetition counts and entangler
   topologies, against two chemistry-motivated ones (`UCCSD`, tUPS/
   pp-tUPS) that reach the reference determinant exactly.
3. **Optimizer**: `COBYLA`, `SPSA` and `ExcitationSolve`, each given the
   same quantum-evaluation budget converted into its own iteration unit.
4. **Method and TN-layers**: plain `VQE` against `TN-VQE` (jointly
   optimising `θ` and `φ`) against the classical-only `TN` control (θ
   alone, no quantum measurements at all), with `TN_Layers_Network`
   swept over `{1, 2, 3}` where it applies — 2 is the value that
   matters most for the comparison against plain VQE.
5. **Mapper × method × TN-layers, deliberately crossed**: does TN-VQE's
   advantage over plain VQE depend on Hamiltonian density, which
   `MolMap_sb` increases relative to JW?

Everything here runs on `aer_simulator`; no run in this file consumes
purchased hardware time or applies error mitigation.

## Campaign structure

Everything this campaign decides lives in this folder; the reusable
machinery it runs on is the shared toolkit in [`utils/`](../../utils/).

| File | What it is |
|---|---|
| [`build_matrix.py`](build_matrix.py) | Generates `targeted_screen.csv`: the molecules, axes, shots, optimizer settings and budget multiplier are all set here |
| [`campaign.py`](campaign.py) | What the shared tools need to know: file locations, Hamiltonian file names, Hartree-Fock states under MolMap_sb, the device to price against |
| [`regenerate_spinblock_mol_map.py`](regenerate_spinblock_mol_map.py) | Builds the MolMap_sb Hamiltonians and the UCCSD/tUPS circuits from them |
| `targeted_screen.csv` | The matrix |
| `hamiltonian_data/`, `qasm/` | The Hamiltonians the runs optimise, and the circuits they run |
| `results/` | Collected runs (gitignored) |
| `run_campaign_batch.ipynb`, `plot_results.ipynb` | Running the campaign interactively, and plotting its results |

The matrix is generated with

```sh
PYTHONPATH=src python campaigns/ibm_tn-vqe_qesem/build_matrix.py --stage targeted
```

Each row defines one VQE or TN-VQE run: a single optimisation of one
Hamiltonian by one method, with its own ansatz, mapper, measurement
method and evaluation budget. `build_targeted_screen()` in
[`build_matrix.py`](build_matrix.py)
is the source of truth for what each row actually is; the axes table
below is a summary of it.

Two things execute the campaign, and they build their runs through the
same module ([`_campaign_runner.py`](../../utils/_campaign_runner.py)),
so neither can drift from the other. Both submit nothing until told to,
both checkpoint per run so an interrupted pass resumes rather than
re-spending time, and both read credentials from the environment rather
than from a notebook cell or a command line.

[`run_campaign.py`](../../utils/run_campaign.py) runs the file from
the command line, selected with `--where` filters:

```sh
PYTHONPATH=src python utils/run_campaign.py --campaign ibm_tn-vqe_qesem --submit
PYTHONPATH=src python utils/run_campaign.py --campaign ibm_tn-vqe_qesem --collect
```

**Submission and collection are separate.** Cebule dispatches to outside
HPC infrastructure, so a task spends most of its life queued rather than
running; submitting one and blocking until it returns spends that queue
time doing nothing, in the one process that could have been submitting
the rest. `--submit` creates tasks and returns, `--collect` harvests
whatever has finished since, and `--max-in-flight N` keeps a steady queue
rather than sending everything at once.

Three files carry the state, beside each other under `results/`:
`targeted_screen.ndjson` holds finished runs, `targeted_screen.
pending.ndjson` the task ids submitted and not yet collected,
`targeted_screen.failed.ndjson` the tasks that came back with status
`error`. A run is skipped if it appears in any of them, so repeating a
command never double-submits and never re-collects, and a failure stays
failed until `--retry-failed` says otherwise.

**Which backend a run uses is the run's own `Backend_Platform`** (always
`aer_simulator` here), not a choice made at submission time — see
`run_campaign.py --backend`'s own help text for why `--collect` never
overrides it.

## The baseline row and axes

**One baseline row**: H2/6-31g, JW, `RealAmplitudes`, `COBYLA`, `VQE`,
2 repetitions. Every other row varies exactly one thing off it,
except the one deliberately crossed axis below.

| Axis | What varies | Held at the baseline |
|---|---|---|
| Mapper | JW ↔ MolMap_sb | Every ansatz — `RealAmplitudes`, `rzryrz`, `UCCSD`, tUPS/pp-tUPS — each run under both |
| Ansatz reps (tUPS/pp-tUPS: layers) | 1, 2, 3, 4 | `RealAmplitudes`, `rzryrz` and tUPS/pp-tUPS, JW |
| Entangler topology | `reverse_linear`, `sca` and `full` on both families (defaults: `reverse_linear` for `RealAmplitudes`, `sca` for `rzryrz`) | `RealAmplitudes` and `rzryrz`, JW, at 2 reps |
| Optimizer | `COBYLA`, `SPSA`, `ExcitationSolve` | `RealAmplitudes` (cheap; also where SPSA's `target_step`/`c` are tuned), `UCCSD` (where SPSA is tuned too, and ExcitationSolve's `frequencies` — see `opt_options_for` in `build_matrix.py`) and `tUPS` at its default 2 layers |
| Method × TN-layers | `TN-VQE`/`TN` × `TN_Layers_Network` ∈ {1,2,3} (2 matters most) | `RealAmplitudes`, JW — `VQE` ignores `TN_Layers_Network` entirely, so it carries no rows in this axis |
| Mapper × method × TN-layers | the same sweep, under MolMap_sb instead of JW | `RealAmplitudes` — does TN-VQE's advantage depend on Hamiltonian density? |
| TN-VQE on tUPS | `TN-VQE` at `TN_Layers_Network` = 2, under JW and MolMap_sb | tUPS/pp-tUPS at 2 layers, `COBYLA` — does TN-VQE's advantage carry over to a chemistry ansatz? Compared against the mapper axis's VQE tUPS rows |
| Richer system | H2O/6-31g, under MolMap_sb and JW (UCCSD under MolMap_sb only — see [Known limitations](#known-limitations)) | `RealAmplitudes` and tUPS/pp-tUPS under both mappers, `UCCSD` under MolMap_sb |

A row that coincides with an earlier one on every field but `Case_ID` and
`Notes` (the reps=2 point of the reps axis *is* the baseline, for
instance) is numbered and then dropped: every row gets a `Case_ID` first,
so a collapsed duplicate leaves a gap rather than reshuffling anything
after it (`assign_case_ids` then `dedupe_rows`, from
`utils/_matrix_io.py`). 46 rows, `Case_ID`s 1–53 with seven gaps.

**Every ansatz-optimizer-mode combination reuses the same Hamiltonian,
pinned circuit and `Phi_Init`** for a given (molecule, basis, mapper)
cell, so a difference between two rows is attributable to the one thing
their axis actually varies.

## Chemistry cells

| Molecule | Active space | Basis | Mapper | Qubits |
|---|---|---|---|---:|
| H2 | unrestricted (2e in 4 orbitals) | 6-31g | JW | 8 |
| H2 | unrestricted (2e in 4 orbitals) | 6-31g | MolMap_sb | 4 |
| H2O | CAS(4,4) | 6-31g | JW | 8 |
| H2O | CAS(4,4) | 6-31g | MolMap_sb | 6 |

Every run is at the experimental equilibrium geometry, given in Angstrom
in the `Geometry` column: H2 at `r = 0.74144`, H2O at `r = 0.9572` and
`104.52` degrees. H2O's CAS(4,4) freezes the O 1s core; it is a screening
space rather than a converged-chemistry one. Every Hamiltonian is
committed under `hamiltonian_data/`.

## Ansätze

| Ansatz | Parameters | Structure |
|---|---|---|
| `RealAmplitudes` | `n(R+1)` | Ry only, reverse-linear entangler by default. Real amplitudes only; the baseline ansatz |
| `rzryrz` | `3n(R+1)` | Rz+Ry+Rz, shifted-circular-alternating entangler by default (Qiskit `n_local` with `sca` entanglement). The circuit `TN_QC_OPT` builds for itself when no `qasm_ansatz` is supplied — in the comparison so the vendor's own default is measured rather than assumed |
| `UCCSD` | 15, 26 | A restricted singles-and-doubles ansatz out of the reference determinant, as a single layer (`Ansatz_Reps` = 1 on every UCCSD row, whatever the axis around it uses). The chemistry anchor the hardware-efficient families are compared against |
| tUPS / pp-tUPS | 9 per layer | Tiled Unitary Product State [7], swept at 1–4 layers (2 is the default). Number-conserving and HF-initialized like UCCSD; `perfect_pairing_order` when occupied and virtual orbitals are equal in number (pp-tUPS), `occupied_middle_order` otherwise (plain tUPS) |

`RealAmplitudes` and `rzryrz` are built by
[`_ansatz_builders.py`](../../utils/_ansatz_builders.py) and pinned as
OpenQASM 3.0 under `qasm/`, one file per distinct (ansatz, qubits,
repetitions, entanglement), named in `Qasm_Ansatz_File` and hashed in
`Qasm_Ansatz_SHA256` so a silently edited circuit is detectable. A named
ansatz is not a circuit — it is a name a library version resolves — so
this is what makes two rows naming the same ansatz comparable.

`UCCSD`'s circuits are supplied by hand rather than generated by
`pin_qasm_ansatz.py`'s generic loop, because mol_map's qubits index
determinants with no occupied/virtual split for excitation operators to
be built from, and because `_ansatz_builders.uccsd()`'s own generalized
singles-and-doubles pool has more parameters (40 at H2/6-31g) than the
restricted ansatz these circuits pin (15, 26). `can_build`/
`SUPPLIED_ANSATZE` in `_ansatz_builders.py` enforce that this repository
never overwrites them. No UCCSD/JW/H2O circuit is currently pinned (see
[Known limitations](#known-limitations)).

tUPS/pp-tUPS is built by
[`regenerate_spinblock_mol_map.py`](regenerate_spinblock_mol_map.py)
from [`_fermionic_ansatz.py`](../../utils/_fermionic_ansatz.py) —
vendored from `CompareVQEs/ansatze.py`, which also supplies the
`MolMap_sb` reordering below. It stays in `SUPPLIED_ANSATZE` for
stem-naming purposes (a chemistry-dependent circuit, like UCCSD, not a
`(qubits, reps)`-only one) even though it is genuinely built, just by
this dedicated script rather than `pin_qasm_ansatz.py`'s generic loop.

**`RealAmplitudes`**, shown at 4 qubits with `reps = 2` (12 parameters).
One Ry rotation layer per repetition and a reverse-linear CX chain:

```text
     ┌──────────┐                             ┌──────────┐                          ┌──────────┐
q_0: ┤ Ry(θ[0]) ├──────────────────────■──────┤ Ry(θ[4]) ├───────────────────■──────┤ Ry(θ[8]) ├
     ├──────────┤                    ┌─┴─┐    ├──────────┤                 ┌─┴─┐    ├──────────┤
q_1: ┤ Ry(θ[1]) ├──────────■─────────┤ X ├────┤ Ry(θ[5]) ├──────■──────────┤ X ├────┤ Ry(θ[9]) ├
     ├──────────┤        ┌─┴─┐    ┌──┴───┴───┐└──────────┘    ┌─┴─┐    ┌───┴───┴───┐└──────────┘
q_2: ┤ Ry(θ[2]) ├──■─────┤ X ├────┤ Ry(θ[6]) ├─────■──────────┤ X ├────┤ Ry(θ[10]) ├────────────
     ├──────────┤┌─┴─┐┌──┴───┴───┐└──────────┘   ┌─┴─┐    ┌───┴───┴───┐└───────────┘
q_3: ┤ Ry(θ[3]) ├┤ X ├┤ Ry(θ[7]) ├───────────────┤ X ├────┤ Ry(θ[11]) ├─────────────────────────
     └──────────┘└───┘└──────────┘               └───┘    └───────────┘
```

`rzryrz`, `UCCSD` and tUPS are not drawn here — at 4 qubits
`rzryrz` is three times the width of the diagram above, and
the mol_map circuits for the other two run to thousands of gates. All
are in `qasm/`, where the pinned file is the authority anyway.

The `full` entangler variant (the entangler-topology axis) pins to its
own file, distinguished in the stem by `qasm_stem`
(`_ansatz_builders.py`) whenever it differs from a family's own default
— `RealAmplitudes_8q_2r_full.qasm` against the default `RealAmplitudes_
8q_2r.qasm`, for instance.

## HF-approximating initial parameters

`RealAmplitudes` and `rzryrz` start from an
HF-approximating `phi_init` (`Phi_Init = "hf-approx"`) rather than a
random draw, so a VQE/TN-VQE/network comparison is not confounded by an
arbitrary starting point. Only the *last* rotation layer is set (π on
each occupied qubit, 0 elsewhere): a CX gate controlled by a qubit still
in `|0⟩` is the identity, so the state stays `|0...0⟩` untouched through
every earlier entangler, and there is no entangler after the final
rotation layer to disturb what it sets — exact regardless of entangler
topology. Verified against the classical reference energy, both mappers,
both families (`_ansatz_builders.hf_approx_phi_init`, backed by
`_fermionic_ansatz.hf_parameters`).

The occupied-qubit pattern itself (`_ansatz_builders.hf_state_for`) is a
formula under JW — the first `Active_Electrons` qubits, the same
convention `UCCSD`'s own reference-state preparation uses — and data
under MolMap_sb, from `regenerate_spinblock_mol_map.py`'s own
computed `hf_state` (`_ansatz_builders.MOL_MAP_SPINBLOCK_HF_STATE`),
since the reordering that produces it is not a formula. `UCCSD` and
tUPS need no such treatment: both are number-conserving and already
HF-initialized at zero amplitudes (`Phi_Init = "zeros"`).

The parameter order matters and is *not* the order a freshly-built
circuit's own `.parameters` gives: once a circuit is loaded from its
pinned QASM text (`qiskit.qasm3.loads`), Cebule binds `phi_init`
positionally against *that* circuit's `.parameters`, which sorts
alphabetically over the raw identifier string (`"_θ_0_"`, `"_θ_10_"`,
`"_θ_11_"`, …, `"_θ_1_"`, …) rather than numerically. `hf_approx_phi_init`
translates by parameter name, never by position.

## Mappers

`Mapper` records the fermion-to-qubit mapping:

| Value | Meaning |
|---|---|
| `JW` | Jordan-Wigner, `2 × Active_Orbitals` qubits, spin-orbitals interleaved |
| `MolMap_sb` | Cebule's constraint-based MOL_MAP encoding, reindexed so alpha and beta spin-orbitals fall in contiguous blocks |

Cebule's MOL_MAP output indexes only the determinants satisfying the
active space's particle-number and spin constraints, so its qubit count
follows the active space rather than the basis set. That output's own
ordering, however, is not the one the fermionic ansätze (`UCCSD`, tUPS)
need to synthesise cheaply — tUPS in particular depends on the two spins
falling in contiguous blocks rather than being interleaved arbitrarily.
`spin_product_mapping` (`_fermionic_ansatz.py`) reindexes a MOL_MAP
mapping matrix into that form; `reorder_mapped_hamiltonian` applies the
same change of basis to the Hamiltonian. Both are purely local
recomputations, from `mapping_matrix` already committed in
`hamiltonian_data/*_mapped.json` — no MOL_MAP submission is made to
produce `MolMap_sb`.

`regenerate_spinblock_mol_map.py` runs this for the campaign's two
mol_map cells and writes `hamiltonian_data/{h2_6-31G,water_6-31G}_
MolMap_sb.json` and the matching `qasm/*_MolMap_sb_
*.qasm` circuits, verifying each against the cell's known Hartree-Fock
energy before writing anything. One thing worth knowing if this is
extended to another cell: a MOL_MAP mapping matrix's row index, as
Cebule reports it, is bit-reversed relative to a Qiskit-native
computational-basis integer. `_committed_D` in that script corrects it;
skipping that step reproduces the right physics for a chemistry cell
whose Hartree-Fock row happens to be a bit-palindrome (H2/6-31g, by
coincidence) and silently the wrong physics for one that isn't
(H2O/6-31g CAS(4,4), where the bug was actually found — a scan of every
computational basis state against the known Hartree-Fock energy matched
none of the matrix's own declared rows, and matched exactly one bit
reversal away from the correct one).

Reordering also dropped the Hamiltonian's own Pauli-term count
substantially: 120 → 52 for H2/6-31g, 1304 → 392 for H2O/6-31g CAS(4,4).

## Columns

| Column | Meaning |
|---|---|
| `Case_ID` | Row index |
| `Stage` | `targeted`, on every row |
| `Molecule`, `Charge`, `Multiplicity`, `Num_Electrons` | `H2` and `H2O`, both neutral closed-shell singlets |
| `Geometry` | Nuclear positions in Angstrom, the experimental equilibrium geometry in every row |
| `Basis`, `Basis_Source` | `6-31g` throughout, from Basis Set Exchange [6] |
| `Active_Space` | `full` (H2) or `valence_cas` (H2O) |
| `Active_Electrons`, `Active_Orbitals` | The space the Hamiltonian is built in |
| `Mapper` | `JW` or `MolMap_sb` — see [Mappers](#mappers) |
| `N_Qubit`, `N_Qubit_Source` | Qubit count and its provenance: `jw_exact` or `MolMap_sb_computed` |
| `Method` | `VQE` (plain), `TN-VQE` (θ and φ jointly optimised) or `TN` (classical-only control: θ alone, no quantum measurements) |
| `Ansatz` | `RealAmplitudes`, `rzryrz`, `UCCSD` or `tUPS` |
| `Ansatz_Reps` | Repetitions (or, for tUPS, layers) of the ansatz circuit |
| `Entanglement` | Blank except on the entangler-topology axis's rows (`RealAmplitudes`/`rzryrz` only), where it names the non-default entanglement |
| `Backend_Platform` | `aer_simulator`, on every row |
| `Optimizer`, `Opt_Options` | `COBYLA`, `SPSA` or `ExcitationSolve`. `Opt_Options` is the dictionary passed to `scipy.optimize.minimize` (or Cebule's own optimizer): `{}` except for SPSA on `RealAmplitudes`/`rzryrz`/`UCCSD`/`tUPS` and ExcitationSolve on `UCCSD`, tuned in `opt_options_for` (`build_matrix.py`) |
| `Quantum_Eval_Budget` | Quantum evaluations the row is allowed, held equal across optimizers and covering the whole run, including SPSA's calibration and closing repeats and ExcitationSolve's flatness check and validation: `max(30, ceil(120 × n_params))`, enough for each run to reach its optimum rather than be cut off -- sized for SPSA on tUPS, the slowest case seen |
| `Quantum_Evals_Per_Iteration` | What one iteration of this row's optimizer spends of the budget: 1 for COBYLA, 2 for SPSA, `4 × n_phi` for ExcitationSolve — 0 wherever φ is frozen, since a θ-only change is served from cache |
| `Cost_Evals_Per_Iteration` | Entries one iteration adds to `cost_history`, the axis convergence curves are aligned on |
| `Iterations` | What `TNQCOptInput.n_iterations` receives |
| `Shots` | 50,000, pinned via `TNQCOptInput.n_shots`, so one evaluation's shot noise is about 1 mHa on H2; `n/a (network mode)` on `TN` rows, which take no quantum measurement |
| `Qiskit_Version` | The installed Qiskit, which fixes the transpiler optimisation level the run receives |
| `TN_Layers_Network` | Layers of θ on the classical tensor-network side; blank on `VQE` rows, which ignore it entirely; 1, 2 or 3 on `TN-VQE`/`TN` rows |
| `TN_Ansatz` | `givens` on every TN-VQE row, or `n/a (not TN-VQE)` |
| `Measurement_Method` | `pauli` (JW rows) or `grouped` (MolMap_sb rows) |
| `Qasm_Ansatz_File`, `Qasm_Ansatz_SHA256` | The pinned circuit and a hash prefix of it |
| `Num_Opt_Params_Phi` | Circuit-side parameter count, the `num_parameters` the pinned QASM loads with. On a `TN` row it is the count held fixed |
| `Phi_Init` | `"zeros"` (`UCCSD`, tUPS), `"hf-approx"` (`RealAmplitudes`, `rzryrz`) — see [HF-approximating initial parameters](#hf-approximating-initial-parameters) |
| `Num_Opt_Params_Theta` | Network-side parameter count on a TN-VQE row |
| `Num_ExpVals_Per_Iter`, `Num_ExpVals_Source` | Measurement circuits one evaluation submits, and where that count came from |
| `Error_Mitigation`, `Precision`, `QESEM_Execution_Mode` | `none`, `n/a (shot-based)`, `n/a (not QESEM)` on every row — no mitigation is applied in this file |
| `Converged_Params_File`, `Converged_Params_SHA256` | Blank on every row in this file — no row here is a stage-3 refinement |
| `Notes` | Per-row provenance and caveats |

## Known limitations

- **`MolMap_sb` covers two chemistry cells.** H2/6-31g and
  H2O/6-31g's CAS(4,4) are what this campaign needs; extending it to
  another cell means running `regenerate_spinblock_mol_map.py` against
  that cell's own committed `mapping_matrix`, correcting for the
  row-bit-reversal noted under [Mappers](#mappers).
- **The entangler-topology axis compares only one alternative, `full`,
  per family.** It answers "does topology matter at all", not "which
  topology is best".
- **tUPS/pp-tUPS is not part of the optimizer or entangler-topology
  axes.** It shares the reps axis with the hardware-efficient families
  (1–4 layers, 2 default) and the mapper axis, but has no entanglement
  pattern to vary, and its own optimizer tuning is untested.
- **UCCSD/JW is not run on H2O.** No `UCCSD_JW_8q_1r_4e.qasm` circuit is
  currently pinned — `_fermionic_ansatz.uccsd()` can build and verify one
  (see [Ansätze](#ansätze); the same generator tUPS uses, wrapped in
  `reverse_bits()`) — but an earlier UCCSD-on-H2O run also took excessive
  wall time, and that cell's cost is not yet confirmed acceptable either;
  H2O/JW in this file is `RealAmplitudes` and tUPS only.
- **`HF_APPROX_ANSATZE` and closed-shell orbitals are assumed together.**
  `hf_state_for`'s JW branch raises if `Active_Electrons` is odd; every
  cell this campaign runs is closed-shell, so this has not been
  exercised for an open-shell system.
- **`ExcitationSolve`'s frequency tuning is UCCSD-specific.**
  `opt_options_for` special-cases `UCCSD` alone, because the workaround is
  for UCCSD's own two-frequency excitation angles; `RealAmplitudes` under
  `ExcitationSolve` and `tUPS` under `ExcitationSolve` run with
  `Opt_Options = "{}"`, unverified to need no similar treatment.
  `SPSA`'s `target_step`/`c` tuning, by contrast, is no longer
  UCCSD-only — `SPSA_TUNED_ANSATZE` covers `RealAmplitudes`,
  `rzryrz` and `tUPS` too. The values were tuned on UCCSD;
  the other families reuse them as a starting hypothesis, and tUPS has no
  SPSA result yet to check it against. Re-check each family once its
  affected rows are (re-)run.
- **RealAmplitudes cannot leave its `hf-approx` start.** That point is a
  zero-gradient local minimum of the ansatz, so every optimizer returns
  roughly the HF energy there, whatever its settings; a `vqe_energy`
  below HF on these rows is the lowest of many noisy evaluations, not
  real progress.
- **`vqe_energy` is biased low; compare statevector energies instead.** It is
  the lowest noisy evaluation a run saw, so it sits a few shot-noise
  widths below the energy of any state the run reached. Result records
  therefore also carry the final `phi`, `theta` and transformed
  Hamiltonian (`h_tn_opt_qubit`), and `plot_results.ipynb` re-evaluates
  the final state by noiseless statevector simulation
  (`utils/_statevector_energy.py`), as `final_state_energy`. Records
  collected before this was stored fall back to `vqe_energy`.

## Open decisions

1. **Whether `RealAmplitudes`/`ExcitationSolve` needs its own
   `opt_options` tuning**, the way `UCCSD` did.

## References

1. Y. Sun *et al.*, "Quantum simulation with hybrid tensor networks",
   [arXiv:2402.12105](https://arxiv.org/abs/2402.12105). The hybrid
   tensor-network and circuit construction `TN_QC_OPT` implements.
2. MQS documentation, quantum-computing section:
   [docs.mqs.dk](https://docs.mqs.dk/sections/section_014_quantum_computing/).
   Cebule's TN-VQE task, the MOL_MAP encoding and the `grouped`
   measurement scheme (checked 2026-07-09).
3. Basis Set Exchange:
   [basissetexchange.org](https://www.basissetexchange.org/). The source
   of the `6-31g` basis set.
4. H. G. A. Burton, "Accurate and gate-efficient quantum ansätze for
   electronic states without adaptive optimization",
   [Phys. Rev. Research 6, 023300](https://doi.org/10.1103/PhysRevResearch.6.023300).
   The Tiled Unitary Product State (tUPS/pp-tUPS) ansatz.
