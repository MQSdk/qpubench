"""Gaussian Boson Sampling (GBS) data schemas.

Covers the Gaussian-state photonic paradigm: squeezed-state / EPR-pair
preparation, covariance-matrix representation, interferometer specification,
photon-number and threshold sampling, and the three main GBS application
domains found in DTU-GBS and photonic_QC:

  1. Direct GBS sampling  — Gaussian program → Fock / threshold samples
  2. Graph-theoretic GBS  — adjacency matrix → Takagi decomp → clique finding
  3. Vibronic spectra     — GAMESS quantum chemistry → Duschinsky transform
                            → GBS circuit params → photoemission spectrum
  4. TDM / Borealis GBS  — time-domain multiplexed GBS on Xanadu Borealis
                            hardware (also accessible via AWS Braket)

Gaussian-state simulation uses the covariance-matrix formalism; amplitudes
are computed via the hafnian (thewalrus library) rather than the permanent.

Schema version: 1.6.0
"""
from __future__ import annotations

import enum

import pydantic

from .primitives import ComplexNumber


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class GBSBackendType(str, enum.Enum):
    """Execution backend for a GBS program."""
    GAUSSIAN_SIMULATOR    = "gaussian_simulator"       # SF Engine("gaussian")
    FOCK_SIMULATOR        = "fock_simulator"           # SF Engine("fock")
    XANADU_X8             = "xanadu_x8"                # Xanadu X8 remote hardware
    XANADU_BOREALIS       = "xanadu_borealis"          # Xanadu Borealis (TDM)
    AWS_BRAKET_BOREALIS   = "aws_braket_borealis"      # Borealis via Amazon Braket


class GBSMeasurementType(str, enum.Enum):
    """Detector model at the output of a GBS circuit."""
    FOCK       = "fock"       # photon-number-resolving (PNR) detector
    THRESHOLD  = "threshold"  # click / no-click (non-PNR, MeasureThreshold)
    HOMODYNE   = "homodyne"   # continuous-variable homodyne; DTU-GBS cluster states
    HETERODYNE = "heterodyne" # full Q-function measurement


class QuadratureOrdering(str, enum.Enum):
    """Ordering convention for the quadrature vector / covariance matrix.

    XP_BLOCKS   (x₁, x₂, …, xₙ, p₁, p₂, …, pₙ)  — thewalrus / SF default
    INTERLEAVED (x₁, p₁, x₂, p₂, …, xₙ, pₙ)     — DTU-GBS convert_index_convention
    """
    XP_BLOCKS   = "xp_blocks"
    INTERLEAVED = "interleaved"


class GaussianStateType(str, enum.Enum):
    VACUUM               = "vacuum"
    COHERENT             = "coherent"
    SQUEEZED             = "squeezed"
    TWO_MODE_SQUEEZED    = "two_mode_squeezed"   # EPR pair
    THERMAL              = "thermal"
    CLUSTER_1D           = "cluster_1d"          # 1D chain (DTU-GBS)
    CLUSTER_2D           = "cluster_2d"          # 2D grid (MBQC substrate)


class TDMSqueezingLevel(str, enum.Enum):
    """Borealis squeezing preset levels."""
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class GraphScalingMethod(str, enum.Enum):
    """Method used to scale the adjacency matrix A before GBS encoding.

    NONE          A used directly (eigenvalues must be < 1)
    DIVIDE_BY_MAX A / max_eigenvalue (ensures spectral norm ≤ 1)
    NORMALISE     nA = A / k  for user-chosen constant k
    LAPLACIAN_B   B = σ(D-A)σ for degree-regularised GBS (Kaur method)
    """
    NONE          = "none"
    DIVIDE_BY_MAX = "divide_by_max"
    NORMALISE     = "normalise"
    LAPLACIAN_B   = "laplacian_b"


# ---------------------------------------------------------------------------
# Gaussian state representation
# ---------------------------------------------------------------------------

