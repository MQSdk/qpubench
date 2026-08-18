# Examples: guides, demos, and tutorials

Runnable, educative examples of what you can do with qpubench, in three tiers:

- **`guides/`** — focused how-tos, one concept each: build a problem, pick a backend, pick an optimizer, persist results, estimate hardware cost.
- **`demos/`** — self-contained showcases that combine several concepts into one narrative, from a first quantum-chemistry calculation to a reaction-path energy study.
- **`tutorials/`** — multi-step scientific workflows on real molecules: bond dissociation, an enzymatic SN2 reaction, covalent ligand binding, ionization potentials, and periodic DFT for carbon capture.

Three standalone scripts at this level predate the tiers and remain good starting points: `gate_based_example.py` (circuit → runner → store round trip on the stub backend), `mbqc_example.py` (an MBQC measurement pattern, FPGA COE file generation, stub execution), and `qforte_vqe_benchmark.py` (three QForte VQE methods on He/cc-pVDZ via the `AlgorithmAdapter` protocol; needs `pip install qforte`).

The molecule for that last one, `He-ccpvdz.json`, lives in QForte's `tests/` directory, which its `setup.py` does not install — so it is only on disk if you installed QForte from a checkout you still have. The example searches the likely places and, failing that, either builds the same system with Psi4 or prints how to fetch the file; you can always point it straight at the file with `export HE_JSON_PATH=/path/to/qforte/tests/He-ccpvdz.json`.

## Two things every example is honest about

**Which Hamiltonians are real.** Some examples use the small illustrative qubit Hamiltonians in `common/toy_hamiltonians.py` — explicitly educational, never presented as physically accurate. Examples that need genuine numbers build or load real ones: via PySCF (`pip install 'qpubench[pyscf]'`), via `qpubench.hamiltonian_sources` (HamLib Chemistry, PennyLane qchem datasets, or ab initio construction from any geometry — see "Real Hamiltonian sources" below), or via QForte. Each script says which kind it uses.

**Which backends are real.** `StubGateAdapter` returns *random* expectation values — ideal for exercising the runner/store control flow, useless as an energy oracle for an optimizer (it would chase noise). Examples that need real convergence use `common/toy_statevector_backend.py`'s `ToyStatevectorAdapter` — a genuine (if minimal, dense-matrix) statevector simulator. `AerAdapter` and `BraketAdapter` (via `BraketLocalBackend`) are real implementations that run with no credentials; `IBMAdapter`/`IQMAdapter` are real but need a live account, so examples touching them show the real construction/run pattern with a runnable stand-in and the swap-in point marked in a comment (see `../docs/backends.md`). `QrackAdapter` remains a documented stub.

## `common/`

| File | Purpose |
|---|---|
| `toy_hamiltonians.py` | Illustrative qubit Hamiltonians (`toy_hamiltonian`, `toy_bond_hamiltonian(r)`, `occupied_virtual_hamiltonian`) + `exact_ground_state_energy()` (real dense diagonalization — a genuine ground truth, not a fabricated number) |
| `toy_statevector_backend.py` | `ToyStatevectorAdapter` — real statevector simulator for the fixed gate vocabulary `integrations/generic_adapt_vqe` emits |
| `real_molecules.py` | Real geometries and active-space choices behind the tutorials (n-butyronitrile, CH3Cl + HCOO⁻, CH3CN + CH3SH, NH3, CO2 + NH3), with the reasoning for each modeling choice |

Requires `pip install 'qpubench[adapt_vqe]'` (scipy + numpy) for anything that runs ADAPT-VQE or exact diagonalization.

## Guides (`guides/`) — one concept per script

**Define the problem:**

| Problem | File |
|---|---|
| Construct a ground-state energy problem and solve it with ADAPT-VQE | `ground_state_energy_problem.py` |
| Select an active space with real PySCF AVAS | `active_space_spec.py` |
| Compute classical reference energies (HF / MP2 / CCSD / FCI) to score quantum results against | `classical_reference_energies.py` |
| Load or build a real molecular Hamiltonian (HamLib, PennyLane qchem, ab initio) | `hamiltonian_library.py` |
| Add a solvent environment (real PySCF PCM-solvated HF) | `create_solvent_model.py` |
| Choose an electron-repulsion-integral builder (standard 4-center vs RI/DF) | `choose_integrals.py` |

**Configure the algorithm:**

| Problem | File |
|---|---|
| Assemble a VQE calculator (ansatz growth + energy oracle + optimizer) | `vqe_calculator.py` |
| Run QAOA for MaxCut (fixed cost/mixer ansatz, `QAOARunConfig`, exact statevector) | `qaoa_maxcut.py` |
| Choose a classical minimizer and stopping criterion from the catalogue | `minimizer_and_stopping_criterion.py` |
| Control how ADAPT-VQE picks its next operator (gradient screening) | `adapt_gate_selector.py` |
| Trade selection cost vs. quality: gradient-screen vs. brute-force gate selectors | `gate_selector.py` |
| Optimize orbitals (real PySCF Newton/CASSCF, kappa-rotation, basin-hopping) | `orbital_optimizer.py` |
| Choose a tensor-network contraction path (real quimb + cotengra) | `choose_contraction_path_finder.py` |

**Run it:**

