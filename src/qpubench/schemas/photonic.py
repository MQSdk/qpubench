"""Photonic quantum computing data schemas — schema v1.4.0.

Covers two photonic compute modalities derived from the photochipsim repository
and companion thesis documents:

1. Linear-optics photonic chip simulation (Kristensen 2023, "Performance Studies
   of Photonic Quantum Computing Schemes for Quantum Chemistry Applications"):
   PMS 6-mode chip, dual-rail qubit encoding, MZI/MMI building blocks, VQE via
   phase-parameter optimisation, permanent-based amplitude computation, Sobol
   sensitivity analysis of hardware parameters.

2. Fusion-based quantum computing with quantum emitters and PICs (Faurby 2024,
   "Fusion-Based Quantum Computing with Quantum Emitters and Photonic Integrated
   Circuits"): InAs/GaAs quantum dot single-photon sources, Si3N4/Si PICs,
   Type-I/II fusion gates, resource state generation, HOM interference, photon
   indistinguishability purification, and photonic analog quantum simulation.

Physical conventions
--------------------
- Fock states: mode-occupation tuples (n_0, n_1, ..., n_{M-1})
- Beamsplitter transmissivity t: diagonal entries √t, off-diagonal i√(1-t)
  (matches photochipsim BS_matrix convention)
- Phase shifter phase θ: U_PS[i,i] = exp(iθ)
- Permanents (thewalrus) used for multi-photon amplitude computation
- Indistinguishability M = HOM dip contrast, corrected for detector/setup losses
- Purity measured via second-order coherence g²(0)
"""
from __future__ import annotations

import enum

import pydantic

from .primitives import ComplexNumber


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PICPlatform(str, enum.Enum):
    """Photonic integrated circuit material platform."""
    SI_N        = "silicon_nitride"    # Si3N4 — low loss, low nonlinearity
    SI          = "silicon"            # Si — compact, CMOS compatible
    GA_AS       = "gallium_arsenide"   # GaAs — quantum dot native platform
    IN_P        = "indium_phosphide"   # InP — telecom wavelengths
    LI_NB_O3    = "lithium_niobate"   # LN — high EO coefficient
    GLASS       = "glass"              # SiO2 / borosilicate — low-cost
    CUSTOM      = "custom"


class PhotonicChipArchitecture(str, enum.Enum):
    """Interferometer mesh topology."""
    CLEMENTS    = "clements"           # column-by-column MZI mesh (optimal depth)
    RECK        = "reck"               # triangular MZI mesh
    RECTANGULAR = "rectangular"        # fixed-grid rectangular mesh
    PMS_CHIP    = "pms_chip"           # 6-mode MZI-MMI PMS chip (photochipsim)
    CUSTOM      = "custom"


class FusionType(str, enum.Enum):
    """Linear-optics fusion gate type."""
    TYPE_I  = "type_i"    # single photon per input rail; succeeds with P=1/2
    TYPE_II = "type_ii"   # dual-rail inputs; generates entanglement, P=1/2


class ResourceStateType(str, enum.Enum):
    """Entangled photonic resource state."""
    BELL_PAIR       = "bell_pair"        # |Φ+⟩ = (|00⟩+|11⟩)/√2
    GHZ3            = "ghz3"             # 3-photon GHZ
    GHZ4            = "ghz4"             # 4-photon GHZ
    LINEAR_CLUSTER  = "linear_cluster"   # 1D cluster state
    RING_CLUSTER    = "ring_cluster"     # ring cluster state
    STAR_CLUSTER    = "star_cluster"
    CUSTOM          = "custom"


class PhotonSourceType(str, enum.Enum):
    """Single-photon source technology."""
    QUANTUM_DOT     = "quantum_dot"      # self-assembled InAs/GaAs QD (deterministic)
    SPDC            = "spdc"             # spontaneous parametric down-conversion (heralded)
    COLOR_CENTER    = "color_center"     # NV or SiV center in diamond
    TRAPPED_ATOM    = "trapped_atom"
    CUSTOM          = "custom"


class PhotonicAnalogHamiltonian(str, enum.Enum):
    """Spin-system Hamiltonian type for photonic analog simulation."""
    ISING           = "ising"
    HEISENBERG      = "heisenberg"
    XY              = "xy"
    TRANSVERSE_FIELD_ISING = "transverse_field_ising"
    CUSTOM          = "custom"


