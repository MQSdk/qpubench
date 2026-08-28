# Schema reference

Every schema type imports from the package root, `from qpubench.schemas
import CircuitSpec, QuantumResult, …`, whichever file it lives in. That is
the stable import path; the directory layout below is an organisational
detail and may change.
The current schema version and module count are tracked in the
[README](../README.md) (see its badge); those metrics are not duplicated here,
so this reference never drifts out of date against them.

The modules fall into three groups, and each group is its own directory:

| Group | Directory | What belongs there |
|---|---|---|
| **1. Core record format** | `schemas/` | The seven modules defining the types every benchmark shares (`primitives` through `record`). |
| **2. Cross-cutting catalogues & registries** | `schemas/catalogs/` | Modules that aggregate *multiple* external sources, or define a catalogue qpubench itself owns (basis sets, Hamiltonian metadata, the community advantage tracker, …). Neither core record types nor a mirror of one upstream project. |
| **3. Project mirrors** | `schemas/mirrors/` | One module per external project, named `<org_or_maintainer>_<package>.py` so the filename alone tells you who maintains the upstream project and what it's called. |

A module in group 2 or 3 is reached as `qpubench.schemas.catalogs.<name>` /
`qpubench.schemas.mirrors.<name>` if you need the file directly, but every
public type is re-exported from `qpubench.schemas`, so you rarely should.

Known gaps in the core record format, and what the mirror layer has revealed
about them, are assessed in [schema_review.md](schema_review.md). Nothing
there has been applied; it is the list of what should be.

---

## Module index

Computing model (paradigm) and qubit modality are separate, independent axes on every circuit, backend, and result: "all" means the module is paradigm-/modality-agnostic; "n/a" means the axis doesn't apply (e.g. classical-chemistry or vendor-tooling modules).

```
   Two independent axes, stamped on every circuit, backend, and result
   ───────────────────────────────────────────────────────────────────

     computing_model   (paradigm: HOW a program is expressed)
        GATE_BASED · MBQC · FUSION_BASED · ADIABATIC · ANNEALING · GBS · SAMPLING
                 ▲
                 │     Each record picks ONE value on each axis, chosen
                 │     independently; the two are not a single flat enum:
                 │        (GATE_BASED , SUPERCONDUCTING)   a gate circuit on IBM
                 │        (GBS        , PHOTONIC)          Gaussian boson sampling
                 │        (ADIABATIC  , NEUTRAL_ATOM)      Rydberg analog (AHS)
                 └──────────────▶
     qubit_modality    (QPU: WHAT hardware realizes it)
        SUPERCONDUCTING · TRAPPED_ION · PHOTONIC · NEUTRAL_ATOM · SILICON_SPIN

     In the tables below:  "all" = axis-agnostic module;
                           "n/a" = axis doesn't apply (classical-chemistry /
                                   vendor-tooling module).
```

### Core record format

