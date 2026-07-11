# Examples: qrunch guides, demos, and tutorials on qpubench — without qrunch

This directory reproduces Kvantify's qrunch [how-to guides](https://qrunch.docs.kvantify.net/docs/guides/guides.html),
[demo examples](https://qrunch.docs.kvantify.net/docs/demo_examples/demo_examples.html),
and [tutorial notebooks](https://github.com/Kvantify/qrunch_tutorials) using
only qpubench's own schemas and adapters — no qrunch install anywhere.
**FAST-VQE and BEAST-VQE are permanently substituted with ADAPT-VQE
everywhere** (qrunch's own algorithms are proprietary and out of scope for
parity — ADAPT-VQE is the adaptive-ansatz alternative qpubench ships via
`integrations/generic_adapt_vqe/`).

## Two things every example is honest about

**No real electronic structure inside qpubench itself.** Most "molecules"
below are one of the small qubit Hamiltonians in
`common/toy_hamiltonians.py` — explicitly illustrative, never presented as
physically accurate. The exceptions call real chemistry packages —
`create_solvent_model.py`, `classical_reference_energies.py`,
`active_space_spec.py` (PySCF, `pip install 'qpubench[pyscf]'`),
`polarizable_embedding_frame.py` (PySCF + CPPE),
`carbon_capture_periodic_dft.py` (PySCF `pbc`) — for genuine numbers on
real molecules; qpubench's own schema layer still does none of the
computing. `../qforte_vqe_benchmark.py` is the ADAPT-VQE equivalent
(He/cc-pVDZ via QForte, `pip install qforte`).

**No random numbers standing in for physics.** `StubGateAdapter` returns
*random* expectation values — fine for exercising the runner/store control
flow, useless as an ADAPT-VQE energy oracle (the optimizer would chase
noise). Examples that need real convergence use `common/
toy_statevector_backend.py`'s `ToyStatevectorAdapter` — a genuine (if
minimal, dense-matrix) statevector simulator, not a stub. **Revised
2026-07-08**: `AerAdapter` / `IBMAdapter` / `IQMAdapter` / `BraketAdapter`
are now real implementations, not stubs (see `../../docs/backends.md`) —
`AerAdapter` and `BraketAdapter` (via `BraketLocalBackend`) run for real
with no credentials needed; `IBMAdapter`/`IQMAdapter` need a live account,
so examples touching those show the real construction/run pattern with the
actual (auth, not `NotImplementedError`) failure mode, falling back to a
runnable stand-in with the swap-in point marked clearly in a comment.
`QrackAdapter` remains a documented stub.

## `common/`

| File | Purpose |
|---|---|
| `toy_hamiltonians.py` | Illustrative qubit Hamiltonians (`toy_hamiltonian`, `toy_bond_hamiltonian(r)`, `occupied_virtual_hamiltonian`) + `exact_ground_state_energy()` (real dense diagonalization — a genuine ground truth, not a fabricated number) |
| `toy_statevector_backend.py` | `ToyStatevectorAdapter` — real statevector simulator for the fixed gate vocabulary `integrations/generic_adapt_vqe` emits |

Requires `pip install 'qpubench[adapt_vqe]'` (scipy + numpy) for anything
that runs ADAPT-VQE or exact diagonalization.

## Guides (`guides/`)

| qrunch guide | Verdict | File |
|---|---|---|
| Construct a Ground State Energy Problem | Yes | `ground_state_energy_problem.py` |
| Define an Active Space | **Yes** | `active_space_spec.py` — real PySCF AVAS selection |
| Build a VQE Calculator | Yes (ADAPT-VQE) | `vqe_calculator.py` |
| Calculate Classical Reference Energies (CI, CC) | **Yes** | `classical_reference_energies.py` — real PySCF HF/MP2/CCSD/FCI |
| Using a Noisy Simulator | **Yes** | `noisy_simulator.py` — real noisy AerAdapter execution |
| Using Quantum Computers | Yes (construction + real run, needs credentials) | `quantum_computers.py` |
| Choose a Backend | Yes | `choose_backend.py` |
| Choose a Minimizer / Choose a Stopping Criterion | **Yes** | `minimizer_and_stopping_criterion.py` — real catalogue objects |
| Create an ADAPT Gate Selector | Yes | `adapt_gate_selector.py` |
| Create an Estimator / Create a Sampler | Yes | `estimator_and_sampler.py` |
| Choose a Data Persister Manager | Yes | `data_persister_manager.py` |
| Using the Logger | **Yes** | `logging_hook.py` — real `BenchmarkLogger` (levels/handlers/formatters) |
| Run basic QI use cases | Yes | already covered — see `../gate_based_example.py`, not duplicated here |
| Create a ReactionConfiguration | Yes | `schemas/reactions.py`'s `ReactionCoordinateSpec` — see `../demos/reaction_path_pes_sweep.py` |
| Construct a Reaction-Path Problem | Yes | same mechanism, same demo |
| Calculate Reaction Path Energies | Yes | `ReactionPathResult.reaction_energy` / `.barrier_height`, same demo |
| Create a Solvent Model | **Yes** | `create_solvent_model.py` — real PySCF PCM-solvated HF |
| Choose a Contraction Path Finder | **Yes** | `choose_contraction_path_finder.py` — real quimb + cotengra |
| Choose Electron-Repulsion Integral Builder | **Yes** | `choose_integrals.py` — real PySCF standard 4-center vs RI/DF |
| Create a FAST Gate Selector | **Yes** | `gate_selector.py` — `FastGateSelector`, real gradient screen |
| Create a Brute Force Gate Selector | **Yes** | `gate_selector.py` — `BruteForceGateSelector`, real full re-optimization per candidate |
| Create an Orbital Optimizer | **Yes** | `orbital_optimizer.py` — real PySCF Newton (CASSCF) / Simple (kappa-rotation) / Basin-Hopping |

**Revised 2026-07-09**, fourth pass: closed the last 4 "no qpubench
mechanism" guide gaps — Choose a Contraction Path Finder (real `quimb` +
`cotengra`, per direct instruction to build this specifically on those two
libraries rather than bare `opt_einsum`), Choose Electron-Repulsion
Integral Builder and Create an Orbital Optimizer (both real PySCF, no new
dependency), Create a Brute Force / FAST Gate Selector (refactored
`integrations/generic_adapt_vqe`'s gradient screen into a swappable
`GateSelector` strategy, added a new exact-but-expensive
`BruteForceGateSelector`). See `docs/schemas.md`'s `contraction_path`
section and `pyscf.py`'s ERI-builder/orbital-optimizer rows,
`tests/test_contraction_path.py`, `tests/test_gate_selector.py`.