# ---------------------------------------------------------------------------
# Single-photon source characterisation
# ---------------------------------------------------------------------------

class SinglePhotonSourceSpec(pydantic.BaseModel):
    """Physical characterisation of a single-photon source.

    All quality metrics are dimensionless ratios in [0, 1] unless noted.

    References
    ----------
    Faurby 2024: QD decay schemes, T1/T2, g²(0), indistinguishability M,
    fine-structure splitting ΔS, HOM visibility, fiber-to-chip coupling.
    """
    source_type:                  PhotonSourceType = PhotonSourceType.QUANTUM_DOT

    # Photon quality
    g2_zero:                      float | None = None   # second-order coherence g²(0); purity = 1 - g²(0)
    indistinguishability:         float | None = None   # M = HOM dip contrast ∈ [0,1]
    raw_hom_visibility:           float | None = None   # uncorrected HOM visibility V_HOM

    # Source efficiency
    beta_factor:                  float | None = None   # coupling to waveguide/cavity mode β ∈ [0,1]
    collection_efficiency:        float | None = None   # fraction of emitted photons collected
    brightness_mhz:               float | None = None   # detected photon rate (MHz)

    # Emission properties
    wavelength_nm:                float | None = None   # centre emission wavelength (nm)
    linewidth_ghz:                float | None = None   # spectral linewidth (GHz)

    # Quantum dot / emitter properties (Faurby Ch.2, Kristensen Ch.4)
    t1_ns:                        float | None = None   # radiative lifetime T1 (ns)
    t2_ns:                        float | None = None   # total coherence time T2 (ns); T2 ≤ 2T1
    t2_star_ns:                   float | None = None   # dephasing time T2* from pure dephasing
    fine_structure_splitting_ueV: float | None = None   # ΔS fine-structure splitting (μeV); Faurby Fig.2.1.2
    bias_voltage_mv:              float | None = None   # Stark-tuning bias voltage V_bias (mV)
    excitation_power_uw:          float | None = None   # above-band excitation power (μW)
    temperature_k:                float | None = None   # operating temperature (K)

    # Material
    material_system:              str | None   = None   # e.g. "InAs/GaAs", "GaN", "SiC"
    chip_id:                      str | None   = None

    @pydantic.field_validator("g2_zero", "indistinguishability", "beta_factor",
                               "collection_efficiency", mode="before")
    @classmethod
    def _unit_interval(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"quality metric must be in [0, 1], got {v}")
        return v

    @property
    def purity(self) -> float | None:
        """Single-photon purity = 1 - g²(0)."""
        return None if self.g2_zero is None else 1.0 - self.g2_zero

    @property
    def pure_dephasing_rate_ghz(self) -> float | None:
        """Extract pure dephasing rate γ* from T1 and T2: 1/T2 = 1/(2T1) + γ*."""
        if self.t1_ns is None or self.t2_ns is None:
            return None
        return 1.0 / self.t2_ns - 0.5 / self.t1_ns   # GHz (1/ns)


# ---------------------------------------------------------------------------
# Photonic integrated circuit hardware
# ---------------------------------------------------------------------------

class BeamsplitterSpec(pydantic.BaseModel):
    """Physical beamsplitter / directional coupler specification.

    transmissivity t ∈ [0, 1]:  η_reflect = 1 - t (reflectivity convention η
    used in photochipsim matches the BSmatrix: t=diagonal).
    transmissivity_error models fabrication deviation from design value.
    """
    target_transmissivity:   float         = 0.5        # design value t
    transmissivity_error:    float         = 0.0        # σ or absolute deviation
    insertion_loss_db:       float         = 0.0        # on-chip loss (dB)
    type:                    str           = "directional_coupler"  # or "mmi"

    @pydantic.field_validator("target_transmissivity", mode="before")
    @classmethod
    def _unit_interval(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"transmissivity must be in [0, 1], got {v}")
        return v

    @property
    def reflectivity(self) -> float:
        return 1.0 - self.target_transmissivity


class PhaseShifterSpec(pydantic.BaseModel):
    """Physical phase shifter specification.

    phase_rad is the target phase θ ∈ [-π, π].
    phase_error models fabrication / thermal noise around the target.
    """
    target_phase_rad:   float = 0.0   # target θ
    phase_error_rad:    float = 0.0   # σ or absolute deviation
    insertion_loss_db:  float = 0.0