class GaussianStateSpec(pydantic.BaseModel):
    """Full Gaussian state description via mean vector and covariance matrix.

    mean_vector        Length-2n quadrature mean [x₁, …, xₙ, p₁, …, pₙ] (or
                       interleaved) in XP_BLOCKS ordering unless noted.
    covariance_matrix  Flattened 2n×2n real covariance matrix V; row-major.
                       σ_q = V + ½I is used to construct the hafnian A matrix.
    quadrature_ordering Convention for both mean and covariance index layout.
    """
    num_modes:            int
    state_type:           GaussianStateType          = GaussianStateType.SQUEEZED
    mean_vector:          list[float]                = []   # length 2n; empty = vacuum
    covariance_matrix:    list[float]                = []   # flattened 2n×2n
    quadrature_ordering:  QuadratureOrdering         = QuadratureOrdering.XP_BLOCKS


class HafnianMatrixSpec(pydantic.BaseModel):
    """A matrix used for hafnian-based photon-number probability computation.

    A = Amat(σ_q) where σ_q = V + ½I and Amat is from thewalrus.
    Stored as two flattened 2n×2n real arrays (real + imaginary parts).
    index_convention tracks whether the matrix has been converted to
    interleaved ordering (DTU-GBS convert_index_convention).
    """
    num_modes:           int
    A_real:              list[float]                # flattened 2n×2n
    A_imag:              list[float]                # flattened 2n×2n
    index_convention:    QuadratureOrdering         = QuadratureOrdering.XP_BLOCKS


# ---------------------------------------------------------------------------
# Gate specifications for Gaussian programs
# ---------------------------------------------------------------------------

class SqueezingGateSpec(pydantic.BaseModel):
    """Single-mode squeezing gate: Sgate(r, phi) applied to one mode.

    r    Squeezing magnitude (r = 0 → vacuum; r > 0 → squeezed).
    phi  Squeezing angle (phi = 0 → x-squeezed; phi = π → p-squeezed).
    """
    mode_index: int
    r:          float
    phi:        float = 0.0


class S2GateSpec(pydantic.BaseModel):
    """Two-mode squeezing gate: S2gate(r, phi) on a mode pair.

    Creates a two-mode squeezed vacuum (EPR pair) from vacuum inputs.
    Distinct from a beamsplitter followed by single-mode squeezers.
    r = 0 → product vacuum; r → ∞ → perfect EPR pair.
    """
    mode_a:     int
    mode_b:     int
    r:          float
    phi:        float = 0.0


class RotationGateSpec(pydantic.BaseModel):
    """Phase-space rotation gate: Rgate(phi) on one mode."""
    mode_index: int
    phi:        float


class HomodyneMeasurementSpec(pydantic.BaseModel):
    """Homodyne measurement MeasureHomodyne(phi) on one mode.

    Measures the quadrature x_phi = x cos(phi) + p sin(phi).
    phi = 0  → x-quadrature;  phi = π/2 → p-quadrature.
    Used in DTU-GBS cluster state measurement patterns.
    """
    mode_index: int
    phi:        float          # measurement angle (radians)
    outcome:    float | None   = None   # measured quadrature value


class InterferometerSpec(pydantic.BaseModel):
    """Passive linear-optics interferometer over a set of modes.

    unitary_real / unitary_imag  Flattened M×M unitary matrix columns
                                  (Clements or Reck decomposition at runtime).
    source  "manual", "takagi", "clements", "reck" — how the matrix was obtained.
    """
    mode_indices:   list[int]
    unitary_real:   list[float]      # flattened M×M real part
    unitary_imag:   list[float]      # flattened M×M imaginary part
    source:         str = "manual"   # how the unitary was produced


class TakagiDecompositionSpec(pydantic.BaseModel):
    """Takagi–Autonne decomposition of a symmetric matrix A = U diag(l) Uᵀ.

    Used to convert a graph adjacency matrix into the squeezing parameters
    and interferometer unitary for a GBS program:
      l → tanh⁻¹(l_scaled) gives per-mode S2gate squeezing
      U → Interferometer applied twice (signal + idler registers)
    """
    singular_values: list[float]   # Takagi singular values lᵢ
    unitary_real:    list[float]   # flattened M×M real part of U
    unitary_imag:    list[float]   # flattened M×M imaginary part of U
    num_modes:       int


# ---------------------------------------------------------------------------
# GBS program and sampling
# ---------------------------------------------------------------------------