**Revised 2026-07-08, three passes.** First two passes (schema v2.1.0 →
2.3.0): checked docs.mqs.dk / Cebule SDK source / PySCF quickstart /
PennyLane's DMET-embedding demo, confirmed InQuanto isn't required for
embedding/periodic chemistry, added real PySCF examples. **Third pass
(schema v2.3.0 → 2.4.0)**, per direct request to close the remaining
backend-adapter, embedding, and partial-guide gaps:

- **Backend adapters are real now.** `AerAdapter`/`IBMAdapter`/
  `IQMAdapter`/`BraketAdapter` went from `raise NotImplementedError` to
  working implementations, verified in this sandbox: Aer and Braket
  (via `qiskit-braket-provider`'s `BraketLocalBackend`) fully executed, no
  credentials needed; IBM and IQM transpile/run logic fully executed
  against bundled fake backends (`FakeManilaV2`, `IQMFakeAdonis`), only the
  credential-fetching call left untestable without a real account. Found
  and fixed two real, current bugs in the process: `qiskit-iqm`/
  `qiskit_on_iqm` are now obsolete packages (`iqm-client[qiskit]` is the
  real replacement), and `BackendSpec.ibm()`/`IBMAdapter`'s default
  `channel="ibm_quantum"` no longer exists in qiskit-ibm-runtime (fixed to
  `"ibm_quantum_platform"`). See `../../docs/backends.md`,
  `tests/test_backend_adapters.py`.
- **Active Space now runs real AVAS** (`pyscf.mcscf.avas`) as the actual
  selection algorithm feeding all three schema containers, closing the
  "no selection algorithm" gap.
- **Minimizer/Stopping-Criterion now has a real catalogue** —
  `schemas/optimizer_catalog.py` (new module).
- **Logger now has a real subsystem** — `qpubench.observability.
  BenchmarkLogger` (new module): status-based levels, configurable
  handlers, `JSONFormatter`.

Still no qpubench mechanism to build a template around, anywhere checked:
Ground State Energy / PT2 via FAST-VQE or BEAST-VQE (proprietary,
permanently out of scope — ADAPT-VQE substitutes for both).

## Demos (`demos/`)

| qrunch demo | Verdict | File |
|---|---|---|
| Your First Quantum Chemistry Calculation | Yes | `getting_started_first_calculation.py` |
| Standard FAST-VQE / BEAST-VQE Convergence Study | Partial (ADAPT-VQE) | `adapt_vqe_convergence_study.py` |
| Running FAST-VQE on Quantum Computers | Partial (ADAPT-VQE; real hardware path needs credentials) | `adapt_vqe_on_quantum_computer.py` |
| Reaction-Path PES Study | Yes | `reaction_path_pes_sweep.py` |
| Polarizable Embedding — The Frame | **Yes** | `polarizable_embedding_frame.py` — real CPPE + PySCF `pyscf.solvent.PE` |
| Projection-Based Wavefunction-in-DFT Embedding Study (+ DMET) | Partial — real code, not installed | `dmet_embedding_demo.py` |

**Revised 2026-07-08.** Polarizable Embedding "The Frame" — real code,
real result, tested here: CPPE (github.com/maxscheurer/cppe) and PyFraME
(github.com/FraME-projects/PyFraME) are both real and pip-installable
(confirmed installed in this sandbox), bridged through PySCF's own
`pyscf.solvent.PE`. `schemas/polarizable_embedding.py` (new module) models
the real CPPE potfile format — verified field-by-field against PySCF's own
test data, not guessed — and the demo converges a real PE-embedded SCF
energy. Projection-Based Wavefunction-in-DFT Embedding (+ its DMET cousin):
PsiEmbed and libDMET are real, documented, PySCF-based packages, but
neither ships on PyPI (git-only install) — per the decision to write real
code without installing from source, `dmet_embedding_demo.py` calls each
package's actual verified API (checked directly against PsiEmbed's own
`examples/input.py` and PennyLane's own DMET-embedding tutorial) behind an
`ImportError` guard; it prints a clear message here and runs for real once
you install either package from source.

## Tutorials (`tutorials/`)

| qrunch tutorial | Verdict | File |
|---|---|---|
| Butyronitrile Dissociation | Partial — **real n-butyronitrile, real C#N bond** | `bond_dissociation_curve.py` |
| Covalent Ligand Binding | Partial — **real cathepsin K nitrile-cysteine model** | `bound_vs_unbound_comparison.py` |
| Dehalogenase Reaction (SN2) | Partial — **real carboxylate-mediated SN2 model** | `reaction_path_sn2.py` |
| Ionization Potentials (ammonia) | Partial — real H2/H2+ Hamiltonian (+ SlowQuant adapter, construction only; + real NH3-at-tutorial's-setup capability check) | `ionization_potential.py` |
| Carbon Capture with COF-999 | Partial — real periodic-DFT piece + real CO2+NH3 binding-site model | `carbon_capture_periodic_dft.py` |

**Revised 2026-07-08/09 (three times).** Ionization Potentials, first revision:
`integrations/slowquant/adapter.py` (new) is a real `SlowQuantAlgorithmAdapter`
implementing qpubench's `AlgorithmAdapter` protocol against SlowQuant's
actual public API — its constructor argument names (`cas`/`excitations`/
`include_active_kappa`) are SlowQuant's own real `WaveFunctionUCC`
arguments, checked against its GitHub source and structurally round-tripped
against a mock of that API — but SlowQuant isn't on PyPI either, so (same
"write real code, don't install" decision as PsiEmbed/libDMET above) it's
shown construction-only, same pattern as `guides/quantum_computers.py`'s
IBM/IQM section.

Second revision, after integrating PennyLane qchem + HamLib Chemistry (see
"Beyond qrunch parity" below): checked whether either closes this gap for
real. PennyLane's qchem collection *does* have real `NH3` — but at 16
qubits/2371 terms it's verified too large for this repo's dense-matrix
reference engine (a real `LiH` Hamiltonian at just 12 qubits/631 terms
already timed out at 2+ minutes for 2 truncated ADAPT-VQE iterations in
this same sandbox). `ionization_potential.py` now runs the tutorial's
neutral/cation delta-particle-number technique on HamLib's real H2
Hamiltonian instead (4 qubits, tractable) — H2/H2+ instead of qrunch's
ammonia, but a genuine molecule with a genuine ionization potential
(~16.2 eV vs. literature ~15.4-16.0 eV) rather than an invented toy
Hamiltonian. NH3 itself stays loadable-but-not-runnable through the toy
engine — a real simulator (Aer, Qrack) or active-space reduction as the
energy backend would be the actual fix, noted as a follow-up.

Butyronitrile Dissociation, Covalent Ligand Binding, Dehalogenase SN2, and
Carbon Capture with COF-999 do **not** close via pre-built libraries —
checked both libraries' full real molecule lists (PennyLane: BH3, BeH2,
C2, C2H2, C2H4, C2H6, CH2, CH2O, CH4, CO, CO2, H10, H2, H2O, H2O2, H3+,
H4-H8, HCN, HF, He2, HeH+, Li2, LiH, N2, N2H2, N2H4, NH3, NeH+, O2, O3,
OH-; HamLib chemistry/electronic: B2,BH,Be2,BeH,C2,CH,F2,H2,HF,Li2,LiH,
N2,NH,Na2,NaLi,O2,O3,OH (standard) + F2/N2/O2-binding (bond_breaking) +
H2-H60 clusters (hydrogen_data) + CoH,Cr2,CrO,CuC,FeC,MnN,NiO,ScC,ScO,TiH,
VH (transition_metals)) — none of butyronitrile, a generic ligand/protein
complex, a dehalogenase SN2 substrate, or the COF-999 MOF appear anywhere;
both libraries only carry small benchmark molecules.

