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
6. **Optimizer × TN-layers and ansatz depth × TN-layers**: TN-VQE under
   the optimizers that converge under shot noise (`SPSA`,
   `ExcitationSolve`), and whether the network makes up for a missing
   tUPS layer.

Most rows run on `aer_simulator` (shot noise only); eighteen repeat
`aer_simulator` rows on `fake_berlin`, the offline noise snapshot of
`ibm_berlin`, the device hardware time is bought on. The five hardware
runs also run as simulator twins, readout correction included, on
`fake_berlin` (cases 128, 122, 129, 130, 131) and on `fake_aachen`
(123–127), the snapshot of the alternative device `ibm_aachen`, and at
half the device shots (132–146) and at 18 sweeps (147–161) on all three
backends. No run in
`targeted_screen.csv` consumes purchased hardware time, and only the
noisy-simulator copies of the hardware runs apply error mitigation. Five of its uncorrected `fake_berlin` rows
are repeated on `ibm_berlin` itself, with readout correction, in a
matrix of their own: [Hardware runs](#hardware-runs).

## Campaign structure

Everything this campaign decides lives in this folder; the reusable
machinery it runs on is the shared toolkit in [`utils/`](../../utils/).

| File | What it is |
|---|---|
| [`build_matrix.py`](build_matrix.py) | Generates `targeted_screen.csv` and `hardware_runs.csv`: the molecules, axes, shots, optimizer settings and budget multiplier are all set here |
| [`campaign.py`](campaign.py) | What the shared tools need to know: file locations, Hamiltonian file names, Hartree-Fock states under MolMap_sb, the device to price against |
| [`regenerate_spinblock_mol_map.py`](regenerate_spinblock_mol_map.py) | Builds the MolMap_sb Hamiltonians and the UCCSD/tUPS circuits from them |
| `excitationsolve_frequencies.json` | ExcitationSolve's frequency set for each circuit parameter, per circuit, Hamiltonian and start; written by `build_matrix.py` the first time a circuit needs it |
| `targeted_screen.csv` | The simulator matrix |
| `hardware_runs.csv` | The `ibm_berlin` runs, each a `fake_berlin` row of `targeted_screen.csv` repeated on the device (see [Hardware runs](#hardware-runs)) |
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

**Which backend a run uses is the run's own `Backend_Platform`**
(`aer_simulator`, or `fake_berlin` on the noisy-simulator rows), not a
choice made at submission time — see
`run_campaign.py --backend`'s own help text for why `--collect` never
overrides it.

## The baseline row and axes

**One baseline row**: H2/6-31g, JW, `RealAmplitudes`, `COBYLA`, `VQE`,
2 repetitions. Every other row varies one thing off it, except where an
axis below names two things it crosses deliberately.

| Axis | What varies | Held at the baseline |
|---|---|---|
| Mapper | JW ↔ MolMap_sb | Every ansatz — `RealAmplitudes`, `rzryrz`, `UCCSD`, tUPS/pp-tUPS — each run under both |
| Ansatz reps (tUPS/pp-tUPS: layers) | 1, 2, 3, 4 | `RealAmplitudes`, `rzryrz` and tUPS/pp-tUPS, JW |
| Entangler topology | `reverse_linear`, `sca` and `full` on both families (defaults: `reverse_linear` for `RealAmplitudes`, `sca` for `rzryrz`) | `RealAmplitudes` and `rzryrz`, JW, at 2 reps |
| Optimizer | `COBYLA`, `SPSA`, `ExcitationSolve` | `RealAmplitudes` (cheap; also where SPSA's `target_step`/`c` are tuned), `UCCSD` (where SPSA is tuned too, and ExcitationSolve's `frequencies` — see `opt_options_for` in `build_matrix.py`) and `tUPS` at its default 2 layers, all under JW; `RealAmplitudes` and `tUPS` also have all three under MolMap_sb, as the VQE rows of the TN-VQE-with-SPSA-and-ExcitationSolve axis |
| Method × TN-layers | `TN-VQE`/`TN` × `TN_Layers_Network` ∈ {1,2,3} (2 matters most) | `RealAmplitudes`, JW — `VQE` ignores `TN_Layers_Network` entirely, so it carries no rows in this axis |
| Mapper × method × TN-layers | the same sweep, under MolMap_sb instead of JW | `RealAmplitudes` — does TN-VQE's advantage depend on Hamiltonian density? |
| TN-VQE on tUPS | `TN-VQE` at `TN_Layers_Network` = 1, 2, 3, under JW and MolMap_sb | tUPS/pp-tUPS at 2 layers, `COBYLA` — does TN-VQE's advantage carry over to a chemistry ansatz? Compared against the mapper axis's VQE tUPS rows |
| Richer system | H2O/6-31g, under MolMap_sb and JW (UCCSD under MolMap_sb only — see [Known limitations](#known-limitations)) | `RealAmplitudes` and tUPS/pp-tUPS under both mappers, `UCCSD` under MolMap_sb, all VQE with `COBYLA`. Cases 167–180 add, for `RealAmplitudes` and tUPS under both mappers, VQE with `ExcitationSolve`, TN-VQE (2 TN layers) with `COBYLA` and with `ExcitationSolve`, and the network-only control. TN-VQE with `ExcitationSolve` runs under MolMap_sb only: its JW twin on H2, at the same 8 qubits and 4 spatial orbitals (case 79), ran too long to finish. UCCSD is not repeated |
| Start point | `hf-approx` ↔ `hf-approx` plus a seeded ~1 rad Gaussian kick (`hf-approx+kick(scale=1.0,seed=20260811)`) | `RealAmplitudes` and `rzryrz`, VQE, `COBYLA`, 2 reps, under both mappers — `hf-approx` is a local minimum for these families, and kicks up to ~0.3 rad fall back into it. The kick is the same vector on every row sharing a circuit |
| TN-VQE with SPSA and ExcitationSolve | `VQE` and `TN-VQE` at `TN_Layers_Network` = 1, 2, 3, under `SPSA` and `ExcitationSolve`, MolMap_sb; plus `TN-VQE` at 2 layers under JW | `RealAmplitudes` and tUPS at 2 reps (JW: tUPS only, against the optimizer axis's tUPS rows) — COBYLA stalls under shot noise, so the COBYLA TN-VQE rows cannot show whether the network helps. MolMap_sb because its circuits are shallow enough for a noisy backend |
| tUPS reps × TN layers | tUPS at 1 and 3 layers, `VQE` and `TN-VQE` at `TN_Layers_Network` = 1, 2, 3, `ExcitationSolve`; 1 layer also under `SPSA` | H2/6-31g, MolMap_sb. 1-layer tUPS stops 13.5 mHa above FCI on its own — does the network make up for the missing layer? 2 layers is the row above; 3 layers checks nothing changes where the circuit suffices. Circuits from `regenerate_spinblock_mol_map.py --h2-tups-layers` |
| Noisy simulator | `aer_simulator` → `fake_berlin` (cases 92–108 but 94, 121 and 122) and 128–131, and `fake_aachen` (123–127) (cases 92–108 and 121 each identical to an `aer_simulator` row but for the backend, and for ExcitationSolve's sweeps) | H2/6-31g, MolMap_sb. RealAmplitudes VQE against TN-VQE under `ExcitationSolve` (2 TN layers), and TN-VQE under `SPSA` (3); 1-layer tUPS VQE and TN-VQE (2 TN layers) against 2-layer tUPS VQE, all `ExcitationSolve`; RealAmplitudes `COBYLA` as a reference. MolMap_sb only: its circuits transpile to 6–118 two-qubit gates on the device, against 586–620 for the JW chemistry circuits. No error mitigation, so energies sit 35–180 mHa high; compare within pairs, and the statevector energy of each run's final parameters. ExcitationSolve rows stop after 6 sweeps (`NOISY_EXCITATIONSOLVE_SWEEPS`) instead of spending the full budget: it stops improving by its third sweep, and a noisy evaluation costs far more. Case 92 is the pilot; it ran the full 55 sweeps before the cap and finished where its noiseless twin did. Cases 100–102 repeat the tUPS rows 96–98 at 18 sweeps, because the 1-layer TN-VQE run was still descending at 6. Cases 103 and 104 spend about the same shots as case 101 differently on that shot-noise-limited row: 6 sweeps fitting each parameter from 18 points (ExcitationSolve's `samples`) instead of the minimal 1 + 2\|f\|, and 6 sweeps at 200,000 shots. All three ended 5.9–7.8 mHa above FCI: on that row the noise moves the minimum rather than blurring it, mostly through readout error. Cases 105–108 run the 1-layer tUPS and RealAmplitudes TN-VQE rows at 25,000 and 12,500 shots, to see whether fewer shots find the same parameters, and cases 162–166 are their `aer_simulator` references (and case 104's) at the same shots, since shot noise also moves where a run ends; case 121 repeats case 108 at 18 sweeps, since it was still descending at 6. Case 122 is case 108 with tn-vqe's tensored readout correction (`Error_Mitigation` = `readout_tensored`), the one corrected row here: it checks the feature on Cebule and measures what it does before hardware case 2 relies on it. Cases 123–127 run the five hardware runs, readout correction and device shots included, on `fake_aachen` instead, and cases 128–131 (with 122) run them on `fake_berlin`. Cases 132–146 run all five at half the device shots, and cases 147–161 at the device shots and 18 sweeps, on `aer_simulator`, `fake_berlin` and `fake_aachen` (see [Hardware runs](#hardware-runs)). Cases 181–183 run 2-layer tUPS TN-VQE (2 TN layers, `ExcitationSolve`, 50,000 shots, 18 sweeps) on the same three, readout corrected on the two noisy simulators. Cases 184–188 run the five hardware runs on `fake_aachen` from the final parameters of each one's full-budget noiseless run (cases 73, 82, 71, 80 and 75), to see how many sweeps a warm start needs (see [Cutting sweeps](#hardware-runs)). Cases 189–192 run the two TN-VQE hardware runs with a 1-layer network instead of 2, on `fake_berlin` (189, 190) and `fake_aachen` (191, 192), readout corrected at the device shots; cases 72 and 81 are their noiseless references. Cases 193–196 do the same with a 3-layer network, against cases 74 and 83 |
| Network-only controls | `TN` (θ alone, the circuit frozen at its start) for every TN-VQE configuration: RealAmplitudes from the Method × TN-layers axes (cases 33–35, 39–41) and tUPS (cases 109–120: 2 layers under JW, 1–3 layers under MolMap_sb, each at `TN_Layers_Network` = 1, 2, 3) | `COBYLA` with 1,000 evaluations per θ parameter (`NETWORK_EVALS_PER_PARAM`), which no run should reach: the contraction is exact and costs no circuits, so a row stops on the optimizer's own tolerance. One row covers every TN-VQE row sharing its mapper, circuit, start and TN layers, whatever their optimizer, shots or backend |

A row that coincides with an earlier one on every field but `Case_ID` and
`Notes` (the reps=2 point of the reps axis *is* the baseline, for
instance) is numbered and then dropped: every row gets a `Case_ID` first,
so a collapsed duplicate leaves a gap rather than reshuffling anything
after it (`assign_case_ids` then `dedupe_rows`, from
`utils/_matrix_io.py`). A retired row is dropped the same way: case 94, a
noisy-simulator SPSA VQE row whose noiseless twin ends at the local minimum
case 92 already covers. 188 rows, `Case_ID`s 1–196 with eight gaps.

**Every ansatz-optimizer-mode combination reuses the same Hamiltonian,
pinned circuit and `Phi_Init`** for a given (molecule, basis, mapper,
ansatz, depth) cell, so a difference between two rows is attributable to
the one thing their axis actually varies. The start-point rows are the
one exception: varying `Phi_Init` is what they are for.

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
| tUPS / pp-tUPS | 9 per layer | Tiled Unitary Product State [4], swept at 1–4 layers under JW and 1–3 under MolMap_sb (2 is the default). Number-conserving and HF-initialized like UCCSD; `perfect_pairing_order` when occupied and virtual orbitals are equal in number (pp-tUPS), `occupied_middle_order` otherwise (plain tUPS) |

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
`rzryrz` is three times the width of the diagram above, and the
chemistry circuits run to hundreds of gates under MolMap_sb and over a
thousand under JW. All are in `qasm/`, where the pinned file is the
authority anyway.

A non-default entangler (the entangler-topology axis) pins to its own
file, distinguished in the stem by `qasm_stem` (`_ansatz_builders.py`)
whenever it differs from the family's own default —
`RealAmplitudes_8q_2r_full.qasm` and `RealAmplitudes_8q_2r_sca.qasm`
against the default `RealAmplitudes_8q_2r.qasm`, for instance.

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

The occupied-qubit pattern itself is a formula under JW
(`_ansatz_builders.jw_hf_state`) — the first `Active_Electrons` qubits,
the same convention `UCCSD`'s own reference-state preparation uses — and
data under MolMap_sb, from `regenerate_spinblock_mol_map.py`'s own
computed `hf_state` (`MOL_MAP_SPINBLOCK_HF_STATE` in
[`campaign.py`](campaign.py)), since the reordering that produces it is
not a formula. `UCCSD` and
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
recomputations, from the `mapping_matrix` of Cebule's original MOL_MAP
output (`hamiltonian_data/*_mapped.json`, since retired) — no MOL_MAP
submission is made to produce `MolMap_sb`.

`regenerate_spinblock_mol_map.py` ran this for the campaign's two
mol_map cells and wrote `hamiltonian_data/{h2_6-31G,water_6-31G}_
MolMap_sb.json` and the matching `qasm/*_MolMap_sb_*.qasm` circuits,
verifying each against the cell's known Hartree-Fock energy before
writing anything. Its reordering step needs those retired source files
restored to run again; its `--h2o-tups` and `--h2-tups-layers` options
read the committed MolMap_sb files and remain re-runnable. One thing worth knowing if this is
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
| `Basis`, `Basis_Source` | `6-31g` throughout, from Basis Set Exchange [3] |
| `Active_Space` | `full` (H2) or `valence_cas` (H2O) |
| `Active_Electrons`, `Active_Orbitals` | The space the Hamiltonian is built in |
| `Mapper` | `JW` or `MolMap_sb` — see [Mappers](#mappers) |
| `N_Qubit`, `N_Qubit_Source` | Qubit count and its provenance: `jw_exact` or `MolMap_sb_computed` |
| `Method` | `VQE` (plain), `TN-VQE` (θ and φ jointly optimised) or `TN` (classical-only control: θ alone, no quantum measurements) |
| `Ansatz` | `RealAmplitudes`, `rzryrz`, `UCCSD` or `tUPS` |
| `Ansatz_Reps` | Repetitions (or, for tUPS, layers) of the ansatz circuit |
| `Entanglement` | Blank except on the entangler-topology axis's rows (`RealAmplitudes`/`rzryrz` only), where it names the non-default entanglement |
| `Backend_Platform` | `aer_simulator`, or `fake_berlin` on the noisy-simulator rows |
| `Optimizer`, `Opt_Options` | `COBYLA`, `SPSA` or `ExcitationSolve`. `Opt_Options` is the dictionary passed to `scipy.optimize.minimize` (or Cebule's own optimizer): `{}` except for SPSA on `RealAmplitudes`/`rzryrz`/`UCCSD`/`tUPS` (`target_step`, `c`) and every ExcitationSolve row, which names the circuit parameters' `frequencies` — one shared set where all are equal, otherwise one per optimized parameter with θ's left `null` for tn-vqe — and `check_flat: false`; see `opt_options_for` (`build_matrix.py`) |
| `Quantum_Eval_Budget` | Quantum evaluations the row is allowed, held equal across optimizers and covering the whole run, including SPSA's calibration and closing repeats and ExcitationSolve's first-sweep validation: `max(30, ceil(120 × n_params))`, enough for each run to reach its optimum rather than be cut off -- sized for SPSA on tUPS, the slowest case seen |
| `Quantum_Evals_Per_Iteration` | What one iteration of this row's optimizer spends of the budget: 1 for COBYLA, 2 for SPSA, and for ExcitationSolve one sweep: `1 + Σ 2|f|` over the φ parameters the energy depends on, `f` being each one's frequency set as `Opt_Options` names it — 0 wherever φ is frozen, since a θ-only change is served from cache |
| `Cost_Evals_Per_Iteration` | Entries one iteration adds to `cost_history`, the axis convergence curves are aligned on |
| `Iterations` | What `TNQCOptInput.n_iterations` receives |
| `Shots` | 50,000, pinned via `TNQCOptInput.n_shots`, so one evaluation's shot noise is about 1 mHa on H2; `n/a (network mode)` on `TN` rows, which take no quantum measurement. Rows on the hardware device default to `DEVICE_SHOTS`: 12,500 for RealAmplitudes, 50,000 for tUPS (see [Known limitations](#known-limitations)); a few `fake_berlin` rows set their own count to test this |
| `Qiskit_Version` | The installed Qiskit, which fixes the transpiler optimisation level the run receives |
| `TN_Layers_Network` | Layers of θ on the classical tensor-network side; blank on `VQE` rows, which ignore it entirely; 1, 2 or 3 on `TN-VQE`/`TN` rows |
| `TN_Ansatz` | `givens` on every TN-VQE row, or `n/a (not TN-VQE)` |
| `Measurement_Method` | `pauli` (JW rows) or `grouped` (MolMap_sb rows) |
| `Qasm_Ansatz_File`, `Qasm_Ansatz_SHA256` | The pinned circuit and a hash prefix of it |
| `Num_Opt_Params_Phi` | Circuit-side parameter count, the `num_parameters` the pinned QASM loads with. On a `TN` row it is the count held fixed |
| `Phi_Init` | `"zeros"` (`UCCSD`, tUPS), `"hf-approx"` (`RealAmplitudes`, `rzryrz`), or `"hf-approx+kick(scale=S,seed=N)"` on the start-point rows — see [HF-approximating initial parameters](#hf-approximating-initial-parameters); `"converged(case=N)"` on the warm-start rows 184–188 |
| `Num_Opt_Params_Theta` | Network-side parameter count on a TN-VQE row |
| `Num_ExpVals_Per_Iter`, `Num_ExpVals_Source` | Measurement circuits one evaluation submits, and where that count came from |
| `Error_Mitigation`, `Precision`, `QESEM_Execution_Mode` | `none`, `n/a (shot-based)`, `n/a (not QESEM)` on every row of `targeted_screen.csv` but cases 122–131, 137–146, 152–161, 182–196; those rows and `hardware_runs.csv` set `Error_Mitigation` to `readout_tensored`, which the runner passes as `readout_mitigation="tensored"` |
| `Converged_Params_File`, `Converged_Params_SHA256` | Blank but on the warm-start rows 184–188, which start from a collected run's final phi (and theta, on TN-VQE), frozen to `converged_params/case_N.json` by `build_matrix.py --freeze-params N`; the runner checks the hash and passes them as `phi_init` and `theta_init`. No row here is a stage-3 refinement |
| `Repeats_Case_ID` | `hardware_runs.csv` only: the `targeted_screen.csv` row the hardware run repeats |
| `Notes` | Per-row provenance and caveats |

## Hardware runs

`hardware_runs.csv` is the set of runs bought on `ibm_berlin`. Each is a
`fake_berlin` row of `targeted_screen.csv` copied unchanged except for
four columns: `Backend_Platform` (`ibm_berlin`), `Error_Mitigation`
(`readout_tensored`), `Shots` (the device count for the ansatz,
`DEVICE_SHOTS`) and `Repeats_Case_ID`, which names the row it repeats.
Circuit, start point, optimizer, sweep cap and budget are the twin's, so
a hardware result reads directly against its simulator twin;
`tests/test_docs_consistency.py` fails if anything else differs.

| Case | Repeats | Run | Question | Twin on `fake_berlin`: final state, best measured (mHa above FCI) | Estimated QPU time (4 ms / 1 ms rep_delay) |
|---|---|---|---|---|---|
| 1 | 92 | RealAmplitudes ×2, VQE, 12,500 shots | Baseline for the TN-VQE gain on a hardware-efficient circuit | 14.4, 63.3 (at 50,000 shots) | 24 / 6 h |
| 2 | 108 | RealAmplitudes ×2, TN-VQE (2 TN layers), 12,500 shots | Does that gain survive the device? | 3.3, 46.9 | 32 / 8 h |
| 3 | 96 | tUPS 1 layer, VQE, 50,000 shots | Baseline for the TN-VQE gain on a chemistry circuit | 13.5, 176.6 | 92 / 23 h |
| 4 | 97 | tUPS 1 layer, TN-VQE (2 TN layers), 50,000 shots | Can the network stand in for a tUPS layer on the device? | 8.7, 163.9 | 165 / 42 h |
| 5 | 98 | tUPS 2 layers, VQE, 50,000 shots | The depth the network stands in for | 1.8, 261.7 | 257 / 65 h |

All five use `ExcitationSolve` capped at 6 sweeps, on H2/6-31g under
`MolMap_sb` with `grouped` measurement. The final-state column is the
twin's final parameters evaluated by noiseless statevector; the measured
column is the lowest noisy evaluation the twin saw, which carries the
device-noise offset (about 40 mHa plus 1.9 mHa per two-qubit gate).
On the twins, the network beats a missing tUPS layer in the measured
energy (case 97 reads 98 mHa below case 98, whose circuit has twice the
two-qubit gates) but not in the final state (8.7 against 1.8 mHa).

**Readout correction.** Every row sets tn-vqe's tensored readout
correction (`readout_mitigation="tensored"`, cebule-tn_vqe `ef0dc47`):
two calibration circuits per run measure each qubit's flip rates, which
are inverted out of every measured distribution. On `fake_berlin` it
removes 29–33 mHa of the offset, and readout error is most of what
moves the noisy minimum (see
[Known limitations](#known-limitations)). The twins named in
`Repeats_Case_ID` ran uncorrected, so a hardware-against-twin difference
mixes the device with the correction; cases 128, 122, 129, 130 and 131
are the same five runs on `fake_berlin` with the correction and device
shots, which separate the two. Cebule must be running that tn-vqe revision or later, so
check the deployed version before submitting: an older one does not
apply the correction.

**Cost.** About 569 h of QPU time in all, priced by
`utils/estimate_ibm_cost.py` from each twin's recorded jobs and circuits
per job (see [ibm_cost_estimator.md](../../docs/integrations/ibm_cost_estimator.md)).
`ibm_berlin` is a Nighthawk device, and its calibration snapshot sets a
4 ms default rep_delay (range 1–4 ms) against Heron's 250 µs; nearly all
of a shot's time is that delay, not the 3–17 µs circuit. At the 1 ms
minimum the five runs take about 144 h, but tn-vqe's `grouped` path
cannot set rep_delay yet, so as things stand they run at the default.
The live value is unconfirmed: the IBM account saved locally cannot see
`ibm_berlin`.

```sh
PYTHONPATH=src python utils/estimate_ibm_cost.py --csv campaigns/ibm_tn-vqe_qesem/hardware_runs.csv
```

**On `ibm_aachen` instead.** `ibm_aachen` is a Heron r3 at a 250 µs
rep_delay, so the same five runs take about 37.8 h there. Cases 123–127
of `targeted_screen.csv` are its simulator twins: the five rows above,
readout correction and device shots included, on `fake_aachen`. Its
tUPS circuits transpile to 84 and 166 two-qubit gates, against 62 and
118 on Berlin, so its noise offset is expected to be larger.

**At half the shots.** Cases 132–146 run the five hardware runs at half
the device shots (6,250 for RealAmplitudes, 25,000 for tUPS) on
`aer_simulator` (132–136), `fake_berlin` (137–141) and `fake_aachen`
(142–146), each with the same 6-sweep cap; the two noisy simulators
apply the readout correction, and `aer_simulator`, which has no readout
error, runs uncorrected. Halving the shots roughly halves each run's QPU
time. Earlier, uncorrected, 1-layer tUPS TN-VQE lost its gain over VQE
at 25,000 shots (case 105); these show whether that holds with the
correction, and on the other four runs.

**At 18 sweeps.** Cases 147–161 run the five hardware runs at the
device shots but 18 sweeps instead of 6, on `aer_simulator` (147–151),
`fake_berlin` (152–156) and `fake_aachen` (157–161), corrected as
above. On the uncorrected `fake_berlin` twins, 1-layer tUPS TN-VQE was
still descending at 6 sweeps (8.7 mHa, against 5.9 mHa at 18); these
show whether any hardware run needs more than the cap.

**Cutting sweeps.** `price_plans.py` takes the sweep at which each run's
longest readout-corrected `fake_aachen` mirror converged (the first
within 0.5 mHa of its plateau) and prices three reduced plans on
`ibm_aachen` from the mirrors' recorded calls:

| Plan | QPU time on `ibm_aachen` |
|---|---|
| As defined | 37.4 h |
| B: each run stopped where its mirror converged | 32.3 h (16.8 h with tUPS at 25,000 shots) |
| C: VQE runs as 10 evaluations at the noiseless optimum, TN-VQE runs warm-started | 5.4 h |
| D: every run warm-started | 9.5 h, assuming one sweep per VQE run |

B barely helps on Aachen: 1-layer tUPS TN-VQE needs 10 sweeps there
(case 160), sitting at the VQE value for the first five, and 2-layer
tUPS VQE needs 4. Warm-started, the TN-VQE runs settle in one and two
sweeps (cases 184 and 185): RealAmplitudes at about 1.0 mHa, where the
cold runs end, and 1-layer tUPS at about 3.6 mHa, below the cold run's
5.3 mHa after 18 sweeps. A warm-started TN-VQE job measures all 16
circuits, against 11–14 from a cold start, since U†HU at a converged
theta has more terms. C leaves only TN-VQE free to adapt to the
device's noise; D gives VQE the same start and the same chance, and its
VQE sweep counts come from cases 186–188 once they are collected.

```sh
PYTHONPATH=src python campaigns/ibm_tn-vqe_qesem/price_plans.py [--tups-shots 25000]
```

The rows are ordered cheapest first, so the RealAmplitudes pair runs before any tUPS row and serves as the pilot. QESEM is not part of
this matrix; it goes through the stage-3 path once a hardware run has
converged parameters to refine.

**Running.** The matrix is generated, and submitted, with

```sh
PYTHONPATH=src python campaigns/ibm_tn-vqe_qesem/build_matrix.py --stage hardware
PYTHONPATH=src python utils/run_campaign.py --csv campaigns/ibm_tn-vqe_qesem/hardware_runs.csv --allow-hardware --submit
```

Results collect in `results/hardware_runs.ndjson`. The runner refuses an
`ibm*` backend without `--allow-hardware`, even for a dry run.

## Known limitations

- **`MolMap_sb` covers two chemistry cells.** H2/6-31g and
  H2O/6-31g's CAS(4,4) are what this campaign needs; extending it to
  another cell means running `regenerate_spinblock_mol_map.py` against
  that cell's own committed `mapping_matrix`, correcting for the
  row-bit-reversal noted under [Mappers](#mappers).
- **The entangler-topology axis covers three of Qiskit's five
  topologies.** `reverse_linear`, `sca` and `full` are run on both
  families; `linear` and `circular` are not.
- **tUPS/pp-tUPS has no entangler-topology axis.** Its circuit has no
  entanglement pattern to vary.
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
- **`ExcitationSolve`'s frequency sets are measured at the start.**
  Each row names its circuit parameters' sets, measured on a noiseless
  statevector at the row's own start and at a second point offset from it
  (`utils/_excitationsolve_frequencies.py`), and checked by refitting. A
  parameter flat at both points gets the empty set and is never
  optimized, even on a TN-VQE row, where the network changes the
  Hamiltonian the circuit sees. Rows collected before the sets were named
  had tn-vqe measure them itself, which on 2- and 3-layer tUPS misses
  frequency 4 on 2 and 4 parameters respectively (it vanishes at the zero
  start); those runs converged regardless, and their sweeps were 4 and 8
  evaluations shorter than the sets now named. UCCSD case 29 ran with
  `{1, 2}` on every parameter.
  `SPSA`'s `target_step`/`c` tuning, by contrast, is no longer
  UCCSD-only — `SPSA_TUNED_ANSATZE` covers `RealAmplitudes`,
  `rzryrz` and `tUPS` too. The values were tuned on UCCSD and work
  unchanged on tUPS (within 0.05–1.5 mHa of FCI, VQE and TN-VQE alike);
  they have not been re-tuned per family.
- **Plain VQE cannot move RealAmplitudes or rzryrz off `hf-approx`.**
  Under JW that point is a zero-gradient local minimum of the ansatz
  (under MolMap_sb, RealAmplitudes reaches a nearby one 14.4 mHa above
  FCI), so every optimizer stops there, whatever its settings; a
  `vqe_energy` below HF on these rows is the lowest of many noisy
  evaluations, not real progress. TN-VQE does move it: the network
  changes the Hamiltonian the circuit sees, and RealAmplitudes/MolMap_sb
  gets to 0.7 mHa (`ExcitationSolve`, 2 TN layers) and 6 mHa (`SPSA`,
  3 TN layers), though not at every layer count. A large kicked
  start is not a substitute (see the start-point axis).
- **H2O/6-31g CAS(4,4) carries little correlation.** HF is only 1.1 mHa
  above FCI in that space, about the size of the differences between
  runs (0.5–1.5 mHa; the RealAmplitudes rows end above HF), so the H2O
  rows cannot separate one method or ansatz from another.
- **COBYLA stops early under shot noise.** It shrinks its trust region
  whenever a step does not lower the energy as its linear model
  predicted, and stops when the radius reaches `tol` (`conv_tol`, 1e-6).
  Once a step changes the true energy by less than one evaluation's
  noise (about 1 mHa at 50,000 shots, reached near a radius of 1e-2),
  every step looks like a failed prediction, so the radius collapses to
  `tol` within a few hundred evaluations, typically 10–25 mHa above FCI
  on H2 and using about a tenth of the budget. Without noise the same
  rows reach FCI. A smaller starting radius or a different `tol` does
  not change this (a `tol` of 1e-2 gives the same energy for about half
  the evaluations). The COBYLA rows therefore measure COBYLA under shot
  noise and cannot separate the method, mapper or depth axes; read
  those from the `SPSA` and `ExcitationSolve` rows.
- **Device noise moves the minimum, not only the energy.** On
  `fake_berlin`, 1-layer tUPS TN-VQE ends 6–8 mHa above its noiseless
  0.34 mHa however the shots are spent (18 sweeps, 18 points per fit, or
  200,000 shots: cases 101, 103, 104). Measured on the device, those runs'
  parameters read about 4 mHa lower than the noiseless optimum's, so the
  optimizer found the noisy energy's minimum correctly; with a readout
  correction applied the noiseless optimum reads lowest again, so readout
  error is most of the shift. Until tn-vqe corrects readout, more shots do
  not help this row; fewer do hurt: at 25,000 and 12,500 shots it ends at
  1-layer VQE's 13.5 mHa, the network's gain gone (cases 105, 106).
  RealAmplitudes TN-VQE keeps its gain at 12,500 shots (3.3–3.7 mHa at
  12,500–50,000: cases 93, 107, 108). Hence `DEVICE_SHOTS`.
- **`vqe_energy` is biased low; compare statevector energies instead.** It is
  the lowest noisy evaluation a run saw, so it sits a few shot-noise
  widths below the energy of any state the run reached. Result records
  therefore also carry the final `phi`, `theta` and transformed
  Hamiltonian (`h_tn_opt_qubit`), and `plot_results.ipynb` re-evaluates
  the final state by noiseless statevector simulation
  (`utils/_statevector_energy.py`), as `final_state_energy`. Records
  collected before this was stored fall back to `vqe_energy`.

## Open decisions

1. **A QPU budget.** The five runs come to about 569 h at the device's
   default rep_delay, against a 12 h target.

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