class GBSProgramSpec(pydantic.BaseModel):
    """Specification for a Gaussian Boson Sampling program.

    Two encoding paths:
      Single-register (standard GBS)
        squeezing_params + interferometer + measurement
      Two-register (graph GBS via S2gate)
        s2_gates + interferometer (applied to both signal/idler) + measurement

    num_modes refers to the number of optical modes in one register; for the
    two-register S2gate path the total program uses 2×num_modes modes.
    """
    num_modes:          int
    squeezing_params:   list[SqueezingGateSpec]   = []   # single-register Sgate path
    s2_gates:           list[S2GateSpec]          = []   # two-register S2gate path
    rotation_gates:     list[RotationGateSpec]    = []   # pre-/post-interferometer Rgates
    interferometer:     InterferometerSpec | None = None
    measurement_type:   GBSMeasurementType        = GBSMeasurementType.FOCK
    homodyne_angles:    list[HomodyneMeasurementSpec] = []   # for cluster state measurement


class GBSSample(pydantic.BaseModel):
    """One shot of a GBS measurement.

    photon_numbers  PNR outcome: photons per mode (length num_modes).
    click_pattern   Threshold outcome: 0/1 per mode (length num_modes).
    homodyne_outcomes  Continuous quadrature values per mode (homodyne path).
    Exactly one of photon_numbers / click_pattern / homodyne_outcomes should
    be populated.
    """
    photon_numbers:      list[int]   = []    # PNR measurement (Fock)
    click_pattern:       list[int]   = []    # threshold (0/1 per mode)
    homodyne_outcomes:   list[float] = []    # homodyne x_φ values

    @property
    def total_photons(self) -> int:
        return sum(self.photon_numbers)

    @property
    def num_clicks(self) -> int:
        return sum(self.click_pattern)


class GBSSamplingConfig(pydantic.BaseModel):
    """GBS sampling run configuration."""
    program:        GBSProgramSpec
    backend_type:   GBSBackendType   = GBSBackendType.GAUSSIAN_SIMULATOR
    num_shots:      int              = 1000
    seed:           int | None       = None
    device_target:  str | None       = None   # e.g. "X8_01" or Braket ARN


class GBSSamplingResult(pydantic.BaseModel):
    """GBS sampling result.

    samples         All recorded shots as GBSSample objects.
    mean_photon_number  Average photon count per sample.
    photon_histogram    Counts indexed by total_photon number.
    sampling_time_s     Wall time for sampling.
    """
    config:                GBSSamplingConfig
    samples:               list[GBSSample]        = []
    mean_photon_number:    float | None           = None
    photon_histogram:      dict[str, int]         = {}   # str(k) → count
    sampling_time_s:       float | None           = None
    num_shots_completed:   int                    = 0


# ---------------------------------------------------------------------------
# Hafnian computation
# ---------------------------------------------------------------------------

class HafnianComputationSpec(pydantic.BaseModel):
    """Input specification for a hafnian (or permanent) computation.

    B_matrix  The complex symmetric hafnian matrix, typically
              B = U @ diag(tanh(r)) @ Uᵀ for a GBS graph program.
    output_pattern  The photon-number pattern s for which haf(B_S) is computed.
    """
    B_real:         list[float]   # flattened n×n real part of B
    B_imag:         list[float]   # flattened n×n imaginary part of B
    output_pattern: list[int]     # Fock output state s₁, …, sₙ
    num_modes:      int


class HafnianResult(pydantic.BaseModel):
    """Result of a hafnian computation.

    hafnian   Complex hafnian value haf(B_S).
    probability  |haf(B_S)|² / (s! × det(cov)^0.5) (if cov supplied).
    method    "thewalrus" (C++ backend) or "classical" (pure Python).
    """
    hafnian:          ComplexNumber
    probability:      float | None   = None
    computation_time_ms: float | None = None
    method:           str            = "thewalrus"


# ---------------------------------------------------------------------------
# Graph-based GBS (clique finding, dense subgraph)
# ---------------------------------------------------------------------------

class GBSGraphConfig(pydantic.BaseModel):
    """Configuration for a graph-based GBS run.

    adjacency_matrix  Symmetric n×n adjacency matrix A, flattened row-major.
    num_photons       Number of photons (graph nodes to select per sample).
    scaling_method    How A is scaled before computing Takagi decomposition.
    scaling_factor    Manual denominator k when method=NORMALISE.
    sigma_vector      Per-node σ values for LAPLACIAN_B method
                      (B = σ(D-A)σ). If empty, uniform 1/sqrt(max_degree).
    """
    adjacency_matrix: list[float]       # flattened n×n symmetric real matrix
    num_nodes:        int
    num_photons:      int               = 0   # 0 = not fixed (threshold mode)
    num_samples:      int               = 1000
    scaling_method:   GraphScalingMethod = GraphScalingMethod.DIVIDE_BY_MAX
    scaling_factor:   float | None      = None
    sigma_vector:     list[float]       = []