**Third revision (2026-07-09): closed 3 of these 4 for real via ab initio
construction instead**, per direct request to build the missing molecules
rather than rely on pre-built libraries.
`qpubench.hamiltonian_sources.ab_initio.build_qubit_hamiltonian` (new)
computes a real qubit Hamiltonian from any geometry (PySCF HF +
frozen-core active-space reduction + Jordan-Wigner via OpenFermion) —
verified to reproduce H2's already-known exact energy to `1e-8`. Checked
the real qrunch tutorial notebooks directly
(github.com/Kvantify/qrunch_tutorials) rather than guessing stand-ins
blind, and found real, specific mechanism details:

- **Butyronitrile**: real molecule, no substitution needed — dissociates
  the real **C#N bond** (the tutorial's own real molecule and coordinate).
  Real setup is 8orb/8e=16 qubits (confirmed to build in 0.26s, too many
  terms to run through this repo's toy engine — built once as a
  capability check); the runnable scan uses a reduced 2orb/2e active
  space, still the real molecule and real bond.
- **Dehalogenase SN2**: the real notebook's own `embedded_atoms` list is
  `[C, O, O, Cl, C]` — a **carboxylate nucleophile**, i.e. the real
  Asp-mediated haloalkane dehalogenase mechanism, not a generic hydroxide
  attack as first assumed. Now modeled as CH3Cl + HCOO-.
