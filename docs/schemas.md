# Schema reference

Schema version **1.11.0** — 19 modules, all in `src/qpubench/schemas/`.  
Import from the package root: `from qpubench.schemas import CircuitSpec, QuantumResult, …`

---

## Module index

| Module | Purpose |
|---|---|
| [`primitives`](#primitives) | Enums and value types used across all other modules |
| [`circuit`](#circuit) | Circuit or problem specification |
| [`observable`](#observable) | Sparse Pauli observables |
| [`backend`](#backend) | Hardware / simulator description |
| [`execution`](#execution) | Execution options and algorithm hyperparameters |
| [`result`](#result) | Execution results (expectation values, counts, fidelity, ADAPT history, modality-specific) |
| [`record`](#record) | Top-level benchmark record and VQA metadata |
| [`mbqc`](#mbqc) | MBQC-FPGA 16-bit program word, measurement patterns |
| [`cebule`](#cebule) | Cebule SDK (MQS) task inputs / outputs |
| [`xenakis`](#xenakis) | Xenakis GA circuit genomes and run results |
| [`excitation_solve`](#excitation_solve) | ExcitationSolve Fourier-series VQE optimizer |
| [`gsopt`](#gsopt) | GSOpt fixed-budget benchmark results |
| [`photonic`](#photonic) | Linear-optics chips, FBQC, HOM, photonic VQE, analog simulation |
| [`qdk_chemistry`](#qdk_chemistry) | QDK chemistry pipeline: SCF → active space → QPE → resource estimation |
| [`gbs`](#gbs) | Gaussian Boson Sampling: hafnian, vibronic spectra, graph clique finding, TDM/Borealis |
| [`qse`](#qse) | Krylov Quantum Diagonalization (KQD / QSE / SQD) |
| [`qesem`](#qesem) | QESEM (Qedma) error suppression and mitigation |
| [`qcschema`](#qcschema) | QCSchema / QCElemental / PennyLane quantum chemistry interoperability |
| [`neutral_atom`](#neutral_atom) | Neutral atom AHS: Bloqade / Aquila atom arrangements, waveforms, drives, results |
| [`slowquant`](#slowquant) | SlowQuant UCC/VQE: ansatz config, SCF result, optimization, RDMs, linear response, circuit spec |

---

## `primitives`

### Enums

| Enum | Values |
|---|---|
| `QPUModality` | `GATE_BASED` · `MBQC` · `ANNEALING` · `PHOTONIC_LINEAR_OPTICS` · `FUSION_BASED` · `QPE` · `GBS` · `KQD` · `NEUTRAL_ATOM` |
| `CircuitFormat` | `QASM2` · `QASM3` · `QGC` · `MEASUREMENT_PATTERN` · `JSON` · `MOLECULE_JSON` · `FOCK_STATE_CIRCUIT` · `LINEAR_OPTICS_UNITARY` |
| `PauliLabel` | `I` · `X` · `Y` · `Z` |
| `ErrorMitigationStrategy` | `NONE` · `DD` · `TREX` · `ZNE` · `PEC` · `QESEM` |
| `FidelityMetric` | `UNITARY` · `FUBINI_STUDY` · `TRACE` · `PROCESS` |
| `JobStatus` | `PENDING` · `RUNNING` · `SUCCEEDED` · `FAILED` · `CANCELLED` |
| `CebuleTaskType` | `MOL_MAP` · `QASM_GEN` · `TN_QC_OPT` · `COVO` |

### Value types

**`PauliLabel`** helpers:
- `.to_qrack_int()` — Q# convention: `I=0, X=1, Z=2, Y=3` (Z and Y are swapped; never hardcode)
- `.to_qiskit_c_bit_term()` — Qiskit C bit-packed encoding

**`ComplexNumber`** — JSON-safe `{re: float, im: float}` avoiding pydantic's `"1+2j"` encoding.  
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
| `modality` | `QPUModality` | `GATE_BASED` | Gate-based, MBQC, photonic, etc. |
| `num_qubits` | `int` | — | Circuit width |
| `num_classical_bits` | `int \| None` | `None` | Classical register width |
| `format` | `CircuitFormat` | `QASM2` | Source format of `serialized` |
| `serialized` | `str \| None` | `None` | Circuit source string or file path |
| `observables` | `list[SparsePauliObservable]` | `[]` | Estimator-path observables |
| `precision` | `float` | `0.01` | Target precision for shot-count estimation |
| `parameters` | `list[str]` | `[]` | Named variational parameters |
| `parameter_bindings` | `list[ParameterBinding]` | `[]` | Bound parameter values |
| `gate_counts` | `dict[str, int]` | `{}` | Gate-name → count (populated after transpilation) |
| `measurement_pattern` | `MBQCPattern \| None` | `None` | MBQC measurement pattern |

**Methods:**

| Method | Returns | Description |
|---|---|---|
| `.from_openqasm3(source, *, num_qubits)` | `CircuitSpec` | Construct with `format=QASM3` |
| `.openqasm3` | `str \| None` | Source string if format is QASM3, else `None` |
| `.openqasm2` | `str \| None` | Source string if format is QASM2, else `None` |
| `.is_parametric()` | `bool` | `True` if `parameters` is non-empty |
| `.is_bound()` | `bool` | All parameters have bindings |
| `.bind(values)` | `CircuitSpec` | Return copy with parameter bindings applied |
| `.circuit_depth` | `int \| None` | Sum of `gate_counts` values (proxy for depth) |

---

## `observable`

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
- `.from_legacy_dict(obs, num_qubits)` — parse VQEBench `{"X1,Z3": 0.5}` format
- `.from_cebule_operators(operators, coefficients, num_qubits)` — parse Cebule `"X0 Y1 Z3"` token format

---

## `backend`

### `QubitCharacteristics` / `GateCharacteristics`

Per-qubit and per-gate hardware noise properties (T1/T2, frequency, readout error, gate duration, error rate). All fields optional — simulators leave them `None`.

### `BackendSpec`

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | — | Unique backend identifier |
| `provider` | `str` | — | See table below |
| `qpu_modality` | `QPUModality` | `GATE_BASED` | |
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

| Field | Default | Description |
|---|---|---|
| `name` | — | `"ADAPTVQE"` · `"UCCNVQE"` · `"TN_QC_OPT"` · `"ExcitationSolve"` · `"KQD"` · … |
| `pool_type` | `"SD"` | Operator pool: `"SD"` · `"GSD"` · `"SDTQ"` · `"sa_SD"` |
| `optimizer` | `"BFGS"` | `"BFGS"` · `"jacobi"` · `"L-BFGS-B"` · `"COBYLA"` · `"excitation_solve"` |
| `use_analytic_grad` | `True` | Set `False` for gradient-free optimizers |
| `opt_thresh` | `1e-5` | Inner optimizer convergence threshold |
| `opt_maxiter` | `200` | Inner optimizer max iterations |
| `avqe_thresh` | `1e-2` | ADAPT-VQE gradient norm convergence |
| `adapt_maxiter` | `20` | ADAPT-VQE macro-iteration limit |
| `num_samples` | `5` | ExcitationSolve: probe points per parameter sweep (≥5) |
| `n_layers_network` | `None` | Cebule TN_QC_OPT: tensor-network depth |
| `n_layers_circuit` | `None` | Cebule TN_QC_OPT: quantum circuit layers |
| `qasm_ansatz` | `None` | Cebule TN_QC_OPT: pre-defined parametric QASM ansatz |
| `theta_init` / `phi_init` | `[]` | TN / circuit parameter initialisation vectors |
| `param_restarts` | `1` | Xenakis: random restarts for local parameter search |
| `local_opt_steps` | `0` | Xenakis: coordinate-descent steps per restart |
| `num_bits` | `None` | QPE/IQPE: ancilla count / sequential measurement bits |
| `shots_per_bit` | `None` | IQPE: shots per ancilla measurement (majority vote) |
| `evolution_time` | `None` | QPE: total evolution time T = π/‖H‖₁ |
| `trotter_order` | `None` | Trotter product formula order (1 or 2) |
| `extra_params` | `{}` | Library-specific escape hatch |

### `ExecutionOptions` QESEM fields

| Field | Default | Description |
|---|---|---|
| `qesem_circuit_options` | `None` | Per-circuit QESEM options (`QESEMCircuitOptions`) |
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
| `algorithm_spec` | `None` | Algorithm hyperparameters for `AlgorithmAdapter` |
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
| `counts` | `{bitstring: count}` — MSB-first (Qiskit convention) |
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
| `modality` | `QPUModality` | |
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
| `photonic_simulation` | `PhotonicSimulationResult \| None` | Photonic chip simulation |
| `photonic_vqe` | `PhotonicVQEResult \| None` | Photonic VQE optimization |
| `photonic_sensitivity` | `PhotonicSensitivityAnalysis \| None` | Sobol / sensitivity analysis |
| `hom_result` | `HOMResult \| None` | Hong-Ou-Mandel interference |
| `indist_purification` | `IndistinguishabilityPurificationResult \| None` | Photon indistinguishability |
| `photonic_analog_sim` | `PhotonicAnalogSimResult \| None` | Analog Hamiltonian simulation |
| `qpe_result` | `QPEResult \| None` | QPE / IQPE phase estimation output |
| `qchem_pipeline` | `QChemPipelineSpec \| None` | Full QDK chemistry pipeline record |
| `gbs_sampling` | `GBSSamplingResult \| None` | GBS photon-number sampling |
| `gbs_clique_finding` | `GBSCliqueFindingResult \| None` | Graph-based GBS clique finding |
| `vibronic_spectrum` | `VibronicSpectrumResult \| None` | Vibronic spectrum (Duschinsky GBS) |
| `tdm_gbs` | `TDMGBSResult \| None` | Borealis TDM GBS |
| `kqd_pipeline` | `KQDPipelineSpec \| None` | Krylov Quantum Diagonalization pipeline |
| `qesem_result` | `QESEMJobRecord \| None` | QESEM job record (noise scaling results, execution details, characterization) |

Property: `.openqasm3_transpiled` — returns `transpiled_circuit` if format is QASM3.

---

## `record`

### `VQAConfig`

Chemistry and algorithm metadata for VQE / VQA runs.

| Field | Description |
|---|---|
| `problem_type` | `"chemistry"` · `"optimization"` · `"ml"` |
| `molecule` | Molecule name (e.g., `"H2"`, `"BH"`) |
| `basis` | Basis set (e.g., `"sto-3g"`) |
| `num_electrons` | Total electron count |
| `num_alpha` / `num_beta` | Spin-up / spin-down electrons |
| `active_electrons` | Electrons in active space |
| `active_orbitals` | Orbitals in active space |
| `hf_energy` | Hartree-Fock reference energy |
| `fci_energy` | Full CI energy (COVO output) |
| `algorithm` | Algorithm name |
| `pool_type` | Operator pool for UCC variants |
| `mapper` | Fermion → qubit mapping: `"Parity"` · `"JordanWigner"` · `"BravyiKitaev"` · `"MQS"` |
| `ansatz` | Ansatz name |
| `optimizer` | Classical optimizer name |
| `num_parameters` | Variational parameters in final ansatz |
| `n_cnot` | CNOT count in final circuit |
| `n_pauli_trm_measures` | Total Pauli measurements |
| `n_layers_network` | Cebule TN depth |
| `n_layers_circuit` | Cebule / GSOpt circuit layer count |
| `nfev` | Total function evaluations |
| `ga_run_id` | Links to `GARunResult.run_id` (Xenakis) |
| `genome_hash` | Stable hash of evolved genome |
| `best_complexity` | Xenakis ad-hoc complexity score |
| `convergence_values` | Energy per optimizer iteration |
| `convergence_parameters` | Parameter vector per iteration |
| `adapt_maxiter_reached` | ADAPT hit `adapt_maxiter` without converging |
| `final_eigenvalue` | Final VQE energy |
| `ground_truth` | Reference energy for error computation |

Properties: `.energy_error`, `.chemical_accuracy` (True if error < 1 mHartree)

### `BenchmarkRecord`

One complete benchmark execution.

| Field | Description |
|---|---|
| `schema_version` | `"1.8.0"` |
| `experiment_id` | UUID (auto-generated) |
| `run_id` | Groups records belonging to the same sweep |
| `timestamp` | UTC timestamp |
| `circuit` | `CircuitSpec` |
| `backend` | `BackendSpec` |
| `options` | `ExecutionOptions` |
| `result` | `QuantumResult` |
| `vqa` | `VQAConfig \| None` |
| `num_qubits` | Circuit width |
| `circuit_depth` | Transpiled depth |
| `ga_run_id` | Links to a `GARunResult` (Xenakis) |
| `tags` | `list[str]` |
| `notes` | Free text |

Class method: `.from_vqe(*, circuit, backend, options, result, vqa, …)`

---

## `mbqc`

Full documentation → [docs/mbqc.md](mbqc.md)

Key types: `MBQCPattern`, `MBQCRound`, `MBQCProgramWord`, `ByproductUpdateSpec`, `AdaptiveSpec`, `CommutationSpec`, `MBQCExecutionResult`, `MBQCQubitState`.

---

## `cebule`

Full documentation → [docs/integrations/cebule.md](integrations/cebule.md)

| Type | Cebule task | Description |
|---|---|---|
| `MolecularGeometry` | shared | Flat geometry + symbols + basis |
| `MolMapInput` / `MolMapResult` | `MOL_MAP` | Molecular → qubit Hamiltonian mapping |
| `QASMGenInput` / `QASMGenResult` | `QASM_GEN` | Hamiltonian → OpenQASM measurement circuits |
| `TNQCOptInput` / `TNQCOptResult` | `TN_QC_OPT` | Tensor-network + quantum circuit VQE |
| `COVOInput` / `COVOResult` | `COVO` | Correlation-optimised virtual orbitals |

---

## `xenakis`

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

## `excitation_solve`

Full documentation → [docs/integrations/excitation_solve.md](integrations/excitation_solve.md)

| Type | Description |
|---|---|
| `ExcitationSolveConfig` | `maxiter`, `tol`, `num_samples`, `hf_energy`, `mode` |
| `ExcitationSolveMode` | `ONE_D` · `TWO_D` · `ADAPT` |
| `ParameterSample` | One `(parameter_variation, energy_sample)` probe |
| `ExcitationSolveSweep` | 5+ probes → Fourier coefficients → optimal parameter |
| `ExcitationSolveIteration` | One sweep round: energy, nfev, parameters |
| `ExcitationSolveResult` | Full output; `to_quantum_result()`, `convergence_values()` |
| `AdaptVQEStep` | One ADAPT macro-step: `prior_cost`, `max_gradient`, `selected_operator` |
| `ExcitationAdaptResult` | Full ADAPT run; `grad_norm_history()`, `to_quantum_result()` |

---

## `gsopt`

Full documentation → [docs/integrations/gsopt.md](integrations/gsopt.md)

| Type | Description |
|---|---|
| `REFERENCE_ENERGIES` | FCI/CCSD(T) energies for BH, LiH, BeH2, H2O, N2 |
| `reference_energy(molecule)` | Lookup helper with case-insensitive aliases |
| `GSOptBenchmarkLane` | `VQE` · `TN` · `DMRG` · `AFQMC` · `GIBBS` |
| `VQEAnsatzType` | `HEA_RY_RING` · `HEA_RYRZ_RING` · `UCCSD` · `CUSTOM` |
| `VQEOptimizerType` | `COBYLA` · `POWELL` · `NELDER_MEAD` |
| `ActiveSpaceSpec` | `active_electrons`, `active_orbitals`, orbital index arrays |
| `VQERunConfig` | The `config` sub-object from `simple_vqe.py` JSON output |
| `GSOptBenchmarkResult` | Full benchmark JSON; `to_quantum_result()`, `to_vqa_config()` |
| `GSOptBenchmarkMeta` | `.gsopt.json` metadata file format |

---

## `photonic`

Full documentation → [docs/integrations/photonic.md](integrations/photonic.md)

Modality: `QPUModality.PHOTONIC_LINEAR_OPTICS` (MZI chips, permanent-based) and `QPUModality.FUSION_BASED` (FBQC).

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
| `BeamsplitterSpec` | `mode_a`, `mode_b`, `theta`, `phi` — standard 2-mode BS |
| `MZISpec` | `mode_a`, `mode_b`, `phi_inner`, `phi_outer` — Mach-Zehnder interferometer |
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
| `HOMSpec` | `source_a`, `source_b`, `beamsplitter` — Hong-Ou-Mandel setup |
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

Result fields in `QuantumResult`: `photonic_simulation`, `photonic_vqe`, `photonic_sensitivity`, `hom_result`, `indist_purification`, `photonic_analog_sim`

---

## `qdk_chemistry`

Full documentation → [docs/integrations/qdk_chemistry.md](integrations/qdk_chemistry.md)

Modality: `QPUModality.QPE`

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
| `ModelHamiltonianSpec` | Union wrapper — exactly one params block + `LatticeGraphSpec` |

`QChemPipelineSpec` is stored in `QuantumResult.qchem_pipeline`.

---

## `gbs`

Full documentation → [docs/integrations/gbs.md](integrations/gbs.md)

Modality: `QPUModality.GBS`

**Key distinction from `photonic`:** `photonic` = permanent-based / MZI chips / Fock states. `gbs` = hafnian-based / Gaussian states (covariance matrix formalism).

### Enums

| Enum | Values |
|---|---|
| `GBSBackendType` | `gaussian_simulator`, `fock_simulator`, `xanadu_x8`, `xanadu_borealis`, `aws_braket_borealis` |
| `GBSMeasurementType` | `fock` (PNR), `threshold` (click), `homodyne`, `heterodyne` |
| `QuadratureOrdering` | `xp_blocks` (SF default), `interleaved` (DTU-GBS convention) |
| `GaussianStateType` | `vacuum`, `coherent`, `squeezed`, `two_mode_squeezed`, `thermal`, `cluster_1d`, `cluster_2d` |
| `TDMSqueezingLevel` | `low`, `medium`, `high` (Borealis presets) |
| `GraphScalingMethod` | `none`, `divide_by_max`, `normalise`, `laplacian_b` (Kaur method) |

### Gaussian state

| Type | Description |
|---|---|
| `GaussianStateSpec` | `num_modes`, `mean_vector` (2n), `covariance_matrix` (2n×2n flattened), `quadrature_ordering` |
| `HafnianMatrixSpec` | `A_real`/`A_imag` (2n×2n flattened) — σ_q-derived A matrix |

### GBS circuit building blocks

| Type | Description |
|---|---|
| `SqueezingGateSpec` | `mode_index`, `r`, `phi` — single-mode Sgate |
| `S2GateSpec` | `mode_a`, `mode_b`, `r`, `phi` — two-mode S2gate (EPR pair) |
| `RotationGateSpec` | `mode_index`, `phi` |
| `InterferometerSpec` | `mode_indices`, `unitary_real`/`imag`, `source` |
| `HomodyneMeasurementSpec` | `mode_index`, `phi`, `outcome` — continuous-variable measurement |
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

### Vibronic spectra (GAMESS + Duschinsky + GBS)

| Type | Description |
|---|---|
| `NormalModeData` | `equilibrium_geometry`, `normal_mode_vectors`, `frequencies_cm1`, `atomic_masses_amu` |
| `DuschinskyResult` | `rotation_matrix_Ud`, `displacement_delta` (from `qchem.duschinsky`) |
| `VibronicGBSParams` | `t`, `U1`, `r`, `U2`, `alpha`, `temperature_K` (from `qchem.vibronic.gbs_params`) |
| `VibronicSpectrumConfig` | `molecule_name`, `ground_state_file`, `excited_state_file`, `temperature_K`, `num_samples` |
| `VibronicSpectrumResult` | `config`, `ground_state_data`, `duschinsky`, `gbs_params`, `sample_energies_cm1`, histograms |

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

---

## `qse`

Full documentation → [docs/integrations/qse.md](integrations/qse.md)

Modality: `QPUModality.KQD`

Three algorithm families from MQSdk/qse:
1. **KQD via Hadamard test** — modified Hadamard test circuits measure ⟨ψ_{I,m}|O|ψ_{J,n}⟩; assembles S and H subspace matrices; regularized generalized eigensolver.
2. **Sample-based KQD (SKQD/SQD)** — Krylov circuits measured in Fock basis; bitstrings post-selected by particle number; subspace projected via qiskit-addon-sqd.
3. **Multi-reference variants** — d_refs reference states each seed their own Krylov series.

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
| `SlaterDeterminantRef` | `ncas`, `occ_alpha`, `occ_beta` — JW encoding; properties: `num_qubits`, `bitstring`, `num_electrons` |
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
| `CholeskyDecompositionSpec` | `num_orbitals`, `eps`, `n_chol`, `max_cholesky`, `accuracy` — low-rank two-electron integral representation |

### Pipeline

| Type | Description |
|---|---|
| `KQDConfig` | `method`, `krylov_dim`, `num_references`, `dt`, `num_trotter_steps`, `shots_per_circuit`, `regularization` |
| `KQDPipelineSpec` | Full pipeline: `num_qubits`, `hamiltonian_label`, `kqd_config`, `time_evolution`, `reference_states`, `circuit_family`, `krylov_matrices`, `hadamard_results`, `eigen_result`, `cumulative_counts`, `sqd_result`, `exact_energy`, `hf_energy`, `cholesky_spec` |

`KQDPipelineSpec` is stored in `QuantumResult.kqd_pipeline`.

---

## `qesem`

Full documentation → [docs/integrations/qesem.md](integrations/qesem.md)

Modality: `QPUModality.GATE_BASED` with `ErrorMitigationStrategy.QESEM`

QESEM (Qedma) wraps IBM gate-based hardware with noise-aware transpilation, device characterization, and quasi-probabilistic error tuning (QET). It runs circuits at multiple noise scale factors then extrapolates to an unbiased zero-noise estimate with a statistical error bar.

### Enums

| Enum | Values |
|---|---|
| `QESEMTranspilationLevel` | `minimal`, `minimal_with_layout_opt`, `standard` |
| `QESEMExecutionMode` | `session` (QPU reserved), `batch` (QPU released — default) |
| `QESEMPrecisionMode` | `JOB` (aggregate precision), `CIRCUIT` (per-instance precision) |
| `QESEMJobStatus` | `INITIALIZING` · `ESTIMATING` · `ESTIMATED` · `RUNNING` · `SUCCEEDED` · `FAILED` · `CANCELLED` |
| `QESEMCharacterizationStatus` | `RUNNING` · `SUCCEEDED` · `FAILED` · `CANCELLED` |

### Observable

| Type | Description |
|---|---|
| `QESEMObservableSpec` | `pauli_terms: dict[str, float]` + `description` — Qedma string dict format, e.g. `{"Z1": 1.0, "Z0,Z3": 0.3}` |

### Circuit and job options

| Type | Description |
|---|---|
| `QESEMCircuitOptions` | `error_suppression_only`, `twirl`, `transpilation_level`, `parallel_execution` |
| `QESEMJobOptions` | `execution_mode` (BATCH or SESSION) |
| `QESEMPrecisionPerFactor` | `scale_precision_map: dict[str, float]` — noise scale → precision target (for QET) |

### Job specification

| Type | Description |
|---|---|
| `QESEMJobSpec` | Full job config: `circuit_qasm`, `num_qubits`, `observables`, `precision`, `precision_per_factor`, `precision_mode`, `backend_name`, `circuit_options`, `parameterized_values`, `description` |

### Expectation value result types

| Type | Description |
|---|---|
| `QESEMExpectationValue` | `value`, `error_bar` — base EV with 1-σ uncertainty |
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
| `QESEMGateInfidelity` | `gate_name`, `qubits: tuple[int, ...]`, `infidelity` — from device characterization |

### Device characterization

| Type | Description |
|---|---|
| `QESEMCharacterizationResult` | `qpu_name`, `measurement_errors: dict[int, float]`, `gate_infidelities`, `qubit_map` |

### Job record

| Type | Description |
|---|---|
| `QESEMJobRecord` | Top-level container: `job_id`, `status`, `qpu_name`, `spec`, `precision_mode`, `execution_mode`, `analytical_qpu_time_s`, `empirical_qpu_time_s`, `total_execution_time_s`, `circuit_results`, `execution_details`, `characterization` |

`QESEMJobRecord` is stored in `QuantumResult.qesem_result`.  
QESEM circuit options are set in `ExecutionOptions.qesem_circuit_options` and `ExecutionOptions.qesem_job_options`.

---

## `qcschema`

Full documentation → [docs/integrations/qcschema.md](integrations/qcschema.md)

Harmonizes qpubench with the [MolSSI QCSchema v2](https://github.com/MolSSI/QCSchema) standard, its Python reference implementation [QCElemental](https://github.com/MolSSI/QCElemental), and the [PennyLane qchem dataset](https://pennylane.ai/datasets/collection/qchem) format. Modality-agnostic — applies to all chemistry problems regardless of QPU execution method.

### Molecule

| Type | Key fields |
|---|---|
| `QCProvenance` | `creator`, `version`, `routine` — source record for any data object |
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
| `QCWavefunctionData` | `basis_name`, `nao`, `nmo`; orbital coefficients (`scf_orbitals_a/b`), density matrices (`scf_density_a/b`), Fock matrices (`scf_fock_a/b`), eigenvalues, occupations, `overlap_matrix`, `core_hamiltonian_a/b`, `two_electron_integrals` — all as flat float lists |

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

`QCSchemaRecord` is stored in `QuantumResult.qcschema_record`.

---

## `neutral_atom`

Full documentation → [docs/integrations/neutral_atom.md](integrations/neutral_atom.md)

Modality: `QPUModality.NEUTRAL_ATOM`

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
| `AtomicSite` | `x`, `y` — 2-D position in µm |
| `AtomArrangement` | `sites: list[AtomicSite]`, `filling: list[int]` (1=atom, 0=empty; defaults all-filled), `lattice_type`, `lattice_spacing_um`; properties: `num_sites`, `num_filled_sites`, `fill_fraction` |

### Waveforms

| Type | Key fields |
|---|---|
| `AHSTimeSeries` | `times_us: list[float]`, `values: list[float]` — explicit discretized waveform; properties: `num_points`, `duration_us` |
| `AHSWaveform` | `waveform_type`, `duration_us`, `durations_us`, `values` — compact Bloqade builder format; property `total_duration_us` |

### Drive fields

| Type | Key fields |
|---|---|
| `AHSLocalDetuning` | `time_series: AHSTimeSeries`, `site_coefficients: list[float]` (h_k ∈ [0,1]) — experimental per-site detuning |
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

`AHSTaskResult` is stored in `QuantumResult.ahs_result`.  
Backend factories: `BackendSpec.aquila()` (QuEra Aquila via AWS Braket) and `BackendSpec.bloqade_emulator()` (local CPU simulation).

---

## `slowquant`

Full documentation → [docs/integrations/slowquant.md](integrations/slowquant.md)

Modality: `QPUModality.GATE_BASED`

Models the complete SlowQuant quantum chemistry workflow: Hartree-Fock SCF → unitary coupled-cluster (UCC/fUCC/tUPS/QNP/SAUPS) wavefunction optimization → reduced density matrices → linear response theory for excitation energies and transition properties → Qiskit quantum circuit metadata for hybrid QPU execution.

### Enums

| Enum | Values |
|---|---|
| `UCCAnsatzType` | `ucc` (standard UCC), `fucc` (factorized UCC), `tups` (truncated UPS), `qnp` (qubit number parity), `saups` (state-averaged UPS) |
| `UCCExcitationLevel` | `S`, `SD`, `SDT`, `SDTQ`, `SDTQ5`, `SDTQ56` — cumulative excitation strings |
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

`SlowQuantRecord` is stored in `QuantumResult.slowquant_record`.  
Backend factories: `BackendSpec.gate_based(...)` with any Qiskit-compatible provider.
