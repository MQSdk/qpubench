"""QESEM (Qedma) quantum error suppression and mitigation schemas.

Models the data produced and consumed by the Qedma QESEM service, available
via the native qedma-api Python client and as an IBM Qiskit Function.

QESEM workflow:
  1. Submit a circuit + observables + precision target + backend.
  2. QESEM runs device characterization → noise model.
  3. Noise-aware transpilation maps to physical qubits + native gates.
  4. Noise-scaled circuits are executed (QET: quasi-probabilistic error tuning).
  5. Classical post-processing extrapolates to an unbiased mitigated estimate
     with a statistical error bar.

References:
  - Qedma documentation: https://docs.qedma.io/
  - IBM Quantum Qiskit Function guide:
    https://quantum.cloud.ibm.com/docs/guides/qedma-qesem

Schema version: 1.8.0
"""
from __future__ import annotations

import enum

import pydantic

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class QESEMTranspilationLevel(str, enum.Enum):
    """QESEM transpilation strategy for mapping circuits to hardware."""
    MINIMAL                   = "minimal"                    # preserve circuit structure
    MINIMAL_WITH_LAYOUT_OPT   = "minimal_with_layout_opt"   # layout search only
    STANDARD                  = "standard"                   # default: multi-transpilation, best chosen


class QESEMExecutionMode(str, enum.Enum):
    """QPU reservation strategy during QESEM execution."""
    SESSION = "session"   # QPU held exclusively; faster time-to-result but higher cost
    BATCH   = "batch"     # QPU released during classical computation (default)


class QESEMPrecisionMode(str, enum.Enum):
    """How the precision target is interpreted when multiple observables are given."""
    JOB     = "JOB"     # precision target for the aggregate sum of expectation values
    CIRCUIT = "CIRCUIT" # precision target applied independently to each circuit instance


class QESEMJobStatus(str, enum.Enum):
    """QESEM server-side job lifecycle states."""
    INITIALIZING = "INITIALIZING"  # job received, pre-execution setup
    ESTIMATING   = "ESTIMATING"    # analytical QPU-time estimation in progress
    ESTIMATED    = "ESTIMATED"     # time estimate ready; job not yet submitted to QPU
    RUNNING      = "RUNNING"       # circuits executing on QPU
    SUCCEEDED    = "SUCCEEDED"
    FAILED       = "FAILED"
    CANCELLED    = "CANCELLED"


class QESEMCharacterizationStatus(str, enum.Enum):
    """Status of a standalone device characterization job."""
    RUNNING   = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED    = "FAILED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Observable specification
# ---------------------------------------------------------------------------

class QESEMObservableSpec(pydantic.BaseModel):
    """A Pauli observable expressed as a weighted sum of Pauli strings.

    pauli_terms maps Qedma-format Pauli strings to real coefficients.
    String format: single-qubit labels are "X1", "Z0"; multi-qubit labels are
    comma-separated "Z0,Z3", "X1,Y2,Z4".  Matches qedma_api.Observable dict
    constructor and SparsePauliOp.from_sparse_list conventions.

    Examples
    --------
    Average magnetization (5 qubits):
        {"Z0": 0.2, "Z1": 0.2, "Z2": 0.2, "Z3": 0.2, "Z4": 0.2}

    Hamiltonian term:
        {"Z0,Z3": 1.0, "X1,Y2": 0.5}
    """
    pauli_terms: dict[str, float]    # Pauli string → coefficient
    description: str | None = None   # free-text label from ObservableMetadata


# ---------------------------------------------------------------------------
# Circuit and job options
# ---------------------------------------------------------------------------

class QESEMCircuitOptions(pydantic.BaseModel):
    """Per-circuit QESEM execution options.

    Mirrors qedma_api.CircuitOptions.

    error_suppression_only  If True, skip classical error mitigation and return
                            the noise-suppressed result only (lower QPU cost).
    twirl                   None = QESEM chooses; True/False = user override.
    transpilation_level     Controls how aggressively QESEM re-transpiles the
                            input circuit to minimise QPU time.
    parallel_execution      Execute multiple circuit patches in parallel on the
                            device; requires a sufficiently large backend.
    """
    error_suppression_only: bool                    = False
    twirl:                  bool | None             = None
    transpilation_level:    QESEMTranspilationLevel = QESEMTranspilationLevel.STANDARD
    parallel_execution:     bool                    = False