- **Covalent Ligand Binding**: real target is **cathepsin K**; its real
  covalent warheads are **nitrile groups reacting with the catalytic
  cysteine thiol** (thioimidate formation), not a Michael-acceptor
  mechanism as first assumed. Now modeled as CH3CN + CH3SH.
- **Ionization (ammonia)**: real setup is cc-pVDZ, 6 active orbitals/8
  active electrons = 12 qubits — `ionization_potential.py` now builds
  this exact real setup as a capability check too (still not run — same
  too-many-terms class as LiH).

Carbon Capture with COF-999 stays independent (not source-verified) —
COF-999 isn't in the `qrunch_tutorials` repo at all (only the four
tutorials above exist there), so the CO2+NH3 amine-binding model added to
`carbon_capture_periodic_dft.py` is a defensible but unverified choice,
unlike the other three. See `examples/common/real_molecules.py` for every
geometry and the reasoning behind each choice.

Carbon Capture with COF-999's periodic-DFT half: previously the hardest
gap, flagged as needing DFT/periodic embedding with no path in qpubench at
all. `carbon_capture_periodic_dft.py` runs real periodic Gamma-point/
k-point PBE-DFT on a diamond-carbon cell via `pyscf.pbc` (bundled GTH
basis/pseudopotentials, no download needed) — the periodic-DFT-reference
building block a COF-999 study would need, not COF-999 itself (much larger
unit cell) or its embedded CO2-binding-site treatment (see the DMET demo
above for that half). Cebule's Quantum-ESPRESSO-backed
`PERIODIC_GEOMETRY_OPT` task remains a plane-wave alternative that likely
scales better for a COF-999-sized cell — a performance tradeoff between two
free options, not a "need InQuanto" situation.