class MZISpec(pydantic.BaseModel):
    """Mach-Zehnder Interferometer — two beamsplitters and two phase shifters.

    mode_i, mode_j: the two waveguide modes coupled by this MZI.
    Ordering follows photochipsim QPU_circuit: BS → PS(inner) → BS → PS(outer).
    """
    mode_i:     int
    mode_j:     int
    bs_in:      BeamsplitterSpec  = pydantic.Field(default_factory=BeamsplitterSpec)
    bs_out:     BeamsplitterSpec  = pydantic.Field(default_factory=BeamsplitterSpec)
    ps_inner:   PhaseShifterSpec  = pydantic.Field(default_factory=PhaseShifterSpec)
    ps_outer:   PhaseShifterSpec  = pydantic.Field(default_factory=PhaseShifterSpec)


class PICSpec(pydantic.BaseModel):
    """Photonic integrated circuit platform and process characterisation.

    References
    ----------
    Faurby Ch.4 (Si3N4 chip, Ch.4.2.2) and Ch.6 (Si PIC for quantum simulation):
    waveguide propagation losses, fiber-chip coupling, operating temperature,
    number of programmable modes.
    """
    platform:                       PICPlatform      = PICPlatform.SI_N
    num_modes:                      int              = 6
    waveguide_loss_db_per_cm:       float | None     = None   # propagation loss
    fiber_chip_coupling_efficiency: float | None     = None   # fiber-to-chip η
    on_chip_efficiency:             float | None     = None   # total on-chip transmission
    num_mzi:                        int | None       = None
    num_phase_shifters:             int | None       = None
    chip_area_mm2:                  float | None     = None
    temperature_k:                  float | None     = None
    fabrication_run:                str | None       = None
    chip_id:                        str | None       = None


# ---------------------------------------------------------------------------
# Fock state and photonic circuit
# ---------------------------------------------------------------------------

class FockState(pydantic.BaseModel):
    """Multi-mode Fock state |n_0, n_1, ..., n_{M-1}⟩.

    occupations[k] = number of photons in mode k.
    total_photons is derived; validated against occupations.
    """
    occupations:   list[int]

    @pydantic.model_validator(mode="after")
    def _non_negative(self) -> FockState:
        if any(n < 0 for n in self.occupations):
            raise ValueError("photon occupation numbers must be non-negative")
        return self

    @property
    def num_modes(self) -> int:
        return len(self.occupations)

    @property
    def total_photons(self) -> int:
        return sum(self.occupations)

    @property
    def is_single_rail(self) -> bool:
        """True if at most one photon per mode (antibunched)."""
        return all(n <= 1 for n in self.occupations)

    def as_tuple(self) -> tuple[int, ...]:
        return tuple(self.occupations)

    @classmethod
    def dual_rail_qubit(cls, qubit_value: int) -> FockState:
        """Dual-rail encoding: |0_L⟩ = |1,0⟩, |1_L⟩ = |0,1⟩."""
        if qubit_value == 0:
            return cls(occupations=[1, 0])
        elif qubit_value == 1:
            return cls(occupations=[0, 1])
        raise ValueError("qubit_value must be 0 or 1")


class PhotonicCircuitSpec(pydantic.BaseModel):
    """Linear-optics photonic circuit specification.

    Gate-based interface to a linear-optics unitary over M modes.

    phase_vector
        Variational phase parameters (rad).  For the PMS chip (photochipsim):
        8 phases [θ_0, φ_0, θ_1, φ_1, θ_2, φ_2, θ_3, φ_3] passed directly to
        QPU_circuit(phase).

    unitary_matrix
        Optional: full M×M unitary matrix stored as a list of M rows, each row
        a list of M ComplexNumber entries.  Populated after simulation.

    mzi_layout
        Explicit MZI component list for hardware-faithful simulations that
        track per-component errors (beamsplitter tolerance, phase noise).

    Architecture notes
    ------------------
    PMS_CHIP:  6 modes, 8 phases, 2 MZI blocks + 1 MMI entangling section.
               Matches photochipsim QPU_circuit layout exactly.
    CLEMENTS:  M modes → M(M-1)/2 MZIs, optimal depth M columns.
    """
    architecture:      PhotonicChipArchitecture   = PhotonicChipArchitecture.CLEMENTS
    num_modes:         int
    num_photons:       int                        = 1
    phase_vector:      list[float]                = []
    mzi_layout:        list[MZISpec]              = []
    unitary_matrix:    list[list[ComplexNumber]]  = []   # M×M; empty = not computed
    description:       str | None                = None

    @pydantic.model_validator(mode="after")
    def _check_unitary_shape(self) -> PhotonicCircuitSpec:
        if self.unitary_matrix:
            M = self.num_modes
            if len(self.unitary_matrix) != M or any(len(r) != M for r in self.unitary_matrix):
                raise ValueError(
                    f"unitary_matrix must be {M}×{M}, "
                    f"got {len(self.unitary_matrix)}×{len(self.unitary_matrix[0]) if self.unitary_matrix else '?'}"
                )
        return self

    @property
    def num_phases(self) -> int:
        return len(self.phase_vector)