class QESEMJobOptions(pydantic.BaseModel):
    """Job-level QESEM execution options.

    Mirrors qedma_api.JobOptions.
    """
    execution_mode: QESEMExecutionMode = QESEMExecutionMode.BATCH


# ---------------------------------------------------------------------------
# Precision specification
# ---------------------------------------------------------------------------

class QESEMPrecisionPerFactor(pydantic.BaseModel):
    """Per-noise-scale-factor precision targets for the QET protocol.

    QESEM's Quasi-probabilistic Error Tuning (QET) runs circuits at multiple
    noise scale factors then extrapolates to the zero-noise limit.

    scale_precision_map  noise_scale → target precision
      scale = 0.0   zero-noise result (standard QESEM mitigated output)
      0 < s < 1     noise reduction for extrapolation
      scale = 1.0   physical device noise level
      scale > 1     noise amplification for Richardson extrapolation

    Example: {0.0: 0.1, 1.0: 0.15, 2.0: 0.2}
    """
    scale_precision_map: dict[str, float]  # str keys for JSON-safe float keys


# ---------------------------------------------------------------------------
# Job specification
# ---------------------------------------------------------------------------

class QESEMJobSpec(pydantic.BaseModel):
    """QESEM job configuration — what was submitted to the QESEM service.

    Captures both the native qedma-api create_job() signature and the Qiskit
    Function `run(pubs=[(circuit, observables)], ...)` interface.

    circuit_qasm             Serialized input circuit (QASM 2.0 or 3.0).
    num_qubits               Number of logical qubits in the circuit.
    observables              Observables to measure (list of QESEMObservableSpec).
    precision                Uniform precision target (σ for all observables).
    precision_per_factor     Per-scale precision map (QET jobs); overrides precision.
    precision_mode           How precision is interpreted (JOB vs CIRCUIT).
    backend_name             Target QPU identifier, e.g. "ibm_fez", "ibm_torino".
    circuit_options          Per-circuit QESEM settings.
    description              User-provided job label.
    parameterized_values     Binding for parametric circuits: {param_name → [v0, v1, ...]}.
    empirical_time_estimation  If True, run a small pilot to estimate QPU time empirically.
    via_qiskit_function      True when submitted through the IBM Qiskit Functions catalog.
    """
    circuit_qasm:               str | None                = None
    num_qubits:                 int | None                = None
    observables:                list[QESEMObservableSpec] = []
    precision:                  float | None              = None
    precision_per_factor:       QESEMPrecisionPerFactor | None = None
    precision_mode:             QESEMPrecisionMode        = QESEMPrecisionMode.JOB
    backend_name:               str | None                = None
    circuit_options:            QESEMCircuitOptions       = pydantic.Field(
        default_factory=QESEMCircuitOptions
    )
    description:                str                       = ""
    parameterized_values:       dict[str, list[float]]    = {}
    empirical_time_estimation:  bool                      = False
    via_qiskit_function:        bool                      = False


# ---------------------------------------------------------------------------
# Expectation value result types
# ---------------------------------------------------------------------------

class QESEMExpectationValue(pydantic.BaseModel):
    """An expectation value estimate with statistical error bar.

    Mirrors qedma_api.ExpectationValue.
    error_bar is the 1-σ statistical uncertainty.
    """
    value:     float
    error_bar: float


class QESEMScaleExpectationValue(QESEMExpectationValue):
    """Expectation value at a specific noise scale factor.

    Mirrors qedma_api.ScaleExpectationValue.
    scale = 0.0  → zero-noise extrapolated result
    scale = 1.0  → physical device noise
    scale > 1.0  → noise-amplified measurement
    """
    scale: float