| Module | Purpose | Computing model · qubit modality | Key types |
|---|---|---|---|
| [`primitives`](#primitives) | Enums and value types used across all other modules | all · all | `ComputingModel`, `QubitModality`, `CircuitFormat`, `PauliLabel`, `ComplexNumber` |
| [`circuit`](#circuit) | Circuit or problem specification | all · all | `CircuitSpec` (`from_openqasm3`, `openqasm3`, `bind`), `ParameterBinding` |
| [`observable`](#observable) | Sparse Pauli observables | all · all | `Pauli` (shorthand factory), `SparsePauliObservable`, `PauliTerm` |
| [`backend`](#backend) | Hardware / simulator description | all · all | `BackendSpec` (31 factory constructors) |
| [`execution`](#execution) | Execution options and algorithm hyperparameters | all · all | `ExecutionOptions`, `AlgorithmSpec`, `VQERunConfig` / `AdaptVQERunConfig` / `QAOARunConfig` (VQE / ADAPT / QAOA runtime hyperparameters; experiment metadata lives in `record.VQAConfig`), `ZNEConfig`, `TranspilerConfig` |
| [`result`](#result) | Execution results (expectation values, counts, fidelity, per-iteration algorithm history) | all · all | `QuantumResult` (15 result-type fields), `ExpectationResult`, `ShotResult`, `TranspileLayout` |
| [`record`](#record) | Top-level benchmark record and algorithm metadata | all · all | `BenchmarkRecord`, `VQAConfig`, `VQAResult` |

### Cross-cutting catalogues & registries (unprefixed)

The **Origin / source** column names where each catalogue's contents come
from. The same attribution is noted in each module's own docstring/class
comments.

A catalogue is named for *what it catalogues*, not by the mirrors'
`<org>_<package>` convention; that form has nothing sensible to say when a
catalogue draws on several upstreams, or when the upstream is a GitHub Pages
community registry whose organisation and project share a name (which would
give `quantum_advantage_tracker_quantum_advantage_tracker`).

| Module | Origin / source | Purpose | Computing model · qubit modality | Key types |
|---|---|---|---|---|
| [`quantum_advantage_tracker`](https://github.com/quantum-advantage-tracker/quantum-advantage-tracker.github.io) | Quantum Advantage Tracker: community registry co-initiated by IBM, Flatiron Institute, BlueQubit, Algorithmiq | Quantum-advantage experiment metadata | all · all | `QuantumAdvantageRecord`, `AdvantageExperimentType`, `ClassicalComparisonMethod` |
| [`optimizer_catalog`](#optimizer_catalog) | qpubench's own, over `scipy.optimize.minimize` | Minimizer / stopping-criterion catalogue over `AdaptVQERunConfig` fields | all · all | `MINIMIZER_CATALOG`, `STOPPING_CRITERION_CATALOG`, `MinimizerCatalogEntry`, `StoppingCriterionCatalogEntry` |
| [`hamiltonian_library`](#hamiltonian_library) | PennyLane qchem · HamLib Chemistry · ab initio (PySCF + OpenFermion) | Metadata for Hamiltonians loaded from those sources | all · all | `HamiltonianSource`, `HamiltonianLibraryRecord` |
| [`basis_sets`](#basis_sets) | Basis Set Exchange · q-vSZP (Grimme group) | Basis-set catalogue: BSE (real, verified counts) + q-vSZP (schema-only) | classical (chemistry) · n/a | `BasisSetCatalogEntry`, `BASIS_SET_CATALOG`, `QvSZPRunConfig`, `QvSZPBasisResult` |
| [`contraction_path`](#contraction_path) | quimb + cotengra | Tensor-network contraction-path strategy/config/result | `GATE_BASED` (TN simulation) · n/a | `ContractionPathStrategy`, `ContractionPathConfig`, `ContractionPathResult` |
| [`reactions`](#reactions) | Cantera · PennyLane · Cebule (MQS) | Reaction-coordinate/PES sweep + kinetics mechanism + rate-constant bridge | all · all | `ReactionCoordinateSpec`, `ReactionPathResult`, `ArrheniusRateConstant`, `ReactionMechanism` |
| [`polarizable_embedding`](#polarizable_embedding) | CPPE + PyFraME (wired through `pyscf.solvent.PE`) | Polarizable embedding ("The Frame") potfile-equivalent environment | classical (chemistry) · n/a | `PolarizableEmbeddingSite`, `PolarizableEmbeddingConfig`, `PolarizableEmbeddingResult` |
| [`fragmentation`](#fragmentation) | Fragme∩t (Herbert group) · quantum-fragment-methods (IBM × Cleveland Clinic) · DMET/EWF literature | Problem-space decomposition: fragments, signed expansions, multilevel layers, adaptive screening, per-fragment solver assignment | all · all | `FragmentationSpec`, `FragmentSpec`, `FragmentExpansionTerm`, `FragmentationLayer`, `FragmentScreeningRule`, `FragmentSolverAssignment`, `FragmentationResult`, `FragmentResult` |
| [`distributed_execution`](#distributed_execution) | DISQCO (arXiv:2503.19082, 2507.16036) · Qdislib (BSC, SC '25) | Circuit-space decomposition: QPU networks, partitioning with teleportation, gate/wire cutting, reconstruction | `GATE_BASED` · all | `QPUNetworkSpec`, `CircuitPartitionSpec`, `CircuitCutSpec`, `EntanglementCost`, `SubcircuitSpec`, `ReconstructionResult`, `DistributedRunConfig`, `DistributedRunResult` |

### Project mirrors (`<org_or_maintainer>_<package>`)

The **Group** column matches the thematic groups used in the README's schema overview.

| Module | Group | Purpose | Computing model · qubit modality | Key types |
|---|---|---|---|---|
| [`microsoft_qdk`](#microsoft_qdk) | Quantum chemistry & VQA | QDK quantum-chemistry pipeline: SCF → active space → state prep → QPE → resource estimation; stages usable independently | `GATE_BASED` · n/a | `QChemPipelineSpec`, `MoleculeStructureSpec`, `SCFResult`, `FermionicHamiltonianSpec`, `QPEResult`, `ResourceEstimationResult`, `ModelHamiltonianSpec` |
| [`molssi_qcschema`](#molssi_qcschema) | Quantum chemistry & VQA | QCSchema / QCElemental / PennyLane quantum chemistry interoperability | all (chemistry) · all | `QCMolecule`, `QCAtomicInput`, `QCAtomicResult`, `QCOptimizationResult`, `QCWavefunctionData`, `QCEnergyComponents`, `PennyLaneMolDataset`, `QCSchemaRecord` |
| [`pyscf_pyscf`](#pyscf_pyscf) | Quantum chemistry & VQA | PySCF molecules/cells, mean-field/DFT, PCM/COSMO solvation (real), DMET/projection-based embedding (schema-only) | classical (chemistry) · n/a | `PySCFMoleculeSpec`, `PySCFCellSpec`, `PySCFMeanFieldConfig`, `PySCFSolvationConfig`, `DMETConfig`, `ERIBuilderConfig`, `OrbitalOptimizerConfig` |
| [`erikkjellgren_slowquant`](#erikkjellgren_slowquant) | Quantum chemistry & VQA | SlowQuant UCC/VQE: ansatz config, SCF result, optimization, RDMs, linear response, circuit spec | `GATE_BASED` · n/a | `SlowQuantRecord`, `UCCWavefunctionConfig`, `UCCOptimizationResult`, `UCCLinearResponseResult`, `UCCExcitedStateResult`, `UCCCircuitSpec`, `UCCSCFResult`, `UCCRDMData` |
| [`evangelistalab_qforte`](#evangelistalab_qforte) | Quantum chemistry & VQA | QForte: pybind11 object layer (Circuit/Gate/QubitOperator) + algorithm-run layer (config, result) for ADAPT-VQE / UCCN-VQE / UCCN-PQE / SPQE | `GATE_BASED` · n/a | `QForteCircuitSpec`, `QForteQubitOperatorSpec`, `QForteSqOpPoolSpec`, `QForteAlgorithmConfig`, `QForteRunResult` |
| [`bestquark_gsopt`](#bestquark_gsopt) | Quantum chemistry & VQA | GSOpt fixed-budget benchmark results | `GATE_BASED` · n/a | `GSOptBenchmarkResult`, `ActiveSpaceSpec`, `REFERENCE_ENERGIES`, per-lane `GSOptRunConfig` / `GSOptVQERunConfig` / `GSOptTNRunConfig` / `GSOptAFQMCRunConfig` / `GSOptGibbsRunConfig` |
| [`dlr_excitation_solve`](#dlr_excitation_solve) | Quantum chemistry & VQA | ExcitationSolve Fourier-series VQE optimizer | `GATE_BASED` · n/a | `ExcitationSolveResult`, `ExcitationSolveSweep`, `ExcitationAdaptResult` |
| [`classiq_classiq`](integrations/classiq.md) | Quantum chemistry & VQA | Classiq synthesis + chemistry/QAOA | `GATE_BASED` · n/a | `ClassiqSynthesisResult`, `ClassiqChemistryModel`, `ClassiqVQEResult`, `ClassiqCombinatorialOptimizationSpec`, `ClassiqConstraints` |
| [`mqsdk_qse`](#mqsdk_qse) | Quantum chemistry & VQA | Krylov Quantum Diagonalization (KQD / QSE / SQD) | `GATE_BASED` · n/a | `KQDPipelineSpec`, `KQDConfig`, `KrylovSubspaceMatrices`, `KrylovEigenResult`, `SQDConvergenceResult`, `CholeskyDecompositionSpec` |
| [`mqsdk_cebule`](#mqsdk_cebule) | Quantum chemistry & VQA | Cebule SDK (MQS) task inputs / outputs | `GATE_BASED` (`TN_QC_OPT`/`COVO`) + classical · n/a | `CosmoResult`, `SigmaResult`, `SolubilityResult`, `AbInitioMDResult`, `GeometryOptResult`, `TNQCOptResult`, `COVOResult` |
| [`fragmentqc_fragment`](#fragmentqc_fragment) | Fragmentation & distribution | Fragme∩t (GitLab `fragment-qc/fragment`): `strategy.yaml` mirror, PIE trees, screening mods, per-layer backends | classical (chemistry) · n/a | `FragmentStrategy`, `FragmentPIETree`, `FragmentPIENode`, `FragmentModSpec`, `FragmentBackendSpec`, `FragmentFragmenterSpec`, `FragmentRunRecord` |
| [`qiskitcommunity_fragment_methods`](#qiskitcommunity_fragment_methods) | Fragmentation & distribution | quantum-fragment-methods: EWF embedding + rule-based SQD / ext-SQD / FCI / CCSD solver assignment (arXiv:2512.17130) | `GATE_BASED` · `SUPERCONDUCTING` | `QFMWorkflowConfig`, `QFMEWFConfig`, `QFMSQDConfig`, `QFMFragment`, `QFMSolverResult`, `QFMWorkflowResult` |
| [`felixburt_disqco`](#felixburt_disqco) | Fragmentation & distribution | DISQCO: multilevel hypergraph partitioning over a QPU network, ebit cost, circuit extraction | `GATE_BASED` · all | `DisqcoNetworkSpec`, `DisqcoPartitionResult`, `DisqcoFMConfig`, `DisqcoCoarsener`, `DisqcoHypergraphStats`, `DisqcoExtractedCircuit` |
| [`bscwdc_qdislib`](#bscwdc_qdislib) | Fragmentation & distribution | Qdislib (BSC): gate/wire cutting, `find_cut`, quasiprobability reconstruction, PyCOMPSs distribution, semantic cache | `GATE_BASED` · all | `QdislibRunRecord`, `QdislibCutRecord`, `QdislibCutCost`, `QdislibFindCutConfig`, `QdislibSubcircuit`, `QdislibCacheStats` |
| [`mqsdk_photoq`](#mqsdk_photoq) | Photonic / GBS | Linear-optics chips + FBQC, Gaussian Boson Sampling, pseudo-PNRD click-counting methods, ORCA PT Series / DTU QCloud / Xanadu Aurora backends | `GATE_BASED` (LOQC) / `FUSION_BASED` / `GBS` · `PHOTONIC` | `PhotonicCircuitSpec`, `GBSProgramSpec`, `HafnianResult`, `PseudoPNRDSpec`, `ClickPatternProbabilityResult`, `MethodComparison`, `TimeBinInterferometerSpec`, `QCloudJobSpec` |
| [`johnrscott_mbqc_fpga`](#johnrscott_mbqc_fpga) | Other paradigms | MBQC-FPGA 16-bit program word, measurement patterns | `MBQC` · n/a (FPGA control logic) | `MBQCPattern`, `MBQCProgramWord`, `MBQCExecutionResult`; bit-exact 16-bit FPGA word |
| [`quera_bloqade`](#quera_bloqade) | Other paradigms | Neutral atom AHS: Bloqade / Aquila atom arrangements, waveforms, drives, results | `ADIABATIC` · `NEUTRAL_ATOM` | `AtomArrangement`, `AHSProgramSpec`, `AHSDrivingField`, `AHSTimeSeries`, `AHSTaskResult`, `AHSShotResult`, `AquilaDeviceSpec`, `AHSBatchSpec` |
| [`qedma_qesem`](#qedma_qesem) | Error mitigation & vendors | QESEM (Qedma) error suppression and mitigation | `GATE_BASED` + `QESEM` · `SUPERCONDUCTING` | `QESEMJobRecord`, `QESEMJobSpec`, `QESEMObservableResult`, `QESEMNoiseScalingResult`, `QESEMCircuitOptions`, `QESEMExecutionDetails`, `QESEMCharacterizationResult` |
| [`qctrl_fire_opal`](https://docs.q-ctrl.com/fire-opal) | Error mitigation & vendors | Q-CTRL Fire Opal noise-robust compilation | `GATE_BASED` · n/a | `FireOpalConfig`, `FireOpalResult` |
| [`unitaryfund_mitiq`](https://github.com/unitaryfund/mitiq) | Error mitigation & vendors | Mitiq: ZNE, PEC, CDR, REM, DDD | `GATE_BASED` · n/a | `MitiqTechnique`, `MitiqZNEConfig`, `MitiqPECConfig`, `MitiqCDRConfig`, `MitiqREMConfig` |
| [`haiqu_rivet`](https://github.com/haiqu-ai/rivet-transpiler) | Error mitigation & vendors | Haiqu Rivet transpilation middleware | `GATE_BASED` · n/a | `HaiquRivetConfig`, `HaiquTranspilationResult` |
| [`parityqc_parityqc`](https://www.parityqc.com) | Error mitigation & vendors | ParityQC parity encoding for combinatorial optimisation | `GATE_BASED` · n/a | `ParityQCProblemEncoding`, `ParityQCConfig`, `ParityQCResult` |
| [`qmatter_qmatter`](https://qmatter.xyz) | Error mitigation & vendors | QMatter quantum problem compression | `GATE_BASED` · n/a | `QMatterConfig`, `QMatterCompressionResult` |
| [`quantum_motion_hardware`](https://quantummotion.tech) | Error mitigation & vendors | Quantum Motion silicon CMOS spin-qubit hardware | `GATE_BASED` · `SILICON_SPIN` | `QuantumMotionDeviceSpec` |
| [`ibm_runtime_v2`](https://github.com/Qiskit/qiskit-ibm-runtime) | Error mitigation & vendors | Qiskit Runtime V2 EstimatorV2/SamplerV2 PUB format, BitArray, ExecutionSpans | `GATE_BASED` · `SUPERCONDUCTING` | `IBMEstimatorPUB`, `IBMSamplerPUB`, `IBMExecutionSpan`, `IBMRuntimeRecord` |
| [`ibm_cost_estimator`](#ibm_cost_estimator) | Error mitigation & vendors | Real resource estimation (ALAP-scheduled transpile + IBM's own usage formula) + dollar cost breakdown across IBM's 4 access plans | `GATE_BASED` · `SUPERCONDUCTING` | `IBMAccessPlan`, `CircuitResourceEstimate`, `PlanCostBreakdown`, `BenchmarkCostEstimate` |
| [`mqsdk_xenakis`](#mqsdk_xenakis) | Circuit search & tooling | Xenakis GA circuit genomes and run results | `GATE_BASED` · n/a | `LayerGenome`, `BitstringGenome`, `QNEATGenome`, `GARunResult`, `XenakisRunConfig` |
| [`hqs_struqture`](#hqs_struqture) | Quantum chemistry & VQA | struqture (HQS): spin / boson / fermion / mixed operator algebra, Lindblad noise operators and open systems, symbolic coefficients, per-object version metadata | all · all | `StruqtureOperator`, `StruqtureNoiseOperator`, `StruqtureOpenSystem`, `StruqtureValue`, `PauliProductSpec`, `ModeProductSpec`, `StruqtureMappedHamiltonian`, `StruqtureSerialisationMeta` |
| [`hqs_active_space_finder`](#hqs_active_space_finder) | Quantum chemistry & VQA | ActiveSpaceFinder (HQS): entropy- and cumulant-driven active-space selection over MP2 natural orbitals + screening DMRG; carries the MO basis its indices refer to | classical (chemistry) · n/a | `ASFActiveSpace`, `ASFSelectionConfig`, `ASFSelectionResult`, `ASFCandidateSpace`, `ASFOrbitalEntropy`, `ASFDMRGConfig` |
| [`hqs_qoqo`](#hqs_qoqo) | Circuit search & tooling | qoqo / roqoqo (HQS): structured circuits with in-circuit PRAGMAs, measurement inputs and their post-processing rules, `QuantumProgram`, time-based device and noise models | `GATE_BASED` · all | `QoqoCircuitSpec`, `QoqoOperation`, `QoqoPragma`, `QoqoPauliZProductInput`, `QoqoExpectationRule`, `QoqoQuantumProgramSpec`, `QoqoDeviceSpec`, `QoqoNoiseModelSpec` |
| [`hqs_qoqo_qasm`](#hqs_qoqo_qasm) | Circuit search & tooling | qoqo_qasm (HQS): OpenQASM version **and dialect** (Vanilla / Qulacs / Roqoqo / Braket), register naming, translation-coverage record | `GATE_BASED` · n/a | `QasmDialect`, `QoqoQasmConfig`, `QoqoQasmTranslationResult` |
| [`questkit_quest`](#questkit_quest) | Other paradigms | QuEST v4 (EPCC): simulator deployment (OpenMP × GPU × MPI × cuQuantum), compile-time precision, state-vector vs density-matrix memory, `mix*` decoherence channels, `calc*` result surface | `GATE_BASED` · n/a | `QuESTQuregSpec`, `QuESTDeployment`, `QuESTPrecision`, `QuESTPauliStrSum`, `QuESTNoiseChannel`, `QuESTCalculationResult`, `QuESTRunRecord` |

---

## `primitives`

### Enums

| Enum | Values |
|---|---|
| `ComputingModel` | `GATE_BASED` · `MBQC` · `FUSION_BASED` · `ADIABATIC` · `ANNEALING` · `GBS` · `SAMPLING` |
| `QubitModality` | `SUPERCONDUCTING` · `TRAPPED_ION` · `NEUTRAL_ATOM` · `PHOTONIC` · `SILICON_SPIN` |
| `AlgorithmFamily` | `ADAPT_VQE` · `VQE` · `UCC_PQE` · `SPQE` · `QAOA` · `TN_QC_OPT` · `GA_CIRCUIT_SEARCH` · `QPE`; package-agnostic algorithm identity, orthogonal to `ComputingModel`. A family is a broad *strategy*: UCC-type ansätze and the ExcitationSolve optimizer are choices under `VQE`, not families of their own |
| `CircuitFormat` | `QASM2` · `QASM3` · `QGC` · `MEASUREMENT_PATTERN` · `JSON` · `MOLECULE_JSON` · `FOCK_STATE_CIRCUIT` · `LINEAR_OPTICS_UNITARY` · `QMOD` |
| `PauliLabel` | `I` · `X` · `Y` · `Z` |
| `ErrorMitigationStrategy` | `NONE` · `DD` · `TREX` · `ZNE` · `PEC` · `QESEM` · `FIRE_OPAL` · `MITIQ_ZNE` · `MITIQ_PEC` · `MITIQ_CDR` · `MITIQ_REM` · `MITIQ_DDD` · `HAIQU` · `PARITY_QC` · `QMATTER` |
| `FidelityMetric` | `UNITARY` · `FUBINI_STUDY` · `TRACE` · `PROCESS` |
| `JobStatus` | `PENDING` · `RUNNING` · `SUCCEEDED` · `FAILED` · `CANCELLED` |

> **ToDo: `AlgorithmFamily` needs refinement.** The current member set is
> chemistry/VQA-heavy and only one family (`ADAPT_VQE`) has more than one
> implementing adapter today (see [`execution`](#execution)). Before it can be
> a stable comparison key across the whole framework it needs: clearer
> criteria for what earns a member, coverage for sampling/annealing/photonic
> paradigms, and a decision on whether single-implementation families
> (`TN_QC_OPT`, `GA_CIRCUIT_SEARCH`, `QPE`) stay here or
> move next to their owning module. Treat the enum as provisional.

> **`CircuitFormat` is a serialization format, not an algorithm.** There is no
> `VQE` member and there should not be; VQE is an *algorithm*, not a way of
> encoding a circuit. Plain (vanilla) VQE **is** supported: describe it with
> `VQAConfig(algorithm="VQE", ...)` (see [`record`](#record)), set its runtime
> knobs in [`VQERunConfig`](#vqerunconfig), and run each energy evaluation as an
> ordinary `CircuitSpec` through a `BackendAdapter`. `AdaptVQERunConfig` is the
> *adaptive* variant's contract; it swaps `layers` for an operator pool and a
> gradient-driven growth budget.

### Value types

**`PauliLabel`** helpers:
- `.to_qrack_int()` follows the Q# convention: `I=0, X=1, Z=2, Y=3` (Z and Y are swapped; never hardcode)
- `.to_qiskit_c_bit_term()`: Qiskit C bit-packed encoding

**`ComplexNumber`**: JSON-safe `{re: float, im: float}` avoiding pydantic's `"1+2j"` encoding.  
Properties: `.value` → Python `complex`. Class method: `.from_complex(c)`.

---

## `circuit`

### `ParameterBinding`

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Parameter name matching a `CircuitSpec.parameters` entry |
| `value` | `float` | Bound value |

### `CircuitSpec`

| Field | Type | Default | Description |
|---|---|---|---|
| `computing_model` | `ComputingModel` | `GATE_BASED` | Paradigm: gate-based, MBQC, GBS, etc. |
| `qubit_modality` | `QubitModality \| None` | `None` | QPU modality, if fixed (e.g. `PHOTONIC` for LOQC/FBQC circuits) |
| `num_qubits` | `int` | n/a | Circuit width |
| `num_classical_bits` | `int \| None` | `None` | Classical register width |
| `format` | `CircuitFormat` | `QASM2` | Source format of `serialized` |
| `serialized` | `str \| None` | `None` | Circuit source string or file path |
| `observables` | `list[SparsePauliObservable]` | `[]` | Estimator-path observables |
| `precision` | `float` | `0.01` | Target precision for shot-count estimation |
| `parameters` | `list[str]` | `[]` | Named variational parameters |
| `parameter_bindings` | `list[ParameterBinding]` | `[]` | Bound parameter values |
| `gate_counts` | `dict[str, int]` | `{}` | Gate-name → count (populated after transpilation) |
| `measurement_pattern` | `dict \| None` | `None` | MBQC measurement pattern, a vendor-neutral dict; pass e.g. a `johnrscott_mbqc_fpga.MBQCPattern` (auto-dumped), rehydrate with `MBQCPattern.model_validate(...)` |
| `photonic_circuit` | `dict \| None` | `None` | Photonic / fusion-based circuit, a vendor-neutral dict; pass e.g. a `mqsdk_photoq.PhotonicCircuitSpec` (auto-dumped) |

**Methods:**

| Method | Returns | Description |
|---|---|---|
| `.from_openqasm3(source, *, num_qubits)` | `CircuitSpec` | Construct with `format=QASM3` |
| `.openqasm3` | `str \| None` | Source string if format is QASM3, else `None` |
| `.openqasm2` | `str \| None` | Source string if format is QASM2, else `None` |
| `.is_parametric()` | `bool` | `True` if `parameters` is non-empty |
| `.is_bound()` | `bool` | All parameters have bindings |
| `.bind(values)` | `CircuitSpec` | Return copy with parameter bindings applied |
| `.total_gates` | `int \| None` | Sum of `gate_counts` values (total gate count, not depth) |

---

## `observable`

### `Pauli(spec, coefficient=1.0, *, num_qubits=None)`

The short spelling is a module-level factory returning a `SparsePauliObservable`, so an observable fits inline in a `CircuitSpec`:

```python
Pauli("Z0 Z1")                      # ⟨ZZ⟩ on a two-qubit register
Pauli("X0", 0.5)                    # 0.5 · X₀
Pauli({"Z0": 0.39, "X0 X1": 0.18})  # a two-term Hamiltonian
Pauli("")                           # the identity term
```

Factors separate on spaces or commas (so both the Cebule `"X0 Y1"` and the comma-separated `"X0,Y1"` spellings parse), letter case is free, and factors are stored sorted by qubit index so operators that are equal compare equal. A qubit carrying two factors raises rather than picking a product order for you. `num_qubits` defaults to one past the highest index mentioned; pass it explicitly for a register wider than the observable touches.

Results compose with the usual operators, so a Hamiltonian reads like maths:

```python
H = -1.05 * Pauli("") + 0.39 * Pauli("Z0") - 0.39 * Pauli("Z1") + 0.18 * Pauli("X0 X1")
```

### `PauliTerm`

| Field | Type | Description |
|---|---|---|
| `qubit_indices` | `tuple[int, ...]` | Target qubit indices |
| `pauli_ops` | `tuple[PauliLabel, ...]` | Pauli operator per qubit |
| `coefficient` | `ComplexNumber` | Weight of this term |

Methods: `.to_qrack_arrays()`, `.to_qiskit_c_arrays()`

### `SparsePauliObservable`

| Field | Type | Description |
|---|---|---|
| `num_qubits` | `int` | Circuit width |
| `terms` | `list[PauliTerm]` | Sparse COO list of Pauli terms |

Class methods:
- `.from_cebule_operators(operators, coefficients, num_qubits)`: parse Cebule `"X0 Y1 Z3"` token format
- `.from_dense_matrix(matrix, num_qubits=None, *, atol=1e-10, max_qubits=8)`: dense → sparse Pauli decomposition (`coeff_P = Tr(P @ H) / 2**n`, keeps `|coeff| > atol`); verified against Qiskit `SparsePauliOp`

Methods:
- `.to_dense_matrix(*, real=True, atol=1e-10, max_qubits=10)`: sparse → dense `2**n × 2**n` Pauli tensor expansion; `real=True` (default) returns `list[list[float]]` for e.g. Cebule `QASMGenInput.operator` and raises if entries are complex; `real=False` returns complex entries
- `.simplify(*, atol=1e-12)`: merge terms with the same Paulis on the same qubits and drop those below `atol`

Arithmetic: `+`, `-`, unary `-`, and scalar `*` / `/` build new observables (`sum()` works too, as it starts from `0`). A sum takes the wider `num_qubits` and concatenates terms; like terms are **not** merged automatically, matching Qiskit's `SparsePauliOp`. Every expectation value is linear in the terms, so a duplicate costs a measurement but never changes the answer; call `.simplify()` to collapse them.

Both conversions are exponential by nature and guarded by `max_qubits`; raise it explicitly for larger observables only if you mean it.

---

## `backend`

### `QubitCharacteristics` / `GateCharacteristics`

Per-qubit and per-gate hardware noise properties (T1/T2, frequency, readout error, gate duration, error rate). All fields optional; simulators leave them `None`.

### `BackendSpec`

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | n/a | Unique backend identifier |
| `provider` | `str` | n/a | See table below |
| `computing_model` | `ComputingModel` | `GATE_BASED` | Paradigm this backend executes |
| `qubit_modality` | `QubitModality \| None` | `None` | QPU modality; `None` for abstract simulators |
| `num_qubits` | `int \| None` | `None` | |
| `simulator` | `bool` | `False` | |
| `native_gates` | `list[str]` | `[]` | |
| `max_shots` | `int \| None` | `None` | |
| `coupling_map` | `list[tuple[int, int]]` | `[]` | |
| `qubit_characteristics` | `list[QubitCharacteristics]` | `[]` | |
| `gate_characteristics` | `list[GateCharacteristics]` | `[]` | |
| `auth` | `dict[str, str]` | `{}` | Provider credentials (env-var references) |

**Convenience constructors:**

```python
# Gate-based simulators
BackendSpec.aer_statevector(num_qubits=None)          # Qiskit Aer statevector
BackendSpec.aer_qasm(num_qubits=None)                 # Qiskit Aer QASM (100k shots max)
BackendSpec.qrack(num_qubits=None, *, gpu=True)       # PyQrack GPU/CPU
BackendSpec.cudaq(target="nvidia", num_qubits=None)   # CUDA-Q (GSOpt default)
BackendSpec.lightning_qubit(num_qubits=None)          # PennyLane (Cebule default)

# Gate-based hardware
BackendSpec.ibm(backend_name, *, instance, channel, token_ref)
BackendSpec.quantinuum(device_name="H2-1E", *, num_qubits=None, user_ref="")  # Quantinuum H-Series (trapped-ion)
BackendSpec.qibo_simulator(backend="numpy", num_qubits=None)   # local Qibo simulator
BackendSpec.qibolab(platform, *, num_qubits=None)              # self-hosted QPU (Qibolab)
BackendSpec.qibo_cloud(platform="sim", *, client="qibo-client", token_ref="")  # remote QPU (qibo-cloud-backends)

# MBQC
BackendSpec.mbqc_fpga(num_logical_qubits, *, fpga_family="xilinx_7series")

# Cebule cloud
BackendSpec.cebule(*, email_ref="", password_ref="")

# Photonic (linear-optics / FBQC)
BackendSpec.photochipsim(num_modes=6)                 # permanent-based simulator
BackendSpec.strawberry_fields(backend="fock", num_modes=6, cutoff_dim=5)
BackendSpec.perceval(backend="SLOS", num_modes=6)     # Quandela Perceval
BackendSpec.photonic_chip_hardware(chip_id, platform, num_modes)

# GBS (Gaussian Boson Sampling)
BackendSpec.xanadu_x8(num_modes=8)                   # Xanadu X8 hardware (PNR)
BackendSpec.xanadu_borealis(via_braket=False)         # Borealis TDM, 216 modes
BackendSpec.strawberry_fields_gaussian(num_modes)     # SF Gaussian state simulator

# QPE / QDK chemistry
BackendSpec.qdk_chemistry_simulator(executor="qdk_sparse_state_simulator", num_qubits=None)
BackendSpec.azure_quantum(target, *, resource_id_ref="", location_ref="")

# QESEM (Qedma)
BackendSpec.qesem(backend_name, *, api_token_ref="", via_qiskit_function=False)

# KQD / QSE
BackendSpec.qiskit_aer(method="statevector", num_qubits=None)
```

---

## `execution`

### `ZNEConfig`

| Field | Default | Description |
|---|---|---|
| `noise_factors` | `(1.0, 3.0, 5.0)` | Gate-folding scale factors |
| `extrapolator` | `"linear"` | `"linear"` · `"poly2"` · `"richardson"` |

### `TranspilerConfig`

| Field | Default | Description |
|---|---|---|
| `layout_method` | `None` | `"trivial"` · `"dense"` · `"sabre"` |
| `routing_method` | `None` | `"sabre"` · `"lookahead"` · `"stochastic"` |
| `approximation_degree` | `1.0` | Synthesis precision [0, 1] |
| `basis_gates` | `[]` | Override backend native gates |
| `initial_layout` | `[]` | Manual virtual → physical qubit mapping |

### `AlgorithmSpec`

> **Dedicated page:** [Algorithms & `AlgorithmSpec`](algorithm_spec.md) treats
> this topic in depth: identity vs. hyperparameters, the `AlgorithmFamily`
> dispatch model, how vanilla VQE differs from ADAPT-VQE, and how to add a new
> algorithm. The section here stays as the field-level quick reference.

Identity only; hyperparameters live in a family-specific config (see
below), not here. This mirrors the `QPUModality`/`error_mitigation.py`
split: each algorithm-library's fields live in that library's own schema
module (`dlr_excitation_solve.ExcitationSolveConfig`,
`mqsdk_xenakis.GAConfig`/`GenomeConfig`, `mqsdk_cebule.TNQCOptInput`,
`microsoft_qdk.QPEConfig`, `evangelistalab_qforte.QForteAlgorithmConfig`),
not duplicated in a shared grab-bag struct.

| Field | Default | Description |
|---|---|---|
| `name` | n/a | `"ADAPTVQE"` · `"UCCNVQE"` · `"TN_QC_OPT"` · …; library-specific label |
| `family` | `None` | `AlgorithmFamily`: package-agnostic identity; set to compare runs of "the same algorithm" across different implementing adapters |
| `extra_params` | `{}` | Escape hatch for adapter-specific kwargs not covered by a typed config |

**Current cross-adapter coverage**: `family` only pays off once ≥2
adapters accept the same shared config for it. Today:

| `AlgorithmFamily` | Implementations | Shared config |
|---|---|---|
| `ADAPT_VQE` | 3: `evangelistalab_qforte`, `ibm_qiskit_adapt_vqe`, `microsoft_qdk_adapt_vqe` | `AdaptVQERunConfig` (below); the only family with a real "switch the adapter, keep the config" story today |
| `VQE` | 1 real adapter: `evangelistalab_qforte` (UCCNVQE, a UCC ansatz choice); the `dlr_excitation_solve` Fourier-series optimizer is also a choice under this family | `VQERunConfig` (below): the package-agnostic contract; per-adapter extras remain in `QForteAlgorithmConfig` / `ExcitationSolveConfig` |
| `UCC_PQE` / `SPQE` | 1: `evangelistalab_qforte` only | `QForteAlgorithmConfig` |
| `QAOA` | 0: no `AlgorithmAdapter` yet; runs as a plain optimization loop (see [`vqa`](vqa.md#running-qaoa)) | `QAOARunConfig` (below): the package-agnostic contract an adapter or loop reads |
| `TN_QC_OPT` | 1: `mqsdk_cebule` only | `TNQCOptInput` |
| `GA_CIRCUIT_SEARCH` | 1: `mqsdk_xenakis` only | `GAConfig`/`GenomeConfig` |
| `QPE` | 0: schema/metadata only, no `AlgorithmAdapter` | `microsoft_qdk.QPEConfig`, a field of the QDK chemistry pipeline record, never dispatched through `BenchmarkRunner` |

The single-implementation families, `QAOA`, and `QPE` still carry a
`family` tag, not because a comparison is possible today, but so a
*second* implementation (e.g. a native-VQE `AlgorithmAdapter`, a QAOA
adapter, or a hardware QPE run) has a name to converge on instead of
inventing its own ad hoc label.
`GA_CIRCUIT_SEARCH`'s only real head-to-head comparison today is against
Classiq's synthesis (a different `AlgorithmFamily`-less strategy, see
`classiq_classiq.CircuitOptimizationComparison`), not against another
`GA_CIRCUIT_SEARCH` implementation.

### `VQERunConfig`

Package-agnostic hyperparameter contract for `AlgorithmFamily.VQE`, the
fixed-ansatz case. Set on `ExecutionOptions.vqe_run_config`. The ansatz is
chosen up front and never grows, so unlike `AdaptVQERunConfig` there is no
operator pool and no gradient-driven macro loop: this config names the ansatz,
its depth, the classical optimizer, and how the starting parameters are made.
A UCC ansatz (QForte's UCCNVQE) and a Fourier-series parameter fit
(`dlr_excitation_solve`) are both choices *under* this family, recorded in
`ansatz` / `optimizer`.

| Field | Default | Description |
|---|---|---|
| `ansatz` | `"UCCSD"` | Circuit family to build: `"UCCSD"` · `"EfficientSU2"` · `"TwoLocal"` · `"HEA"` · … ; each adapter maps it onto its own constructor |
| `layers` | `1` | Ansatz repetition depth (Qiskit's `reps`); `1` for ansätze with no repeating block |
| `optimizer` | `"BFGS"` | Classical optimizer name; each adapter maps it onto its own set |
| `max_iterations` | `200` | Classical-optimizer step cap |
| `energy_threshold` | `1e-5` | Optimizer convergence threshold on the energy |
| `initialization` | `"zeros"` | Starting-parameter strategy: `"zeros"` · `"random"` · `"hf"` (Hartree-Fock reference) · `"custom"` |
| `initial_parameters` | `[]` | Explicit starting vector; read when `initialization="custom"` |
| `init_scale` | `1e-2` | Std-dev of the random draw when `initialization="random"` |
| `use_analytic_gradient` | `True` | Analytic gradient (parameter-shift) vs finite-difference |

> No `seed` field: `ExecutionOptions.seed` already governs the random draw.
> And not to be confused with `bestquark_gsopt.GSOptVQERunConfig`, which is a
> *record* of one GSOpt benchmark run's parameterisation rather than a contract;
> see [`bestquark_gsopt`](#bestquark_gsopt).

### `AdaptVQERunConfig`

> **How does this relate to `VQAConfig`?** They are two objects at two layers.
> [`VQAConfig`](#record) (on `BenchmarkRecord.vqa`) is *experiment metadata*:
> it labels what you ran (`molecule`, `basis`, `ansatz`, `optimizer`,
> `algorithm`, …), has `extra="forbid"`, and changes nothing about execution;
> it is the single config that describes a VQA run and will grow to cover QAOA.
> `AdaptVQERunConfig` (here, on `ExecutionOptions.adapt_vqe_run_config`, next to
> `ZNEConfig`/`TranspilerConfig`) is the *runtime hyperparameter contract* an
> adapter reads to drive the adaptive loop. It is a separate class rather than a
> `VQAConfig` field for two reasons: it belongs on the "how to execute" layer,
> not on record metadata; and it is a package-agnostic contract shared unchanged
> by all three ADAPT-VQE adapters, which keeps per-family knobs out of
> `VQAConfig` so it doesn't balloon as QAOA/ADAPT/etc. are added. See
> [Algorithms & `AlgorithmSpec`](algorithm_spec.md) for the full rationale.

Package-agnostic hyperparameter contract for `AlgorithmFamily.ADAPT_VQE`,
shared by every ADAPT-VQE-family adapter (`evangelistalab_qforte`,
`ibm_qiskit_adapt_vqe`, `microsoft_qdk_adapt_vqe`). Set on
`ExecutionOptions.adapt_vqe_run_config`.

| Field | Default | Description |
|---|---|---|
| `pool_type` | `"SD"` | Operator pool: `"SD"` · `"GSD"` · `"SDTQ"` · `"sa_SD"` |
| `optimizer` | `"BFGS"` | Classical optimizer name; each adapter maps this onto its own supported set |
| `gradient_threshold` | `1e-2` | Macro-iteration stop: ‖gradient‖ below this ends ansatz growth |
| `energy_threshold` | `1e-5` | Micro-optimizer (parameter fit) convergence threshold |
| `max_macro_iterations` | `20` | Operator-pool growth steps / ansatz depth cap |
| `max_micro_iterations` | `200` | Optimizer steps per macro-iteration |
| `use_analytic_gradient` | `True` | Analytic gradient vs finite-difference (QForte has analytic; the `generic_adapt_vqe` engine used by `ibm_qiskit_adapt_vqe`/`microsoft_qdk_adapt_vqe` always uses finite differences; see its README) |

### `QAOARunConfig`

Package-agnostic hyperparameter contract for `AlgorithmFamily.QAOA`. Same
layering as `AdaptVQERunConfig`: it is the *runtime* contract (on
`ExecutionOptions.qaoa_run_config`), while experiment metadata, including
`algorithm="QAOA"` and the optimization `problem_type`, lives in
[`VQAConfig`](#record). QAOA's ansatz is *fixed-structure* (p alternating
cost/mixer layers with 2·p angles), so unlike ADAPT-VQE there is no operator
pool or gradient-driven growth; the config just picks p, the mixer, and the
classical optimizer. No `AlgorithmAdapter` implements it yet; it drives a
plain optimization loop today (see [`vqa`](vqa.md#running-qaoa)).

| Field | Default | Description |
|---|---|---|
| `reps` | `1` | p, the number of cost+mixer layers; ansatz carries 2·p angles (γ, β) |
| `mixer` | `"x"` | Mixer Hamiltonian: `"x"` (transverse field, standard) · `"xy"` (ring/parity-preserving) · `"grover"` |
| `optimizer` | `"COBYLA"` | Classical optimizer name; each adapter/loop maps it onto its own set |
| `max_iterations` | `100` | Classical-optimizer step cap |
| `initialization` | `"ramp"` | Starting-angle strategy: `"zeros"` · `"random"` · `"ramp"` (TQA-style linear schedule) |
| `alpha_cvar` | `1.0` | CVaR tail fraction; `1.0` = plain expectation, `<1.0` optimizes the best-α quantile of sampled bitstrings |

### `ExecutionOptions` QESEM fields

| Field | Default | Description |
|---|---|---|
| `mitigation_options` | `{}` | Vendor-neutral dict for strategy-specific options (e.g. QESEM: build with `qedma_qesem.qesem_mitigation_options()`) |
| `qesem_job_options` | `None` | Job-level QESEM options (`QESEMJobOptions`) |

### `ExecutionOptions`

| Field | Default | Description |
|---|---|---|
| `shots` | `None` | `None` = statevector; integer = shot sampling |
| `optimization_level` | `1` | Transpiler tier 0–3 |
| `error_mitigation` | `NONE` | `ErrorMitigationStrategy` |
| `zne_config` | auto | Auto-populated when `error_mitigation=ZNE` |
| `seed` | `None` | RNG seed |
| `timeout_s` | `None` | Execution timeout |
| `memory` | `False` | Return per-shot bitstrings in `ShotResult.memory` |
| `rep_delay_s` | `None` | Repetition delay (hardware) |
| `init_qubits` | `True` | Reset qubits before each shot |
| `transpiler` | `TranspilerConfig()` | Routing / layout / synthesis options |
| `algorithm_spec` | `None` | Which algorithm to run (`name` + `AlgorithmFamily`) |
| `adapt_vqe_run_config` | `None` | Package-agnostic hyperparameters for `AlgorithmFamily.ADAPT_VQE` |
| `qaoa_run_config` | `None` | Package-agnostic hyperparameters for `AlgorithmFamily.QAOA` |
| `cluster_depth` | `None` | MBQC: measurement rounds |
| `adaptive_corrections` | `True` | MBQC: apply byproduct corrections |

---

## `result`

### `ExpectationResult`

| Field | Description |
|---|---|
| `observable_index` | Index into `CircuitSpec.observables` |
| `value` | Expectation value |
| `std_error` | Statistical standard error from shot noise |
| `num_shots` | Number of shots used |
| `raw_values` | Per-ZNE noise-factor values before extrapolation |

### `ShotResult`

| Field | Description |
|---|---|
| `num_qubits` | Circuit width |
| `num_shots` | Total shots |
| `counts` | `{bitstring: count}`, MSB-first (Qiskit convention) |
| `memory` | Per-shot bitstrings when `ExecutionOptions.memory=True` |

Methods: `.probabilities()`, `.most_probable()`, `.marginal(qubits)`

### `FidelityResult`

| Field | Description |
|---|---|
| `fidelity` | Fidelity value [0, 1] |
| `metric` | `UNITARY` (Qrack) · `FUBINI_STUDY` (MBQC-FPGA) · `TRACE` · `PROCESS` |
| `reference_label` | Optional label for the reference state |

### `AdaptIteration`

Per-macro-iteration record from ADAPT-VQE:

| Field | Description |
|---|---|
| `iteration` | Macro-iteration index |
| `energy` | Energy at this iteration |
| `grad_norm` | Gradient norm (convergence criterion) |
| `n_operators` | Operators in the ansatz at this point |
| `n_cnot` | CNOT count |
| `n_classical_params` | Number of variational parameters |

### `TranspileLayout`

Mirrors Qiskit C `QkTranspileLayout`:

| Field | Description |
|---|---|
| `num_virtual` | Number of virtual qubits |
| `num_physical` | Number of physical qubits |
| `initial_layout` | Placement-stage virtual → physical mapping |
| `final_layout` | Combined initial + SWAP-routing permutation |
| `output_permutation` | SWAP-induced rearrangement only |

### `QuantumResult`

Top-level result container. Populate only the fields relevant to the run.

| Field | Type | Description |
|---|---|---|
| `computing_model` | `ComputingModel` | |
| `qubit_modality` | `QubitModality \| None` | |
| `expectation_values` | `list[ExpectationResult] \| None` | Estimator path (VQE, QAOA) |
| `shots` | `ShotResult \| None` | Sampler path |
| `fidelity` | `FidelityResult \| None` | State / process fidelity |
| `mbqc_rounds` | `list[MBQCRoundResult] \| None` | Per-round MBQC data |
| `adapt_history` | `list[AdaptIteration] \| None` | ADAPT-VQE history |
| `quasi_probabilities` | `dict[str, float] \| None` | PEC / TREX mitigated probabilities |
| `transpile_layout` | `TranspileLayout \| None` | |
| `transpiled_circuit` | `str \| None` | Circuit after transpilation |
| `transpiled_circuit_format` | `CircuitFormat \| None` | Format of `transpiled_circuit` |
| `status` | `JobStatus` | `SUCCEEDED` · `FAILED` · … |
| `job_id` | `str \| None` | Provider-assigned job ID |
| `qpu_time_s` | `float \| None` | Time on QPU only |
| `total_time_s` | `float \| None` | Total wall time |
| `wall_seconds` | `float \| None` | Actual wall time (GSOpt convention) |
| `wall_budget_seconds` | `float \| None` | Allowed budget (GSOpt) |
| `error_message` | `str \| None` | Error detail on failure |
| `metadata` | `dict` | Adapter-specific extras |
| `vendor_results` | `dict[str, Any]` | Vendor result records, keyed by stable name; keeps the core vendor-free |

Property: `.openqasm3_transpiled` returns `transpiled_circuit` if the format is QASM3.

**`vendor_results`** carries vendor-specific result records as plain dicts;
Pydantic models passed as values are dumped automatically, and readers
rehydrate with the vendor schema:

```python
result = QuantumResult(..., vendor_results={"qforte_result": run_result})
rr = QForteRunResult.model_validate(result.vendor_results["qforte_result"])
```

Established keys (each carries the vendor schema of the same name):
`photonic_simulation`, `photonic_vqe`, `photonic_sensitivity`, `hom_result`,
`indist_purification`, `photonic_analog_sim`, `gbs_sampling`,
`gbs_clique_finding`, `tdm_gbs`,
`click_pattern_probability`, `method_comparison`, `pt_series_sampling`,
`qcloud_job` (mqsdk_photoq) ·
`qpe_result`, `qchem_pipeline` (microsoft_qdk) · `kqd_pipeline` (mqsdk_qse) ·
`qesem_result` (qedma_qesem) · `qcschema_record` (molssi_qcschema) ·
`ahs_result` (quera_bloqade) · `slowquant_record` (erikkjellgren_slowquant) ·
`qforte_result` (evangelistalab_qforte) · `fire_opal_result`, `mitiq_result`,
`haiqu_result`, `parity_qc_result`, `qmatter_result` (error-mitigation
vendors) · `ibm_runtime_record` (ibm_runtime_v2)

---

## `record`

### `VQAConfig`

VQE / VQA experiment **inputs**: what the user chose to run. Computed
outputs live in `VQAResult`; they are produced by the run, never supplied
by the user.

| Field | Description |
|---|---|
| `problem_type` | `"chemistry"` · `"optimization"` · `"ml"` |
| `molecule` | Molecule name (e.g., `"H2"`, `"BH"`) |
| `basis` | Basis set (e.g., `"sto-3g"`) |
| `num_electrons` | Total electron count |
| `num_alpha` / `num_beta` | Spin-up / spin-down electrons |
| `active_electrons` | Electrons in active space |
| `active_orbitals` | Orbitals in active space |
| `algorithm` | Algorithm name |
| `pool_type` | Operator pool for UCC variants |
| `mapper` | Fermion → qubit mapping: `"Parity"` · `"JordanWigner"` · `"BravyiKitaev"` · `"MQS"` |
| `ansatz` | Ansatz name |
| `optimizer` | Classical optimizer name |
| `n_layers_network` | Cebule TN depth |
| `n_layers_circuit` | Cebule / GSOpt circuit layer count |
| `ga_run_id` | Links to `GARunResult.run_id` (Xenakis) |
| `genome_hash` | Stable hash of evolved genome |
| `classiq_synthesis_id` | Links to `ClassiqSynthesisResult.program_id` |
| `vendor_data` | Vendor-keyed extension dict for vendor-only metadata |

### `VQAResult`

Computed **outputs** of a VQE / VQA run. Algorithm adapters return one from
`run_algorithm()`; for estimator-path circuit runs the runner derives
`final_eigenvalue` from `QuantumResult.expectation_values` automatically.

| Field | Description |
|---|---|
| `final_eigenvalue` | Converged variational energy |
| `ground_truth` | Computed exact reference (FCI / exact diagonalisation) |
| `hf_energy` | Hartree-Fock reference energy |
| `fci_energy` | Full CI energy (ground-truth fallback) |
| `num_parameters` | Variational parameters in final ansatz |
| `n_cnot` | CNOT count in final circuit |
| `n_pauli_trm_measures` | Total Pauli measurements |
| `nfev` | Total function evaluations |
| `convergence_values` | Energy per optimizer iteration |
| `convergence_parameters` | Parameter vector per iteration |
| `adapt_maxiter_reached` | ADAPT hit `adapt_maxiter` without converging |
| `best_complexity` | Xenakis ad-hoc complexity score |

Properties: `.reference_energy` (ground_truth, falling back to fci_energy),
`.energy_error`, `.chemical_accuracy` (True if error < 1.6 mHartree)

### `BenchmarkRecord`

One complete benchmark execution.

| Field | Description |
|---|---|
| `schema_version` | Current `SCHEMA_VERSION` (auto-stamped; see the README badge) |
| `experiment_id` | UUID (auto-generated) |
| `run_id` | Groups records belonging to the same sweep |
| `timestamp` | UTC timestamp |
| `circuit` | `CircuitSpec` |
| `backend` | `BackendSpec` |
| `options` | `ExecutionOptions` |
| `result` | `QuantumResult` |
| `vqa` | `VQAConfig \| None`, experiment inputs |
| `vqa_result` | `VQAResult \| None`, computed outputs |
| `num_qubits` | Circuit width |
| `circuit_depth` | Transpiled depth |
| `ga_run_id` | Links to a `GARunResult` (Xenakis) |
| `tags` | `list[str]` |
| `notes` | Free text |

Class method: `.from_vqe(*, circuit, backend, options, result, vqa, vqa_result, …)`

---

## `reactions`

Not a framework-core type; it bridges three real external tools rather than
being a shape qpubench invented outright: **Cantera** (reaction-kinetics
data format), **PennyLane**'s chemical-reactions demo (quantum PES →
classical rate constant), and **Cebule SDK**'s `RXN_OPT`/catalyst-design
tasks (`mqsdk_cebule.py`, a complementary, network-level concept, not
merged into this module). See the module docstring for the full rationale
and the real Cantera gotchas found while verifying it (default `quantity`
unit is `kmol` not `mol`; three-body/falloff reactions need an explicit
third-body marker in the `equation` string itself).

### `ReactionCoordinateSpec` / `ReactionPathResult`

Ties a sweep of point calculations (bond dissociation, reaction path, PES)
together as one object. `BenchmarkRunner.sweep()` alone returns a flat
`list[BenchmarkRecord]`; this module adds the missing "which coordinate,
what order, which points are reactant/product/TS" structure around it.
No chemistry or curve-fitting; build `problems` with whatever pipeline you
like (a raw `CircuitSpec` per geometry, a qubit Hamiltonian via
`integrations/generic_adapt_vqe`, a QForte molecule JSON, ...).

**`ReactionCoordinateSpec`**

| Field | Description |
|---|---|
| `label` | Human-readable name, e.g. `"N-Cl bond dissociation"` |
| `coordinate_name` | What varies, e.g. `"bond_length_angstrom"` |
| `coordinate_values` | Ordered scalar values, one per point |
| `problems` | One `CircuitSpec` per point, same order/length as `coordinate_values` |
| `reactant_index` / `product_index` / `transition_state_index` | Optional indices into `coordinate_values` marking reaction endpoints / barrier |

Validated: `len(problems) == len(coordinate_values)`; any set index is in range.

**`ReactionPathResult`**

| Field | Description |
|---|---|
| `spec` | The `ReactionCoordinateSpec` that was run |
| `records` | One `BenchmarkRecord` per point, same order as `spec.coordinate_values` |

Properties: `.energies` (per point: `vqa_result.final_eigenvalue`, falling back to
the first expectation value, Hartree), `.barrier_height`, `.reaction_energy`,
`.to_dict_for_plot()` → `{coordinate_name: values, "energy": energies}`.

Methods bridging to classical kinetics (PennyLane-demo construction):
`.rate_constant(temperature_k, prefactor_hz=1e13)` → Arrhenius
`k = A exp(-Ea/RT)` computed directly from `barrier_height`;
`.to_arrhenius_rate_constant(prefactor_hz=1e13)` → the same barrier packaged
as an `ArrheniusRateConstant` (Ea converted Hartree → J/mol) ready to drop
into a `KineticsReactionSpec.rate_constant`.

### Cantera-style kinetics: `ArrheniusRateConstant` / `KineticsSpeciesSpec` / `KineticsReactionSpec` / `ReactionMechanism`

Real, Cantera-loadable shapes: `ReactionMechanism.to_cantera_yaml()`
produces text `cantera.Solution(yaml=...)` evaluates rate constants from
directly (verified in this repo's own sandbox against `cantera==3.2.0`,
all three `ReactionType` values: elementary, three-body, falloff). No
thermo (NASA7) or transport data modeled; Cantera evaluates reaction rate
constants without them; only whole-phase thermodynamic/equilibrium
calculations need that data, out of scope for this "schema, not solver"
package.

| Type | Key fields |
|---|---|
| `ArrheniusRateConstant` | `A`, `b` (default 0.0), `Ea` (J/mol); `.rate_at(T)` computes `A·T^b·exp(-Ea/RT)`, `.to_cantera_dict()` → Cantera's `rate-constant` mapping |
| `ReactionType` | `ELEMENTARY` (default) / `THREE_BODY` / `FALLOFF` |
| `KineticsSpeciesSpec` | `name`, `composition` (element → count), `charge` |
| `KineticsReactionSpec` | `equation`, `type`, `rate_constant`, `low_p_rate_constant` (FALLOFF only), `efficiencies`, `reversible` |
| `ReactionMechanism` | `phase_name`, `thermo_model`, `kinetics_model`, `species`, `reactions`; `.to_cantera_yaml()` for a loadable mechanism file |

`pip install "qpubench[cantera]"` for `pyyaml` (deferred import inside
`to_cantera_yaml()`; this module has no hard dependency beyond pydantic,
same as every other schema module). Installing the real `cantera` package
is only needed to *run* the exported mechanism, not to build it.

---

## `johnrscott_mbqc_fpga`

Full documentation → [Compute architectures: FPGAs for MBQC](compute_architectures.md#fpgas-real-time-control-for-mbqc)

Key types: `MBQCPattern`, `MBQCRound`, `MBQCProgramWord`, `ByproductUpdateSpec`, `AdaptiveSpec`, `CommutationSpec`, `MBQCExecutionResult`, `MBQCQubitState`.

---

## `mqsdk_cebule`

Full documentation → [docs/integrations/cebule.md](integrations/cebule.md)

Revised 2026-07-08 against the real SDK source
(`gitlab.com/mqsdk/python-sdk`'s `mqsdk/core/cebule.py` `TaskType` enum).
Every row below is confirmed against that source except `MOL_MAP`/
`QASM_GEN`, kept but flagged unconfirmed; see the linked doc for detail.

The `TN_QC_OPT` models were revised again 2026-08-08 against the TN-VQE
implementation itself (cebule-tn_vqe @ dev-kba `a760489`) rather than the
docs page. **`TNQCOptResult.qubit_operators` was removed** — the task
returns one `h_tn_opt_qubit` 2-tuple of (labels, coefficients), never two
parallel keys — under the mirror exception in `AGENTS.md`. Also:
`h_tn_opt_fermionic` added; `tn_ansatz` / `n_shots` / `opt_options` added
as inputs; `three_para_tn` deprecated; and the `backend`, `conv_tol` and
`n_layers_circuit` defaults corrected.

Revised again 2026-08-11: **`TNQCOptInput.phi_init` is now
`list[float] | None`, defaulting to `None`** rather than `list[float] =
[]`. `None` is upstream's "unset" sentinel — `run_TNQCOpt` randomises
(`2*pi*random`) only when `phi_init is None` — so the old default was
neither the documented random init nor a valid vector: an empty list
reaches the shape check as a length-0 array against a `phi_shape` of
`(3n(R+1),)`. Callers that want a pinned initialisation now pass one
explicitly. `backend`'s inline suggestion was corrected in the same pass:
`get_backend` routes only the four named simulators, `fake*` and `ibm*`
to Qiskit, so `"qiskit.aer"` selected the *PennyLane* path — use
`aer_simulator` locally and `ibm*` for hardware.

Revised again 2026-08-24, against cebule-tn_vqe @ **main** `07dacfb` —
the earlier passes cited `dev-kba a760489`, now an ancestor of main, and
main has since gained a `mapped_hamiltonian` module.

- **`TNQCOptInput.mapping_matrix` added.** MOL_MAP's mapping operator D,
  now accepted back by TN_QC_OPT (upstream `1c0ba84` / `8259dce`). It was
  modelled only as `MolMapResult.mapping_matrix`, so the mirror described
  both ends of the hand-off but not the hand-off. Supplying it *with*
  `tn_ansatz="givens"` makes the run an orbital rotation on the reduced
  register, and that changes four things at once: θ is sized by the **spatial
  orbitals** rather than the register, as a network of nearest-neighbour
  Givens gates over them (`tn_theta_shape(..., n_spatial=m)`; depth still
  matters, since roughly `m/2` layers span the rotation group), U†HU comes
  from an exterior power rather than the integral route, `grouped` is
  served the dense operator instead of Pauli terms, and `network` mode
  takes a different optimizer. The new `TNQCOptInput.rotates_orbitals`
  property carries that condition so callers need not re-derive it.
- **`TNQCOptInput.n_layers_network` is now optional, default 1**
  (upstream `b0085c9`); it was declared required.
- **`TNQCOptInput.theta_init` defaults to `None`, not `[]`** — the same
  "unset" sentinel correction `phi_init` got on 2026-08-11, for the same
  reason: an empty list reaches the shape check as a length-0 array.
- **`TNQCOptResult.h_tn_opt_fermionic` removed.** Upstream withdrew the
  output (`f5ab81e` / `cdaf59e`, "Stop computing the fermionic
  Hamiltonian nobody reads"). The 2026-08-08 revision had added it
  against an unfinished upstream rather than a settled contract, and no
  qpubench run has recorded the field, so the append-only rule has no
  stored records to protect and the field is deleted outright rather
  than deprecated. `from_task_result` drops the key if an older payload
  still carries it; `tests/test_schemas.py` pins that behaviour.
- Not enforced here, but new upstream and worth knowing: `n_iterations`
  is now **rejected** for COBYLA when below `varied + 2`, counting only
  the parameters the chosen `optimization_mode` varies
  (`_check_iteration_budget`, `e44d32a`). `opt_options["maxiter"]` wins
  over `n_iterations` in that check.

| Type | Cebule task | Description |
|---|---|---|
| `MolecularGeometry` | shared | Flat geometry + symbols + basis |
| `CebuleTaskEnvelope` | shared | `max_processors` / `connected_task_id` / `connected_model_id` / `connected_dataset_id`, common to every task below |
| `MolMapInput` / `MolMapResult` | `MOL_MAP` *(unconfirmed)* | Molecular → qubit Hamiltonian mapping |
| `QASMGenInput` / `QASMGenResult` | `QASM_GEN` *(unconfirmed)* | Hamiltonian → OpenQASM measurement circuits |
| `TNQCOptInput` / `TNQCOptResult` | `TN_QC_OPT` | Tensor-network + quantum circuit VQE |
| `TNAnsatz` / `TNAnsatzProperties` | `TN_QC_OPT` | The four M-gate rotation families and their params/node, entangling and number-conserving flags |
| `COVOInput` / `COVOResult` | `COVO` | Correlation-optimised virtual orbitals |
| `CosmoInput` / `CosmoResult` | `COSMO` | Continuum solvation (dielectric + VDW radii) |
| `SigmaInput` / `SigmaResult` | `SIGMA` | COSMO-SAC/-RS sigma profile, chained from `COSMO` |
| `SolubilityInput` / `SolubilityResult` | `SOLUBILITY` | Solubility from one or more `SIGMA` profiles |
| `AbInitioMDInput` / `AbInitioMDResult` | `BORN_OPPENHEIMER_MD`, `CAR_PARRINELLO_MD` | Quantum-ESPRESSO-backed ab initio MD (periodic-capable); raw QE input text, not kwargs |
| `ForceFieldMDInput` / `ForceFieldMDResult` | `FORCE_FIELD_MD` | Classical MD (mixture/solvent box) |
| `GeometryOptInput` / `GeometryOptResult` | `GEOMETRY_OPT` | Force-field + semi-empirical geometry optimisation |
| `PeriodicGeometryOptInput` / `PeriodicGeometryOptResult` | `PERIODIC_GEOMETRY_OPT` | Geometry optimisation under periodic boundary conditions (fields inferred, no usage example found) |
| `GroupContributionInput` / `GroupContributionResult` | `GROUP_CONTRIBUTION` | Group-contribution property estimation, batchable over mixtures |
| `AtomOrderInput` / `AtomOrderResult` | `ATOM_ORDER` | Canonical atom ordering for a SMILES (+ optional geometry) |
| `ActivityCoefficientInput` / `ActivityCoefficientResult` | `ACTIVITY_COEFFICIENT` | Enum-confirmed only; no fields modeled beyond the envelope |
| `GNNDatasetCreateInput/Result`, `GNNDatasetExtendInput`, `GNNDatasetGetInput`, `GNNDatasetDeleteInput`, `GNNTrainInput/Result`, `GNNPredictInput/Result`, `GNNMoleculeChunk` | `GNN_DATASET_*`, `GNN_TRAIN`, `GNN_PREDICT` | Property-prediction GNN dataset/model lifecycle |

---

## `mqsdk_xenakis`

Full documentation → [docs/integrations/xenakis.md](integrations/xenakis.md)

| Type | Source | Description |
|---|---|---|
| `LayerGenome` | qarchga | Structured layer genome; `from_struct()` / `to_circuit_spec()` |
| `BitstringGenome` | Xenakis (original) | Binary string genome; data holder only |
| `QNEATGenome` | Xenakis+qNEAT | NEAT innovation-numbered genome; `to_circuit_spec()` |
| `GAConfig` / `GenomeConfig` | all | GA hyperparameters matching `config_snapshot.yaml` |
| `XenakisMolecule` | all | Molecule spec with `coordinates_angstrom` tuples |
| `XenakisRunConfig` | all | Full run configuration snapshot |
| `GAGenerationRecord` | all | Per-generation stats (covers `history.csv` + `GenRecord`) |
| `GARunResult` | all | Complete GA run; `best_circuit_spec()` |

---

## `dlr_excitation_solve`

Full documentation → [docs/integrations/excitation_solve.md](integrations/excitation_solve.md)

Tracks the upstream [`excitationsolve`](https://github.com/dlr-wf/ExcitationSolve)
release (Comms. Physics 2025, doi:10.1038/s42005-025-02375-9), including the
Haas et al. 2026 follow-up ([arXiv:2602.10776](https://arxiv.org/abs/2602.10776))
on operator-selection and warm-start strategies; see the fields below.

| Type | Description |
|---|---|
| `ExcitationSolveConfig` | `maxiter`, `tol`, `num_samples`, `hf_energy`, `mode`, `parameter_occ` (upstream ordering hint), `warm_start_double_excitations` (`optimal_theta` HF warm start) |
| `ExcitationSolveMode` | `ONE_D` · `TWO_D` · `ADAPT` |
| `ParameterSample` | One `(parameter_variation, energy_sample)` probe |
| `ExcitationSolveSweep` | 5+ probes → Fourier coefficients → optimal parameter |
| `ExcitationSolveIteration` | One sweep round: energy, nfev, parameters |
| `ExcitationSolveResult` | Full output; `to_quantum_result()`, `convergence_values()` |
| `AdaptVQEStep` | One ADAPT macro-step: `prior_cost`, `max_gradient`, `selected_operator`, `optimal_theta` (analytic HF warm-start value, if used) |
| `ExcitationAdaptResult` | Full ADAPT run; `operator_selection` (Haas et al. 2026 strategy label), `grad_norm_history()`, `to_quantum_result()` |

---

## `bestquark_gsopt`

Full documentation → [docs/integrations/gsopt.md](integrations/gsopt.md)

| Type | Description |
|---|---|
| `REFERENCE_ENERGIES` | FCI/CCSD(T) energies for BH, LiH, BeH2, H2O, N2 |
| `reference_energy(molecule)` | Lookup helper with case-insensitive aliases |
| `GSOptBenchmarkLane` | `VQE` · `TN` · `DMRG` · `AFQMC` · `GIBBS` |
| `VQEAnsatzType` | `HEA_RY_RING` · `HEA_RYRZ_RING` · `UCCSD` · `CUSTOM` |
| `VQEOptimizerType` | `COBYLA` · `POWELL` · `NELDER_MEAD` |
| `ActiveSpaceSpec` | `active_electrons`, `active_orbitals`, orbital index arrays |
| `GSOptRunConfig` | Base for every lane's `config` sub-object; `name` is the one field all five lanes share |
| `GSOptVQERunConfig` | `vqe` lane (CUDA-Q circuits): `ansatz`, `layers`, `optimizer`, `max_steps`, `init_scale`, `seed`, optimizer-specific tolerances |
| `GSOptTNRunConfig` | `tn` + `dmrg` lanes (MPS sweeping): `bond_schedule`, `cutoff`, `solver_tol`, `max_sweeps`, `init_bond_dim`, `init_seed`; TN-only `method`, `init_state`, `tau`, `chi`, `local_eig_ncv` |
| `GSOptAFQMCRunConfig` | `afqmc` lane (PySCF + ipie): SCF trial stage (`trial`, `scf_conv_tol`, `diis_space`, `chol_cut`, …) + walker propagation (`num_walkers_per_rank`, `num_blocks`, `timestep`, …) |
| `GSOptGibbsRunConfig` | `gibbs` lane (MCMC thermal sampling): `length`, `beta`, `coupling`, `field`, `num_chains`, `burn_in_sweeps`, `sample_sweeps`, `thinning`, `seed` |
| `GSOptLaneRunConfig` | Union of the above, most-specific-first; the type of `GSOptBenchmarkResult.config` |
| `GSOptBenchmarkResult` | Full benchmark JSON; `to_quantum_result()`, `to_vqa_config()` (VQE lane only; raises `TypeError` otherwise) |
| `GSOptBenchmarkMeta` | `.gsopt.json` metadata file format |

> **GSOpt is method-agnostic.** VQE is one of its five lanes, alongside tensor
> networks, DMRG, AFQMC and Gibbs sampling, several of which are neither
> quantum nor variational. So each lane mirrors its own source script's
> `RunConfig` dataclass instead of everything being bent into a VQE shape.
> None of these is a cross-implementation contract; for that see
> [`VQERunConfig`](#vqerunconfig) and friends in [`execution`](#execution).
>
> `GSOptBenchmarkResult` currently models the **molecular** lanes' result shape
> (`molecule`, `cas`, `hf_energy` are required, which fits VQE and AFQMC). The
> spin-model lanes report `model` / `nsites` / `energy_per_site` /
> `entropy_midchain`, or a distribution distance for Gibbs, and are not
> modelled yet; the config layer is lane-complete ahead of the result layer.

---

## `mqsdk_photoq`

Full documentation → [docs/integrations/photonic.md](integrations/photonic.md) · [docs/integrations/gbs.md](integrations/gbs.md)

The MQSdk **photoq** module for photonic quantum computing. Covers three photonic paradigms and their backends:

- **Linear-optics chips + FBQC**: `ComputingModel.GATE_BASED` (permanent-based LOQC) / `ComputingModel.FUSION_BASED`.
- **Gaussian Boson Sampling**: `ComputingModel.GBS` (hafnian-based, covariance-matrix formalism).
- **Pseudo-PNRD (click-counting) methods**: the four simulation methods of the photoq paper for GBS read out by multiplexed on/off detectors.

Qubit modality: `QubitModality.PHOTONIC` throughout.

### A. Linear-optics photonic chips + FBQC

### Enums

| Enum | Values |
|---|---|
| `PhotonSourceType` | `ideal`, `thermal`, `spdc`, `quantum_dot`, `nv_center` |
| `PICPlatform` | `silicon_nitride`, `silicon_on_insulator`, `indium_phosphide`, `lithium_niobate` |
| `PhotonicChipArchitecture` | `mzi_mesh`, `rectangular_mesh`, `triangular_mesh`, `diamond_mesh` |
| `FusionType` | `type_I`, `type_II` |
| `ResourceStateType` | `linear_4_photon`, `star`, `ghz`, `tree`, `raussendorf_lattice` |

### Circuit building blocks

| Type | Description |
|---|---|
| `BeamsplitterSpec` | `mode_a`, `mode_b`, `theta`, `phi`; standard 2-mode BS |
| `MZISpec` | `mode_a`, `mode_b`, `phi_inner`, `phi_outer`; Mach-Zehnder interferometer |
| `PhaseShifterSpec` | `mode`, `phi` |
| `FusionGateSpec` | `mode_a`, `mode_b`, `fusion_type`, `success_probability` |

### Core state types

| Type | Description |
|---|---|
| `FockState` | `mode_occupations` list; properties: `num_photons`, `num_modes` |
| `FockAmplitude` | `state: FockState`, `amplitude: ComplexNumber` |
| `SinglePhotonSourceSpec` | `platform`, `indistinguishability`, `brightness`, `g2`, `wavelength_nm` |

### Circuit and simulation

| Type | Description |
|---|---|
| `PICSpec` | `platform`, `num_modes`, `depth`, architecture |
| `PhotonicCircuitSpec` | Full circuit: beamsplitters, MZIs, phase shifters, fusions, input/output Fock states |
| `PhotonicSimulationResult` | `output_state_amplitudes`, `permanent`, `sampling_time_s` |
| `PhotonicSensitivityAnalysis` | Sobol indices (`S1`, `ST`) from parameter sweeps |

### Photonic VQE

| Type | Description |
|---|---|
| `PhotonicVQEConfig` | `num_modes`, `num_photons`, `max_iterations`, `optimizer`, `target_unitary` |
| `PhotonicVQEStep` | One iteration: `iteration`, `energy`, `parameters` |
| `PhotonicVQEResult` | Full VQE run: steps, `final_energy`, `converged`, `final_parameters` |

### HOM and indistinguishability

| Type | Description |
|---|---|
| `HOMSpec` | `source_a`, `source_b`, `beamsplitter`; Hong-Ou-Mandel setup |
| `HOMResult` | `coincidence_rate`, `visibility`, `dip_depth`, `integration_time_s` |
| `IndistinguishabilityPurificationSpec` | `input_sources`, `purification_rounds`, `target_indistinguishability` |
| `IndistinguishabilityPurificationResult` | `achieved_indistinguishability`, `loss_db`, `success_probability` |

### FBQC (Fusion-Based QC)

| Type | Description |
|---|---|
| `ResourceStateSpec` | `state_type`, `num_photons`, `generation_circuit` |
| `FBQCRunConfig` | `resource_state`, `fusion_network`, `logical_qubits`, `num_rounds`, `noise_model` |

### Analog Hamiltonian simulation

| Type | Description |
|---|---|
| `PhotonicAnalogHamiltonian` | Tight-binding Hamiltonian: coupling matrix + on-site energies |
| `PhotonicAnalogSimConfig` | `hamiltonian`, `evolution_time`, `num_modes`, `initial_fock_state` |
| `PhotonicAnalogSimResult` | `time_evolved_state`, `site_populations`, `energy_expectation` |

Result entries in `QuantumResult.vendor_results`: `photonic_simulation`, `photonic_vqe`, `photonic_sensitivity`, `hom_result`, `indist_purification`, `photonic_analog_sim`

---

## `microsoft_qdk`

Full documentation → [docs/integrations/qdk_chemistry.md](integrations/qdk_chemistry.md)

Mirrors the Microsoft QDK's quantum-chemistry functionality. The QDK is a general package; this module models its chemistry pipeline stage by stage (SCF, orbital localization, active-space selection, Hamiltonian construction, state preparation, QPE, resource estimation), and each stage is an independent model, so you can record any subset of the pipeline, not only full QPE runs.

Computing model: `ComputingModel.GATE_BASED` (QPE is one of the algorithms the pipeline can run, see `QPEMethod`; the ADAPT-VQE adapter in `integrations/microsoft_qdk_adapt_vqe/` is another QDK-flavored consumer of these schemas)

### Pipeline overview

`MoleculeStructureSpec` → `SCFRunConfig` / `SCFResult` → `OrbitalLocalizationResult` → `ActiveSpaceSelectionResult` → `SCIWavefunctionSpec` → `FermionicHamiltonianSpec` → `QubitHamiltonianSpec` → `StatePrepConfig` / `StatePrepCircuitResult` → `QPEConfig` / `QPEResult` → `ResourceEstimatorConfig` / `ResourceEstimationResult`

All stages captured in `QChemPipelineSpec`.

### Enums

| Enum | Values |
|---|---|
| `CoordinateUnit` | `angstrom`, `bohr` |
| `SCFMethod` | `rhf`, `uhf`, `rohf`, `dft_b3lyp`, `dft_pbe` |
| `OrbitalLocalizerType` | `mp2_no`, `qdk_valence`, `pyscf_avas`, `qdk_autocas`, `qdk_autocas_eos`, `qdk_occupation` |
| `ActiveSpaceSelectorType` | `mp2_no`, `qdk_valence`, `pyscf_avas`, `qdk_autocas`, `qdk_autocas_eos`, `qdk_occupation` |
| `StatePrepMethod` | `sparse_isometry_gf2x`, `qiskit_regular_isometry` |
| `QPEMethod` | `standard`, `iterative` |
| `TimeEvolutionBuilderType` | `suzuki_trotter`, `qdrift`, `partially_randomized` |
| `QubitParamsType` | `GATE_US_E3`, `GATE_US_E4`, `GATE_NS_E3`, `GATE_NS_E4`, `MAJ_NS_E4`, `MAJ_NS_E6` |
| `QECScheme` | `surface_code`, `floquet_code` |
| `QubitEncodingType` | `jordan_wigner`, `bravyi_kitaev`, `parity` |
| `ModelHamiltonianType` | `ising`, `heisenberg`, `hubbard`, `huckel`, `ppp` |
| `LatticeTopology` | `chain`, `ring`, `patch`, `torus` |
| `MCCalculatorType` | `macis`, `asci`, `fci` |

### Key types

| Type | Description |
|---|---|
| `AtomSpec` | `symbol`, `x`, `y`, `z` (coordinates in chosen units) |
| `MoleculeStructureSpec` | `atoms`, `charge`, `spin_multiplicity`, `units`, `name` |
| `SCFRunConfig` | `method`, `basis`, `convergence_threshold`, `max_iterations` |
| `SCFResult` | `hf_energy`, `num_electrons`, `num_alpha`, `num_beta`, `num_orbitals`, `orbital_energies` |
| `OrbitalLocalizationConfig` / `OrbitalLocalizationResult` | Localizer type + orbital entanglement entropies |
| `OrbitalEntanglementEntropies` | `s1_entropies` (single-orbital), `mutual_information` (flattened) |
| `ActiveSpaceSelectionConfig` / `ActiveSpaceSelectionResult` | Selector type + `active_electrons`, `active_orbitals`, `orbital_indices` |
| `SCIWavefunctionSpec` | Selected-CI: `determinants`, `coefficients`, `selected_ci_energy`, `mc_calculator_type` |
| `FermionicHamiltonianSpec` | `num_orbitals`, `num_electrons`, `core_energy`, `one_body_integrals`, `two_body_integrals`, `schatten_norm` |
| `QubitHamiltonianSpec` | `encoding`, `num_qubits`, `num_pauli_terms`, `pauli_terms` (`PauliStringTerm` list) |
| `StatePrepConfig` / `StatePrepCircuitResult` | Method + `circuit_qasm`, `num_cnots`, `circuit_depth` |
| `QPEConfig` | `method`, `evolution_time`, `num_bits`, `shots_per_bit`, `qft_do_swaps`, `time_evolution` |
| `QPEResult` | `raw_energy`, `bitstring_msb_first`, `alias_branches`, `error_mha`, `iteration_circuits` |
| `TimeEvolutionConfig` | `builder_type`, `trotter_order`, `num_steps`, `dt` |
| `TrotterConfig` | `order`, `num_steps`, `dt` |
| `QDriftConfig` | `num_samples`, `evolution_time`, `seed` |
| `ResourceEstimatorConfig` | `qubit_params`, `qec_scheme`, `error_budget` |
| `ErrorBudgetPartition` | `logical_error`, `rotation_synthesis`, `t_state_distillation` |
| `ResourceEstimationResult` | `num_physical_qubits`, `runtime_s`, `t_gate_count`, `logical_qubits`, `code_distance` |
| `QuantumErrorProfile` | `gate_error_1q`, `gate_error_2q`, `readout_error`, `t1_s`, `t2_s` |
| `DepolarizingNoiseSpec` / `PauliNoiseSpec` | Per-gate noise models |

### Model Hamiltonians

| Type | Parameters |
|---|---|
| `IsingParams` | `J`, `h` (transverse-field Ising) |
| `HeisenbergParams` | `Jx`, `Jy`, `Jz`, `h` (XXX/XXZ/XYZ) |
| `HubbardParams` | `t` (hopping), `U` (on-site) |
| `HuckelParams` | `t` (tight-binding hopping), `t_prime` (NNN hopping) |
| `PPPParams` | `t`, `U` (Ohno potential), `V_ij` (long-range Coulomb) |
| `LatticeGraphSpec` | `topology`, `num_sites`, `dimensions` |
| `ModelHamiltonianSpec` | Union wrapper: exactly one params block + `LatticeGraphSpec` |

`QChemPipelineSpec` is stored in `QuantumResult.vendor_results["qchem_pipeline"]`.

---

## `mqsdk_photoq`: B. Gaussian Boson Sampling, pseudo-PNRD methods & backends

Continuation of the [`mqsdk_photoq`](#mqsdk_photoq) module (the LOQC/FBQC types are documented above). `ComputingModel.GBS`, `QubitModality.PHOTONIC`.

**Key distinction from the LOQC section:** LOQC = permanent-based / MZI chips / Fock states; GBS = hafnian-based / Gaussian states (covariance-matrix formalism).

### GBS enums

| Enum | Values |
|---|---|
| `GBSBackendType` | `gaussian_simulator`, `fock_simulator`, `xanadu_x8`, `xanadu_borealis`, `aws_braket_borealis`, `orca_pt_series`, `dtu_qcloud` |
| `GBSMeasurementType` | `fock` (PNR), `threshold` (click), `pseudo_pnr` (click-counting), `homodyne`, `heterodyne` |
| `QuadratureOrdering` | `xp_blocks` (SF default), `interleaved` (DTU-GBS convention) |
| `GaussianStateType` | `vacuum`, `coherent`, `squeezed`, `two_mode_squeezed`, `thermal`, `cluster_1d`, `cluster_2d` |
| `TDMSqueezingLevel` | `low`, `medium`, `high` (Borealis presets) |
| `GraphScalingMethod` | `none`, `divide_by_max`, `normalise`, `laplacian_b` (Kaur method) |

### Gaussian state

| Type | Description |
|---|---|
| `GaussianStateSpec` | `num_modes`, `mean_vector` (2n), `covariance_matrix` (2n×2n flattened), `quadrature_ordering` |
| `HafnianMatrixSpec` | `A_real`/`A_imag` (2n×2n flattened); σ_q-derived A matrix |

### GBS circuit building blocks

| Type | Description |
|---|---|
| `SqueezingGateSpec` | `mode_index`, `r`, `phi`; single-mode Sgate |
| `S2GateSpec` | `mode_a`, `mode_b`, `r`, `phi`; two-mode S2gate (EPR pair) |
| `RotationGateSpec` | `mode_index`, `phi` |
| `InterferometerSpec` | `mode_indices`, `unitary_real`/`imag`, `source` |
| `HomodyneMeasurementSpec` | `mode_index`, `phi`, `outcome`; continuous-variable measurement |
| `TakagiDecompositionSpec` | `singular_values`, `unitary_real`/`imag`, `num_modes` (from `sf.decompositions.takagi`) |

### Direct GBS sampling

| Type | Description |
|---|---|
| `GBSProgramSpec` | `num_modes`, `squeezing_params`, `s2_gates`, `rotation_gates`, `interferometer`, `measurement_type` |
| `GBSSample` | `photon_numbers`, `click_pattern`, `homodyne_outcomes`; properties: `total_photons`, `num_clicks` |
| `GBSSamplingConfig` | Sampling hyperparameters |
| `GBSSamplingResult` | `config`, `samples`, `mean_photon_number`, `sampling_time_s` |

### Hafnian

| Type | Description |
|---|---|
| `HafnianComputationSpec` | `B_real`/`B_imag` (flattened), `output_pattern` |
| `HafnianResult` | `hafnian: ComplexNumber`, `probability`, `method` ("thewalrus") |

### Graph GBS (clique finding)

| Type | Description |
|---|---|
| `GBSGraphConfig` | `adjacency_matrix` (flattened n×n), `num_nodes`, `num_photons`, `num_samples`, `scaling_method` |
| `GBSCliqueFindingResult` | `raw_samples`, `shrunk_cliques`, `searched_cliques`, `mean_density`, `mean/max/min_clique_size` |

### TDM GBS / Borealis

| Type | Description |
|---|---|
| `TDMDelaySpec` | `delays` [1,6,36], `effective_modes` (216 for Borealis) |
| `TDMGBSConfig` | `delays`, `squeezing_level`, `num_shots`, `crop`, `device_arn` |
| `TDMGBSResult` | `samples` (shots × modes), `num_modes_effective`, `mean_photon_per_mode` |

### CV cluster states

| Type | Description |
|---|---|
| `ClusterStateSpec` | `state_type`, `num_nodes`, `squeezing_r`, `measurement_angles`, `boundary_condition` |

### C. Pseudo-PNRD (click-counting) detectors & the four simulation methods

For GBS devices read out by *pseudo photon-number-resolving detectors*, a mode demultiplexed across `N` on/off (click) detectors that report the number `k` of branches that clicked. From the photoq paper *"Classical simulation of Gaussian boson sampling with click-counting detectors"*.

| Enum | Values |
|---|---|
| `SimulationMethod` | `kensingtonian_formula` (i), `hafnian_modified` (ii), `tensor_network_mps` (iii), `brute_force_povm` (iv), `thermal_povm` |
| `DistributionDistanceMetric` | `total_variation`, `kl_divergence`, `bhattacharyya`, `fidelity` |

| Type | Description |
|---|---|
| `PseudoPNRDSpec` | `num_branches` (N), `multiplexing`, `detector_efficiency`; `collision_error(n)` helper |
| `ClickPatternProbabilityResult` | `method`, `click_patterns`, `probabilities`, `total_probability`, `fock_cutoff` |
| `KensingtonianResult` | `click_pattern`, `value: ComplexNumber`, `probability` (method i matrix function) |
| `MPSSimulationConfig` | `physical_dimension` (d), `bond_dimension` (χ), `truncation_fidelity` (f_t), `dd` |
| `MethodComparison` | per-method `computation_time_s`, `total_variation_distance`, `kl_divergence`, `fidelity` (Figs. 5–11) |

### D. Photonic backends

| Type | Description |
|---|---|
| `TimeBinInterferometerSpec` | ORCA PT Series TBI: `num_modes`, `num_loops`, `beamsplitter_angles`, `squeezing`, `input_type` |
| `PTSeriesSamplingConfig` / `PTSeriesSamplingResult` | PT-1/PT-2 sampling (simulated or hardware); GBS / Fock / distinguishable inputs |
| `QCloudJobType` | `tn-covariance`, `tn-sampling`, `redpitaya` (DTU QCloud REST API v1) |
| `TNCovarianceParams` / `TNSamplingParams` | Typed payloads for the two QCloud GBS job shapes |
| `QCloudJobSpec` / `QCloudJobResult` | Submitted job + status/result (covariance matrix or samples) |
| `AuroraExperiment` / `AuroraDatasetSpec` | Xanadu Aurora dataset slice (`cluster_state` / `decoder_demo`), S3 key pinning |

Backend factory methods: `BackendSpec.orca_pt_series(...)`, `BackendSpec.dtu_qcloud(...)`, `BackendSpec.xanadu_aurora(...)` (plus the existing `xanadu_x8`, `xanadu_borealis`, `strawberry_fields_gaussian`).

Result entries in `QuantumResult.vendor_results`: `photonic_simulation`, `photonic_vqe`, `photonic_sensitivity`, `hom_result`, `indist_purification`, `photonic_analog_sim`, `gbs_sampling`, `gbs_clique_finding`, `tdm_gbs`, `click_pattern_probability`, `method_comparison`, `pt_series_sampling`, `qcloud_job`.

---

## `mqsdk_qse`

Full documentation → [docs/integrations/qse.md](integrations/qse.md)

Computing model: `ComputingModel.GATE_BASED` (KQD is an algorithmic technique on top of gate-based circuits; see `KQDMethod`)

Three algorithm families from MQSdk/qse:
1. **KQD via Hadamard test**: modified Hadamard test circuits measure ⟨ψ_{I,m}|O|ψ_{J,n}⟩; assembles S and H subspace matrices; regularized generalized eigensolver.
2. **Sample-based KQD (SKQD/SQD)**: Krylov circuits measured in Fock basis; bitstrings post-selected by particle number; subspace projected via qiskit-addon-sqd.
3. **Multi-reference variants**: d_refs reference states each seed their own Krylov series.

### Enums

| Enum | Values |
|---|---|
| `KQDMethod` | `hadamard_test`, `sample_based_sqd`, `multi_ref_hadamard`, `multi_ref_sqd` |
| `KQDReferenceStateType` | `neel`, `slater_det`, `computational`, `entangled` |
| `KrylovTimeEvolutionVariant` | `lie_trotter`, `efficient_alternating` |
| `EigensolverMethod` | `scipy_eigh`, `scipy_eigsh`, `numpy_eigvalsh` |

### Reference states

| Type | Description |
|---|---|
| `NeelStateSpec` | `num_spins`, `shift` (0→1010…, 1→0101…) for antiferromagnetic spin chains |
| `SlaterDeterminantRef` | `ncas`, `occ_alpha`, `occ_beta`: JW encoding; properties: `num_qubits`, `bitstring`, `num_electrons` |
| `KQDReferenceSpec` | `state_type`, `bitstring`, optional `neel`/`slater_det`, `label` |

### Time evolution

| Type | Description |
|---|---|
| `KQDTimeEvolutionSpec` | `dt`, `num_trotter_steps`, `variant`; property `dt_circ = dt / num_trotter_steps`; dt ≈ π/‖H‖₂ |

### Krylov circuit family

| Type | Description |
|---|---|
| `KrylovCircuitFamilySpec` | `method`, `num_qubits_system`, `krylov_dim`, `num_references`, `circuit_labels`, `shots_per_circuit`, `ancilla_qubits` |

### Subspace matrices (Hadamard test path)

| Type | Description |
|---|---|
| `KrylovMatrixSpec` | `label` ("S"/"H"), `dim`, `matrix_real`/`matrix_imag` (flattened dim×dim) |
| `KrylovSubspaceMatrices` | `S_matrix`, `H_matrix`, `assembly_method` ("hadamard_test") |
| `HadamardTestObservableSpec` | `matrix_type`, `pauli_string`, `coeff`, `quadrature` ("real"/"imag") |
| `HadamardTestIterationResult` | `circuit_label`, `observable_index`, `real_part`, `imag_part` |

### Regularized eigenvalue solve

| Type | Description |
|---|---|
| `RegularizationConfig` | `threshold` (ε=1e-6), `num_eigenvalues_k`, `solver` |
| `KrylovEigenResult` | `eigenvalues`, `ground_state_energy`, `S_eigenvalues`, `num_eigenvalues_discarded`, `krylov_dim_effective` |

### SQD path (sample-based)

| Type | Description |
|---|---|
| `SQDPostselectionConfig` | `num_ones` (particle number), `min_unique` |
| `SQDStep` | `krylov_step`, `num_bitstrings`, `subspace_dim`, `energy_hartree` |
| `SQDConvergenceResult` | `steps`, `final_energy`, `exact_energy`; property `error_mha` (milli-Hartree) |
| `KrylovBitstringCounts` | `krylov_step`, `reference_index`, `counts` dict; property `num_unique_bitstrings` |
| `CumulativeKrylovCounts` | Pooled counts across steps; `postselection`, `raw_counts_per_circuit` |

### Cholesky decomposition

| Type | Description |
|---|---|
| `CholeskyDecompositionSpec` | `num_orbitals`, `eps`, `n_chol`, `max_cholesky`, `accuracy`; low-rank two-electron integral representation |

### Pipeline

| Type | Description |
|---|---|
| `KQDConfig` | `method`, `krylov_dim`, `num_references`, `dt`, `num_trotter_steps`, `shots_per_circuit`, `regularization` |
| `KQDPipelineSpec` | Full pipeline: `num_qubits`, `hamiltonian_label`, `kqd_config`, `time_evolution`, `reference_states`, `circuit_family`, `krylov_matrices`, `hadamard_results`, `eigen_result`, `cumulative_counts`, `sqd_result`, `exact_energy`, `hf_energy`, `cholesky_spec` |

`KQDPipelineSpec` is stored in `QuantumResult.vendor_results["kqd_pipeline"]`.

---

## `qedma_qesem`

Full documentation → [docs/integrations/qesem.md](integrations/qesem.md)

Computing model: `ComputingModel.GATE_BASED` with `ErrorMitigationStrategy.QESEM`. Qubit modality: `QubitModality.SUPERCONDUCTING` (wraps IBM hardware)

QESEM (Qedma) wraps IBM gate-based hardware with noise-aware transpilation, device characterization, and quasi-probabilistic error tuning (QET). It runs circuits at multiple noise scale factors then extrapolates to an unbiased zero-noise estimate with a statistical error bar.

### Enums

| Enum | Values |
|---|---|
| `QESEMTranspilationLevel` | `minimal`, `minimal_with_layout_opt`, `standard` |
| `QESEMExecutionMode` | `session` (QPU reserved), `batch` (QPU released, default) |
| `QESEMPrecisionMode` | `JOB` (aggregate precision), `CIRCUIT` (per-instance precision) |
| `QESEMJobStatus` | `INITIALIZING` · `ESTIMATING` · `ESTIMATED` · `RUNNING` · `SUCCEEDED` · `FAILED` · `CANCELLED` |
| `QESEMCharacterizationStatus` | `RUNNING` · `SUCCEEDED` · `FAILED` · `CANCELLED` |

### Observable

| Type | Description |
|---|---|
| `QESEMObservableSpec` | `pauli_terms: dict[str, float]` + `description`; Qedma string dict format, e.g. `{"Z1": 1.0, "Z0,Z3": 0.3}` |

### Circuit and job options

| Type | Description |
|---|---|
| `QESEMCircuitOptions` | `error_suppression_only`, `twirl`, `transpilation_level`, `parallel_execution` |
| `QESEMJobOptions` | `execution_mode` (BATCH or SESSION) |
| `QESEMPrecisionPerFactor` | `scale_precision_map: dict[str, float]`; noise scale → precision target (for QET) |

### Job specification

| Type | Description |
|---|---|
| `QESEMJobSpec` | Full job config: `circuit_qasm`, `num_qubits`, `observables`, `precision`, `precision_per_factor`, `precision_mode`, `backend_name`, `circuit_options`, `parameterized_values`, `description` |

### Expectation value result types

| Type | Description |
|---|---|
| `QESEMExpectationValue` | `value`, `error_bar`; base EV with 1-σ uncertainty |
| `QESEMScaleExpectationValue` | Extends `QESEMExpectationValue` with `scale` (noise scale factor) |
| `QESEMHeuristicResult` | Extends `QESEMExpectationValue` with `extrapolation` method and `scale_factors` list |
| `QESEMNoiseScalingResult` | `scaling_method="QESEM"`, `results_per_scale`; properties: `scale_factors`, `zero_noise_result` |
| `QESEMObservableResult` | `unmitigated`, `noise_scaling`, `qesem_heuristic`; property `mitigated` (best available estimate) |
| `QESEMCircuitObservableResult` | `observable: QESEMObservableSpec`, `result: QESEMObservableResult` |
| `QESEMCircuitResult` | `parameter_index`, `observable_results`; properties: `mitigated_evs`, `mitigated_stds`, `noisy_evs` |

### Execution details

| Type | Description |
|---|---|
| `QESEMTranspiledCircuit` | `circuit_qasm`, `qubit_maps` (logical→physical per block), `num_measurement_bases` |
| `QESEMExecutionDetails` | `total_shots`, `mitigation_shots`, `gate_fidelities: dict[str, float]`, `transpiled_circuits` |
| `QESEMGateInfidelity` | `gate_name`, `qubits: tuple[int, ...]`, `infidelity`; from device characterization |

### Device characterization

| Type | Description |
|---|---|
| `QESEMCharacterizationResult` | `qpu_name`, `measurement_errors: dict[int, float]`, `gate_infidelities`, `qubit_map` |

### Job record

| Type | Description |
|---|---|
| `QESEMJobRecord` | Top-level container: `job_id`, `status`, `qpu_name`, `spec`, `precision_mode`, `execution_mode`, `analytical_qpu_time_s`, `empirical_qpu_time_s`, `total_execution_time_s`, `circuit_results`, `execution_details`, `characterization` |

`QESEMJobRecord` is stored in `QuantumResult.vendor_results["qesem_result"]`.  
QESEM options are carried in the vendor-neutral `ExecutionOptions.mitigation_options` dict; build the entries with `qesem_mitigation_options(circuit_options=..., job_options=...)` and rehydrate with `QESEMCircuitOptions.model_validate(...)` / `QESEMJobOptions.model_validate(...)`.

---

## `molssi_qcschema`

Full documentation → [docs/integrations/qcschema.md](integrations/qcschema.md)

Harmonizes qpubench with the [MolSSI QCSchema v2](https://github.com/MolSSI/QCSchema) standard, its Python reference implementation [QCElemental](https://github.com/MolSSI/QCElemental), and the [PennyLane qchem dataset](https://pennylane.ai/datasets/collection/qchem) format. Modality-agnostic: it applies to all chemistry problems regardless of QPU execution method.

### Molecule

| Type | Key fields |
|---|---|
| `QCProvenance` | `creator`, `version`, `routine`; source record for any data object |
| `QCMolecule` | `symbols: list[str]`, `geometry: list[float]` (3×nat, Bohr), `molecular_charge`, `molecular_multiplicity`, `connectivity`, `fragments`, `fragment_charges`, `fragment_multiplicities`, `fix_com`, `fix_orientation`; properties: `num_atoms`, `formula` |

### Method specification

| Type | Key fields |
|---|---|
| `QCDriver` | `ENERGY` · `GRADIENT` · `HESSIAN` · `PROPERTIES` |
| `QCModel` | `method: str` (e.g. `"hf"`, `"ccsd(t)"`), `basis: str | None` |

### Calculation properties

| Type | Key fields |
|---|---|
| `QCCalcInfo` | `nbasis`, `nmo`, `nalpha`, `nbeta`, `natom` |
| `QCEnergyComponents` | `nuclear_repulsion_energy`, `scf_one_electron_energy`, `scf_two_electron_energy`, `scf_xc_energy`, `mp2_correlation_energy`, `mp2_total_energy`, `ccsd_correlation_energy`, `ccsd_total_energy`, `ccsd_t_total_energy`, `ccsdt_total_energy`, `fci_total_energy` |
| `QCAtomicResultProperties` | `calcinfo`, `return_energy`, `energy_components`, `scf_dipole_moment`, `scf_quadrupole_moment`, `mp2_dipole_moment`, `ccsd_dipole_moment`, `return_gradient`, `return_hessian` |

### Wavefunction

| Type | Key fields |
|---|---|
| `QCWavefunctionData` | `basis_name`, `nao`, `nmo`; orbital coefficients (`scf_orbitals_a/b`), density matrices (`scf_density_a/b`), Fock matrices (`scf_fock_a/b`), eigenvalues, occupations, `overlap_matrix`, `core_hamiltonian_a/b`, `two_electron_integrals`; all as flat float lists |

### Atomic computation

| Type | Key fields |
|---|---|
| `QCAtomicInput` | `schema_name="qcschema_input"`, `molecule`, `driver`, `model`, `keywords`, `id` |
| `QCAtomicResult` | `schema_name="qcschema_output"`, `molecule`, `driver`, `model`, `return_result`, `properties`, `wavefunction`, `success`, `error_message`, `provenance` |

### Geometry optimization

| Type | Key fields |
|---|---|
| `QCOptimizationInput` | `input_specification: QCAtomicInput`, `initial_molecule`, `keywords` |
| `QCOptimizationResult` | `input_specification`, `initial_molecule`, `final_molecule`, `trajectory: list[QCAtomicResult]`, `energies: list[float]`, `success`; properties: `num_steps`, `converged_energy` |

### PennyLane dataset

| Type | Key fields |
|---|---|
| `PennyLaneMolDataset` | `molname`, `basis`, `bondlength`, `hf_energy`, `fci_energy`, `ccsd_energy`, `num_electrons`, `num_qubits`, `pauli_terms`, `dataset_tag`; property `correlation_energy` (FCI − HF) |

### Top-level record

| Type | Key fields |
|---|---|
| `QCSchemaRecord` | `atomic_result`, `optimization_result`, `pennylane_dataset`; property `reference_energy` (best available classical reference energy) |

`QCSchemaRecord` is stored in `QuantumResult.vendor_results["qcschema_record"]`.

---

## `quera_bloqade`

Full documentation → [docs/integrations/neutral_atom.md](integrations/neutral_atom.md)

Computing model: `ComputingModel.ADIABATIC`. Qubit modality: `QubitModality.NEUTRAL_ATOM`

Models the Analog Hamiltonian Simulation (AHS) paradigm for neutral Rydberg atom QPUs, harmonized with the [Bloqade SDK](https://github.com/QuEraComputing/bloqade) and QuEra's Aquila hardware (available via AWS Braket). Atoms are trapped at 2-D coordinates by optical tweezers; a global laser drive applies time-dependent Rabi oscillations (Ω) and detuning (Δ); measurement yields per-site ground/Rydberg bitstrings.

### Enums

| Enum | Values |
|---|---|
| `NeutralAtomCoupling` | `rydberg` (|g⟩↔|r⟩, primary AHS mode), `hyperfine` |
| `AHSWaveformType` | `constant`, `linear`, `piecewise_linear` (Rabi/detuning), `piecewise_constant` (phase), `poly`, `custom` |
| `SpatialModulationType` | `uniform` (global), `local` (per-site coefficients) |
| `AHSShotStatus` | `success`, `partial_success`, `failure` |
| `LatticeGeometryType` | `chain`, `square`, `honeycomb`, `kagome`, `triangular`, `rectangular`, `lieb`, `custom` |

### Geometry

| Type | Key fields |
|---|---|
| `AtomicSite` | `x`, `y`; 2-D position in µm |
| `AtomArrangement` | `sites: list[AtomicSite]`, `filling: list[int]` (1=atom, 0=empty; defaults all-filled), `lattice_type`, `lattice_spacing_um`; properties: `num_sites`, `num_filled_sites`, `fill_fraction` |

### Waveforms

| Type | Key fields |
|---|---|
| `AHSTimeSeries` | `times_us: list[float]`, `values: list[float]`: explicit discretized waveform; properties: `num_points`, `duration_us` |
| `AHSWaveform` | `waveform_type`, `duration_us`, `durations_us`, `values`: compact Bloqade builder format; property `total_duration_us` |

### Drive fields

| Type | Key fields |
|---|---|
| `AHSLocalDetuning` | `time_series: AHSTimeSeries`, `site_coefficients: list[float]` (h_k ∈ [0,1]); experimental per-site detuning |
| `AHSDrivingField` | `coupling`, `rabi_amplitude`, `rabi_phase`, `detuning` (all `AHSTimeSeries | None`), `spatial_modulation` |
| `AHSProgramSpec` | `atom_arrangement`, `driving_fields`, `local_detunings`, `total_duration_us`, `description`; properties: `num_qubits`, `coupling` |
| `AHSBatchSpec` | `variable_names`, `parameter_values` (parallel lists), `num_shots_per_batch`; property `batch_size` |

### Hardware

| Type | Key fields |
|---|---|
| `AquilaDeviceSpec` | `max_qubits=256`, `area_width_um=75.0`, `area_height_um=76.0`, `min_atom_spacing_um=4.0`, `rabi_max_rad_us=15.8`, `detuning_min/max_rad_us=±125.0`, `max_pulse_duration_us=4.0`, `time_resolution_us=0.001`, `c6_rad_us_um6=5.42e6`, `max_shots=1000`, `cost_per_shot_usd=0.01` |

### Results

| Type | Key fields |
|---|---|
| `AHSExecutionMetadata` | `task_id`, `device_id`, `status`, `created_at`, `ended_at`, `cost_usd` |
| `AHSShotResult` | `status`, `pre_sequence: list[int]` (1=atom present), `post_sequence: list[int]` (1=ground, 0=Rydberg); property `is_perfect_fill` |
| `AHSTaskResult` | `metadata`, `num_shots_requested`, `shot_results`; properties: `successful_shots`, `perfect_fill_shots`, `bitstrings`, `counts`, `rydberg_densities` |

`AHSTaskResult` is stored in `QuantumResult.vendor_results["ahs_result"]`.  
Backend factories: `BackendSpec.aquila()` (QuEra Aquila via AWS Braket) and `BackendSpec.bloqade_emulator()` (local CPU simulation).

---

## `erikkjellgren_slowquant`

Full documentation → [docs/integrations/slowquant.md](integrations/slowquant.md)

Computing model: `ComputingModel.GATE_BASED`

Models the complete SlowQuant quantum chemistry workflow: Hartree-Fock SCF → unitary coupled-cluster (UCC/fUCC/tUPS/QNP/SAUPS) wavefunction optimization → reduced density matrices → linear response theory for excitation energies and transition properties → Qiskit quantum circuit metadata for hybrid QPU execution.

### Enums

| Enum | Values |
|---|---|
| `UCCAnsatzType` | `ucc` (standard UCC), `fucc` (factorized UCC), `tups` (truncated UPS), `qnp` (qubit number parity), `saups` (state-averaged UPS) |
| `UCCExcitationLevel` | `S`, `SD`, `SDT`, `SDTQ`, `SDTQ5`, `SDTQ56`; cumulative excitation strings |
| `UCCOptimizationMethod` | `one_step` (θ only), `two_step` (alternating θ + κ orbital rotation), `rotosolve` (sequential single-parameter) |
| `UCCLinearResponseType` | `naive`, `projected`, `self_consistent`, `state_transfer` |

### Active space

| Type | Key fields |
|---|---|
| `UCCActiveSpaceConfig` | `num_active_electrons`, `num_active_orbitals`, `num_total_electrons`, `num_total_orbitals`, `frozen_core_orbitals`, `frozen_virtual_orbitals`, `include_orbital_optimization`; property `num_qubits` (= 2 × num_active_orbitals) |

### Wavefunction

| Type | Key fields |
|---|---|
| `UCCWavefunctionConfig` | `ansatz`, `excitations`, `active_space`, `num_states` (>1 for SAUPS), `spin_adapted`, `ansatz_options`; property `num_qubits` |

### Integrals

| Type | Key fields |
|---|---|
| `UCCIntegralData` | `basis_set`, `num_basis_functions`, `h_ao` (nao² core Hamiltonian, flat), `g_ao` (nao⁴ ERI, flat; omit if large), `overlap_ao` (nao² overlap) |

### SCF result

| Type | Key fields |
|---|---|
| `UCCSCFResult` | `hf_energy`, `nuclear_repulsion`, `num_iterations`, `converged`, `mo_energies`, `orbital_occupations`, `homo_index`; property `homo_lumo_gap` |

### Optimization

| Type | Key fields |
|---|---|
| `UCCIterationRecord` | `iteration`, `energy`, `gradient_norm`, `theta_norm` |
| `UCCOptimizationResult` | `method`, `num_iterations`, `converged`, `final_energy`, `theta` (circuit amplitude params), `kappa` (orbital rotation params), `iteration_history`, `gradient_norm_final`; properties: `num_theta_params`, `num_kappa_params` |

### Reduced density matrices

| Type | Key fields |
|---|---|
| `UCCRDMData` | `num_active_orbitals`, `rdm1` (nact² flat), `rdm2` (nact⁴ flat; omit if large), `has_rdm3`, `has_rdm4` |

### Linear response / excited states

| Type | Key fields |
|---|---|
| `UCCExcitedStateResult` | `state_index`, `excitation_energy_au`, `excitation_energy_ev` (auto-filled ×27.2114 if absent), `transition_dipole: list[float]` ([µx, µy, µz] a.u.), `oscillator_strength` |
| `UCCLinearResponseResult` | `response_type`, `excitation_level`, `num_states_computed`, `excited_states`; properties: `excitation_energies_au`, `excitation_energies_ev`, `oscillator_strengths` |

### Quantum circuit / measurement

| Type | Key fields |
|---|---|
| `UCCCircuitSpec` | `ansatz_type`, `excitation_level`, `num_qubits`, `num_parameters`, `gate_depth`, `cx_count`, `single_qubit_gates`, `qubit_encoding` (default `"jordan_wigner"`), `spin_adapted` |
| `UCCMeasurementConfig` | `num_cliques` (commuting measurement groups), `postselection_enabled`, `shots_per_evaluation`, `num_pauli_strings`, `error_mitigation` |

### Top-level record

| Type | Key fields |
|---|---|
| `SlowQuantRecord` | `molecule_name`, `basis_set`, `integral_data`, `scf_result`, `wavefunction_config`, `optimization_result`, `rdm_data`, `linear_response`, `circuit_spec`, `measurement_config`, `hf_energy`, `ucc_energy`, `extras`; properties: `correlation_energy` (ucc − hf), `num_qubits` |

`SlowQuantRecord` is stored in `QuantumResult.vendor_results["slowquant_record"]`.  
Backend factories: `BackendSpec.gate_based(...)` with any Qiskit-compatible provider.

---

## `evangelistalab_qforte`

Full documentation → [integrations/qforte/README.md](../integrations/qforte/README.md) · [Backends & adapters](backends.md)

Computing model: `ComputingModel.GATE_BASED`

`QForteAlgorithmConfig` wraps the package-agnostic `AdaptVQERunConfig`; the
experiment-metadata side (molecule, basis, `algorithm="ADAPTVQE"`/`"UCCNVQE"`,
etc.) still goes in `VQAConfig` (see [`record`](#record)), exactly as for any
other adapter: metadata in `VQAConfig`, runtime knobs in the config on
`ExecutionOptions`. See the [`AdaptVQERunConfig` note](#adaptvqerunconfig) for how the
two relate.

Two layers, both verified against the real [evangelistalab/qforte](https://github.com/evangelistalab/qforte) pybind11 source rather than assumed:

### pybind11 object layer (mirrors `src/qforte/bindings.cc`)

| Type | Mirrors | Key fields |
|---|---|---|
| `QForteGateSpec` | `Gate` | `gate_id`, `target`, `control`, `parameter` |
| `QForteCircuitSpec` | `Circuit` | `gates: list[QForteGateSpec]`, `is_pauli`, `num_cnots`; `.size` property |
| `QForteQubitOperatorTerm` | one `QubitOperator.terms()` entry | `coefficient: ComplexNumber`, `pauli_circuit: QForteCircuitSpec` |
| `QForteQubitOperatorSpec` | `QubitOperator` | `terms`, `num_qubits`; `.to_sparse_pauli_observable()` converts to the canonical cross-package `SparsePauliObservable` |
| `QForteQubitOpPoolSpec` | `QubitOpPool` | `operators`, `coeffs` |
| `QForteSqOpPoolSpec` | `SQOpPool` | `term_strings`, `coeffs` (fermionic, pre-Jordan-Wigner) |

### Algorithm layer (mirrors `abc/algorithm.py`, `abc/ansatz.py`, `ucc/adaptvqe.py`)

| Type | Key fields |
|---|---|
| `QForteAlgorithmConfig` | `base: AdaptVQERunConfig` (package-agnostic contract) + QForte-only extras: `use_cumulative_thresh`, `add_equiv_ops`, `qubit_excitations`, `compact_excitations`, `diis_max_dim`, `opt_ftol`, `noise_factor`; `.to_run_kwargs(algorithm_name)` translates to QForte's `run()` kwargs |
| `QForteRunResult` | `final_energy`, `hf_energy`, `n_qubits`, `converged`, `final_gradient_norm`, `selected_operators`, `amplitudes`, `n_cnot`, `n_classical_params`, `n_pauli_trm_measures`, `n_ham_measurements`, `n_commut_measurements`, `energies_history`, `grad_norms_history`, `n_cnot_history`, `n_classical_params_history`, `n_pauli_trm_measures_history`, `max_circuit_depth_repr`; field-to-real-attribute mapping documented on the class itself |

`QForteRunResult` is stored in `QuantumResult.vendor_results["qforte_result"]`. Previously these fields were read via bare `getattr()` in `integrations/qforte/converters.py` with no typed contract: several real attributes (`_tops`, `_tamps`, `_commutator_pool`, `_n_ham_measurements`, `_n_commut_measurements`, `_curr_grad_norm`) were silently dropped; all are now captured.

`AlgorithmFamily.ADAPT_VQE` has two more implementations that don't require QForte at all; see [Switching AlgorithmAdapter implementations](integrations.md#switching-algorithmadapter-implementations).

---

## `pyscf_pyscf`

Full documentation → [docs/integrations/pyscf.md](integrations/pyscf.md)

PySCF-backed embedding/periodic-boundary quantum chemistry. Molecule/cell/
mean-field/solvation types are verified directly against the real PySCF API
(`pip install 'qpubench[pyscf]'`, no compiler required); embedding types are
schema-only, same boundary as `erikkjellgren_slowquant`/`microsoft_qdk`
(PsiEmbed/libDMET are real but not on PyPI).

| Type | Verified against real PySCF | Purpose |
|---|---|---|
| `PySCFAtomSpec`, `PySCFMoleculeSpec` | Yes, energies match `gto.M()` exactly | Molecule spec |
| `PySCFCellSpec` | Yes, builds a real `pbc.gto.Cell()` | Periodic boundary conditions |
| `PySCFMeanFieldConfig`/`Result` | Yes (RHF and RKS/B3LYP both converge) | HF/DFT |
| `PySCFSolvationConfig`/`Result` | Yes, defaults match a real `PCM(mol)` instance | PCM/COSMO continuum solvation |
| `ProjectionEmbeddingConfig` | No, schema-only | Manby-Miller projection-based WF-in-DFT embedding (PsiEmbed) |
| `DMETConfig` | No, schema-only | Density Matrix Embedding Theory (libDMET + PennyLane) |
| `EmbeddedHamiltonianResult` | No, schema-only | Active-space integrals + core energy from either embedding method |
| `ERIBuilderConfig`/`Result` | Yes, RI/DF matches standard 4-center ERIs to 2e-5 Ha on H2O/cc-pVDZ | Choose standard 4-center vs resolution-of-identity ERIs (`mol.intor('int2e')` vs `mf.density_fit()`) |
| `OrbitalOptimizerConfig`/`Result`, `OrbitalOptimizerBasinHoppingConfig` | Yes, Newton (`mcscf.CASSCF`), Simple (kappa-rotation + `mcscf.CASCI`), and Basin-Hopping all verified to agree on H2/6-31G CAS(2e,2o) (Newton vs Basin-Hopping: 3e-9 Ha; Newton vs Simple: 6e-5 Ha) | Newton / Simple (kappa-rotation) / Basin-Hopping orbital optimization |

Added 2026-07-09: `ERIBuilderConfig`/`Result` and the orbital-optimizer
types back the "choose an electron-repulsion integral builder" and
"create an orbital optimizer" guides; both are real PySCF mechanisms, with no new
dependency. See `examples/guides/choose_integrals.py` and
`examples/guides/orbital_optimizer.py`.

## `polarizable_embedding`

Added 2026-07-08 to close the "Polarizable Embedding: The Frame" gap; no
qpubench schema existed for it at all before. Unlike `pyscf_pyscf.py`'s embedding
types, both real packages here (CPPE and PyFraME) are on PyPI and confirmed
installed and working, wired through `pyscf.solvent.PE`. Field names and
`to_potfile_string()`'s output format are verified against PySCF's own test
data (`pyscf/solvent/test/test_pol_embed.py`), and the whole pipeline
converges for real in this repo's own sandbox; see
`examples/demos/polarizable_embedding_frame.py`.

| Type | Verified against real CPPE/PySCF | Purpose |
|---|---|---|
| `PolarizableEmbeddingSite` | Yes, matches PySCF's own potfile test fixture exactly | One multipole + polarizability site |
| `PolarizableEmbeddingConfig` | Yes, `to_potfile_string()` output converges via `pyscf.solvent.PE` | Full potfile-equivalent environment |
| `PolarizableEmbeddingResult` | Yes | PE-embedded SCF energy + polarization energy |

## `optimizer_catalog`

Added 2026-07-08 to close the "Choose a Minimizer" / "Choose a Stopping
Criterion" gap; `AdaptVQERunConfig.optimizer` (`execution.py`) was free-text
with no catalogue/registry object alongside it. `MINIMIZER_CATALOG` /
`STOPPING_CRITERION_CATALOG` are lookup tables over the same
`AdaptVQERunConfig` fields `integrations/generic_adapt_vqe` already consumes,
not a new execution mechanism. See
`examples/guides/minimizer_and_stopping_criterion.py`.

| Type | Purpose |
|---|---|
| `MinimizerCatalogEntry` / `MINIMIZER_CATALOG` | 7 named `scipy.optimize.minimize` methods with gradient/stochastic metadata |
| `StoppingCriterionCatalogEntry` / `STOPPING_CRITERION_CATALOG` | 4 named criteria mapped to the `AdaptVQERunConfig` field each one configures |

## `hamiltonian_library`

Added 2026-07-08 to integrate real Hamiltonian sources: two external
repositories (PennyLane qchem datasets, pennylane.ai/datasets/collection/
qchem, and HamLib Chemistry, portal.nersc.gov/cfs/m888/dcamps/hamlib/
chemistry/) plus, added the same day, **ab initio construction from any
geometry** (`hamiltonian_sources/ab_initio.py`, PySCF + OpenFermion), as
real chemistry problem sources, not a new execution mechanism: all three
return a `SparsePauliObservable` directly usable by any existing
`AlgorithmAdapter`/`BackendAdapter` Estimator path. This schema module
only holds the metadata record; it stays free of any
`h5py`/`pennylane`/`requests`/`openfermion`/`pyscf` import, same boundary
as `pyscf_pyscf.py`.

All three sources verified for real in this repo's own sandbox: HamLib's
real H2 Hamiltonian, fed into the existing `GenericAdaptVQEEngine`,
converged to `-1.131459761897349 Ha`, matching real dense diagonalization
to `7e-15`; the ab initio pipeline independently reproduces the exact same
H2 result from raw geometry via real PySCF HF + Jordan-Wigner, and was
used to compute real qubit Hamiltonians for 3 of the 5 chemistry tutorials
that would otherwise use illustrative toy Hamiltonians (butyronitrile's actual
C#N dissociation, a real carboxylate-mediated SN2 model matching the real
dehalogenase notebook's own mechanism, and a real nitrile-cysteine
covalent model matching cathepsin K's real inhibition chemistry; see
`examples/common/real_molecules.py`). See
`examples/guides/hamiltonian_library.py`,
`tests/test_hamiltonian_sources.py`, `tests/test_ab_initio.py`.

**Where downloaded data goes**: none of it is part of the repo; each
source pulls on demand the first time you call it, and both cache
locations below are `.gitignore`d:

- **HamLib Chemistry**: `load_hamlib_chemistry()` downloads and caches to
  `~/.cache/qpubench/hamiltonian_sources/hamlib/` (outside the repo tree
  entirely); override with `load_hamlib_chemistry(molecule, cache_dir=...)`.
  Never re-fetched once present; `bond_breaking` archives run up to ~330MB.
- **PennyLane qchem**: `load_pennylane_qchem()` wraps `qml.data.load()`,
  whose own real default is `folder_path=Path("datasets")`, i.e. a
  `datasets/` directory relative to wherever you run the script. Pass
  `load_pennylane_qchem(molname, folder_path="/somewhere/else")` (forwarded
  via `**params`) to redirect it.
- **Ab initio (PySCF/OpenFermion)**: nothing to download;
  `build_qubit_hamiltonian()` computes the Hamiltonian live from geometry
  on every call.

| Type | Purpose |
|---|---|
| `HamiltonianSource` | `PENNYLANE_QCHEM` \| `HAMLIB_CHEMISTRY` \| `AB_INITIO_PYSCF` |
| `HamiltonianLibraryRecord` | molecule/basis/encoding + whichever of `fci_energy`/`hf_energy`/`vqe_energy`/`one_norm` the source actually ships (never fabricated); `AB_INITIO_PYSCF` is the only source that fills in a real `hf_energy` (it computes HF itself) |

## `basis_sets`

Full documentation → [docs/integrations/basis_sets.md](integrations/basis_sets.md)

Added 2026-07-09 to back `data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv`'s `Basis`
column with a real catalogue instead of a free-text string. Two sources,
**both real**, corrected 2026-07-09 after actually downloading and
parsing q-vSZP's own data files: an earlier version of this module wrongly
claimed q-vSZP needed ORCA + its Fortran CLI just to know its composition.
It doesn't; only the contraction *coefficients* are charge-dependent, not
the basis-function count, which is a fixed per-element property parsed
straight from `q-vSZP_basis/basisq` (confirmed against the
independently-generated CP2K-format file too).

- **Basis Set Exchange** (basissetexchange.org, `pip install
  'qpubench[bse]'`); covers `sto-3g`/`6-31g`/`cc-pvdz`/`cc-pvtz`/
  `def2-svp`/`def2-tzvp`. Ships its data locally (no network at runtime).
  `count_basis_functions()`'s spherical-harmonic function counts were
  cross-checked against real `pyscf.gto.M(...).nao` for every
  (element, basis) pair in the benchmark CSV, an exact match in all 18
  cases (`tests/test_basis_sets.py`).
- **q-vSZP** (github.com/grimme-lab/qvSZP, Grimme group, `pip install
  'qpubench[qvszp]'`); downloads+caches the real `basisq`/`basisq_
  lesspolfunc`/`basisq_gxtb`/`ecpq`/CP2K-format files directly from the
  repo (same pattern as `hamlib.py`) and parses real per-element shell
  composition: no ORCA, no Fortran CLI. This caught a real error in the
  original benchmark CSV draft: its Li2/qvSZP qubit count (34) was
  physically impossible for a homonuclear diatomic; the real value is 36.
  What remains schema-only (`QvSZPRunConfig`/`QvSZPBasisResult`, same
  boundary as `pyscf.ProjectionEmbeddingConfig`/`DMETConfig`) is only
  producing the true molecule-specific charge-*adapted* coefficients for
  an actual ORCA run, not the basis composition itself.

| Type | Verified against real data | Purpose |
|---|---|---|
| `BasisSetCatalogEntry` / `BASIS_SET_CATALOG` | Yes, all 7 entries | Basis identity: family, cardinality, polarization, element coverage source |
| `get_basis_set_entry()` / `list_available_elements()` / `count_basis_functions()` (`hamiltonian_sources/basis_set_exchange.py`) | Yes, live `bse.get_metadata()`/`get_basis()` calls | Look up / confirm a basis is real; real per-element spatial AO function counts |
| `count_basis_functions()` / `ecp_core_electrons()` / `get_cp2k_format_text()` (`hamiltonian_sources/qvszp.py`) | Yes, live download + parse of the real `q-vSZP_basis/` files | Real per-element q-vSZP function counts/ECP coverage; ready-to-use CP2K basis text |
| `QvSZPRunConfig` / `QvSZPBasisResult` | No, schema-only | Real `qvSZP` CLI invocation shape for molecule-adapted coefficients (build from source; no adapter here calls it) |

## `contraction_path`

Added 2026-07-09 to back the "choose a contraction path finder"
guide, a real `quimb` + `cotengra` mechanism
(`qpubench.tensor_network.contraction_path`), per direct instruction to
build this specifically on quimb/cotengra rather than bare `opt_einsum`.
This schema module stays free of the `quimb`/`cotengra` import (same
"container, not solver" boundary as `pyscf_pyscf.py`/`hamiltonian_library.py`);
the real mechanism lives in `src/qpubench/tensor_network/
contraction_path.py`.

`build_quimb_circuit()` builds a real `quimb.tensor.Circuit` from a
`CircuitSpec` (QASM2 direct via `Circuit.from_openqasm2_str()`; QASM3
bridged through `qiskit.qasm2.dumps(load_qiskit_circuit(circuit))`, since
quimb has no QASM3 loader). `choose_contraction_path()` maps the four
strategies onto real `optimize=` values and returns real
`opt_einsum.contract.PathInfo` cost stats, verified on a Bell circuit:
`SEQUENTIAL`/`RANDOM_GREEDY_128`/`MULTI_STRATEGY` all give `opt_cost=56.0`;
`NONE` (no path pre-optimization, bypasses a real quimb
`contraction_info(optimize=False)` bug: cotengra's dispatch mistakes
`False` for a custom path-finder callable) gives the correctly-higher
`opt_cost=320.0`. See `examples/guides/` (contraction path finder guide),
`tests/test_contraction_path.py`.

| Type | Purpose |
|---|---|
| `ContractionPathStrategy` | `SEQUENTIAL` \| `RANDOM_GREEDY_128` \| `MULTI_STRATEGY` \| `NONE`; the four contraction-path strategies |
| `ContractionPathConfig` | strategy + `num_repeats` (cotengra `HyperOptimizer.max_repeats`) + `max_memory_fraction`/`memory_budget_elements` (mapped to a real cotengra slicing `target_size` for `MULTI_STRATEGY`) |
| `ContractionPathResult` | `strategy_used` + real `opt_cost`/`largest_intermediate` from `opt_einsum.contract.PathInfo` |

## `ibm_cost_estimator`

Full documentation → [docs/integrations/ibm_cost_estimator.md](integrations/ibm_cost_estimator.md)

Added 2026-07-09: real per-circuit resource estimation for IBM Quantum
hardware, plus a dollar-cost breakdown across all four IBM access plans
(Open / Pay-As-You-Go / Flex / Premium), answering "how long will this
take and what will it cost" *before* submitting anything to
`backends/ibm_adapter.py`, and without needing an IBM Quantum account.
Same real-vs-sourced-but-unconfirmed split as `basis_sets`: resource
estimation is real Qiskit output; the exact $/minute figures could not be
confirmed against `ibm.com/quantum/products` directly (403 to automated
fetches in this session) and are cross-referenced from IBM's own docs
(what's confirmed there) plus two independent analyst/press sources (the
rest); see the module docstring and integration doc for the exact split,
and verify before budgeting.

`backends/ibm_cost_estimator.py` (real, Qiskit-dependent): transpiles +
ALAP-schedules a `CircuitSpec` against a real IBM calibration snapshot
(`qiskit_ibm_runtime.fake_provider.FakeBrisbane` etc, no credentials
needed, or a live backend via `IBMAdapter.get_live_backend()`), then
applies IBM's own documented usage formula from
quantum.cloud.ibm.com/docs/en/guides/estimate-job-run-time. Verified: a
4-qubit test circuit against `FakeBrisbane` gives real `depth=14`, 3 `ecr`
gates, `3.52` microsecond circuit duration (`tests/test_ibm_cost_estimator.py`).

`schemas/mirrors/ibm_cost_estimator.py` (pure Pydantic, no Qiskit import): turns
total QPU-seconds into a `PlanCostBreakdown` per plan: Open Plan's free
10-min/28-day quota, Pay-As-You-Go's per-second billing, Flex's prepaid
$30k-minimum lump sum, Premium's $249,600/year minimum annual
subscription. `aggregate_benchmark_cost()` rolls up a whole study's worth
of per-job estimates. See `utils/estimate_ibm_cost.py` for an
end-to-end walkthrough costing `data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv`.

| Type | Verified against real data | Purpose |
|---|---|---|
| `CircuitResourceEstimate` | Yes, real Qiskit transpile/schedule/duration | Per-circuit depth, 1Q/2Q gate counts, real duration, IBM-formula QPU-time estimate |
| `estimate_circuit_resources()` (`backends/ibm_cost_estimator.py`) | Yes, real `FakeBrisbane`/live-backend transpilation | Builds a `CircuitResourceEstimate` from a `CircuitSpec` |
| `IBMPricingRates` | Partially; see docstring for confirmed-vs-cross-referenced split per field | Per-plan $/minute rates, free quota, minimums, all overridable |
| `IBMAccessPlan` | n/a | `OPEN` \| `PAY_AS_YOU_GO` \| `FLEX` \| `PREMIUM` |
| `PlanCostBreakdown` / `estimate_all_plans()` / `aggregate_benchmark_cost()` | Arithmetic only, real once `IBMPricingRates` is confirmed | Dollar cost per plan for a given QPU-time total |

## `fragmentation`

Full documentation → [docs/integrations/fragmentation.md](integrations/fragmentation.md)

Added 2026-07-28. Cross-cutting module: the *general* vocabulary for
decomposing an intractable molecular problem into fragments, shared by the
two project mirrors ([`fragmentqc_fragment`](#fragmentqc_fragment) and
[`qiskitcommunity_fragment_methods`](#qiskitcommunity_fragment_methods))
rather than mirroring either.

Every fragmentation method (MBE, GMBE, DMET, EWF, ONIOM) reduces to the
same four things: a set of fragments, a signed **expansion** over them, a
solver per fragment, and optionally screening rules (the *adaptive* part) and
layers (the *multilevel* part). `FragmentExpansionTerm` is deliberately the
most general form, an arbitrary real coefficient on an arbitrary fragment,
so no method needs a schema of its own. A complete expansion has coefficients
summing to 1; `FragmentationSpec.is_complete()` checks it, and a shortfall
tells you screening dropped terms rather than that something failed.

Fragmentation decomposes the *problem*;
[`distributed_execution`](#distributed_execution) decomposes the *circuit*
that solves each fragment. They compose: `FragmentResult.record_id` links a
fragment to the `BenchmarkRecord` of the run that produced its energy, which
may itself have been partitioned or cut across QPUs.

| Type | Purpose |
|---|---|
| `FragmentationScheme` | `MBE` \| `GMBE` \| `BOTTOM_UP` \| `TOP_DOWN` \| `MBCP` \| `BSSE_BALANCED` \| `DMET` \| `EWF` \| `IAO` \| `ATOMIC` \| `ONIOM` \| `CUSTOM`: how fragment energies are combined |
| `FragmenterType` | `PDB` \| `WATER` \| `COVALENT_COMPONENTS` \| `GROUPS` \| `SUPERSYSTEM` \| `RAW` \| `COMPOUND` \| `ATOMIC` \| `ORBITAL` \| `CUSTOM`: how fragments are carved out; orthogonal to the scheme |
| `SolverKind` | `CLASSICAL` \| `QUANTUM` \| `HYBRID` |
| `ScreeningMetric` | `com_distance` \| `closest_distance` \| `energy_delta` \| `energy_product` \| `bath_occupancy` \| `amplitude` \| `custom` |
| `FragmentSpec` | One subsystem: atom **and** orbital indices, electron/orbital counts, bath size, and `num_qubits`; the estimate that decides whether it fits a given QPU |
| `FragmentExpansionTerm` | `(fragment_id, coefficient)` plus optional per-term method override and a `screened` flag |
| `FragmentScreeningRule` | Adaptive term dropping: metric + per-order `thresholds` + the cheap `backend` that evaluates it |
| `FragmentationLayer` | One level of a multilevel calculation: `max_order`, `method`, `basis`, `sign` (−1 for subtractive ONIOM layers) |
| `FragmentSolverAssignment` | Priority-ordered solver rule; `matches()` evaluates the machine-checkable `max_orbitals`/`max_electrons`/`max_qubits`/`max_order` limits |
| `FragmentationSpec` | The whole plan; `coefficient_sum`, `is_complete()`, `terms_by_order()`, `assign_solver()`, `quantum_fragments()`, `max_fragment_qubits` |
| `FragmentResult` | Per-fragment solver output; `weighted_energy`, `record_id` link to a `BenchmarkRecord` |
| `FragmentationResult` | The reconstruction; `reconstructed_energy` (recomputed from the stored terms; compare it against `total_energy`), `energy_error`, `chemical_accuracy`, `quantum_fragment_fraction`, `to_quantum_result()` |

## `distributed_execution`

Full documentation → [docs/integrations/distributed_qc.md](integrations/distributed_qc.md)

Added 2026-07-28. Cross-cutting module covering the two ways one logical
circuit is run across several QPUs, shared by
[`felixburt_disqco`](#felixburt_disqco) and
[`bscwdc_qdislib`](#bscwdc_qdislib).

The two mechanisms answer the same question and pay different currencies:

- **Partitioning** keeps one entangled computation and teleports qubits
  between QPUs. Cost = **EPR pairs (ebits)** on the network links, counted
  per hop along real routes, so a partition that is cheap on a complete graph
  can be expensive on a linear one. Needs a quantum network.
- **Cutting** breaks the circuit into genuinely independent subcircuits with
  no quantum link. Cost = **classical sampling overhead**: 6 quasiprobability
  terms per gate cut, 8 per wire cut, so `k` cuts need `base ** k` subcircuit
  evaluations. Exponential in cuts, but embarrassingly parallel and needs no
  network at all.

Sharing `QPUNetworkSpec`, `SubcircuitSpec` and `DistributedRunResult` is what
makes them comparable: the same circuit can be benchmarked both ways and read
off one set of fields. `DistributedRunResult.communication_cost` reports
whichever currency the run paid; the two are *not* interchangeable units, so
it is for identifying the dominant knob, not for direct comparison.

| Type | Purpose |
|---|---|
| `DistributionStrategy` | `NONE` \| `PARTITION` \| `GATE_CUT` \| `WIRE_CUT` \| `HADAMARD_GATE_CUT` \| `MIXED_CUT` \| `CIRCUIT_KNITTING` |
| `PartitionerType` | `FIDUCCIA_MATTHEYSES` \| `MULTILEVEL_FM` \| `GENETIC` \| `GENETIC_FM_HYBRID` \| `FGP` \| `KERNIGHAN_LIN` \| `GIRVAN_NEWMAN` \| `SPECTRAL` \| `METIS` \| `RANDOM` \| `MANUAL` |
| `CoarseningStrategy` | `NONE` \| `FULL` \| `STATIC` \| `BLOCKS` \| `RECURSIVE` \| `RECURSIVE_BATCHES` \| `SUBGRAPH` \| `NETWORK`: the multilevel hierarchy the partitioner ran on |
| `NetworkTopology` | `ALL_TO_ALL` \| `LINEAR` \| `GRID` \| `TREE` \| `RANDOM` \| `NETWORK_OF_GRIDS` \| `CUSTOM` |
| `ReconstructionMethod` | `QUASIPROBABILITY` \| `SAMPLING` \| `LOCC` \| `NONE` |
| `QPUNodeSpec` / `QPULinkSpec` / `QPUNetworkSpec` | The network: data vs communication qubits per node, per-link ebit rate/fidelity/latency; `neighbors()`, `is_connected()`, `from_sizes()` |
| `QubitAssignment` | `(qubit, node_id, time_step)`: `time_step=None` is a static placement; a qubit with several time steps was teleported |
| `CircuitPartitionSpec` | Assignment + partitioner + coarsening; `is_time_varying`, `qubits_per_node()`, `exceeds_capacity()` |
| `EntanglementCost` | `ebits`, split into `cat_entanglements` / `teleportations`, plus `ebits_per_link` and `depth_overhead` |
| `CutSpec` / `CircuitCutSpec` | Individual cuts and the whole decomposition; `sampling_overhead` is the product of per-cut term counts (6/8 by default) |
| `SubcircuitSpec` / `SubcircuitResult` | One independently executable piece and its outcome; `qubit_map` back to the original circuit, `coefficient` may be negative |
| `ReconstructionResult` | The recovered observable, with `exact_value` and derived `error` |
| `DistributedRunConfig` | Execution-layer inputs; attach to `ExecutionOptions.distributed_run_config` |
| `DistributedRunResult` | The full record; `ebits`, `sampling_overhead`, `communication_cost`, `to_quantum_result()` |

## `fragmentqc_fragment`

Full documentation → [docs/integrations/fragmentation.md](integrations/fragmentation.md)

Added 2026-07-28. Mirror of [Fragme∩t](https://gitlab.com/fragment-qc/fragment)
(Herbert group, Apache-2.0), a framework for prototyping and benchmarking
fragmentation *methods*, driven by a declarative `strategy.yaml`.

The one idea imported wholesale is the **PIE tree**: nodes keyed by a set of
primary-fragment indices, each with an integer coefficient. A 2-body MBE, a
generalized MBE over overlapping fragments and a screened high-order expansion
are all the same object, differing only in coefficients.
`FragmentPIETree.to_expansion()` converts it to
[`fragmentation`](#fragmentation)`.FragmentExpansionTerm`, which is what makes
Fragme∩t results comparable with embedding-based methods.

Upstream's own `fragment/schemas/` models are Pydantic **v1**; these are
independent v2 mirrors, and qpubench never imports the upstream package.

| Type | Purpose |
|---|---|
| `FragmentStrategy` | A whole `strategy.yaml`: field names match verbatim, so a real file round-trips; `to_fragmentation_spec()` converts one calculation |
| `FragmentModSpec` / `FragmentModName` | The 11 mods, flattened into one superset model; `to_screening_rule()` returns `None` for non-screening mods (basis, MIC) |
| `FragmentBackendSpec` / `FragmentBackendProgram` | Per-layer electronic-structure program (Q-Chem, CP2K, ORCA, NWChem, xTB, PySCF, MOPAC), with the nested PySCF `procedure` block flattened |
| `FragmentFragmenterSpec` / `FragmentCombinator` | Fragmenter + `bottom_up` / `top_down` / `mbe` combinator |
| `FragmentPIENode` / `FragmentPIETree` | The expansion; `coefficient_sum()` (1 when complete), `nonzero_nodes`, `to_expansion()`, `to_fragments()` |
| `FragmentLayerSpec` / `FragmentCalculationSpec` | Multilevel layer stack (backend × view) and the calculation it belongs to |
| `FragmentJobRecord` / `FragmentRunRecord` | One completed fragment job and the whole run; `to_fragmentation_result()` |

## `qiskitcommunity_fragment_methods`

Full documentation → [docs/integrations/fragmentation.md](integrations/fragmentation.md)

Added 2026-07-28. Mirror of
[quantum-fragment-methods](https://github.com/qiskit-community/quantum-fragment-methods)
(IBM Quantum × Cleveland Clinic, Apache-2.0), implementing Shajan et al.,
*Molecular Quantum Computations on a Protein* (arXiv:2512.17130).

This is the piece that connects fragmentation to a QPU: a protein is
partitioned into fragments, each gets a solver by **priority-ordered
rule-based assignment**: quantum (SQD, ext-SQD) where it fits the hardware,
classical (FCI, CCSD) elsewhere, and the energies are recombined. The
per-fragment quantum subproblems are independent, so they are the natural unit
of distribution across QPUs.

**Credentials are deliberately absent.** The upstream `qpu.credentials` block
holds an API token; `QFMQPUConfig` mirrors `channel` and `instance` (which
service was used; a benchmark record should state that) but has **no token
field**, and `from_config_dict()` drops it rather than carrying a secret into
a stored record.

| Type | Purpose |
|---|---|
| `QFMWorkflowConfig` | A whole `config.yaml`; `from_config_dict()` parses the upstream nesting, `to_fragmentation_spec()` emits the general spec with SQD/CCSD priority rules |
| `QFMEWFConfig` / `QFMBathType` | Embedded-wavefunction settings; `truncation` is the single knob trading fragment size (qubit count) against accuracy; `to_screening_rule()` expresses it as a general screening rule |
| `QFMSQDConfig` / `QFMLUCJConfig` / `QFMSBDConfig` | Sample-based quantum diagonalization: subspace size (`total_samples`), self-consistent iterations, LUCJ ansatz shape, external diagonalizer |
| `QFMExtSQDConfig` | `dprime_cutoff`; dominant-configuration selection for extended SQD |
| `QFMQPUConfig` / `QFMSamplerOptions` | Backend, channel/instance, shots, DD sequence, twirling |
| `QFMFragment` | `from_fragment()` duck-types the upstream object (no import); `estimated_qubits` = 2 × spatial orbitals under Jordan-Wigner |
| `QFMSolverResult` | Per-fragment energy; RDMs are **not** stored (records stay JSON-serialisable); `has_rdm1`/`has_rdm2` record that they existed |
| `QFMWorkflowResult` | The reconstructed total; `to_fragmentation_result()` |

## `felixburt_disqco`

Full documentation → [docs/integrations/distributed_qc.md](integrations/distributed_qc.md)

Added 2026-07-28. Mirror of [DISQCO](https://github.com/felix-burt/DISQCO),
implementing *A Multilevel Framework for Partitioning Quantum Circuits*
(arXiv:2503.19082) and *Entanglement-Efficient Distribution of Quantum
Circuits over Large-Scale Quantum Networks* (arXiv:2507.16036).

A circuit becomes a **temporally extended hypergraph**: a vertex per
`(qubit, time)`, a hyperedge per group of gates that can share one distributed
control. Partitioning assigns every vertex to a QPU; because vertices are
time-resolved, a qubit may live on different QPUs at different depths; the
partitioner is choosing *when to teleport*. The objective is the auxiliary EPR
pairs consumed along real network routes.

"Multilevel" means two distinct things here, both recorded: **hypergraph
coarsening** (contract the time axis, partition the coarsest level, project
down and refine) and **network coarsening** (contract the network into
sub-regions and partition hierarchically across them).

> **Assignment array convention.** Upstream an assignment is a NumPy array
> indexed `[qubit][time]` holding a QPU *index*.
> `DisqcoPartitionResult.assignment` keeps that layout as nested lists, and the
> conversion helpers map indices to `QPUNodeSpec.node_id` strings via the
> network's node ordering, so the index order in `DisqcoNetworkSpec.qpu_sizes`
> is significant. `to_partition_spec()` raises without a `network`, because the
> indices are meaningless unnamed.

| Type | Purpose |
|---|---|
| `DisqcoNetworkSpec` | `QuantumNetwork` mirror: `qpu_sizes`, `comm_sizes`, explicit `connectivity`, `hetero` flag; `to_network_spec()` |
| `DisqcoPartitionerType` / `DisqcoCoarsener` / `DisqcoNetworkCoupling` | The upstream factory strings, each with a `to_*()` mapping into the general enums |
| `DisqcoHypergraphStats` | Hypergraph shape plus `group_gates` / `anti_diag`, which materially change the achievable ebit count |
| `DisqcoFMConfig` | FM / multilevel-FM hyperparameters; `is_multilevel` |
| `DisqcoPartitionResult` | `final_cost` (the ebit objective), per-pass `cost_list` / `time_list`, `[qubit][time]` assignment; `ebits`, `improvement`, `is_time_varying`, `to_partition_spec()`, `to_distributed_run_result()` |
| `DisqcoExtractedCircuit` | The extractor's output: data + communication registers per QPU, one shared classical register; `epr_pairs_per_link` counts only directly-linked pairs (multi-hop routes appear as several requests), `to_circuit_spec()` |

## `bscwdc_qdislib`

Full documentation → [docs/integrations/distributed_qc.md](integrations/distributed_qc.md)

Added 2026-07-28. Mirror of [Qdislib](https://github.com/bsc-wdc/qdislib)
(Barcelona Supercomputing Centre): Tejedor et al., SC '25 Workshops
(doi:10.1145/3731599.3767547) and the semantic circuit cache
(arXiv:2604.26788); hardware-aware cut selection follows SparseCut
(arXiv:2511.05492).

Cutting replaces a two-qubit gate or a wire with a quasiprobability
decomposition, splitting the circuit into subcircuits with no quantum link.
Every evaluation is independent, which is exactly the shape PyCOMPSs
distributes across CPUs, GPUs and QPUs.

Upstream names cuts by gate label (a gate cut is `["CZ_2"]`, a wire cut a
pair of endpoints `[("H_1", "CZ_2")]`), and callers dispatch on the element
shape. `QdislibCutRecord.from_find_cut()` applies that same shape test once
and stores the kind explicitly, so a stored record never re-infers it.

| Type | Purpose |
|---|---|
| `QdislibCutKind` / `QdislibSoftware` | `gate` \| `wire` \| `hadamard` \| `mixed`; and the emission backend (`qibo` \| `qiskit` \| `cudaq` \| `pennylane`), which must match the backend the subcircuits are evaluated on |
| `QdislibFindCutConfig` | `find_cut` arguments; supplying `coupling_map` switches on hardware-aware (SparseCut) selection |
| `QdislibCutCost` | The `cut_cost()` dict: `num_cuts`, `kind`, `base`, `terms`; `from_cut_cost()` ingests it verbatim |
| `QdislibCutRecord` | The chosen cut; `from_find_cut()` classifies a raw return value, `terms` = `6**gate × 8**wire`, `to_cut_spec()` |
| `QdislibSubcircuit` / `QdislibSubcircuitResult` | One subcircuit and its evaluation, including `executed_on` (cpu/gpu/qpu) and `cache_hit`; the three-step workflow puts execution under the caller's control, so these vary within one run |
| `QdislibCacheStats` | Semantic cache hits/misses and `hit_rate`; the cache keys on circuit *semantics*, so equivalent subcircuits share an entry |
| `QdislibEstimateMetrics` | The `estimate(..., return_metrics=True)` dict |
| `QdislibRunRecord` | The whole run; `sampling_overhead`, `qubit_reduction`, `error` against an exact reference, `to_distributed_run_result()`, `to_quantum_result()` |
| `sampling_overhead()` / `max_cuts_for_budget()` | Size a run before launching it: terms for a cut mix, and the inverse, how many cuts fit a term budget |

---

## `hqs_struqture`

Added 2026-07-29. Mirror of [struqture](https://github.com/HQSquantumsimulations/struqture)
(HQS Quantum Simulations), a typed serialisation format for operators, not a
simulator. Four algebras (spins, bosons, fermions, mixed), each with the same
four-layer stack: Product (the index) → Operator → Hamiltonian →
LindbladNoiseOperator / LindbladOpenSystem.

Two things it carries that nothing else in this package does:

- **Second-quantised operators before a qubit mapping.** `SparsePauliObservable`
  is the *result* of Jordan-Wigner; `StruqtureMappedHamiltonian` keeps the
  fermionic source, the mapping, and the mapped qubit operator together, so
  `VQAConfig.mapper` becomes verifiable rather than decorative.
- **Lindblad dissipators keyed by an ordered pair** (L_i, L_j) with rate M_ij.
  Off-diagonal entries, coherences between decay channels, have no
  representation in a flat rate list; `StruqtureNoiseOperator.has_off_diagonal_rates`
  flags a payload that would lose information on the way to a channel-list
  simulator.

Struqture's versioning is stricter than qpubench's and worth knowing about:
every object embeds `{type_name, min_version, version}` and refuses a load
when the reader is older than the writer's declared minimum, a per-type
contract rather than one library-wide number.

| Type | Purpose |
|---|---|
| `StruqtureSerialisationMeta` | Per-object `{type_name, min_version, version}`; `can_be_read_by()` applies struqture's own compatibility rule |
| `StruqtureType` / `StruqtureAlgebra` | The 19 concrete 2.0 type names; which submodule an object lives in. `STRUQTURE_1_TO_2_NAMES` maps the pre-2.0 `*System` names |
| `StruqtureValue` | A coefficient: numeric (`ComplexNumber`) **or** symbolic expression strings, mirroring `CalculatorComplex` |
| `PauliProductSpec` | `{X,Y,Z}` product; converts both ways with the core `PauliTerm` |
| `DecoherenceProductSpec` / `PlusMinusProductSpec` | The `{X,iY,Z}` and `{σ⁺,σ⁻,Z}` bases: **not** interchangeable with Pauli strings; iY carries a factor of i |
| `ModeProductSpec` | Fermionic / bosonic normal-ordered product; `hermitian=True` enforces the canonical creators[0] ≤ annihilators[0] representative |
| `MixedProductSpec` | Tensor product across spin/boson/fermion subsystems; `subsystem_counts` is the structural signature |
| `StruqtureOperator` | Operator **or** Hamiltonian (same wire shape, distinguished by `meta.type_name`); `to_sparse_pauli_observable()` / `from_sparse_pauli_observable()` |
| `StruqtureNoiseTerm` / `StruqtureNoiseOperator` | The dissipator, keyed by (left, right) product pairs |
| `StruqtureOpenSystem` | Hamiltonian + noise; what a master-equation solver integrates |
| `StruqtureMappedHamiltonian` | Fermionic source + `StruqtureMapping` + resulting spin operator |

---

## `hqs_active_space_finder`

Added 2026-07-29. Mirror of [ActiveSpaceFinder](https://github.com/HQSquantumsimulations/ActiveSpaceFinder)
(HQS, with Covestro): SCF → MP2 natural orbitals → cheap screening DMRG →
entropy + cumulant analysis → *several* candidate active spaces.

This is the fourth active-space type in the package, and deliberately so;
they sit at different points in the pipeline:

| Where | Type | What it holds |
|---|---|---|
| record level | `VQAConfig.active_electrons` / `.active_orbitals` | the two numbers, for cross-run filtering |
| chosen space | `bestquark_gsopt.ActiveSpaceSpec` | occupied + active MO indices |
| one selector | `microsoft_qdk.ActiveSpaceSelectionConfig` / `…Result` | spin-resolved alpha/beta indices |
| selection provenance | `hqs_active_space_finder.ASFActiveSpace` | indices **plus the MO basis they refer to** |

That last column is ASF's own emphatic warning and a real correctness trap:
the MP2-natural-orbital step reorders and remixes the MOs, so index 7 in an
ASF result is not index 7 in the preceding SCF. `mo_coeff_ref` records the
link; `to_gsopt_active_space()` converts to the index-only form and says in
its docstring what it drops.

| Type | Purpose |
|---|---|
| `ASFActiveSpace` | `nel` + `mo_list` + `mo_coeff_ref`; `cas_label`, `num_qubits_jordan_wigner`, index remapping helpers |
| `ASFSelectionConfig` | Everything needed to reproduce a selection: `entropy_threshold` (default `-0.1·ln(0.25)`), `cumulant_threshold`, bounds, SCF settings |
| `ASFDMRGConfig` | The screening DMRG: `max_bond_dimension` 500 by default, low on purpose |
| `ASFSelectionMode` | `entropy` (size is an output) \| `sized` (size is an input, the NISQ case) \| `many` (all candidates) |
| `ASFPreselection` | How the *initial* subspace was chosen; the final space can only ever be a subset of it |
| `ASFOrbitalEntropy` / `ASFCandidateSpace` | Per-orbital s₁(i); a candidate with `max_entropy_excluded`; the diagnostic for "is this space too small?" |
| `ASFSelectionResult` | The run: chosen space, candidates it was chosen over, entropies, SCF convergence |

---

## `hqs_qoqo`

Added 2026-07-29. Mirror of [qoqo / roqoqo](https://github.com/HQSquantumsimulations/qoqo)
(HQS): circuit representation and measurement post-processing, deliberately
with no transpiler, optimiser or algorithm library.

Two things it makes explicit that the core currently splits or drops:

- **The measurement is part of the program.** `CircuitSpec.observables` says
  what to measure; nothing says how counts become that number.
  `QoqoPauliZProductInput` carries the basis-rotation circuits, a qubit mask
  per Pauli product, and `QoqoExpectationRule`, the linear or symbolic
  combination that produces each named expectation value. That rule is the
  missing link between `ShotResult.counts` and `ExpectationResult.value`.
- **PRAGMAs are positioned in the circuit.** `PragmaDamping` after gate 4 is
  not expressible as an `ExecutionOptions` field. `QoqoPragma` enumerates all
  27, grouped by what they do.

`QoqoDeviceSpec` is also notable for being *time-based rather than
error-rate-based*: gate durations plus a per-qubit 3×3 Lindblad rate matrix,
with noise following from their product. `to_backend_spec()` projects onto
`BackendSpec` (T1 = 1/M₀₀, T2 = 1/M₂₂) and says which off-diagonal
information that projection drops.

| Type | Purpose |
|---|---|
| `QoqoCircuitSpec` | Ordered operation list + classical registers; `num_qubits` is derived (qoqo circuits declare no width), `pragmas`, `gate_counts()`, `to_circuit_spec()` |
| `QoqoOperation` / `QoqoOperationCategory` | One entry: hqslang name + gate/definition/measurement/pragma/input |
| `QoqoParameter` | `CalculatorFloat`: a bound float **or** a free expression string |
| `QoqoPragma` | All 27 PRAGMAs by group: readout, state prep, noise, control flow, scheduling |
| `QoqoPauliZProductInput` | `number_qubits`, `use_flipped_measurement` (readout-asymmetry cancellation as measurement structure, not a mitigation pass), products and rules; `num_circuits_per_evaluation` |
| `QoqoPauliProductMask` / `QoqoExpectationRule` | Which qubits a product spans; the linear/symbolic combination that reads it |
| `QoqoCheatedInput` / `QoqoCheatedOperatorEntry` | Arbitrary observables as sparse matrices; the one non-Pauli-decomposed observable form here |
| `QoqoMeasurementSpec` / `QoqoMeasurementType` | The four strategies; the real/cheated pairing isolates shot noise with everything else fixed |
| `QoqoQuantumProgramSpec` | Measurement + **ordered** `input_parameter_names`; a callable unit of quantum work |
| `QoqoDeviceSpec` / `QoqoDeviceTopology` | Connectivity, gate times, 3×3 decoherence matrices; `to_backend_spec()` |
| `QoqoNoiseModelSpec` / `QoqoNoiseModelType` | The five models, distinguished by *when* noise applies: continuous / on-gate / on-idle / at-readout / overrotation |
| `QoqoOverrotationDescription` | A miscalibrated rotation, a coherent error that accumulates, which no Lindblad rate expresses |

---

## `hqs_qoqo_qasm`

Added 2026-07-29. Mirror of [qoqo_qasm](https://github.com/HQSquantumsimulations/qoqo_qasm)
(HQS). One disproportionately useful idea: **"OpenQASM 3.0" is not one
format.** `roqoqo_qasm::QasmVersion` is a version *and* a dialect, and the
same circuit emits materially different text under each.

`CircuitFormat` has `QASM2` and `QASM3` and stops there, so two records can
both claim `format=QASM3` while one is portable and the other only loads
under Braket. `QasmDialect` names the difference and maps back onto the core
enum via `.circuit_format`.

| Type | Purpose |
|---|---|
| `QasmDialect` | `2.0Vanilla` \| `2.0Qulacs` \| `3.0Vanilla` \| `3.0Roqoqo` \| `3.0Braket`; the exact strings upstream parses. `is_portable`, `supports_pragmas`, `circuit_format` |
| `QoqoQasmConfig` | `qubit_register_name` (roqoqo has a flat qubit space; QASM needs a named register, default `q`) + dialect |
| `QoqoQasmTranslationResult` | `untranslated_ops` (translation *refused*, not partial) vs `dropped_pragmas` (succeeded, but means something different); `succeeded` and `is_faithful` are not the same predicate |

---

## `questkit_quest`

Added 2026-07-29. Mirror of [QuEST v4](https://github.com/QuEST-Kit/QuEST)
(EPCC, University of Edinburgh), a C/C++ simulator with no circuit object:
a program is a sequence of calls mutating a `Qureg` in place. **A QuEST run
therefore has no serialisable circuit**; what this mirror records is the
deployment and precision the numbers were produced at, which change both the
runtime and the answer and have no `BackendSpec` fields today.

| Type | Purpose |
|---|---|
| `QuESTDeployment` | OpenMP × CUDA/HIP × MPI × cuQuantum, independently combinable; `num_nodes`, `summary` (`"gpu+mpi(4)"`) |
| `QuESTPrecision` | `FLOAT_PRECISION` 1/2/4 → float/double/long double, **compile-time**; `epsilon` bounds the accuracy a run can claim. Quad is CPU-only |
| `QuESTQuregSpec` | `is_density_matrix` (4ⁿ vs 2ⁿ amplitudes, and the only mode `mix*` works in); derived `num_amplitudes`, `state_bytes`, `bytes_per_node`; `to_backend_spec()` |
| `QuESTPauliStr` / `QuESTPauliStrSum` | QuEST's observable; `to_base4_masks()` packs into `lowPaulis`/`highPaulis` (I=0,X=1,Y=2,Z=3; sequential, *unlike* `PauliLabel.to_qrack_int`). `is_approx_hermitian` mirrors QuEST's lazily-evaluated tri-state |
| `QuESTChannelType` / `QuESTNoiseChannel` | The nine `mix*` channels with a `position` in the host program's call sequence; the only record of where a channel was applied |
| `QuESTCalculation` / `QuESTCalculationResult` | The `calc*` family; recording *which* call produced a number is what makes it interpretable (`calcFidelity` and `calcPurity` are both "near 1") |
| `QuESTRunRecord` | The whole run; attaches to `QuantumResult.vendor_results["quest_run"]`. Rejects noise channels on a state-vector `Qureg` |

Backend factory: `BackendSpec.quest(num_qubits, density_matrix=…, gpu=…, distributed_nodes=…, precision=…)`.