| Problem | File |
|---|---|
| Choose a backend from the support matrix | `choose_backend.py` |
| Use estimator (expectation values) vs. sampler (shot counts) execution paths | `estimator_and_sampler.py` |
| Add realistic noise to a simulation (real noisy AerAdapter execution) | `noisy_simulator.py` |
| Run on real quantum computers (IBM / IQM construction + run pattern; needs credentials) | `quantum_computers.py` |
| Estimate what a benchmark costs on IBM hardware *before* submitting | `estimate_ibm_cost.py` |
| Split a large benchmark into batches sized to IBM access-plan budgets | `split_benchmark_batches.py` |
| Count how many circuits one cost-function evaluation really submits | `count_measurement_bases.py` |

**Keep the results:**

| Problem | File |
|---|---|
| Choose and configure a result store (NDJSON / Parquet / S3) | `data_persister_manager.py` |
| Structured logging of every record with `BenchmarkLogger` | `logging_hook.py` |

## Demos (`demos/`) — several concepts, one narrative

| What it shows | File |
|---|---|
| Your first quantum-chemistry calculation: build a problem, build a calculator, solve, check the answer | `getting_started_first_calculation.py` |
| An ADAPT-VQE convergence study: energy vs. iteration across configurations | `adapt_vqe_convergence_study.py` |
| Taking ADAPT-VQE from simulator to quantum hardware (real hardware path needs credentials) | `adapt_vqe_on_quantum_computer.py` |
| A reaction-path potential-energy-surface study tied together with `ReactionPathResult` | `reaction_path_pes_sweep.py` |
| Polarizable embedding ("The Frame"): real CPPE + PySCF `pyscf.solvent.PE` | `polarizable_embedding_frame.py` |
| Projection-based wavefunction-in-DFT embedding + DMET (real PsiEmbed/libDMET APIs behind an `ImportError` guard — both are git-only installs) | `dmet_embedding_demo.py` |

## Tutorials (`tutorials/`) — multi-step scientific workflows

Each tutorial is a small research story on a real molecule: it builds a real qubit Hamiltonian ab initio (PySCF HF + active-space reduction + Jordan-Wigner — see `common/real_molecules.py`), runs the quantum algorithm, and interprets the result. Where the full active space is too large for the bundled dense-matrix engine, the script builds the full-size Hamiltonian once as a capability check and runs a reduced-active-space scan — the same molecule and the same chemistry, sized to run on your laptop; a real simulator backend (e.g. Aer) lifts that limit.

| Scientific question | File |
|---|---|
| How does the energy change as the C≡N bond of n-butyronitrile stretches to breaking? | `bond_dissociation_curve.py` |
| What is the barrier of a carboxylate-mediated SN2 reaction (the haloalkane-dehalogenase mechanism, modeled as CH3Cl + HCOO⁻)? | `reaction_path_sn2.py` |
| How strongly does a nitrile warhead bind a cysteine thiol (covalent ligand binding at cathepsin K, modeled as CH3CN + CH3SH)? | `bound_vs_unbound_comparison.py` |
| What is the ionization potential of H2, computed as a neutral/cation energy difference (~16.2 eV vs. literature 15.4–16.0 eV)? | `ionization_potential.py` |
| What does a periodic-DFT + binding-site treatment of CO2 capture in a covalent organic framework look like? | `carbon_capture_periodic_dft.py` |

## Real Hamiltonian sources

`qpubench.hamiltonian_sources` loads or computes real molecular Hamiltonians as a `SparsePauliObservable`, ready to drop into any `AlgorithmAdapter`/`BackendAdapter` estimator path with zero changes to that machinery:

- **HamLib Chemistry** ([portal.nersc.gov/cfs/m888/dcamps/hamlib/chemistry/](https://portal.nersc.gov/cfs/m888/dcamps/hamlib/chemistry/)) — `hamiltonian_sources/hamlib.py`, `load_hamlib_chemistry()`. Downloads and caches HamLib's real HDF5 files and parses their OpenFermion-text format (verified field-by-field against a real downloaded H2 file) — no `openfermion` dependency needed.
- **PennyLane qchem datasets** ([pennylane.ai/datasets/collection/qchem](https://pennylane.ai/datasets/collection/qchem)) — `hamiltonian_sources/pennylane_qchem.py`, `load_pennylane_qchem()`. Wraps `qml.data.load()` and converts the `LinearCombination` output.
- **Ab initio construction** — `hamiltonian_sources/ab_initio.py`, `build_qubit_hamiltonian()`. Real PySCF HF (via `openfermionpyscf`) + optional frozen-core active-space reduction + Jordan-Wigner (via `openfermion`), for *any* geometry — not just what a library happens to ship.

All three are verified against independent ground truth: the parsed H2 Hamiltonian's exact ground-state energy matches PennyLane's own `fci_energy` to `1e-11`; running HamLib's H2 Hamiltonian through `GenericAdaptVQEEngine` matches dense diagonalization to `7e-15`; and `build_qubit_hamiltonian` reproduces the same H2 result from raw geometry. See `guides/hamiltonian_library.py`, `tests/test_hamiltonian_sources.py`, `tests/test_ab_initio.py`, and `docs/schemas.md#hamiltonian_library`.

**None of this data ships with the repo** — it's pulled on demand the first time you call a loader: HamLib caches to `~/.cache/qpubench/hamiltonian_sources/hamlib/` (override with `cache_dir=`); PennyLane qchem downloads into a local `datasets/` folder (override with `folder_path=`, forwarded through `load_pennylane_qchem()`'s `**params`). Both paths are `.gitignore`d. Ab initio construction needs no download at all.
