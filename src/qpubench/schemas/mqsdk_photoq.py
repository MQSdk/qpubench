"""MQSdk photoq — consolidated photonic / GBS quantum-computing schemas.

This module replaces the former ``dtu_photonic`` and ``dtu_gbs`` modules,
consolidating them together with the newer developments collected in the
``photoq`` repository (MQSdk).  photoq brings together five previously separate
code bases (Photo-Q/GBS-with-pseudo-PNRD, Photo-Q/dasq_wrapper, Photo-Q/gbs_mps,
MQSdk/DTU-GBS, MQSdk/photonic_QC) plus new backends and applications.

The module covers, in order:

A. **Linear-optics photonic chips + fusion-based QC** (formerly ``dtu_photonic``):
   PMS 6-mode chip, dual-rail qubits, MZI/beamsplitter building blocks, photonic
   VQE, permanent-based amplitudes, Sobol sensitivity, single-photon sources,
   HOM interference, indistinguishability purification, Type-I/II fusion gates,
   FBQC, and photonic analog spin simulation.

B. **Gaussian Boson Sampling** (formerly ``dtu_gbs``): squeezed-state /
   covariance-matrix representation, hafnian-based probabilities, direct GBS
   sampling, graph clique finding, vibronic spectra, TDM/Borealis GBS, and CV
   cluster states.

C. **Pseudo-PNRD (click-counting) detectors and the four simulation methods**
   of the photoq paper draft *"Classical simulation of Gaussian boson sampling
   with click-counting detectors"* (Solodovnikova, Kristjuhan, Barfknecht, Bock
   Michelsen): pseudo photon-number-resolving detectors built from N multiplexed
   on/off detectors, the Kensingtonian matrix function (method i), the
   hafnian-modified distribution (method ii), the tensor-network / MPS method
   (method iii), and the brute-force / thermal POVM method (method iv), plus a
   cross-method comparison record.

D. **New backends**: the ORCA PT Series time-bin interferometer, the DTU QCloud
   REST API (tn-covariance / tn-sampling / redpitaya jobs), and the Xanadu
   Aurora dataset.  (Xanadu X8 and Borealis are already covered by the GBS
   backend enum and ``BackendSpec`` factory methods.)

E. **New application**: the minimum-dominating-set benchmark driven by the
   Binary Bosonic Solver (Park, Stepney & D'Amico, arXiv:2605.30935), and GBS
   latent-prior generation for peptide design.

Physical conventions
--------------------
- Fock states: mode-occupation tuples (n_0, n_1, ..., n_{M-1})
- Gaussian states: covariance-matrix formalism, σ_q = V + ½I → hafnian A matrix
- Beamsplitter transmissivity t: diagonal entries √t, off-diagonal i√(1-t)
- Permanents (thewalrus) for LOQC amplitudes; hafnians for GBS probabilities
- Pseudo-PNRD: paper uses M modes / N on/off detectors; the code uses lower-case
  m / n for the same quantities

Schema version: 3.1.0
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic

from .primitives import ComplexNumber


# ===========================================================================
# SECTION A — Linear-optics photonic chips + fusion-based QC
# ===========================================================================

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
# Photonic backend constructor helper
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


# ===========================================================================
# SECTION B — Gaussian Boson Sampling (Gaussian-state paradigm)
# ===========================================================================

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
    ORCA_PT_SERIES        = "orca_pt_series"           # ORCA PT-1/PT-2 time-bin interferometer
    DTU_QCLOUD            = "dtu_qcloud"               # DTU QCloud tn-sampling (REST v1)


class GBSMeasurementType(str, enum.Enum):
    """Detector model at the output of a GBS circuit."""
    FOCK       = "fock"       # photon-number-resolving (PNR) detector
    THRESHOLD  = "threshold"  # click / no-click (non-PNR, MeasureThreshold)
    PSEUDO_PNR = "pseudo_pnr" # click-counting / pseudo-PNRD (N multiplexed on/off detectors)
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

    Also the record type for GBS molecular docking (TACE-AS max-clique search),
    where nodes encode ligand-pharmacophore contacts.
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


# ===========================================================================
# SECTION C — Pseudo-PNRD (click-counting) detectors and simulation methods
# ===========================================================================
#
# The photoq paper draft ("Classical simulation of Gaussian boson sampling with
# click-counting detectors") studies GBS devices whose outputs are read by
# *pseudo photon-number-resolving detectors* (pPNRD): a single mode is
# demultiplexed across N on/off (click) detectors, and the detector reports the
# number k ∈ {0, …, N} of branches that clicked.  The paper presents four
# methods for the full click-pattern probability distribution P(k); this section
# schematises the detector, the methods, and their comparison.

class SimulationMethod(str, enum.Enum):
    """One of the paper's four click-pattern probability methods (+ variants).

    KENSINGTONIAN_FORMULA  method i  — the Kensingtonian matrix function
                           (Eq. 26, arXiv:2305.00853); the click-counting
                           analogue of the hafnian.  Code: kenform/.
    HAFNIAN_MODIFIED       method ii — Fock (hafnian) probabilities modified by
                           the pPNRD model P_{k,n}(N).  Code: kenhaf/.
    TENSOR_NETWORK_MPS     method iii — matrix-product-state simulation with a
                           truncation fidelity cutoff f_t.  Code: mps/, mps_fast/.
    BRUTE_FORCE_POVM       method iv — explicit POVM trace over the Gaussian
                           state (demultiplex + vacuum projection).  Code: ppnrd.py.
    THERMAL_POVM           method iv variant — pPNRD POVM written as a linear
                           combination of thermal Gaussians (Bourassa et al.).
    """
    KENSINGTONIAN_FORMULA = "kensingtonian_formula"
    HAFNIAN_MODIFIED      = "hafnian_modified"
    TENSOR_NETWORK_MPS    = "tensor_network_mps"
    BRUTE_FORCE_POVM      = "brute_force_povm"
    THERMAL_POVM          = "thermal_povm"


class DistributionDistanceMetric(str, enum.Enum):
    """Similarity measure between two click-pattern distributions (paper §VII C)."""
    TOTAL_VARIATION = "total_variation"    # TVD = ½ Σ|p−q|
    KL_DIVERGENCE   = "kl_divergence"      # D_KL(p‖q)
    BHATTACHARYYA   = "bhattacharyya"      # −ln Σ√(p·q)
    FIDELITY        = "fidelity"           # (Σ√(p·q))²


class PseudoPNRDSpec(pydantic.BaseModel):
    """Pseudo photon-number-resolving (click-counting) detector.

    A mode is demultiplexed across ``num_branches`` (N) on/off detectors; the
    detector reports the number of branches that clicked, k ∈ {0, …, N}.  With N
    branches a pPNRD can resolve up to N photons, but suffers a
    binning/collision error when two photons land in one branch
    (see ``pseudo_PNRD_error`` in the source).

    multiplexing   "spatial" (a demux tree of beamsplitters) or "temporal"
                   (a delay-loop demux, as on Borealis / PT Series).
    """
    num_branches:          int                # N on/off detectors per mode (paper's N)
    multiplexing:          str    = "spatial"  # "spatial" | "temporal"
    detector_efficiency:   float | None = None  # per-branch click efficiency η ∈ [0,1]
    dark_count_prob:       float | None = None  # per-branch dark-count probability

    @pydantic.field_validator("num_branches")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("num_branches (N) must be ≥ 1")
        return v

    def collision_error(self, n_photons: int) -> float:
        """P(two or more photons share a branch) for n photons into N branches.

        ways_total = C(n+N-1, n); ways_allowed = C(N, n); the complement is the
        undesired (collision) fraction.  Matches ``pseudo_PNRD_error`` in
        photoq's ``utility/ppnrd.py``.
        """
        from math import comb
        n, N = int(n_photons), self.num_branches
        if n > N:
            return 1.0
        ways_total = comb(n + N - 1, n)
        return (ways_total - comb(N, n)) / ways_total


class ClickPatternProbabilityResult(pydantic.BaseModel):
    """Full click-pattern probability distribution P(k) for a pPNRD-read GBS device.

    Produced by one of the four :class:`SimulationMethod` methods on a Gaussian
    state (given by its covariance matrix).  Each ``click_patterns`` entry is a
    tuple k = (k_0, …, k_{m-1}) with 0 ≤ k_i ≤ N, and ``probabilities`` the
    matching P(k).
    """
    num_modes:            int
    num_branches:         int                       # N click detectors per mode
    method:               SimulationMethod
    click_patterns:       list[list[int]]           = []
    probabilities:        list[float]               = []
    total_probability:    float | None              = None   # Σ P(k); sanity ≈ 1
    fock_cutoff:          int | None                = None   # Fock truncation used (methods ii–iv)
    computation_time_s:   float | None              = None

    @pydantic.model_validator(mode="after")
    def _check_lengths(self) -> ClickPatternProbabilityResult:
        if self.click_patterns and len(self.click_patterns) != len(self.probabilities):
            raise ValueError("click_patterns and probabilities must have equal length")
        return self


class KensingtonianResult(pydantic.BaseModel):
    """Kensingtonian matrix function value for a single click pattern (method i).

    The Kensingtonian is the click-counting analogue of the hafnian; its value
    gives the (unnormalised) probability of a click pattern k for a Gaussian
    state read out by N-branch pPNRDs (Eq. 9 / Eq. 26, arXiv:2305.00853).
    """
    click_pattern:   list[int]
    num_branches:    int
    value:           ComplexNumber
    probability:     float | None = None


class MPSSimulationConfig(pydantic.BaseModel):
    """Tensor-network (MPS) GBS simulation parameters (paper method iii).

    These map onto the DTU QCloud ``tn-sampling`` job parameters, which is the
    server-side successor of the DASQ Kensingtonian sampler.

    physical_dimension  Fock cutoff per mode d (QCloud 'd', 1–12).
    bond_dimension      MPS bond dimension χ (QCloud 'chi', 1–1000).
    truncation_fidelity Gate-truncation fidelity f_t; None → bond-dim-limited.
    dd                  QCloud 'dd' parameter (1–12; demux depth / doubling).
    """
    num_modes:            int
    physical_dimension:   int              = 8      # d
    bond_dimension:       int              = 100    # chi
    truncation_fidelity:  float | None     = None   # f_t ∈ (0, 1]
    dd:                   int | None       = None
    num_branches:         int | None       = None   # N pPNRD branches, if click-counting


class MethodComparison(pydantic.BaseModel):
    """Cross-method comparison on one circuit — the paper's Figs. 5–11.

    Records the per-method computation time and the distance of each method's
    click-pattern distribution from a reference method (brute force by default).
    Dictionary keys are :class:`SimulationMethod` values.
    """
    num_modes:                int
    num_branches:             int
    reference_method:         SimulationMethod = SimulationMethod.BRUTE_FORCE_POVM
    methods:                  list[SimulationMethod]       = []
    computation_time_s:       dict[str, float]             = {}   # method → seconds
    total_variation_distance: dict[str, float]             = {}   # method → TVD vs reference
    kl_divergence:            dict[str, float]             = {}   # method → D_KL vs reference
    fidelity:                 dict[str, float]             = {}   # method → distribution fidelity
    mps_truncation_fidelity:  float | None                 = None # f_t for the MPS run, if any
    mps_bond_dimension:       int | None                   = None
    mean_photon_number:       float | None                 = None
    circuit_label:            str | None                   = None  # e.g. "clements_4mode"


# ===========================================================================
# SECTION D — New backends (ORCA PT Series, DTU QCloud, Xanadu Aurora)
# ===========================================================================

# ---------------------------------------------------------------------------
# ORCA PT Series time-bin interferometer
# ---------------------------------------------------------------------------

class PTSeriesInputType(str, enum.Enum):
    """Input state fed into an ORCA PT Series time-bin interferometer."""
    GBS             = "gbs"             # squeezed-vacuum input (Gaussian boson sampling)
    FOCK            = "fock"            # single-photon Fock input per mode
    DISTINGUISHABLE = "distinguishable" # classical control: no multi-photon interference


class TimeBinInterferometerSpec(pydantic.BaseModel):
    """ORCA PT-1/PT-2 time-bin interferometer (TBI).

    A single physical beamsplitter plus one or more fibre delay loops, applied
    repeatedly so that pulses in successive time bins interfere.  Each loop
    couples every adjacent pair of the ``num_modes`` time bins, so a loop needs
    ``num_modes - 1`` beamsplitter angles; the implied unitary is num_modes ×
    num_modes.

    squeezing   Per-input-mode squeezing parameter r (GBS input); the ``input``
                bundle format that pep-q-gan consumes.
    """
    num_modes:            int                    # time bins
    num_loops:            int              = 1   # delay loops
    beamsplitter_angles:  list[float]      = []  # length num_loops * (num_modes - 1)
    phases:               list[float]      = []  # optional, same length as angles
    squeezing:            list[float]      = []  # r per input mode (GBS input)
    input_type:           PTSeriesInputType = PTSeriesInputType.GBS

    @property
    def num_angles_expected(self) -> int:
        return self.num_loops * (self.num_modes - 1)


class PTSeriesSamplingConfig(pydantic.BaseModel):
    """Configuration for an ORCA PT Series sampling run (simulated or hardware).

    device       "PT-1", "PT-2", or "simulated".  The simulated path draws
                 hafnian samples from the TBI covariance matrix (thewalrus).
    fock_cutoff  Fock cutoff used when building the conditional distributions.
    max_photons  Reject a sample above this total photon number.
    """
    interferometer:  TimeBinInterferometerSpec
    num_samples:     int              = 1000
    fock_cutoff:     int              = 12
    max_photons:     int              = 30
    device:          str              = "simulated"   # "PT-1" | "PT-2" | "simulated"
    seed:            int | None       = None


class PTSeriesSamplingResult(pydantic.BaseModel):
    """Result of an ORCA PT Series sampling run.

    samples  (num_samples × num_modes) photon counts.
    distinguishable_control  True if produced by the distinguishable-photon
                             control path (classical, no interference).
    """
    config:                  PTSeriesSamplingConfig
    samples:                 list[list[int]]  = []   # n_samples × n_modes
    mean_photon_number:      float | None     = None
    sampling_time_s:         float | None     = None
    distinguishable_control: bool             = False


# ---------------------------------------------------------------------------
# DTU QCloud REST API (v1)
# ---------------------------------------------------------------------------

class QCloudJobType(str, enum.Enum):
    """Job types accepted by the DTU QCloud REST API v1 (qcloud.dtu.dk).

    TN_COVARIANCE  build a covariance matrix server-side from {nmodes, r_db,
                   loss, basis} or an explicit gate list.
    TN_SAMPLING    tensor-network GBS sampling from a covariance matrix with MPS
                   parameters (d, chi, dd, N, n) — the successor of the DASQ
                   Kensingtonian sampler, aligned with the paper's method iii.
    REDPITAYA      drive the RedPitaya signal generator (worker 'catlab').
    """
    TN_COVARIANCE = "tn-covariance"
    TN_SAMPLING   = "tn-sampling"
    REDPITAYA     = "redpitaya"


class TNCovarianceParams(pydantic.BaseModel):
    """Parameters for a QCloud ``tn-covariance`` job.

    Either the parametric form (r_db, loss, basis ∈ {'x','p','pi4'}) or an
    explicit ``gates`` list, e.g.
    [['Sp', 1, 2], ['Sx', 1, 0], ['BS', {'theta': 'pi/4', 'phi': 0}, [1, 0]]].
    """
    nmodes:  int
    r_db:    float | None       = None
    loss:    float | None       = None
    basis:   str | None         = None   # 'x' | 'p' | 'pi4'
    gates:   list[Any] | None   = None


class TNSamplingParams(pydantic.BaseModel):
    """Parameters for a QCloud ``tn-sampling`` job.

    cov_matrix  Covariance matrix of the Gaussian state (flattened row-major).
    d           Physical (Fock) dimension, 1–12.
    chi         Bond dimension, 1–1000.
    dd          Demux-depth parameter, 1–12.
    N           Number of shots, 1–5_000_000.
    n           Number of modes / samples parameter, 1–5000.
    """
    cov_matrix: list[float]      = []
    d:          int              = 8
    chi:        int              = 100
    dd:         int              = 1
    N:          int              = 1000
    n:          int              = 1


class QCloudJobSpec(pydantic.BaseModel):
    """A job submitted to the DTU QCloud REST API v1.

    ``params`` carries the job-type-specific payload; :class:`TNCovarianceParams`
    / :class:`TNSamplingParams` document the two GBS shapes.  ``worker`` records
    the target worker if known ('catlab', 'tn-sampling').
    """
    job_type:  QCloudJobType
    params:    dict[str, Any]  = {}
    job_id:    str | None      = None
    worker:    str | None      = None
    base_url:  str             = "https://qcloud.dtu.dk"


class QCloudJobResult(pydantic.BaseModel):
    """Result / status record for a DTU QCloud job.

    covariance_matrix  Flattened covariance matrix returned by a tn-covariance job.
    samples            Photon-count samples returned by a tn-sampling job.
    """
    spec:               QCloudJobSpec
    status:             str              = "pending"   # pending | running | succeeded | failed
    covariance_matrix:  list[float]      = []
    samples:            list[list[int]]  = []
    result_data:        dict[str, Any]   = {}
    submitted_at:       str | None       = None
    completed_at:       str | None       = None


# ---------------------------------------------------------------------------
# Xanadu Aurora dataset
# ---------------------------------------------------------------------------

class AuroraExperiment(str, enum.Enum):
    """The two experiment sets in the Xanadu Aurora dataset (Nature 638, 2025)."""
    CLUSTER_STATE = "cluster_state"   # cluster-state acquisition (Fig. 3b)
    DECODER_DEMO  = "decoder_demo"    # decoder demo (Figs. 3c-d)


class AuroraDatasetSpec(pydantic.BaseModel):
    """Descriptor for a slice of the Xanadu Aurora dataset.

    Aurora is the modular photonic quantum computer of "Scaling and networking a
    modular photonic quantum computer" (Nature 638, 2025): 35 chips, 84
    squeezers, 36 PNRDs, 12 qubit modes per clock cycle.  The public dataset
    lives in the S3 bucket ``xanadu-aurora-data``; this spec pins the S3 key of
    one file so callers do not have to guess it.

    condition   For the decoder demo: 'signal' | 'random' | 'vacuum'.
    """
    experiment:       AuroraExperiment
    num_qubit_modes:  int              = 12
    condition:        str | None       = None   # decoder demo only
    basis:            str | None       = None   # cluster state: 'q' | 'p'
    batch_index:      int | None       = None
    s3_key:           str | None       = None
    size_bytes:       int | None       = None


# ===========================================================================
# SECTION E — Applications (minimum dominating set / BBS, peptide latent priors)
# ===========================================================================

# ---------------------------------------------------------------------------
# Minimum dominating set benchmark (Binary Bosonic Solver)
# ---------------------------------------------------------------------------

class DominatingSetProblemSpec(pydantic.BaseModel):
    """A minimum-dominating-set instance.

    A dominating set S ⊆ V is a set such that every vertex is in S or adjacent
    to a vertex in S; the objective is the smallest such S.  The benchmark graph
    family is generated by seed (Park, Stepney & D'Amico, arXiv:2605.30935).
    """
    num_nodes:  int
    edges:      list[tuple[int, int]]  = []
    seed:       int | None             = None


class BBSConfig(pydantic.BaseModel):
    """Binary Bosonic Solver configuration (Algorithm 1, arXiv:2605.30935).

    BBS is a gradient-free variational algorithm: it reprograms the
    interferometer angles θ each iteration, samples photons, threshold-maps them
    to a bit string, applies a learned per-bit flip layer, and evaluates the
    dominating-set cost.  ``num_iterations`` / ``num_samples`` are the paper's
    NIter / NSamp (400 / 600).
    """
    problem:          DominatingSetProblemSpec
    num_iterations:   int              = 400    # NIter
    num_samples:      int              = 600    # NSamp
    learning_rate:    float            = 1e-2
    input_state:      PTSeriesInputType = PTSeriesInputType.GBS
    num_loops:        int              = 1      # TBI delay loops (1-loop / 2-loop)
    optimiser:        str              = "nevergrad"   # "nevergrad" | "(1+1)-ES"
    backend:          GBSBackendType   = GBSBackendType.ORCA_PT_SERIES
    seed:             int | None       = None


class BBSResult(pydantic.BaseModel):
    """Outcome of one Binary Bosonic Solver run.

    convergence_iteration  I_con: earliest iteration the run could have stopped
                           without a worse answer (paper Eq. 4).
    The timing breakdown (sampling/cost/update) reproduces the paper's central
    point that photon sampling dominates the runtime.
    """
    config:                 BBSConfig
    best_bitstring:         list[int]       = []
    best_set_size:          int | None      = None
    best_energy:            float | None    = None
    is_dominating:          bool | None     = None
    energy_history:         list[float]     = []   # best-so-far per iteration
    runtime_s:              float | None    = None
    convergence_iteration:  int | None      = None
    sampling_time_s:        float | None    = None
    cost_time_s:            float | None    = None
    update_time_s:          float | None    = None
    optimiser:              str | None      = None
    sampler:                str | None      = None


class DominatingSetBenchmarkResult(pydantic.BaseModel):
    """Comparison of BBS against classical baselines over the graph family.

    Reproduces the paper's Figure 3: found set size and runtime per method and
    graph size.  ``methods`` names the entries (e.g. "BBS 1-loop (gbs)",
    "greedy", "networkx", "ilp"); the dict fields are keyed by method name and
    hold one value per entry in ``graph_sizes``.
    """
    graph_sizes:      list[int]                    = []
    methods:          list[str]                    = []
    mean_set_size:    dict[str, list[float]]       = {}   # method → per-size mean
    min_set_size:     dict[str, list[float]]       = {}
    runtime_s:        dict[str, list[float]]       = {}
    valid_fraction:   dict[str, list[float]]       = {}   # fraction of runs that were dominating
    num_seeds:        int                          = 1


# ---------------------------------------------------------------------------
# Peptide design — GBS latent priors (Pep-Q-GAN)
# ---------------------------------------------------------------------------

class LatentPriorConfig(pydantic.BaseModel):
    """Configuration for GBS latent-prior generation for peptide design.

    Generates photonic samples used as the latent prior of Pep-Q-GAN (Engdal et
    al., "Hybrid quantum-classical de novo design of MHC-binding peptides",
    bioRxiv 2026).  Upstream ships no quantum samples; photoq generates
    equivalent ones locally via the PT Series TBI.
    """
    num_modes:        int
    num_samples:      int              = 600
    squeezing:        float            = 0.5
    input_type:       PTSeriesInputType = PTSeriesInputType.GBS
    num_loops:        int              = 1
    standardise:      bool             = True   # zero-mean / unit-variance per mode
    seed:             int | None       = None


class LatentPriorResult(pydantic.BaseModel):
    """Generated GBS latent-prior bundle for peptide design.

    samples  (num_samples × num_modes) photon counts.
    analytic_mean / analytic_std  per-mode analytic moments used to standardise
                                  the bundle (matches pep-q-gan's obs.py).
    """
    config:          LatentPriorConfig
    samples:         list[list[int]]  = []
    analytic_mean:   list[float]      = []
    analytic_std:    list[float]      = []
    sampled_mean:    list[float]      = []
    sampled_std:     list[float]      = []
    generation_time_s: float | None   = None
