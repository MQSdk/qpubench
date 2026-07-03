"""Error correction and error mitigation provider schemas.

Covers integrations with:
  Q-CTRL Fire Opal     — noise-robust compilation service (fire-opal package)
  Mitiq                — open-source error mitigation: ZNE, PEC, CDR, REM, DDD
  Haiqu Rivet          — hardware-aware transpilation middleware (rivet package)
  ParityQC             — parity encoding for combinatorial optimisation
  QMatter              — quantum problem compression for life-sciences simulations
  Quantum Motion       — silicon CMOS spin-qubit hardware characterisation
  IBM V2 Primitives    — EstimatorV2/SamplerV2 PUB format, BitArray, ExecutionSpans
  Quantum Advantage    — experiment metadata compatible with Quantum Advantage Tracker

Schema version: 1.12.0
"""

from __future__ import annotations

import enum
from typing import Any

import pydantic


# ---------------------------------------------------------------------------
# Shared enumerations
# ---------------------------------------------------------------------------


class MitiqTechnique(str, enum.Enum):
    ZNE = "zne"  # zero-noise extrapolation
    PEC = "pec"  # probabilistic error cancellation
    CDR = "cdr"  # Clifford data regression
    REM = "rem"  # readout error mitigation
    DDD = "ddd"  # dynamical decoupling (Mitiq variant)


class MitiqNoiseScalingMethod(str, enum.Enum):
    FOLD_GLOBAL = "fold_global"  # whole-circuit gate folding; simplest
    FOLD_GATES_RANDOM = "fold_gates_at_random"  # random gate-level folding
    FOLD_GATES_FROM_LEFT = "fold_gates_from_left"
    FOLD_GATES_FROM_RIGHT = "fold_gates_from_right"
    PULSE_STRETCH = "pulse_stretch"  # pulse-level noise scaling


class MitiqZNEFactory(str, enum.Enum):
    LINEAR = "linear"  # linear extrapolation; fast but biased for large noise
    RICHARDSON = "richardson"  # Richardson extrapolation; order = len(scale_factors) - 1
    POLY2 = "poly2"  # degree-2 polynomial
    EXP = "exponential"  # exponential decay model


class MitiqDDDRule(str, enum.Enum):
    XX = "xx"  # X–X pair
    XYXY = "xyxy"  # alternating X–Y–X–Y; suppresses depolarising + dephasing
    YY = "yy"  # Y–Y pair


class ParityQCProblemEncoding(str, enum.Enum):
    QUBO = "qubo"  # Quadratic Unconstrained Binary Optimisation
    HCBO = "hcbo"  # Higher-order Constrained Binary Optimisation
    ISING = "ising"  # Ising Hamiltonian (J/h form)


class IBMExecutionMode(str, enum.Enum):
    SESSION = "session"  # exclusive QPU hold; lowest queue latency; billed by wall time
    BATCH = "batch"  # jobs queued independently; billed by cumulative QPU time
    SINGLE = "single"  # one-shot job; no session or batch context


class IBMPrimitiveType(str, enum.Enum):
    ESTIMATOR = "estimator"  # EstimatorV2 — returns expectation values ± stds
    SAMPLER = "sampler"  # SamplerV2   — returns BitArray shot data


class AdvantageExperimentType(str, enum.Enum):
    OBSERVABLE_ESTIMATION = "observable_estimation"  # Loschmidt echo, Ising magnetization, OTOC
    VARIATIONAL = "variational"  # VQE, QAOA objective
    CLASSICALLY_VERIFIABLE = "classically_verifiable"  # peaked circuits, boson sampling variants


class ClassicalComparisonMethod(str, enum.Enum):
    TENSOR_NETWORK = "tensor_network"  # MPS, DMRG, iTEBD
    EXACT = "exact"  # full statevector simulation
    MONTE_CARLO = "monte_carlo"  # QMC, MCMC
    PERTURBATION = "perturbation"  # perturbative expansion
    CLASSICAL_EM = "classical_em"  # classical-only error mitigation baseline
    NONE = "none"  # no classical baseline available


# ---------------------------------------------------------------------------
# Q-CTRL Fire Opal
# ---------------------------------------------------------------------------


class FireOpalConfig(pydantic.BaseModel):
    """Configuration for a Q-CTRL Fire Opal execution.

    Fire Opal is a closed-box error suppression service that applies
    noise-robust compilation (pulse-level optimisation + DD) transparently
    before submitting to IBM Quantum hardware.

    Python API:
      fo.execute(circuits, shot_count, credentials, backend_name)
      fo.iterate(circuits, parameter_values, ...)  # PQC / VQE loops

    circuit_format   "qasm3" (default) or "qiskit" (QuantumCircuit object).
    parameter_names  non-empty for PQC / iterative VQE runs via fo.iterate().
    """

    backend_name: str
    shot_count: int = 1024
    circuit_format: str = "qasm3"  # "qasm3" | "qiskit"
    parameter_names: list[str] = []
    fire_opal_version: str | None = None