class QESEMHeuristicResult(QESEMExpectationValue):
    """Heuristic-extrapolated mitigated result.

    Mirrors qedma_api.HeuristicResult.  QESEM applies one or more heuristic
    extrapolation methods (linear, poly2, Richardson) to the noise-scaled
    measurements to produce the final mitigated estimate.
    """
    extrapolation:  str          # extrapolation method used, e.g. "linear", "richardson"
    scale_factors:  list[float]  # which noise scales were used in this extrapolation


class QESEMNoiseScalingResult(pydantic.BaseModel):
    """Results at multiple noise scale factors from QESEM's QET protocol.

    Mirrors qedma_api.NoiseScalingResult.
    scaling_method is always "QESEM".
    results_per_scale holds one ScaleExpectationValue per scale factor run.
    """
    scaling_method:     str                            = "QESEM"
    results_per_scale:  list[QESEMScaleExpectationValue] = []

    @property
    def scale_factors(self) -> list[float]:
        return [r.scale for r in self.results_per_scale]

    @property
    def zero_noise_result(self) -> QESEMScaleExpectationValue | None:
        """The scale=0.0 result — QESEM's primary mitigated estimate."""
        for r in self.results_per_scale:
            if r.scale == 0.0:
                return r
        return None


class QESEMObservableResult(pydantic.BaseModel):
    """Full QESEM result for one observable in one circuit evaluation.

    Mirrors qedma_api.QesemObservableResult.

    unmitigated     Raw (noisy) expectation value without QESEM processing.
    noise_scaling   Results at all noise scale factors run by QET.
    qesem_heuristic Final heuristic-extrapolated mitigated results (one per method).
    """
    unmitigated:     QESEMExpectationValue | None       = None
    noise_scaling:   QESEMNoiseScalingResult | None     = None
    qesem_heuristic: list[QESEMHeuristicResult]         = []

    @property
    def mitigated(self) -> QESEMExpectationValue | None:
        """Best mitigated value: first heuristic result, else zero-noise scaling."""
        if self.qesem_heuristic:
            return self.qesem_heuristic[0]
        if self.noise_scaling:
            return self.noise_scaling.zero_noise_result
        return None


class QESEMCircuitObservableResult(pydantic.BaseModel):
    """Mitigated result for one (observable, circuit-instance) pair."""
    observable:  QESEMObservableSpec
    result:      QESEMObservableResult


class QESEMCircuitResult(pydantic.BaseModel):
    """All observable results for one circuit instance (one parameter binding).

    For non-parameterized circuits, parameter_index = 0 and there is one entry.
    For parameterized circuits with N parameter sets there are N entries.
    """
    parameter_index:      int                               = 0
    observable_results:   list[QESEMCircuitObservableResult] = []

    @property
    def mitigated_evs(self) -> list[float | None]:
        return [
            r.result.mitigated.value if r.result.mitigated else None
            for r in self.observable_results
        ]

    @property
    def mitigated_stds(self) -> list[float | None]:
        return [
            r.result.mitigated.error_bar if r.result.mitigated else None
            for r in self.observable_results
        ]

    @property
    def noisy_evs(self) -> list[float | None]:
        return [
            r.result.unmitigated.value if r.result.unmitigated else None
            for r in self.observable_results
        ]


# ---------------------------------------------------------------------------
# Execution details and device characterization
# ---------------------------------------------------------------------------

class QESEMGateInfidelity(pydantic.BaseModel):
    """Per-gate infidelity measured during QESEM device characterization.

    Mirrors qedma_api.GateInfidelity.
    infidelity = 1 − fidelity; lower is better.
    """
    gate_name:  str
    qubits:     tuple[int, ...]
    infidelity: float


class QESEMTranspiledCircuit(pydantic.BaseModel):
    """Circuit compiled by QESEM's noise-aware transpiler.

    Mirrors qedma_api.TranspiledCircuit.

    circuit_qasm          Compiled circuit in QASM format (native gates only).
    qubit_maps            List of logical→physical qubit mappings, one per
                          parallel execution block.
    num_measurement_bases Number of distinct Pauli measurement bases required
                          to estimate all observables.
    """
    circuit_qasm:          str | None               = None
    qubit_maps:            list[dict[str, int]]     = []  # {str(logical): physical}
    num_measurement_bases: int                       = 0


