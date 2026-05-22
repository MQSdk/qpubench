# Schema reference

Schema version **1.3.0** — 13 modules, all in `src/qpubench/schemas/`.  
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
| [`result`](#result) | Execution results (expectation values, counts, fidelity, ADAPT history) |
| [`record`](#record) | Top-level benchmark record and VQA metadata |
| [`mbqc`](#mbqc) | MBQC-FPGA 16-bit program word, measurement patterns |
| [`cebule`](#cebule) | Cebule SDK (MQS) task inputs / outputs |
| [`xenakis`](#xenakis) | Xenakis GA circuit genomes and run results |
| [`excitation_solve`](#excitation_solve) | ExcitationSolve Fourier-series VQE optimizer |
| [`gsopt`](#gsopt) | GSOpt fixed-budget benchmark results |

---

## `primitives`

### Enums

| Enum | Values |
|---|---|
| `QPUModality` | `GATE_BASED` · `MBQC` · `ANNEALING` |
| `CircuitFormat` | `QASM2` · `QASM3` · `QGC` · `MEASUREMENT_PATTERN` · `JSON` · `MOLECULE_JSON` |
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
| `modality` | `QPUModality` | `GATE_BASED` | Gate-based, MBQC, or annealing |
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
| `provider` | `str` | — | `"aer"` · `"ibm"` · `"iqm"` · `"qibo"` · `"qrack"` · `"mbqc"` · `"cudaq"` · `"pennylane"` · `"cebule"` |
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
BackendSpec.aer_statevector(num_qubits=None)
BackendSpec.aer_qasm(num_qubits=None)
BackendSpec.ibm(backend_name, *, instance, channel, token_ref)
BackendSpec.qrack(num_qubits=None, *, gpu=True)
BackendSpec.mbqc_fpga(num_logical_qubits, *, fpga_family="xilinx_7series")
BackendSpec.lightning_qubit(num_qubits=None)   # PennyLane; Cebule default
BackendSpec.cudaq(target="nvidia", num_qubits=None)   # GSOpt VQE
BackendSpec.cebule(*, email_ref="", password_ref="")  # Cebule cloud
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
| `name` | — | `"ADAPTVQE"` · `"UCCNVQE"` · `"UCCNPQE"` · `"SPQE"` · `"TN_QC_OPT"` · `"ExcitationSolve"` · … |
| `pool_type` | `"SD"` | Operator pool: `"SD"` · `"GSD"` · `"SDTQ"` · `"sa_SD"` |
| `optimizer` | `"BFGS"` | `"BFGS"` · `"jacobi"` · `"L-BFGS-B"` · `"COBYLA"` · `"excitation_solve"` |
| `use_analytic_grad` | `True` | Set `False` for gradient-free optimizers |
| `opt_thresh` | `1e-5` | Inner optimizer convergence threshold / ExcitationSolve `tol` |
| `opt_maxiter` | `200` | Inner optimizer max iterations / ExcitationSolve `maxiter` |
| `avqe_thresh` | `1e-2` | ADAPT-VQE gradient norm convergence |
| `adapt_maxiter` | `20` | ADAPT-VQE macro-iteration limit |
| `num_samples` | `5` | ExcitationSolve: probe points per parameter sweep (≥5) |
| `n_layers_network` | `None` | Cebule TN_QC_OPT: tensor-network depth |
| `n_layers_circuit` | `None` | Cebule TN_QC_OPT: quantum circuit layers |
| `qasm_ansatz` | `None` | Cebule TN_QC_OPT: pre-defined parametric QASM ansatz |
| `theta_init` / `phi_init` | `[]` | TN / circuit parameter initialisation vectors |
| `param_restarts` | `1` | Xenakis: random restarts for local parameter search |
| `local_opt_steps` | `0` | Xenakis: coordinate-descent steps per restart |
| `extra_params` | `{}` | Library-specific escape hatch |

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
| `active_electrons` | Electrons in active space (GSOpt / ExcitationSolve) |
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
| `nfev` | Total function evaluations (GSOpt, ExcitationSolve) |
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
| `schema_version` | `"1.3.0"` |
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