# ---------------------------------------------------------------------------
# Photonic VQE
# ---------------------------------------------------------------------------

class PhotonicVQEStep(pydantic.BaseModel):
    """One optimiser step in photonic VQE.

    phases are the variational parameters (phase shifter angles) at this step.
    energy is the expectation value ⟨H⟩ computed from photon count statistics
    weighted by Pauli Hamiltonian coefficients.
    """
    step_index:     int
    phases:         list[float]
    energy:         float
    fidelity:       float | None = None   # fidelity with exact ground state, if known
    num_shots:      int  | None = None
    nfev:           int  | None = None    # cumulative function evaluations


class PhotonicVQEConfig(pydantic.BaseModel):
    """Configuration for a photonic VQE run.

    Closely maps to photochipsim twoqb_vqe.vqe_performance parameters:
    phase ansatz, optimizer, Hamiltonian coefficients per bond distance.

    hamiltonian_labels   Pauli strings, e.g. ['II','IX','IZ','ZI','ZZ','XX']
    bond_distances_ang   R values (Å) for the bond dissociation sweep
    coefficients         shape [len(R), len(labels)]; coeff[r][p] = c_p(R_r)
    """
    molecule:             str                    # "HeH+", "H2", ...
    basis:                str   = "STO-3G"
    hamiltonian_labels:   list[str]              = []
    bond_distances_ang:   list[float]            = []
    coefficients:         list[list[float]]      = []   # shape [R, Pauli]
    num_phases:           int                    = 8    # variational parameter count
    initial_phases:       list[float]            = []   # starting ansatz
    optimizer:            str   = "Powell"       # scipy.optimize.minimize method
    num_shots:            int   = 1000           # photon sampling shots
    chip_architecture:    PhotonicChipArchitecture = PhotonicChipArchitecture.PMS_CHIP
    max_iterations:       int   = 500

    @pydantic.model_validator(mode="after")
    def _check_coeff_shape(self) -> PhotonicVQEConfig:
        if self.coefficients and self.bond_distances_ang:
            if len(self.coefficients) != len(self.bond_distances_ang):
                raise ValueError(
                    "coefficients outer dimension must match bond_distances_ang length"
                )
        return self


class PhotonicVQEResult(pydantic.BaseModel):
    """Complete result of a photonic VQE bond dissociation sweep.

    ground_state_energies[r]  best energy found at bond_distances_ang[r]
    best_phases[r]            optimised phase vector at bond_distances_ang[r]
    vqe_steps                 per-step optimisation trace (one run at R_min only,
                              or all runs if record_all_steps=True)
    """
    config:                 PhotonicVQEConfig
    ground_state_energies:  list[float]           = []
    best_phases:            list[list[float]]     = []   # [R_index][phase_index]
    vqe_steps:              list[PhotonicVQEStep] = []   # optimisation trace
    hartree_fock_energies:  list[float]           = []   # reference HF energies
    exact_energies:         list[float]           = []   # FCI / exact reference
    converged:              bool                  = False
    total_function_evals:   int | None            = None
    optimizer_message:      str | None            = None

    @property
    def energy_error_at_minimum(self) -> float | None:
        """Absolute error vs exact at the equilibrium bond distance."""
        if not self.ground_state_energies or not self.exact_energies:
            return None
        idx = min(range(len(self.exact_energies)), key=lambda i: self.exact_energies[i])
        return abs(self.ground_state_energies[idx] - self.exact_energies[idx])