class QESEMExecutionDetails(pydantic.BaseModel):
    """Shot-level and hardware metrics from a completed QESEM job.

    Mirrors qedma_api.ExecutionDetails.

    total_shots       All shots consumed: calibration + characterization + mitigation.
    mitigation_shots  Shots allocated to the final error-mitigated estimation only.
    gate_fidelities   Average fidelity per native gate type as characterised by QESEM,
                      e.g. {"CNOT": 0.990, "ID1Q": 0.9989}.
    transpiled_circuits  Hardware-mapped circuits with qubit layout and measurement info.
    """
    total_shots:          int | None                    = None
    mitigation_shots:     int | None                    = None
    gate_fidelities:      dict[str, float]              = {}
    transpiled_circuits:  list[QESEMTranspiledCircuit]  = []


class QESEMCharacterizationResult(pydantic.BaseModel):
    """Device noise characterization produced by QESEM's noise-learning protocol.

    QESEM runs a characterization sub-job tailored to the submitted circuit to
    build a reliable noise model before executing the main mitigation job.

    measurement_errors   Per-qubit readout error probability (0–1).
    gate_infidelities    Per-(gate-type, qubit-tuple) infidelity values.
    qubit_map            Logical → physical qubit assignment chosen by QESEM.
    qpu_name             Backend the characterization was run on.
    """
    qpu_name:           str | None                  = None
    measurement_errors: dict[int, float]            = {}   # qubit_index → error_prob
    gate_infidelities:  list[QESEMGateInfidelity]   = []
    qubit_map:          dict[int, int]              = {}   # logical → physical


# ---------------------------------------------------------------------------
# Top-level job record
# ---------------------------------------------------------------------------

class QESEMJobRecord(pydantic.BaseModel):
    """Complete record of a QESEM job: spec, results, and execution metadata.

    Populated from qedma_api.ClientJobDetails after job completion.
    Stored in QuantumResult.qesem_result.

    A typical single-circuit, non-parameterized job has one entry in
    circuit_results (parameter_index=0).  A parameterized job with N parameter
    sets has N entries.
    """
    job_id:                         str | None                    = None
    status:                         QESEMJobStatus                = QESEMJobStatus.SUCCEEDED
    qpu_name:                       str | None                    = None
    spec:                           QESEMJobSpec                  = pydantic.Field(
        default_factory=QESEMJobSpec
    )
    precision_mode:                 QESEMPrecisionMode            = QESEMPrecisionMode.JOB
    execution_mode:                 QESEMExecutionMode            = QESEMExecutionMode.BATCH
    analytical_qpu_time_s:          float | None                  = None
    empirical_qpu_time_s:           float | None                  = None
    total_execution_time_s:         float | None                  = None
    created_at:                     str | None                    = None  # ISO-8601
    circuit_results:                list[QESEMCircuitResult]      = []
    execution_details:              QESEMExecutionDetails | None  = None
    characterization:               QESEMCharacterizationResult | None = None
    warnings:                       list[str]                     = []
    errors:                         list[str]                     = []


# ---------------------------------------------------------------------------
# Bridge to the core ExecutionOptions.mitigation_options dict
# ---------------------------------------------------------------------------

def qesem_mitigation_options(
    circuit_options: QESEMCircuitOptions | None = None,
    job_options: QESEMJobOptions | None = None,
) -> dict[str, dict[str, object]]:
    """Build the ExecutionOptions.mitigation_options entries for QESEM.

    The core schema stores vendor mitigation options as a plain dict so it
    stays free of vendor imports.  Rehydrate on the consuming side with:

        co = QESEMCircuitOptions.model_validate(
            options.mitigation_options["qesem_circuit_options"])
        jo = QESEMJobOptions.model_validate(
            options.mitigation_options["qesem_job_options"])
    """
    out: dict[str, dict[str, object]] = {}
    if circuit_options is not None:
        out["qesem_circuit_options"] = circuit_options.model_dump()
    if job_options is not None:
        out["qesem_job_options"] = job_options.model_dump()
    return out