class FireOpalResult(pydantic.BaseModel):
    """Result from a Q-CTRL Fire Opal execution.

    mitigated_counts   Noise-suppressed bitstring counts (Fire Opal output).
    raw_counts         Counts with Fire Opal suppression disabled (baseline).
    suppression_ratio  |mitigated − ideal| / |raw − ideal|; < 1 = improvement.
    """

    mitigated_counts: dict[str, int] = {}
    raw_counts: dict[str, int] = {}
    suppression_ratio: float | None = None
    job_id: str | None = None
    backend_name: str | None = None


# ---------------------------------------------------------------------------
# Mitiq
# ---------------------------------------------------------------------------


class MitiqZNEConfig(pydantic.BaseModel):
    """Zero-noise extrapolation configuration (Mitiq).

    scale_factors    noise amplification factors applied to the circuit,
                     e.g. [1.0, 3.0, 5.0]; must all be ≥ 1.0.
    scaling_method   how noise is amplified at the gate or pulse level.
    factory          extrapolation model fit to the noise-scaled values.
    num_to_average   circuit instances averaged per scale factor.
    """

    scale_factors: list[float] = [1.0, 3.0, 5.0]
    scaling_method: MitiqNoiseScalingMethod = MitiqNoiseScalingMethod.FOLD_GLOBAL
    factory: MitiqZNEFactory = MitiqZNEFactory.RICHARDSON
    num_to_average: int = 1


class MitiqPECConfig(pydantic.BaseModel):
    """Probabilistic error cancellation configuration (Mitiq).

    num_samples    Monte Carlo samples drawn from the quasi-probability distribution.
    precision      target precision (σ); overrides num_samples if set.
    representation_labels   descriptive labels for the quasi-prob decomposition
                            of each noisy gate, e.g. "cx(0,1)".
    """

    num_samples: int = 200
    precision: float | None = None
    representation_labels: list[str] = []


class MitiqCDRConfig(pydantic.BaseModel):
    """Clifford data regression configuration (Mitiq).

    Near-Clifford training circuits are used to learn a noise model, then
    the learned correction is applied to the target (non-Clifford) circuit.

    fraction_non_clifford   fraction of non-Clifford gates left in training circuits
                            to capture near-Clifford noise behaviour.
    fit_function            regression model: "linear" | "poly2" | "nn".
    """

    num_training_circuits: int = 10
    fraction_non_clifford: float = 0.1
    fit_function: str = "linear"  # "linear" | "poly2" | "nn"


class MitiqREMConfig(pydantic.BaseModel):
    """Readout error mitigation configuration (Mitiq).

    inverse_confusion_matrix   calibrated inverse M^{-1} of the readout confusion
                               matrix M[i,j] = P(measure i | prepare j).
                               Stored as a flat row-major list of length 4^num_qubits.
    """

    num_qubits: int
    inverse_confusion_matrix: list[float] = []  # flat row-major; len = 4^num_qubits


class MitiqDDDConfig(pydantic.BaseModel):
    """Mitiq dynamical decoupling (DDD) configuration.

    rule     DD pulse sequence inserted in idle windows.
    spacing  number of identity gates between each DD gate pair; 0 = tight.
    """

    rule: MitiqDDDRule = MitiqDDDRule.XYXY
    spacing: int = 0


class MitiqConfig(pydantic.BaseModel):
    """Top-level Mitiq mitigation configuration (one technique per run).

    Populate only the config sub-model corresponding to technique.
    executor_backend   label for the underlying execution backend, e.g. "aer".
    """

    technique: MitiqTechnique
    mitiq_version: str | None = None
    executor_backend: str | None = None
    zne: MitiqZNEConfig | None = None
    pec: MitiqPECConfig | None = None
    cdr: MitiqCDRConfig | None = None
    rem: MitiqREMConfig | None = None
    ddd: MitiqDDDConfig | None = None


class MitiqResult(pydantic.BaseModel):
    """Result from a Mitiq error-mitigated execution.

    scale_values   ZNE: raw expectation values per noise scale factor
                   (pre-extrapolation); empty for non-ZNE techniques.
    """

    technique: MitiqTechnique
    mitigated_value: float
    unmitigated_value: float | None = None
    std_error: float | None = None
    num_shots_total: int | None = None
    scale_values: list[float] = []


# ---------------------------------------------------------------------------
# Haiqu Rivet
# ---------------------------------------------------------------------------