class GBSCliqueFindingResult(pydantic.BaseModel):
    """Result of a graph clique-finding experiment via GBS.

    raw_samples         Threshold/PNR samples, each a list of clicked nodes.
    shrunk_cliques      Result after applying clique.shrink() to each sample.
    searched_cliques    Result after applying clique.search() local search.
    mean_density        Mean density of the raw sampled subgraphs (GBS quality).
    """
    config:              GBSGraphConfig
    raw_samples:         list[list[int]]      = []   # each entry: list of clicked node indices
    shrunk_cliques:      list[list[int]]      = []
    searched_cliques:    list[list[int]]      = []
    mean_density:        float | None         = None
    mean_clique_size:    float | None         = None
    max_clique_size:     int | None           = None
    min_clique_size:     int | None           = None
    sampling_time_s:     float | None         = None
    takagi_decomposition: TakagiDecompositionSpec | None = None


# ---------------------------------------------------------------------------
# Vibronic spectra (Duschinsky transform + GBS)
# ---------------------------------------------------------------------------

class NormalModeData(pydantic.BaseModel):
    """Normal-mode data for one electronic state, as read from a GAMESS log.

    equilibrium_geometry   Flattened 3N Cartesian coordinates (Bohr or Å).
    normal_mode_vectors    Flattened (3N-6) × 3N matrix of normal modes;
                           row i = displacement pattern for mode i.
    frequencies_cm1        Vibrational frequencies in cm⁻¹ (length 3N-6).
    atomic_masses_amu      Atomic masses in atomic mass units (length N).
    source_file            GAMESS output filename or provenance label.
    """
    num_atoms:              int
    num_modes:              int   # = 3N - 6 for non-linear; 3N - 5 for linear
    equilibrium_geometry:   list[float]   # length 3N (Bohr)
    normal_mode_vectors:    list[float]   # flattened (3N-6) × 3N
    frequencies_cm1:        list[float]   # length num_modes
    atomic_masses_amu:      list[float]   # length N
    source_file:            str | None    = None


class DuschinskyResult(pydantic.BaseModel):
    """Duschinsky transformation relating ground and excited normal modes.

    Ud (rotation matrix) and delta (displacement vector) satisfy:
        Q_excited = Ud @ Q_ground + delta
    where Q are dimensionless normal coordinates.

    Computed via strawberryfields.apps.qchem.duschinsky().
    """
    num_modes:           int
    rotation_matrix_Ud:  list[float]   # flattened num_modes × num_modes (real)
    displacement_delta:  list[float]   # length num_modes


class VibronicGBSParams(pydantic.BaseModel):
    """GBS circuit parameters for vibronic spectrum computation.

    Derived by strawberryfields.apps.qchem.vibronic.gbs_params():
      t      Single-mode squeezing parameters (length num_modes)
      U1     First passive unitary (pre-squeezing; flattened M×M complex)
      r      Two-mode squeezing parameters (length num_modes)
      U2     Second passive unitary (post-squeezing; flattened M×M complex)
      alpha  Displacement amplitudes (length num_modes)
      temperature_K  Thermal photons included when T > 0

    The corresponding GBS circuit is:
      U1 → S2gate(r) → U2 → Sgate(t) → Dgate(alpha) → MeasureFock
    """
    num_modes:       int
    t:               list[float]   # single-mode squeezing magnitudes
    U1_real:         list[float]   # flattened M×M
    U1_imag:         list[float]
    r:               list[float]   # two-mode squeezing magnitudes
    U2_real:         list[float]   # flattened M×M
    U2_imag:         list[float]
    alpha_real:      list[float]   # displacement real parts
    alpha_imag:      list[float]   # displacement imaginary parts
    temperature_K:   float         = 0.0