# ---------------------------------------------------------------------------
# Sobol sensitivity analysis
# ---------------------------------------------------------------------------

class SobolParameterResult(pydantic.BaseModel):
    """First- and total-order Sobol sensitivity indices for one parameter.

    Computed by SALib.analyze.sobol (Saltelli sampling).
    S1  = first-order index (individual contribution to output variance)
    ST  = total-order index (including all interaction effects)
    _conf = 95% confidence interval half-width from bootstrap resampling.

    Reference: photochipsim sensitivity_analysis/analysis.py using SALib.
    """
    parameter_name:  str
    S1:              float
    S1_conf:         float
    ST:              float
    ST_conf:         float


class PhotonicSensitivityAnalysis(pydantic.BaseModel):
    """Sobol sensitivity analysis of VQE energy w.r.t. chip hardware parameters.

    Typical parameters analysed (Kristensen Ch.6.2.1):
      - num_shots (shot noise)
      - initial_ansatz_theta_1..4 (initial phase sensitivity)
    Can also be applied to beamsplitter reflectivities, phase errors, etc.

    parameter_bounds[i] = [lower, upper] for parameter i.
    S2                  = second-order interaction matrix (n×n).
    S2_conf             = 95 % confidence interval for S2 entries.
    """
    parameter_names:   list[str]
    parameter_bounds:  list[list[float]]      # [n_params][2]
    num_samples:       int                    # Saltelli N (total evals ≈ N*(2+n_params))
    conf_level:        float   = 0.95
    output_metric:     str     = "vqe_energy"
    first_and_total:   list[SobolParameterResult] = []
    S2:                list[list[float]]      = []   # n×n matrix
    S2_conf:           list[list[float]]      = []   # n×n matrix

    @pydantic.model_validator(mode="after")
    def _check_consistency(self) -> PhotonicSensitivityAnalysis:
        n = len(self.parameter_names)
        if self.parameter_bounds and len(self.parameter_bounds) != n:
            raise ValueError("parameter_bounds length must match parameter_names")
        if self.S2 and len(self.S2) != n:
            raise ValueError("S2 must be n×n")
        return self


# ---------------------------------------------------------------------------
# Photonic simulation amplitude results
# ---------------------------------------------------------------------------

class FockAmplitude(pydantic.BaseModel):
    """Transition amplitude between two Fock states through a unitary.

    amplitude = perm(U_sub) / sqrt(prod(n_in!) * prod(n_out!))
    probability = |amplitude|^2
    Computed via thewalrus.perm (photochipsim get_amplitude).
    """
    fock_in:      FockState
    fock_out:     FockState
    amplitude:    ComplexNumber
    probability:  float

    @pydantic.field_validator("probability", mode="before")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < -1e-9:
            raise ValueError(f"probability must be non-negative, got {v}")
        return max(v, 0.0)


class PhotonicSimulationResult(pydantic.BaseModel):
    """Output of a linear-optics photonic chip simulation.

    amplitudes    All computed (fock_in, fock_out) pairs with amplitudes/probs.
    post_select   Probability of measuring within the post-selected Fock subspace
                  (e.g. dual-rail qubit subspace for the PMS chip).
    chip_config   The phase vector / architecture used.

    Dual-rail qubit mapping (PMS chip):
        |00⟩ ↔ (0,1,0,1,0,0)
        |01⟩ ↔ (0,1,0,0,1,0)
        |10⟩ ↔ (0,0,1,1,0,0)
        |11⟩ ↔ (0,0,1,0,1,0)
    """
    circuit:                PhotonicCircuitSpec
    input_fock_state:       FockState
    amplitudes:             list[FockAmplitude]    = []
    post_select_probability: float | None          = None
    expectation_value:      float | None           = None   # ⟨H⟩ from weighted sum


# ---------------------------------------------------------------------------
# Hong-Ou-Mandel interference
# ---------------------------------------------------------------------------

class HOMSpec(pydantic.BaseModel):
    """Experimental configuration for a Hong-Ou-Mandel measurement.

    Two photons are sent into a 50/50 beamsplitter; the HOM dip measures
    their temporal / spectral overlap (indistinguishability).
    delay_ps     time delay between the two input photons (ps)
    """
    beamsplitter_transmissivity:  float = 0.5
    delay_ps:                     float = 0.0      # temporal offset from zero-delay
    polarisation_alignment:       bool  = True     # whether polarisations are matched