## Beyond qrunch parity — real Hamiltonian libraries + ab initio construction

Not a qrunch guide/demo/tutorial — a framework capability added on
request: `qpubench.hamiltonian_sources` (new package) loads or computes
real molecule Hamiltonians, as a `SparsePauliObservable` ready to drop
into any existing `AlgorithmAdapter`/`BackendAdapter` Estimator path with
zero changes to that machinery.

- **HamLib Chemistry** (portal.nersc.gov/cfs/m888/dcamps/hamlib/chemistry/)
  — `hamiltonian_sources/hamlib.py`, `load_hamlib_chemistry()`. Downloads
  and caches HamLib's real HDF5 files, parses their real OpenFermion-text
  format (verified field-by-field against a real downloaded H2 file, not
  guessed) via a small regex — no `openfermion` dependency needed.
- **PennyLane qchem datasets** (pennylane.ai/datasets/collection/qchem) —
  `hamiltonian_sources/pennylane_qchem.py`, `load_pennylane_qchem()`.
  Wraps `qml.data.load()`, converts the real `LinearCombination` output.
- **Ab initio construction** (added 2026-07-09, per direct request to
  build the missing molecules rather than rely on pre-built libraries) —
  `hamiltonian_sources/ab_initio.py`, `build_qubit_hamiltonian()`. Real
  PySCF HF (via `openfermionpyscf`) + optional frozen-core active-space
  reduction + Jordan-Wigner (via `openfermion`), for *any* geometry — not
  just what a library happens to ship. `str(qubit_operator)` turned out to
  be byte-identical in format to HamLib's own stored strings, so
  `hamlib.parse_hamlib_qubit_operator()` is reused as-is, not
  reimplemented.

All three verified for real in this sandbox: the parsed H2 Hamiltonian's
exact ground-state energy matches PennyLane's own `fci_energy` to
`1e-11`; running HamLib's real H2 Hamiltonian through the existing
`GenericAdaptVQEEngine` converges to `-1.131459761897349 Ha`, matching
real dense diagonalization to `7e-15`; and `build_qubit_hamiltonian`
independently reproduces the same H2 result from raw geometry. Used this
session to compute real qubit Hamiltonians for 3 of the 5 qrunch
tutorials that previously used invented toy Hamiltonians (see the
Tutorials section above and `examples/common/real_molecules.py`). See
`examples/guides/hamiltonian_library.py`,
`tests/test_hamiltonian_sources.py`, `tests/test_ab_initio.py`,
`docs/schemas.md#hamiltonian_library`.