class VibronicSpectrumConfig(pydantic.BaseModel):
    """Configuration for a GBS vibronic spectrum simulation.

    Uses GAMESS output for both ground and excited electronic states,
    applies the Duschinsky transformation, derives GBS circuit parameters,
    samples photon-number patterns, and computes transition energies.
    """
    molecule_name:       str
    ground_state_file:   str | None       = None   # GAMESS .log filename
    excited_state_file:  str | None       = None
    temperature_K:       float            = 0.0
    num_samples:         int              = 100
    freq_range_cm1:      tuple[float, float] | None = None   # (min, max) plot range


class VibronicSpectrumResult(pydantic.BaseModel):
    """Result of a GBS vibronic spectrum simulation.

    sample_energies_cm1  Transition energies in cm⁻¹ for each Fock sample.
    histogram_bins        Bin edges in cm⁻¹ for the spectral histogram.
    histogram_counts      Photon counts per bin.
    reference_peak_positions  Experimental peak positions (cm⁻¹) if available.
    reference_peak_intensities  Experimental normalised intensities.
    """
    config:                     VibronicSpectrumConfig
    ground_state_data:          NormalModeData | None      = None
    excited_state_data:         NormalModeData | None      = None
    duschinsky:                 DuschinskyResult | None    = None
    gbs_params:                 VibronicGBSParams | None   = None
    sample_energies_cm1:        list[float]                = []
    histogram_bins:             list[float]                = []
    histogram_counts:           list[float]                = []
    reference_peak_positions:   list[float]                = []
    reference_peak_intensities: list[float]                = []
    num_samples_completed:      int                        = 0


# ---------------------------------------------------------------------------
# TDM (Time-Domain Multiplexed) GBS — Borealis
# ---------------------------------------------------------------------------

class TDMDelaySpec(pydantic.BaseModel):
    """Delay-line loop configuration for a TDM photonic processor.

    delays     Lengths of the delay-line loops in time bins, e.g. [1, 6, 36].
               A d-loop delay multiplies the effective mode count by (d+1).
    effective_modes  Total number of virtual time-bin modes: ∏(dᵢ + 1).
    """
    delays:           list[int]
    effective_modes:  int


class TDMGBSConfig(pydantic.BaseModel):
    """Configuration for a TDM GBS run on Borealis or equivalent hardware.

    gate_args_list  Per-time-step gate parameters produced by
                    borealis_gbs(device, modes, squeezing).
                    Outer list: one entry per gate type (Sgate, Rgate×n, BSgate×n).
                    Inner list: one value per time-bin.
    crop            Whether to crop boundary time bins from results.
    device_arn      AWS Braket ARN for Borealis hardware.
    """
    delays:             TDMDelaySpec
    squeezing_level:    TDMSqueezingLevel   = TDMSqueezingLevel.HIGH
    num_shots:          int                = 10_000
    crop:               bool               = True
    num_modes_requested: int               = 216   # Borealis default
    device_arn:         str | None         = None   # AWS Braket device ARN
    phase_warnings:     dict[str, int]     = {}     # gate → n shifted args


class TDMGBSResult(pydantic.BaseModel):
    """Result of a TDM GBS run.

    samples  Shape (num_shots, num_modes_effective), flattened row-major.
             Each entry is a non-negative integer photon count per time bin.
    num_modes_effective  Actual number of time-bin modes in samples.
    """
    config:                TDMGBSConfig
    samples:               list[list[int]] = []   # shots × modes
    num_shots_completed:   int             = 0
    num_modes_effective:   int             = 0
    mean_photon_per_mode:  float | None    = None
    sampling_time_s:       float | None    = None


# ---------------------------------------------------------------------------
# Cluster state (CV-MBQC substrate)
# ---------------------------------------------------------------------------

class ClusterStateSpec(pydantic.BaseModel):
    """Specification of a Gaussian cluster state.

    1D chain (DTU-GBS): n EPR pairs, adjacent A-modes coupled by a beamsplitter.
    Parameterised by the squeezing parameter r (same for all modes).

    measurement_angles  Homodyne measurement angles for the A-modes
                        (length n).  Determines the computation performed.
    """
    state_type:          GaussianStateType    = GaussianStateType.CLUSTER_1D
    num_nodes:           int
    squeezing_r:         float
    measurement_angles:  list[float]          = []   # radians; length = num_nodes
    boundary_condition:  str                  = "open"   # "open" or "periodic"