class HOMResult(pydantic.BaseModel):
    """Result of a Hong-Ou-Mandel dip measurement.

    raw_visibility       V_HOM = (C_dist - C_hom) / C_dist, uncorrected
    corrected_M          indistinguishability M after correcting for g²(0),
                         setup losses, and beamsplitter imbalance (Faurby Ch.4.3.1)
    coincidence_rate_hz  measured 2-photon coincidence rate at zero delay
    accidentals_hz       accidental coincidences from non-zero-delay reference
    """
    spec:                HOMSpec
    raw_visibility:      float
    corrected_M:         float | None        = None
    g2_zero:             float | None        = None   # measured purity at same run
    coincidence_rate_hz: float | None        = None
    accidentals_hz:      float | None        = None
    num_events:          int   | None        = None

    @pydantic.field_validator("raw_visibility", mode="before")
    @classmethod
    def _unit_interval(cls, v: float) -> float:
        if not (-0.01 <= v <= 1.01):
            raise ValueError(f"HOM visibility must be in [0,1], got {v}")
        return v


# ---------------------------------------------------------------------------
# Photon indistinguishability purification (Faurby Ch.5)
# ---------------------------------------------------------------------------

class IndistinguishabilityPurificationSpec(pydantic.BaseModel):
    """Protocol for purifying photon indistinguishability via quantum interference.

    The scheme (Faurby 2024 Ch.5, PRL 133(3):033604) uses quantum interference
    between N input photons followed by heralded detection on a subset, improving
    the effective indistinguishability of the remaining photons independent of the
    distinguishability-inducing error source.

    n_input_photons      total photons entering the purification network
    heralding_modes      number of modes used for heralded detection
    protocol_type        "space_domain" or "time_domain" implementation
    """
    n_input_photons:          int
    heralding_modes:          int
    protocol_type:            str     = "space_domain"  # or "time_domain"
    beamsplitter_network:     str | None = None          # description of the network


class IndistinguishabilityPurificationResult(pydantic.BaseModel):
    """Measured outcome of an indistinguishability purification run.

    input_M   measured indistinguishability before purification
    output_M  measured indistinguishability of heralded output photons
    heralding_efficiency  fraction of runs where herald fires (accepted events)
    """
    spec:                     IndistinguishabilityPurificationSpec
    input_M:                  float
    output_M:                 float
    heralding_efficiency:     float | None = None
    purification_factor:      float | None = None   # output_M / input_M

    @pydantic.model_validator(mode="after")
    def _compute_factor(self) -> IndistinguishabilityPurificationResult:
        if self.purification_factor is None and self.input_M > 0:
            self.purification_factor = self.output_M / self.input_M
        return self


# ---------------------------------------------------------------------------
# Fusion-based quantum computing (FBQC)
# ---------------------------------------------------------------------------

class ResourceStateSpec(pydantic.BaseModel):
    """Specification of an entangled photonic resource state.

    Resource states are generated deterministically (or near-deterministically)
    from quantum emitters before any fusion operations are performed.
    (Faurby Ch.3: spin-photon entanglement generating time-bin Bell pairs)

    fidelity         state fidelity with ideal resource state
    generation_ns    typical time to generate one copy (nanoseconds)
    photon_source    the emitter used to generate photons
    """
    state_type:         ResourceStateType = ResourceStateType.BELL_PAIR
    num_photons:        int               = 2
    fidelity:           float | None      = None
    generation_ns:      float | None      = None
    photon_source:      SinglePhotonSourceSpec | None = None
    description:        str | None        = None


class FusionGateSpec(pydantic.BaseModel):
    """Linear-optics fusion gate specification.

    Fusion gates are probabilistic linear-optics measurements that entangle
    two resource states (Faurby Ch.3.2, "Entanglement fusion").

    Type-I fusion: one photon per input, P(success) = 1/2.
    Type-II fusion: two photons per input (dual-rail), P(success) = 1/2, but
    generates more entanglement per success event.

    input_modes_a / input_modes_b  mode indices of the two resource state inputs
    success_probability  theoretical maximum (1/2 for linear optics without
                         ancilla photons); can be boosted to ~3/4 with ancillae
    fidelity             measured Bell-state fidelity of the fused output
    """
    fusion_type:           FusionType      = FusionType.TYPE_II
    input_modes_a:         list[int]       = []
    input_modes_b:         list[int]       = []
    beamsplitter:          BeamsplitterSpec = pydantic.Field(
        default_factory=lambda: BeamsplitterSpec(target_transmissivity=0.5)
    )
    success_probability:   float | None    = None
    fidelity:              float | None    = None
    post_select_outcome:   list[int]       = []   # detector click pattern that heralds success