class HaiquRivetConfig(pydantic.BaseModel):
    """Haiqu Rivet transpilation middleware configuration.

    Rivet (haiqu-ai/rivet, Apache-2.0) is a hardware-agnostic transpilation
    layer that caches and pipelines decomposition, routing, and scheduling
    passes.  Supported backends: "qiskit" | "bqskit" | "pytket".

    compression_level   proprietary state-compression level (0 = off, only the
                        open-source Rivet package; >0 requires proprietary SDK).
    pass_config         JSON-serialisable dict of transpiler pass arguments.
    """

    transpiler_backend: str = "qiskit"  # "qiskit" | "bqskit" | "pytket"
    optimization_level: int = 1
    caching: bool = True
    compression_level: int = 0  # 0 = disabled (open-source Rivet)
    pass_config: dict[str, Any] = {}
    rivet_version: str | None = None


class HaiquTranspilationResult(pydantic.BaseModel):
    """Circuit-quality metrics from a Haiqu Rivet transpilation pass."""

    gate_count_before: int | None = None
    gate_count_after: int | None = None
    depth_before: int | None = None
    depth_after: int | None = None
    two_qubit_gates_before: int | None = None
    two_qubit_gates_after: int | None = None
    cache_hit: bool = False
    transpile_time_s: float | None = None


# ---------------------------------------------------------------------------
# ParityQC
# ---------------------------------------------------------------------------


class ParityQCConfig(pydantic.BaseModel):
    """ParityQC parity encoding compilation configuration.

    ParityOS (Parity Twine compiler) maps QUBO/HCBO optimisation problems
    to parity-encoded circuits on a square lattice, reducing 2-qubit gate
    count and depth compared to standard compilation.

    lattice_rows × lattice_cols   parity lattice dimensions; product ≥ n_variables.
    parity_version                ParityOS version label, e.g. "v2.3".
    """

    problem_encoding: ParityQCProblemEncoding = ParityQCProblemEncoding.QUBO
    n_variables: int | None = None
    lattice_rows: int | None = None
    lattice_cols: int | None = None
    parity_version: str | None = None


class ParityQCResult(pydantic.BaseModel):
    """Result from a ParityQC parity-encoding compilation pass."""

    gate_count_native: int | None = None  # gates in parity-compiled output
    gate_count_direct: int | None = None  # gates without parity (baseline)
    depth_native: int | None = None
    depth_direct: int | None = None
    two_qubit_reduction_pct: float | None = None  # % reduction in 2Q gate count


# ---------------------------------------------------------------------------
# QMatter
# ---------------------------------------------------------------------------


class QMatterConfig(pydantic.BaseModel):
    """QMatter quantum problem compression configuration.

    QMatter compresses quantum simulation problems (chemistry, materials)
    to their 'essential core', reducing qubit and gate requirements for
    life-sciences / drug-discovery workloads.

    target_domain   "chemistry" | "materials" | "drug_discovery" | "finance"
    """

    compression_method: str = "active_space"  # "active_space" | "qmatter_compress"
    target_domain: str = "chemistry"
    qmatter_version: str | None = None


class QMatterCompressionResult(pydantic.BaseModel):
    """Result from a QMatter problem compression run."""

    qubits_before: int | None = None
    qubits_after: int | None = None
    gates_before: int | None = None
    gates_after: int | None = None
    compression_ratio: float | None = None  # qubits_after / qubits_before


# ---------------------------------------------------------------------------
# Quantum Motion
# ---------------------------------------------------------------------------


class QuantumMotionDeviceSpec(pydantic.BaseModel):
    """Hardware characterisation for a Quantum Motion silicon CMOS spin-qubit QPU.

    Quantum Motion fabricates spin-qubit processors in standard CMOS foundries
    and exposes their QPU via Qiskit- or Cirq-compatible backends.

    fabrication_node   CMOS process node, e.g. "22nm", "28nm".
    gate_access        "qiskit" | "cirq"
    """

    device_name: str
    qubit_technology: str = "silicon_cmos_spin_qubit"
    fabrication_node: str | None = None
    num_qubits: int | None = None
    gate_access: str = "qiskit"  # "qiskit" | "cirq"
    t1_us: float | None = None  # T1 energy relaxation (µs)
    t2_us: float | None = None  # T2 dephasing (µs)
    single_qubit_fidelity: float | None = None
    two_qubit_fidelity: float | None = None
    readout_fidelity: float | None = None


# ---------------------------------------------------------------------------
# IBM Qiskit Runtime V2 — PUB structure and BitArray result
# ---------------------------------------------------------------------------


class IBMEstimatorPUB(pydantic.BaseModel):
    """IBM EstimatorV2 Primitive Unified Bloc (PUB).

    EstimatorV2.run(pubs) where each PUB is:
      (circuit, observables, parameter_values?, precision?)

    observable_labels   SparsePauliOp Pauli string labels, e.g. ["ZZ", "IXX"].
    parameter_values    flat vector of parameter bindings (broadcast by Qiskit).
    precision           target statistical precision σ; replaces fixed shot count.
    """

    observable_labels: list[str] = []
    parameter_values: list[float] = []
    precision: float | None = None


