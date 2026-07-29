"""Neutral atom (Rydberg / AHS) quantum computing schemas.

Models the Analog Hamiltonian Simulation (AHS) paradigm used by QuEra's
Bloqade SDK and the Aquila QPU (available via AWS Braket).

In AHS, neutral atoms are trapped at programmable positions in a 2-D plane
by optical tweezers.  A global laser drive applies time-dependent Rabi
oscillations (Ω) and detuning (Δ), inducing coherent evolution through the
Rydberg blockade interaction.  Measurement yields a bitstring per shot:
ground state (1) or Rydberg excited (0) for each filled site.

References
----------
Bloqade SDK    https://github.com/QuEraComputing/bloqade
Aquila QPU     https://queracomputing.github.io/Bloqade.jl/dev/capabilities/
AWS Braket AHS https://docs.aws.amazon.com/braket/latest/developerguide/braket-quera-submitting-analog-program-aquila.html

Schema version: 1.10.0
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class NeutralAtomCoupling(str, enum.Enum):
    """Which atomic transition the drive targets."""
    RYDBERG   = "rydberg"    # primary mode for AHS; drives |g⟩ ↔ |r⟩
    HYPERFINE = "hyperfine"  # drives hyperfine ground-state manifold


class AHSWaveformType(str, enum.Enum):
    """Shape of a time-dependent control field."""
    CONSTANT           = "constant"
    LINEAR             = "linear"
    PIECEWISE_LINEAR   = "piecewise_linear"    # required for Rabi amplitude & detuning
    PIECEWISE_CONSTANT = "piecewise_constant"  # required for Rabi phase
    POLY               = "poly"
    CUSTOM             = "custom"              # arbitrary Python function (after sampling)


class SpatialModulationType(str, enum.Enum):
    """Whether a field is applied uniformly or with per-site weights."""
    UNIFORM = "uniform"   # same value for all atoms
    LOCAL   = "local"     # per-site scaling coefficients h_k ∈ [0, 1]


class AHSShotStatus(str, enum.Enum):
    """Execution outcome of a single AHS shot."""
    SUCCESS         = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE         = "failure"


class LatticeGeometryType(str, enum.Enum):
    """Pre-defined or user-defined atom arrangement geometry."""
    CHAIN       = "chain"
    SQUARE      = "square"
    HONEYCOMB   = "honeycomb"
    KAGOME      = "kagome"
    TRIANGULAR  = "triangular"
    RECTANGULAR = "rectangular"
    LIEB        = "lieb"
    CUSTOM      = "custom"   # arbitrary site positions


# ---------------------------------------------------------------------------
# Atom arrangement (geometry)
# ---------------------------------------------------------------------------

class AtomicSite(pydantic.BaseModel):
    """Single tweezer site in the 2-D atom array.

    Coordinates are in micrometres (µm), matching Bloqade / Aquila conventions.
    The Aquila device operates within a 75 µm × 76 µm field.
    """
    x: float   # µm
    y: float   # µm


class AtomArrangement(pydantic.BaseModel):
    """Spatial layout of neutral atoms loaded into optical tweezers.

    sites      2-D positions of tweezer sites (µm).
    filling    Binary occupancy per site (1 = atom loaded, 0 = empty).
               Length must equal len(sites).  Defaults to all-filled.
    lattice_type    Geometry type for pre-defined lattices or CUSTOM.
    lattice_spacing_um  Nearest-neighbour spacing for regular lattices.

    Aquila minimum inter-site spacing: 4.0 µm.
    """
    sites:               list[AtomicSite]
    filling:             list[int]             = []    # 0 or 1, len = len(sites)
    lattice_type:        LatticeGeometryType   = LatticeGeometryType.CUSTOM
    lattice_spacing_um:  float | None          = None

    @pydantic.model_validator(mode="after")
    def _fill_defaults(self) -> AtomArrangement:
        if not self.filling:
            object.__setattr__(self, "filling", [1] * len(self.sites))
        return self

    @property
    def num_sites(self) -> int:
        return len(self.sites)

    @property
    def num_filled_sites(self) -> int:
        return sum(self.filling)

    @property
    def fill_fraction(self) -> float:
        return self.num_filled_sites / self.num_sites if self.num_sites else 0.0


# ---------------------------------------------------------------------------
# Waveforms
# ---------------------------------------------------------------------------

class AHSTimeSeries(pydantic.BaseModel):
    """Explicit (time, value) waveform used for hardware submission.

    times_us   Time points in microseconds (µs).
    values     Physical values at each time point:
                 Rabi amplitude   rad/µs   (Ω)
                 Detuning         rad/µs   (Δ)
                 Phase            rad      (φ)

    Aquila time resolution: 0.001 µs.  Maximum duration: 4.0 µs.
    """
    times_us: list[float]
    values:   list[float]

    @property
    def num_points(self) -> int:
        return len(self.times_us)

    @property
    def duration_us(self) -> float:
        if not self.times_us:
            return 0.0
        return self.times_us[-1] - self.times_us[0]


class AHSWaveform(pydantic.BaseModel):
    """Compact waveform spec in Bloqade builder format.

    Segment-based description before hardware discretization.

    PIECEWISE_LINEAR — Rabi amplitude and detuning.
      durations_us: N segment durations.
      values:       N+1 boundary values (start, [midpoints…], end).

    PIECEWISE_CONSTANT — Rabi phase.
      durations_us: N segment durations.
      values:       N constant values (one per segment).

    CONSTANT
      duration_us:  single duration.
      values:       [constant_value].

    LINEAR
      duration_us:  duration.
      values:       [start, stop].

    POLY
      duration_us:  duration.
      values:       polynomial coefficients [c₀, c₁, c₂, …]
                    → v(t) = c₀ + c₁·t + c₂·t² + …
    """
    waveform_type: AHSWaveformType = AHSWaveformType.PIECEWISE_LINEAR
    duration_us:   float | None    = None   # for scalar-duration types
    durations_us:  list[float]     = []     # for piecewise types
    values:        list[float]     = []

    @property
    def total_duration_us(self) -> float:
        if self.duration_us is not None:
            return self.duration_us
        return sum(self.durations_us)


# ---------------------------------------------------------------------------
# Drive fields
# ---------------------------------------------------------------------------

class AHSLocalDetuning(pydantic.BaseModel):
    """Site-dependent detuning applied on top of the global drive.

    The effective local detuning for site k is:
        Δ_local_k(t) = site_coefficients[k] × time_series.values(t)

    site_coefficients  per-site scaling h_k ∈ [0.0, 1.0],
                       length must equal AtomArrangement.num_sites.
    time_series        time-varying amplitude (rad/µs).

    This is an experimental capability on Aquila.
    """
    time_series:       AHSTimeSeries
    site_coefficients: list[float]   # h_k ∈ [0, 1], one per site


class AHSDrivingField(pydantic.BaseModel):
    """Complete coherent drive: Rabi amplitude + phase + detuning.

    All three field components act globally (UNIFORM spatial modulation).
    Each is stored as a discretized AHSTimeSeries ready for hardware submission.

    rabi_amplitude   Ω(t) in rad/µs — envelope of the drive laser.
                     Must be piecewise linear; range [0, 15.8] rad/µs on Aquila.
    rabi_phase       φ(t) in rad — optical phase of the drive.
                     Must be piecewise constant; range [-99, 99] rad.
    detuning         Δ(t) in rad/µs — frequency detuning from resonance.
                     Must be piecewise linear; range [-125, 125] rad/µs.
    """
    coupling:         NeutralAtomCoupling  = NeutralAtomCoupling.RYDBERG
    rabi_amplitude:   AHSTimeSeries | None = None
    rabi_phase:       AHSTimeSeries | None = None
    detuning:         AHSTimeSeries | None = None
    spatial_modulation: SpatialModulationType = SpatialModulationType.UNIFORM


class AHSProgramSpec(pydantic.BaseModel):
    """Complete AHS program: atom arrangement + time-dependent drive.

    Directly mirrors the Bloqade / AWS Braket AHS IR structure:
      ahs_register    → atom_arrangement
      drivingFields   → driving_fields
      localDetuning   → local_detunings

    total_duration_us  Total pulse duration (µs); inferred from driving fields
                       if not set explicitly.  Aquila maximum: 4.0 µs.
    """
    atom_arrangement: AtomArrangement
    driving_fields:   list[AHSDrivingField]  = []
    local_detunings:  list[AHSLocalDetuning] = []
    total_duration_us: float | None          = None
    description:      str | None             = None
    extras:           dict[str, Any]         = {}

    @property
    def num_qubits(self) -> int:
        """Number of filled atom sites (effective qubit count)."""
        return self.atom_arrangement.num_filled_sites

    @property
    def coupling(self) -> NeutralAtomCoupling:
        if self.driving_fields:
            return self.driving_fields[0].coupling
        return NeutralAtomCoupling.RYDBERG


class AHSBatchSpec(pydantic.BaseModel):
    """Parametric sweep specification for batched AHS execution.

    Bloqade's .batch_assign() sweeps over parallel lists of variable values.
    All variable lists must have the same length (no Cartesian product).

    variable_names      Names of the free parameters.
    parameter_values    parameter_values[i] is the list of values for
                        variable_names[i] across the batch.
    num_shots_per_batch Shots executed per batch instance.
    """
    variable_names:      list[str]
    parameter_values:    list[list[float]]   # outer: variables, inner: batch instances
    num_shots_per_batch: int = 100

    @property
    def batch_size(self) -> int:
        return len(self.parameter_values[0]) if self.parameter_values else 0


# ---------------------------------------------------------------------------
# Hardware specification
# ---------------------------------------------------------------------------

class AquilaDeviceSpec(pydantic.BaseModel):
    """QuEra Aquila hardware constraints and capabilities.

    Aquila is a 256-qubit Rydberg neutral-atom QPU available on AWS Braket.
    All default values match the published Aquila device parameters.

    Positions are in µm; times in µs; field strengths in rad/µs or rad.
    C₆ coefficient (van der Waals): V_ij = C₆ / r_ij⁶.
    """
    max_qubits:                  int   = 256
    area_width_um:               float = 75.0
    area_height_um:              float = 76.0
    min_atom_spacing_um:         float = 4.0
    position_resolution_um:      float = 0.1
    # Rabi amplitude Ω(t)
    rabi_max_rad_us:             float = 15.8
    rabi_resolution_rad_us:      float = 4e-4
    max_rabi_slope_rad_us2:      float = 250.0
    # Detuning Δ(t)
    detuning_min_rad_us:         float = -125.0
    detuning_max_rad_us:         float = 125.0
    detuning_resolution_rad_us:  float = 2e-7
    max_detuning_slope_rad_us2:  float = 2500.0
    # Phase φ(t)
    phase_min_rad:               float = -99.0
    phase_max_rad:               float = 99.0
    phase_resolution_rad:        float = 5e-7
    # Timing
    max_pulse_duration_us:       float = 4.0
    time_resolution_us:          float = 0.001
    # Interaction
    c6_rad_us_um6:               float = 5.42e6   # van der Waals C₆ coefficient
    # Execution
    max_shots:                   int   = 1000
    cost_per_shot_usd:           float = 0.01


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class AHSExecutionMetadata(pydantic.BaseModel):
    """Task submission and execution metadata from AWS Braket / Bloqade."""
    task_id:    str | None = None
    device_id:  str | None = None
    status:     str | None = None
    created_at: str | None = None
    ended_at:   str | None = None
    cost_usd:   float | None = None
    extras:     dict[str, Any] = {}


class AHSShotResult(pydantic.BaseModel):
    """Outcome of a single AHS shot.

    pre_sequence   Atom filling before evolution — 1 = atom present, 0 = empty.
                   A shot with all-1s is a "perfect fill" shot.
    post_sequence  Measurement outcome after evolution —
                   1 = atom in ground state,  0 = Rydberg excited or site empty.
    """
    status:        AHSShotStatus  = AHSShotStatus.SUCCESS
    pre_sequence:  list[int]      = []   # 1=atom, 0=empty
    post_sequence: list[int]      = []   # 1=ground, 0=Rydberg/empty

    @property
    def is_perfect_fill(self) -> bool:
        """True when every site was filled before evolution."""
        return bool(self.pre_sequence) and all(p == 1 for p in self.pre_sequence)


class AHSTaskResult(pydantic.BaseModel):
    """Complete result from an AHS task (one program, many shots).

    Mirrors AnalogHamiltonianSimulationQuantumTaskResult from the AWS Braket SDK.
    Analysis properties filter to shots with SUCCESS status and perfect filling
    (matching Bloqade's filter_perfect_filling=True default).

    rydberg_densities  Per-site Rydberg excitation probability:
                       ⟨n_r_i⟩ = P(post_sequence[i] == 0 | perfect fill)
    bitstrings         post_sequence arrays for all good shots.
    counts             Histogram of bitstring frequencies.
    """
    metadata:             AHSExecutionMetadata  = pydantic.Field(
        default_factory=AHSExecutionMetadata
    )
    num_shots_requested:  int                   = 0
    shot_results:         list[AHSShotResult]   = []
    program_description:  str | None            = None

    @property
    def num_shots_completed(self) -> int:
        return len(self.shot_results)

    @property
    def successful_shots(self) -> list[AHSShotResult]:
        return [s for s in self.shot_results if s.status == AHSShotStatus.SUCCESS]

    @property
    def perfect_fill_shots(self) -> list[AHSShotResult]:
        """Successful shots with all sites filled before evolution."""
        return [s for s in self.successful_shots if s.is_perfect_fill]

    @property
    def bitstrings(self) -> list[list[int]]:
        return [s.post_sequence for s in self.perfect_fill_shots]

    @property
    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for shot in self.perfect_fill_shots:
            key = "".join(str(b) for b in shot.post_sequence)
            result[key] = result.get(key, 0) + 1
        return result

    @property
    def rydberg_densities(self) -> list[float]:
        """Per-site Rydberg excitation probability (averaged over perfect-fill shots)."""
        good = self.perfect_fill_shots
        if not good:
            return []
        n = len(good[0].post_sequence)
        return [
            sum(1 - s.post_sequence[i] for s in good) / len(good)
            for i in range(n)
        ]
