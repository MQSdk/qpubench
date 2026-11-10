# TN-VQE vs VQE: a targeted simulator study, repeated on hardware

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
   encoding, reindexed for circuit efficiency (`MolMap_sb`).
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

The campaign runs in two parts:

- **Simulator runs** (`targeted_screen.csv`, 200 rows): mostly on
  `aer_simulator` (shot noise only), with copies on `fake_berlin` and
  `fake_aachen`, the offline noise snapshots closest to the devices.
  The design, the matrix and its columns:
  [docs/simulator_runs.md](docs/simulator_runs.md).
- **Hardware runs** (`hardware_runs.csv`): five of the `fake_berlin`
  rows (cases 202–206) repeated on `ibm_phoenix`, a Nighthawk r2. Twins,
  cost, recovery of interrupted runs and device-noise analysis:
  [docs/hardware_runs.md](docs/hardware_runs.md).

## Campaign structure

Everything this campaign decides lives in this folder; the reusable
machinery it runs on is the shared toolkit in [`utils/`](../../utils/).

| File | What it is |
|---|---|
| [`build_matrix.py`](build_matrix.py) | Generates `targeted_screen.csv` and `hardware_runs.csv`: the molecules, axes, shots, optimizer settings and budget multiplier are all set here |
| [`campaign.py`](campaign.py) | What the shared tools need to know: file locations, Hamiltonian file names, Hartree-Fock states under MolMap_sb, the device to price against |
| [`regenerate_spinblock_mol_map.py`](regenerate_spinblock_mol_map.py) | Builds the MolMap_sb Hamiltonians and the UCCSD/tUPS circuits from them |
| [`price_plans.py`](price_plans.py) | Prices reduced hardware plans from the simulator mirrors' recorded calls |
| `excitationsolve_frequencies.json` | ExcitationSolve's frequency set for each circuit parameter, per circuit, Hamiltonian and start; written by `build_matrix.py` the first time a circuit needs it |
| `targeted_screen.csv` | The simulator matrix |
| `hardware_runs.csv` | The `ibm_phoenix` runs, each a `fake_berlin` row of `targeted_screen.csv` repeated on the device |
| `hamiltonian_data/`, `qasm/`, `converged_params/` | The Hamiltonians the runs optimise, the circuits they run, and the parameters warm-started and resumed runs start from |
| `results/` | Collected runs (gitignored) |
| `run_campaign_batch.ipynb`, `plot_results.ipynb` | Running the campaign interactively, and plotting its results |
| [`docs/`](docs/) | The simulator and hardware runs in detail |

```sh
PYTHONPATH=src python campaigns/ibm_tn-vqe_qesem/build_matrix.py --stage targeted
PYTHONPATH=src python utils/run_campaign.py --campaign ibm_tn-vqe_qesem --submit
PYTHONPATH=src python utils/run_campaign.py --campaign ibm_tn-vqe_qesem --collect
```

## Simulator results