class IBMSamplerPUB(pydantic.BaseModel):
    """IBM SamplerV2 Primitive Unified Bloc (PUB).

    SamplerV2.run(pubs) where each PUB is:
      (circuit, parameter_values?, shots?)
    """

    parameter_values: list[float] = []
    shots: int | None = None


class IBMExecutionSpan(pydantic.BaseModel):
    """One ExecutionSpan from IBM Runtime result metadata.

    IBM Runtime returns a list of SliceSpan / DoubleSliceSpan objects; each
    carries start/stop wall-clock timestamps and index slices that map the
    span to specific PUB result indices.

    start_iso / stop_iso   ISO-8601 UTC timestamps.
    pub_indices            PUB result indices covered by this span.
    """

    start_iso: str | None = None  # ISO-8601 UTC
    stop_iso: str | None = None
    duration_s: float | None = None
    pub_indices: list[int] = []


class IBMBitArrayMeta(pydantic.BaseModel):
    """Metadata describing a SamplerV2 BitArray result.

    BitArray preserves the full ND structure of a parameterized PUB:
      shape = (num_parameter_sets, num_shots_per_set)
    For a non-parametric circuit: shape = (num_shots,).

    The dense shot data is held in QuantumResult.shots (ShotResult) after
    the adapter converts BitArray to bitstring counts via .get_counts().
    """

    shape: list[int]  # ND shape, e.g. [1024] or [50, 512]
    num_bits: int
    register_name: str = "meas"


class IBMRuntimeRecord(pydantic.BaseModel):
    """IBM Quantum Runtime job metadata.

    Captures session/batch context, PUB structure, and timing spans for
    reproducible experiment annotation on QuantumResult.

    session_id   IBM Runtime Session ID; None for BATCH and SINGLE modes.
    batch_id     IBM Runtime Batch ID; None for SESSION and SINGLE modes.
    resilience_level   0 (raw) | 1 (TREX) | 2 (ZNE) | 3 (PEC) —
                       maps to ErrorMitigationStrategy values.
    """

    job_id: str | None = None
    session_id: str | None = None  # None for BATCH / SINGLE
    batch_id: str | None = None  # None for SESSION / SINGLE
    execution_mode: IBMExecutionMode = IBMExecutionMode.SINGLE
    primitive_type: IBMPrimitiveType = IBMPrimitiveType.ESTIMATOR
    backend_name: str | None = None
    resilience_level: int | None = None  # 0–3
    shots: int | None = None
    execution_spans: list[IBMExecutionSpan] = []
    estimator_pub: IBMEstimatorPUB | None = None
    sampler_pub: IBMSamplerPUB | None = None
    bit_array_meta: IBMBitArrayMeta | None = None  # populated on Sampler path


# ---------------------------------------------------------------------------
# Quantum Advantage Tracker
# ---------------------------------------------------------------------------


class QuantumAdvantageRecord(pydantic.BaseModel):
    """Experiment metadata compatible with the Quantum Advantage Tracker.

    The Quantum Advantage Tracker (quantum-advantage-tracker.github.io) is a
    community-governed registry of experiments claiming or supporting quantum
    advantage, co-initiated by IBM, Flatiron Institute, BlueQubit, and
    Algorithmiq.

    Three experiment categories (AdvantageExperimentType):
      OBSERVABLE_ESTIMATION   — Loschmidt echo, Ising magnetization, OTOC
      VARIATIONAL             — VQE energy, QAOA approximation ratio
      CLASSICALLY_VERIFIABLE  — peaked circuits, boson sampling variants

    Fields mirror the tracker's GitHub issue submission template.

    coupling_params   problem-specific parameters, e.g. {"b": 1.0, "delta": 0.5}
                      for an Ising model with longitudinal field b and anisotropy δ.
    floquet_layers    number of Floquet / Trotter evolution layers.
    verified          True if the quantum advantage claim has been independently
                      verified by a third party.
    submission_url    GitHub issue URL or permalink on the tracker site.
    """

    experiment_type: AdvantageExperimentType
    circuit_name: str | None = None
    num_qubits: int | None = None
    backend_name: str | None = None
    floquet_layers: int | None = None
    circuit_depth: int | None = None
    observable_value: float | None = None
    observable_error_bound: float | None = None
    classical_method: ClassicalComparisonMethod = ClassicalComparisonMethod.NONE
    classical_time_s: float | None = None
    coupling_params: dict[str, float] = {}
    verified: bool = False
    submission_url: str | None = None
    publication_doi: str | None = None
    notes: str = ""