**None of this data ships with the repo** — it's pulled on demand the
first time you call the loader, not cloned/installed upfront:
HamLib caches to `~/.cache/qpubench/hamiltonian_sources/hamlib/`
(override with `cache_dir=`); PennyLane qchem downloads into a local
`datasets/` folder (PennyLane's own `qml.data.load(folder_path="datasets")`
default — override with `folder_path=`, forwarded through
`load_pennylane_qchem()`'s `**params`). Both paths are `.gitignore`d.
Ab initio construction needs no download at all — see
`docs/schemas.md#hamiltonian_library` for the full breakdown.

## What changed in the framework to support this

**Fifth pass (schema v2.5.0 → 2.6.0)**, ab initio Hamiltonian
construction:

- **`HamiltonianSource.AB_INITIO_PYSCF`** added to
  `schemas/hamiltonian_library.py`.
- **`src/qpubench/hamiltonian_sources/ab_initio.py`** (new) —
  `build_qubit_hamiltonian()`: real geometry -> PySCF HF
  (`openfermionpyscf`) -> optional frozen-core active-space reduction ->
  Jordan-Wigner (`openfermion`) -> `SparsePauliObservable` (reuses
  `hamlib.parse_hamlib_qubit_operator()` — confirmed byte-identical text
  format). New `openfermion` extra in `pyproject.toml`
  (`openfermion`, `openfermionpyscf`, `pyscf`).
- **`examples/common/real_molecules.py`** (new) — real geometries for the
  4 tutorials that previously used toy Hamiltonians, checked against the
  actual qrunch tutorial notebooks (github.com/Kvantify/qrunch_tutorials)
  rather than guessed.
- Rewrote **`tutorials/bond_dissociation_curve.py`** (real butyronitrile
  C#N scan), **`tutorials/reaction_path_sn2.py`** (real CH3Cl+HCOO-),
  **`tutorials/bound_vs_unbound_comparison.py`** (real CH3CN+CH3SH); added
  a real CO2+NH3 section to **`tutorials/carbon_capture_periodic_dft.py`**
  and a real NH3-at-tutorial's-setup capability check to
  **`tutorials/ionization_potential.py`**.
- **`tests/test_ab_initio.py`** (new) — real, offline, cross-checks the
  whole PySCF->OpenFermion->parse chain against independently-known H2
  values.

**Fourth pass (schema v2.4.0 → 2.5.0)**, integrating real Hamiltonian
libraries:

- **`src/qpubench/schemas/hamiltonian_library.py`** (new module) —
  `HamiltonianSource` enum + `HamiltonianLibraryRecord`. See
  `../../docs/schemas.md#hamiltonian_library`.
- **`src/qpubench/hamiltonian_sources/`** (new package) — `hamlib.py`
  (`load_hamlib_chemistry`, `list_hamlib_datasets`,
  `parse_hamlib_qubit_operator`) and `pennylane_qchem.py`
  (`load_pennylane_qchem`, `hamiltonian_to_observable`). Both lazily
  import their SDK (h5py/requests, pennylane) inside functions — the
  schema module itself stays SDK-free.
- **`pyproject.toml`**: new `hamlib` (`h5py`, `requests`) and `pennylane`
  (`pennylane`, `aiohttp`, `fsspec`, `h5py`) extras.
- **`examples/guides/hamiltonian_library.py`** (new) + rewrote
  **`examples/tutorials/ionization_potential.py`** to use a real H2/H2+
  Hamiltonian instead of the toy one.

**Third pass (schema v2.3.0 → 2.4.0)**, closing the backend-adapter,
embedding-schema, and partial-guide gaps:

- **`src/qpubench/backends/{aer,ibm,iqm,braket}_adapter.py`** (real
  implementations, replacing `NotImplementedError` stubs) — see
  `../../docs/backends.md` for the full verification writeup per adapter.
  New shared helper `src/qpubench/backends/_qiskit_common.py`
  (`load_qiskit_circuit`) and `SparsePauliObservable.to_qiskit_pauli_list()`
  (`schemas/observable.py`) factor out the CircuitSpec -> Qiskit conversion
  all four/three of them share.
- **`src/qpubench/schemas/polarizable_embedding.py`** (new module) —
  `PolarizableEmbeddingSite`/`Config`/`Result`, real CPPE potfile format.
  See `../../docs/schemas.md#polarizable_embedding`.
- **`src/qpubench/schemas/optimizer_catalog.py`** (new module) —
  `MINIMIZER_CATALOG` / `STOPPING_CRITERION_CATALOG`. See
  `../../docs/schemas.md#optimizer_catalog`.
- **`src/qpubench/observability.py`** (new module) — `BenchmarkLogger` +
  `JSONFormatter`, built on `BenchmarkRunner.add_hook()`.
- **`integrations/slowquant/adapter.py`** (new) — `SlowQuantAlgorithmAdapter`,
  real code against SlowQuant's verified API, not installed/executed (not
  on PyPI). See `integrations/slowquant/README.md`.
- **`BackendSpec.ibm()` / `IBMAdapter` default `channel`** fixed from the
  now-defunct `"ibm_quantum"` to `"ibm_quantum_platform"` — a real,
  current qiskit-ibm-runtime migration, discovered while testing
  `guides/quantum_computers.py` (`QiskitRuntimeService` now raises
  `ValueError` for the old channel name).
- **`pyproject.toml`**: added the `iqm` extra (`iqm-client[qiskit]` — the
  standalone `qiskit-iqm` package is obsolete), `qiskit-braket-provider` to
  the `braket` extra, `qiskit_qasm3_import` to the `qiskit` extra.

**Earlier passes (schema v2.1.0 → v2.3.0)**:

- **`src/qpubench/schemas/reactions.py`** (renamed from `reaction.py`,
  moved out of the framework-core module group, and expanded) —
  `ReactionCoordinateSpec`/`ReactionPathResult` tie a sweep of point
  calculations into one reaction path / PES, with `.barrier_height`,
  `.reaction_energy`, `.to_dict_for_plot()`, and now
  `.rate_constant()`/`.to_arrhenius_rate_constant()` (PennyLane-demo-style
  quantum-barrier → classical Arrhenius rate constant). Also adds real
  Cantera-style kinetics types (`ArrheniusRateConstant`,
  `KineticsSpeciesSpec`, `KineticsReactionSpec`, `ReactionMechanism`) —
  `ReactionMechanism.to_cantera_yaml()` produces a mechanism file real
  Cantera loads and evaluates rate constants from directly, verified
  against `cantera==3.2.0` in this repo's own sandbox. Used by
  `demos/reaction_path_pes_sweep.py` and both
  `tutorials/bond_dissociation_curve.py` and `tutorials/reaction_path_sn2.py`.
  See `../../docs/schemas.md#reactions`.
- **`BackendSpec.braket()` + `src/qpubench/backends/braket_adapter.py`** (new)
  — generic gate-based AWS Braket access (Rigetti/IonQ/OQC QPUs, SV1/DM1/TN1
  simulators), distinct from the Borealis/Aquila-specific Braket wiring that
  already existed. See `../../docs/backends.md`.
- **`src/qpubench/schemas/mqsdk_cebule.py`** (rewritten) — checked directly
  against `mqsdk/core/cebule.py`'s `TaskType` enum on
  [gitlab.com/mqsdk/python-sdk](https://gitlab.com/mqsdk/python-sdk) and
  found real drift: qpubench modeled `MOL_MAP`/`QASM_GEN` (neither in the
  current SDK) while missing 15 confirmed task types. Now models `COSMO`/
  `SIGMA`/`SOLUBILITY` (solvation), `BORN_OPPENHEIMER_MD`/
  `CAR_PARRINELLO_MD` (Quantum-ESPRESSO-backed ab initio MD, periodic-
  capable), `FORCE_FIELD_MD`, `GEOMETRY_OPT`/`PERIODIC_GEOMETRY_OPT`,
  `GROUP_CONTRIBUTION`, `ATOM_ORDER`, `ACTIVITY_COEFFICIENT`, and the GNN
  dataset/model lifecycle. See `../../docs/integrations/cebule.md`.
- **`src/qpubench/schemas/pyscf_pyscf.py`** (new module) — molecule/cell/mean-
  field/DFT/PCM-solvation types verified directly against the real PySCF
  API; DMET/projection-based-embedding types schema-only (PsiEmbed/libDMET
  aren't on PyPI). See `../../docs/integrations/pyscf.md`.