All energies are of the final state, evaluated by noiseless statevector,
in mHa above FCI on H2/6-31g unless stated.
[docs/simulator_runs.md](docs/simulator_runs.md#known-limitations) has
the evidence behind each.

- **TN-VQE moves circuits plain VQE cannot.** `hf-approx` is a local
  minimum of `RealAmplitudes` and `rzryrz`, so plain VQE stays there
  under every optimizer (14.4 mHa for RealAmplitudes under MolMap_sb).
  The network changes the Hamiltonian the circuit sees, and TN-VQE takes
  the same circuit to 0.7 mHa (`ExcitationSolve`, 2 TN layers).
- **The network partly stands in for a tUPS layer.** 1-layer tUPS VQE
  stops at 13.5 mHa; with a 2-layer network it reaches 4.4 on
  `fake_berlin` (case 205), against 1.1 for 2-layer tUPS VQE (case 206),
  which has twice the two-qubit gates.
- **COBYLA stalls under shot noise**, typically 10–25 mHa above FCI for
  about a tenth of the budget, so the method, mapper and depth axes are
  read from the `SPSA` and `ExcitationSolve` rows.
- **Device noise moves the minimum, not only the energy.** On
  `fake_berlin`, readout error is most of that shift, and tensored
  readout correction removes 29–33 mHa of the offset. Hence the device
  shots (`DEVICE_SHOTS`) and readout correction on every hardware run.
- **H2O/6-31g CAS(4,4) cannot separate methods**: HF is only 1.1 mHa
  above FCI in that space.

## Hardware results

Each hardware run repeats a `fake_berlin` twin unchanged but for the
device, so a difference between them is the device's. All use
`ExcitationSolve` capped at 12 sweeps on H2/6-31g under `MolMap_sb`,
with tensored readout correction and batched jobs.

| Case | Repeats | Run | Question | Twin: final state, best measured (mHa above FCI) | Device: final state, best measured | Jobs | QPU time per job | QPU time on `ibm_phoenix` |
|---|---|---|---|---|---|---|---|---|
| 1 | 202 | RealAmplitudes ×2, VQE, 12,500 shots | Baseline for the TN-VQE gain on a hardware-efficient circuit | 14.6, 22.2 | 15.0, 20.8 | 158 | 5.9 s | 15.5 min (billed) |
| 2 | 203 | RealAmplitudes ×2, TN-VQE (2 TN layers), 12,500 shots | Does that gain survive the device? | 1.2, 6.1 | 3.4, −0.9 (with case 6, 8 of 12 sweeps) | 158 | 7.2 s | 19 min |
| 3 | 204 | tUPS 1 layer, VQE, 50,000 shots | Baseline for the TN-VQE gain on a chemistry circuit | 13.5, 120.1 | 21.7, 139.5 | 86 | 18.6 s | 27 min |
| 4 | 205 | tUPS 1 layer, TN-VQE (2 TN layers), 50,000 shots | Can the network stand in for a tUPS layer on the device? | 4.4, 112.2 | 13.7, 122.8 | 86 | 31.4 s | 45 min |
| 5 | 206 | tUPS 2 layers, VQE, 50,000 shots | The depth the network stands in for | 1.1, 235.1 | | 194 | 22.1 s | 71 min |
| 6 | 207 | Case 2 resumed from its first attempt's sweep 2, 10 sweeps | Finishes case 2 without repeating its first two sweeps | 1.7, 6.1 | 3.4, −0.9 (halted after 6 of 10 sweeps; replayed) | 132 | 7.4 s | 16 min |
| 7 | 208 | Case 5 cut to 3 sweeps, pinned to qubits `[70, 80, 71, 81]` | Does a region chosen from the calibration give the damping it predicts? | | | about 50 | | about 20 min (a quarter of case 5) |

The final-state columns are the final parameters evaluated by noiseless
statevector; the measured columns are the lowest noisy evaluation the
run saw. Jobs and QPU time are the twin's until a run is collected.

- **RealAmplitudes VQE (case 1) matches its twin.** Both stay at the
  `hf-approx` local minimum.
- **RealAmplitudes TN-VQE (cases 2 and 6) keeps most of the network's
  gain**, 3.4 mHa against VQE's 15.0, but stalls there while its twin
  descends to 1.0–1.6. Its measured energies follow shot noise of a few
  mHa. Two interruptions, neither from the run itself, were recovered by
  replaying IBM's job files offline.
- **The tUPS runs stall on the device.** VQE (case 3) ends at 21.7
  against its twin's 13.5, and TN-VQE (case 4) at 13.7 against 4.4, so
  the network's gain over VQE survives (8 mHa) but at a higher level.
  The deeper circuits carry 2–3× shot noise of gate error that readout
  correction cannot remove, and it moves the minimum. Case 3 also lost a
  qubit region partway through, which pinning runs to physical qubits
  (`Initial_Layout`) now guards against.
- **2-layer tUPS (case 5, running) keeps 0.29 of its signal** on the
  qubits the transpiler chose, against 0.47 their calibration predicts.
  Case 7 runs the same circuit for 3 sweeps on a region chosen from the
  calibration, to see whether such a choice can be trusted
  ([Layout probe](docs/hardware_runs.md#layout-probe)).
- **Cost.** About 3 h of QPU time for all six, but wall-clock time runs
  to days, since every job queues on its own.

## Open decisions

1. **Physical qubits for the remaining runs.** `HARDWARE_INITIAL_LAYOUTS`
   is empty, so the transpiler still chooses the qubits per evaluation.
   Pinning a run to one healthy region would have kept case 3 off the
   region that failed mid-run; which region to pin is open.

The QPU budget is settled: the hardware runs come to about 3 h on
`ibm_phoenix`, well inside the 12 h target. The earlier 569 h was the
same runs on `ibm_berlin` at its 4 ms default rep_delay.

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