class FBQCRunConfig(pydantic.BaseModel):
    """Configuration for a fusion-based quantum computing experiment or simulation.

    Faurby 2024 Ch.3: spin-fusion demonstration (time-like fusion of emitter-
    generated Bell pairs). Generalised here to track the full resource-state
    generation + fusion network pipeline.

    logical_qubits        target number of logical qubits
    fusion_network        list of fusion gates in topological order
    resource_states       list of resource state specs consumed per layer
    error_budget          per-component error contributions (photon loss,
                          fusion failure, source impurity, etc.)
    """
    logical_qubits:     int
    resource_states:    list[ResourceStateSpec] = []
    fusion_network:     list[FusionGateSpec]    = []
    error_budget:       dict[str, float]        = {}   # component → error rate
    pic_spec:           PICSpec | None          = None


# ---------------------------------------------------------------------------
# Photonic analog quantum simulation (Faurby Ch.6)
# ---------------------------------------------------------------------------

class PhotonicAnalogSimConfig(pydantic.BaseModel):
    """Configuration for photonic analog quantum simulation.

    Faurby Ch.6: a programmable Si PIC (large reprogrammable silicon chip)
    implements the Metropolis algorithm to sample ground-state spin configurations
    of disordered spin systems (Ising / Heisenberg / XY models).

    hamiltonian_type   spin model simulated
    num_spins          number of spin sites
    coupling_matrix    J_{ij} exchange couplings (n×n, symmetric)
    external_fields    h_i transverse or longitudinal field per site
    pic_spec           silicon PIC used as the sampling engine
    algorithm          sampling algorithm ("metropolis", "exact_diagonalisation")
    num_samples        number of Metropolis MC steps
    """
    hamiltonian_type:   PhotonicAnalogHamiltonian = PhotonicAnalogHamiltonian.ISING
    num_spins:          int
    coupling_matrix:    list[list[float]]          = []   # J_{ij}
    external_fields:    list[float]                = []   # h_i
    pic_spec:           PICSpec | None             = None
    algorithm:          str   = "metropolis"
    num_samples:        int   = 1000
    temperature:        float | None               = None   # k_B T / J (reduced)
    random_seed:        int   | None               = None

    @pydantic.model_validator(mode="after")
    def _check_coupling_shape(self) -> PhotonicAnalogSimConfig:
        n = self.num_spins
        if self.coupling_matrix:
            if len(self.coupling_matrix) != n or any(len(r) != n for r in self.coupling_matrix):
                raise ValueError(f"coupling_matrix must be {n}×{n}")
        return self


class PhotonicAnalogSimResult(pydantic.BaseModel):
    """Results of a photonic analog spin simulation.

    sampled_configs    list of spin configurations {±1}^n sampled by the PIC
    energies           energy of each sampled configuration
    acceptance_rate    Metropolis acceptance fraction
    ground_state_energy_estimate  minimum energy found across all samples
    two_point_correlations         ⟨σ_i σ_j⟩ correlation matrix
    """
    config:                         PhotonicAnalogSimConfig
    sampled_configs:                list[list[int]]      = []   # each ∈ {-1, +1}^n
    energies:                       list[float]          = []
    acceptance_rate:                float | None         = None
    ground_state_energy_estimate:   float | None         = None
    two_point_correlations:         list[list[float]]    = []   # n×n


# ---------------------------------------------------------------------------
# Backend constructor helper
# ---------------------------------------------------------------------------

class PhotonicBackendSpec(pydantic.BaseModel):
    """Backend descriptor for photonic chip simulators and hardware.

    Extends the generic BackendSpec concept for photonic-specific fields.
    Can be stored in BackendSpec.auth for cross-modality serialisation, or
    used standalone.
    """
    name:            str
    simulator:       bool             = True
    pic_spec:        PICSpec | None   = None
    source_spec:     SinglePhotonSourceSpec | None = None
    library:         str | None       = None   # "photochipsim", "strawberry_fields", "perceval", ...
    library_version: str | None       = None
