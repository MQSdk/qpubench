# Integrations

qpubench's schema layer bridges several external frameworks. Each integration is a **data schema bridge only** — the external library is not imported into qpubench.

Schema modules are named `<org_or_maintainer>_<package>.py` — the maintainer/GitHub-handle identifies *who*, the suffix identifies *what*, so one glance at the filename tells you both. Modules with no single vendor (interoperability standards, the framework's own core types) stay unprefixed.

| Integration | External repo | Schema module | Key algorithms | Computing model | Qubit modality | Detail |
|---|---|---|---|---|---|---|
| Cebule SDK | [docs.mqs.dk](https://docs.mqs.dk/sections/section_014_quantum_computing/) · [gitlab.com/mqsdk/python-sdk](https://gitlab.com/mqsdk/python-sdk) | `schemas/mqsdk_cebule.py` | COSMO/SIGMA/SOLUBILITY · ab initio + classical MD · GEOMETRY_OPT · GROUP_CONTRIBUTION · GNN · TN_QC_OPT · COVO | `GATE_BASED` (`TN_QC_OPT`/`COVO`) + classical | — | [cebule.md](integrations/cebule.md) |
| Xenakis GA | [github.com/mqsdk/xenakis](https://github.com/mqsdk/xenakis) | `schemas/mqsdk_xenakis.py` | Layer-genome GA · bitstring-genome GA · QNEAT genome search | `GATE_BASED` | — | [xenakis.md](integrations/xenakis.md) |
| QForte | [github.com/evangelistalab/qforte](https://github.com/evangelistalab/qforte) | `schemas/evangelistalab_qforte.py` | ADAPT-VQE · UCCN-VQE · UCCN-PQE · SPQE | `GATE_BASED` | — | [integrations/qforte/](../integrations/qforte/) |
| ExcitationSolve | [github.com/dlr-wf/ExcitationSolve](https://github.com/dlr-wf/ExcitationSolve) | `schemas/dlr_excitation_solve.py` | Fourier-series VQE optimizer · ADAPT-VQE | `GATE_BASED` | — | [excitation_solve.md](integrations/excitation_solve.md) |
| GSOpt | [github.com/bestquark/gsopt](https://github.com/bestquark/gsopt) | `schemas/bestquark_gsopt.py` | VQE · TN · DMRG · AFQMC · Gibbs benchmark lanes | `GATE_BASED` | — | [gsopt.md](integrations/gsopt.md) |
| photoq (MQSdk) | photoq — linear-optics chips + FBQC, GBS, pseudo-PNRD, ORCA/Xanadu/DTU backends | `schemas/mqsdk_photoq.py` | LOQC VQE · FBQC · HOM · Sobol · GBS sampling · clique finding · TDM/Borealis · pseudo-PNRD click-counting methods · ORCA PT Series / DTU QCloud / Xanadu Aurora backends | `GATE_BASED` (LOQC) / `FUSION_BASED` / `GBS` | `PHOTONIC` | [photonic.md](integrations/photonic.md) · [gbs.md](integrations/gbs.md) |
| QDK Chemistry | [microsoft/qsharp](https://github.com/microsoft/qsharp) | `schemas/microsoft_qdk.py` | SCF · active-space selection (MACIS) · state preparation · QPE/IQPE · resource estimation — pipeline stages usable independently | `GATE_BASED` | — | [qdk_chemistry.md](integrations/qdk_chemistry.md) |
| MQSdk/qse (KQD) | [github.com/MQSdk/qse](https://github.com/MQSdk/qse) | `schemas/mqsdk_qse.py` | KQD (Hadamard test) · SQD (sample-based Krylov) | `GATE_BASED` (KQD technique) | — | [qse.md](integrations/qse.md) |
| QESEM (Qedma) | [docs.qedma.io](https://docs.qedma.io/) | `schemas/qedma_qesem.py` | QET noise-scaled mitigation · device characterization | `GATE_BASED` + `QESEM` | `SUPERCONDUCTING` | [qesem.md](integrations/qesem.md) |
| QCSchema / QCElemental / PennyLane | [MolSSI QCSchema](https://github.com/MolSSI/QCSchema) · [QCElemental](https://github.com/MolSSI/QCElemental) · [PennyLane qchem](https://pennylane.ai/datasets/collection/qchem) | `schemas/molssi_qcschema.py` | Standard chemistry I/O interop · PennyLane qchem datasets | all (chemistry) | all | [qcschema.md](integrations/qcschema.md) |
| Bloqade / Aquila (QuEra) | [github.com/QuEraComputing/bloqade](https://github.com/QuEraComputing/bloqade) | `schemas/quera_bloqade.py` | Analog Hamiltonian Simulation (AHS) · Rydberg MIS graph problems | `ADIABATIC` | `NEUTRAL_ATOM` | [neutral_atom.md](integrations/neutral_atom.md) |
| SlowQuant | [github.com/erikkjellgren/SlowQuant](https://github.com/erikkjellgren/SlowQuant) · [slowquant.readthedocs.io](https://slowquant.readthedocs.io/en/latest/) | `schemas/erikkjellgren_slowquant.py` | HF/SCF · UCC · fUCC/tUPS · SAUPS excited states · linear response · VQE | `GATE_BASED` | — | [slowquant.md](integrations/slowquant.md) |
| PySCF | [pyscf.org](https://pyscf.org/) | `schemas/pyscf_pyscf.py` | Mean-field/DFT · PCM/COSMO solvation · periodic PBC (all verified real) · DMET/projection-based embedding (schema-only) | `GATE_BASED` (embedding output) + classical | — | [pyscf.md](integrations/pyscf.md) |
| Fragme∩t | [gitlab.com/fragment-qc/fragment](https://gitlab.com/fragment-qc/fragment) | `schemas/fragmentqc_fragment.py` | MBE · GMBE via PIE trees · multilevel layers · adaptive screening mods | classical (chemistry) | — | [fragmentation.md](integrations/fragmentation.md) |
| quantum-fragment-methods | [github.com/qiskit-community/quantum-fragment-methods](https://github.com/qiskit-community/quantum-fragment-methods) | `schemas/qiskitcommunity_fragment_methods.py` | EWF / DMET embedding · rule-based SQD / ext-SQD / FCI / CCSD solver assignment | `GATE_BASED` | `SUPERCONDUCTING` | [fragmentation.md](integrations/fragmentation.md) |
| DISQCO | [github.com/felix-burt/DISQCO](https://github.com/felix-burt/DISQCO) | `schemas/felixburt_disqco.py` | Multilevel hypergraph circuit partitioning over a QPU network · ebit minimisation · circuit extraction | `GATE_BASED` | all | [distributed_qc.md](integrations/distributed_qc.md) |
| Qdislib | [github.com/bsc-wdc/qdislib](https://github.com/bsc-wdc/qdislib) | `schemas/bscwdc_qdislib.py` | Gate / wire / Hadamard cutting · `find_cut` · quasiprobability reconstruction · PyCOMPSs distribution | `GATE_BASED` | all | [distributed_qc.md](integrations/distributed_qc.md) |

Two of these bridge into framework-general cross-cutting modules rather than standing alone — `schemas/fragmentation.py` (problem-space decomposition) and `schemas/distributed_execution.py` (circuit-space decomposition). Together they cover adaptive multilevel fragmentation executed via distributed quantum computing: fragment the molecule, solve each fragment on a QPU, and partition or cut the fragments whose circuits still do not fit.

Error-mitigation and hardware-vendor schemas that used to be bundled in one `error_mitigation.py` grab-bag are now one module per vendor:

| Vendor | Schema module | What it covers |
|---|---|---|
| Q-CTRL | `schemas/qctrl_fire_opal.py` | Fire Opal noise-robust compilation service |
| Unitary Fund | `schemas/unitaryfund_mitiq.py` | Mitiq — ZNE, PEC, CDR, REM, DDD |
| Haiqu | `schemas/haiqu_rivet.py` | Rivet hardware-aware transpilation middleware |
| ParityQC | `schemas/parityqc_parityqc.py` | Parity encoding for combinatorial optimisation |
| QMatter | `schemas/qmatter_qmatter.py` | Quantum problem compression |
| Quantum Motion | `schemas/quantum_motion_hardware.py` | Silicon CMOS spin-qubit hardware characterisation (a QPU vendor, not error mitigation — moved out of the old grab-bag) |
| IBM | `schemas/ibm_runtime_v2.py` | Qiskit Runtime V2 EstimatorV2/SamplerV2 PUB format, BitArray, ExecutionSpans |
| *(community registry)* | `schemas/advantage.py` | Quantum Advantage Tracker metadata — co-initiated by IBM, Flatiron Institute, BlueQubit, Algorithmiq; not a single vendor's SDK, so it stays unprefixed |

## Switching AlgorithmAdapter implementations

For the full picture of the variational-algorithm family — how VQE and ADAPT-VQE relate, the package-agnostic contract, and worked examples — see **[VQA algorithms](vqa.md)**. In brief:

`AlgorithmSpec` carries identity only (`name` + `AlgorithmFamily`); hyperparameters live in a family-specific config so the same run configuration works across every adapter that implements that family. `AlgorithmFamily.ADAPT_VQE` has three interchangeable implementations, sharing the package-agnostic `AdaptVQERunConfig` (`schemas/execution.py`):

| Adapter | Schema module | Engine |
|---|---|---|
| `integrations/qforte/QForteAlgorithmAdapter` | `schemas/evangelistalab_qforte.py` | QForte's native C++ statevector |
| `integrations/ibm_qiskit_adapt_vqe/IBMQiskitAdaptVQEAdapter` | — (uses core `SparsePauliObservable`/`CircuitSpec`) | `integrations/generic_adapt_vqe/` — pure Python + scipy |
| `integrations/microsoft_qdk_adapt_vqe/MicrosoftQDKAdaptVQEAdapter` | — (uses core `SparsePauliObservable`/`CircuitSpec`) | `integrations/generic_adapt_vqe/` — pure Python + scipy |

`integrations/generic_adapt_vqe/` implements the fermionic singles+doubles operator pool (Jordan-Wigner mapped), Pauli-exponential circuit synthesis, and finite-difference gradient screening from scratch — no vendor SDK needed, and both the Jordan-Wigner math and the circuit synthesis are independently verified against dense-matrix ground truth in `tests/test_generic_adapt_vqe.py` rather than taken from a textbook formula on faith.

For adapters (code that calls the library and returns a `QuantumResult`), see [backends.md](backends.md) and the templates in `integrations/`.

## Orchestration

Unlike everything above, this isn't a schema bridge — it's a layer for
*running* qpubench's algorithmic steps as scheduled, resourced,
dashboard-visible units of compute.

| Integration | External repo | Package | What it orchestrates | Detail |
|---|---|---|---|---|
| Kubeflow Pipelines (kfp) | [github.com/kubeflow/pipelines](https://github.com/kubeflow/pipelines) | `integrations/kubeflow/` | Cebule MOL_MAP → TN_QC_OPT → QASM_GEN → circuit execution, as a kfp DAG | [kubeflow.md](integrations/kubeflow.md) |
