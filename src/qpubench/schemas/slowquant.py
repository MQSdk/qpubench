"""SlowQuant quantum chemistry schema harmonization.

Models the data produced and consumed by the SlowQuant package
(https://github.com/erikkjellgren/SlowQuant), which specializes in
unitary parameterized wave functions, linear response theory, and
hybrid classical-quantum VQE workflows via Qiskit.

SlowQuant covers:
  - Hartree-Fock / DIIS SCF
  - Unitary Coupled Cluster (UCC) — classical statevector
  - Factorized UCC (fUCC) and Truncated UPS (tUPS) — hardware-efficient ansätze
  - State-Averaged UPS (SAUPS) — excited states
  - Linear response theory — excitation energies, transition dipoles, oscillator strengths
  - Quantum circuit VQE via Qiskit — parameter-compatible with classical solvers
  - Clique-based measurement grouping and post-selection error mitigation

All parameters are classical Python scalars or flat float lists (JSON-safe).

Schema version: 1.11.0
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class UCCAnsatzType(str, enum.Enum):
    """Unitary coupled cluster / product state ansatz family.

    UCC      Standard unitary coupled cluster (non-factorized).
    FUCC     Factorized UCC — product of individual excitation unitaries.
    TUPS     Truncated Unitary Product State — hardware-efficient.
    QNP      Qubit Number Parity — preserves qubit number parity.
    SAUPS    State-Averaged UPS — simultaneous ground + excited state optimization.
    """
    UCC   = "ucc"
    FUCC  = "fucc"
    TUPS  = "tups"
    QNP   = "qnp"
    SAUPS = "saups"


class UCCExcitationLevel(str, enum.Enum):
    """Excitation level string passed to WaveFunctionUCC/UPS `excitations` parameter.

    SlowQuant accepts cumulative strings: "SD" = singles + doubles,
    "SDTQ" = through quadruples, etc.
    """
    S     = "S"
    SD    = "SD"
    SDT   = "SDT"
    SDTQ  = "SDTQ"
    SDTQ5 = "SDTQ5"
    SDTQ56 = "SDTQ56"


class UCCOptimizationMethod(str, enum.Enum):
    """Optimization strategy for UCC wavefunction parameters.

    ONE_STEP    Optimize circuit parameters (θ) only; keep MO fixed.
    TWO_STEP    Alternating θ-optimization and κ-orbital-rotation steps.
    ROTOSOLVE   RotoSolve sequential single-parameter sweeps (hardware-friendly).
    """
    ONE_STEP  = "one_step"
    TWO_STEP  = "two_step"
    ROTOSOLVE = "rotosolve"


class UCCLinearResponseType(str, enum.Enum):
    """Level of orbital response included in linear response theory.

    NAIVE              No orbital response — bare UCC response.
    PROJECTED          Projected orbital response contribution.
    SELF_CONSISTENT    Fully self-consistent orbital response (most accurate).
    STATE_TRANSFER     State-transfer linear response (alternative formulation).
    """
    NAIVE           = "naive"
    PROJECTED       = "projected"
    SELF_CONSISTENT = "self_consistent"
    STATE_TRANSFER  = "state_transfer"


# ---------------------------------------------------------------------------
# Active space
# ---------------------------------------------------------------------------

class UCCActiveSpaceConfig(pydantic.BaseModel):
    """Complete active space (CAS) specification.

    Maps to SlowQuant's `cas=[num_active_electrons, num_active_orbitals]` and
    the `include_active_kappa` orbital-optimization flag.

    num_total_electrons / num_total_orbitals describe the full molecule
    before freezing; frozen_core / frozen_virtual count inactive orbitals.
    """
    num_active_electrons:      int
    num_active_orbitals:       int
    num_total_electrons:       int | None = None
    num_total_orbitals:        int | None = None
    frozen_core_orbitals:      int        = 0
    frozen_virtual_orbitals:   int        = 0
    include_orbital_optimization: bool    = False   # SlowQuant include_active_kappa

    @property
    def num_qubits(self) -> int:
        """Jordan-Wigner qubit count for the active space (= 2 × num_active_orbitals)."""
        return 2 * self.num_active_orbitals


# ---------------------------------------------------------------------------
# Wavefunction configuration
# ---------------------------------------------------------------------------

class UCCWavefunctionConfig(pydantic.BaseModel):
    """Specification of the UCC / UPS wavefunction to construct and optimize.

    ansatz          Ansatz family (UCC, fUCC, tUPS, QNP, SAUPS).
    excitations     Excitation level string ("SD", "SDTQ", etc.).
    active_space    CAS + orbital optimization flag.
    num_states      For SAUPS: number of states in state-averaged expansion.
    ansatz_options  Ansatz-specific key-value options (passed to WaveFunctionUPS).
    spin_adapted    Use spin-adapted operators (fewer parameters, same accuracy).
    """
    ansatz:        UCCAnsatzType       = UCCAnsatzType.UCC
    excitations:   UCCExcitationLevel  = UCCExcitationLevel.SD
    active_space:  UCCActiveSpaceConfig
    num_states:    int                 = 1   # > 1 for SAUPS
    spin_adapted:  bool                = False
    ansatz_options: dict[str, Any]     = {}

    @property
    def num_qubits(self) -> int:
        return self.active_space.num_qubits


# ---------------------------------------------------------------------------
# Integral data
# ---------------------------------------------------------------------------

class UCCIntegralData(pydantic.BaseModel):
    """Molecular integral tensors produced before SCF.

    h_ao       Core (one-electron) Hamiltonian in AO basis —
               flat list of nao² entries (nao × nao, row-major).
    g_ao       Electron repulsion integrals in AO basis —
               flat list of nao⁴ entries.  Omit for large systems
               (nao > ~12) since storage grows as O(nao⁴).
    overlap_ao Overlap matrix — flat list of nao² entries.
    basis_set  Basis set name (e.g. "STO-3G", "cc-pVDZ").
    num_basis_functions  Number of AO basis functions (nao).
    """
    basis_set:             str
    num_basis_functions:   int
    h_ao:                  list[float] = []   # nao², core Hamiltonian
    g_ao:                  list[float] = []   # nao⁴, ERI; omit if large
    overlap_ao:            list[float] = []   # nao², overlap matrix


# ---------------------------------------------------------------------------
# Hartree-Fock result
# ---------------------------------------------------------------------------

class UCCSCFResult(pydantic.BaseModel):
    """Hartree-Fock SCF result — starting point for UCC optimization.

    hf_energy           Total HF energy (Hartree).
    nuclear_repulsion   Nuclear repulsion contribution (Hartree).
    num_iterations      SCF cycles until convergence.
    converged           Whether DIIS converged within the cycle limit.
    mo_energies         Canonical MO eigenvalues (Hartree), length nmo.
    orbital_occupations Occupation numbers (0.0 or 2.0 for RHF), length nmo.
    homo_index          Zero-based index of the HOMO.
    homo_lumo_gap       LUMO − HOMO gap (Hartree).
    """
    hf_energy:           float
    nuclear_repulsion:   float | None  = None
    num_iterations:      int   | None  = None
    converged:           bool          = True
    mo_energies:         list[float]   = []
    orbital_occupations: list[float]   = []
    homo_index:          int   | None  = None

    @property
    def homo_lumo_gap(self) -> float | None:
        if (
            self.homo_index is not None
            and len(self.mo_energies) > self.homo_index + 1
        ):
            return self.mo_energies[self.homo_index + 1] - self.mo_energies[self.homo_index]
        return None


# ---------------------------------------------------------------------------
# Optimization results
# ---------------------------------------------------------------------------

class UCCIterationRecord(pydantic.BaseModel):
    """Energy and gradient information for one optimization iteration."""
    iteration:    int
    energy:       float
    gradient_norm: float | None = None   # L2 norm of parameter gradient
    theta_norm:   float | None = None    # L2 norm of θ parameters


class UCCOptimizationResult(pydantic.BaseModel):
    """Result of UCC wavefunction parameter optimization.

    theta   Optimized circuit amplitude parameters (θ), length varies with
            excitation level and active space.
    kappa   Orbital rotation parameters (κ) — non-empty when
            include_orbital_optimization=True.
    iteration_history  Per-iteration energy + gradient records.
    """
    method:            UCCOptimizationMethod = UCCOptimizationMethod.ONE_STEP
    num_iterations:    int
    converged:         bool
    final_energy:      float
    theta:             list[float]            = []   # circuit amplitude params
    kappa:             list[float]            = []   # orbital rotation params
    iteration_history: list[UCCIterationRecord] = []
    gradient_norm_final: float | None         = None

    @property
    def num_theta_params(self) -> int:
        return len(self.theta)

    @property
    def num_kappa_params(self) -> int:
        return len(self.kappa)

    @property
    def correlation_energy(self) -> float | None:
        """UCC correlation energy relative to the HF reference stored externally."""
        return None   # computed externally: ucc_energy - hf_energy


# ---------------------------------------------------------------------------
# Reduced density matrices
# ---------------------------------------------------------------------------

class UCCRDMData(pydantic.BaseModel):
    """Reduced density matrices from the optimized UCC wavefunction.

    rdm1   1-electron RDM in MO basis — flat list of nact² entries.
    rdm2   2-electron RDM in MO basis — flat list of nact⁴ entries.
           Omit for nact > ~8 (storage O(nact⁴) = 4096 for nact=8).
    has_rdm3 / has_rdm4  Whether the 3- and 4-RDMs were computed
             (required for high-accuracy property evaluation).
    num_active_orbitals  Active space orbital count (nact).
    """
    num_active_orbitals: int
    rdm1:      list[float] = []   # nact², row-major
    rdm2:      list[float] = []   # nact⁴; omit if large
    has_rdm3:  bool        = False
    has_rdm4:  bool        = False


# ---------------------------------------------------------------------------
# Linear response / excited states
# ---------------------------------------------------------------------------

class UCCExcitedStateResult(pydantic.BaseModel):
    """Properties of one electronically excited state from linear response.

    excitation_energy_au   Excitation energy in Hartree.
    excitation_energy_ev   Excitation energy in electron-volts (×27.2114).
    transition_dipole      Transition dipole moment vector [µx, µy, µz] in a.u.
    oscillator_strength    Dimensionless oscillator strength f = (2/3) E |µ|².
    """
    state_index:           int
    excitation_energy_au:  float
    excitation_energy_ev:  float | None = None
    transition_dipole:     list[float]  = []   # [µx, µy, µz] a.u.
    oscillator_strength:   float | None = None

    @pydantic.model_validator(mode="after")
    def _fill_ev(self) -> UCCExcitedStateResult:
        if self.excitation_energy_ev is None and self.excitation_energy_au is not None:
            object.__setattr__(
                self, "excitation_energy_ev", self.excitation_energy_au * 27.211_386_245_988
            )
        return self


class UCCLinearResponseResult(pydantic.BaseModel):
    """Results from UCC linear response theory.

    Covers all four response levels (naive, projected, self-consistent,
    state-transfer) at any supported excitation level up to SDTQ56.
    """
    response_type:        UCCLinearResponseType    = UCCLinearResponseType.NAIVE
    excitation_level:     UCCExcitationLevel       = UCCExcitationLevel.SD
    num_states_computed:  int
    excited_states:       list[UCCExcitedStateResult] = []

    @property
    def excitation_energies_au(self) -> list[float]:
        return [s.excitation_energy_au for s in self.excited_states]

    @property
    def excitation_energies_ev(self) -> list[float | None]:
        return [s.excitation_energy_ev for s in self.excited_states]

    @property
    def oscillator_strengths(self) -> list[float | None]:
        return [s.oscillator_strength for s in self.excited_states]


# ---------------------------------------------------------------------------
# Quantum circuit metadata (VQE / Qiskit interface)
# ---------------------------------------------------------------------------

class UCCCircuitSpec(pydantic.BaseModel):
    """Quantum circuit metadata for the UCC/UPS ansatz (Qiskit-compiled).

    Records the compiled circuit properties after SlowQuant maps the
    fermionic excitation operators to qubit gates.  gate_depth and
    cx_count depend on the compiler / optimization level.

    All classical wavefunction parameters (theta, kappa) are
    parameter-compatible — the same floats can be used in both the
    classical statevector simulation and the quantum circuit.
    """
    ansatz_type:           UCCAnsatzType
    excitation_level:      UCCExcitationLevel
    num_qubits:            int
    num_parameters:        int                # len(theta) [+ len(kappa) if orbital opt]
    gate_depth:            int | None = None
    cx_count:              int | None = None
    single_qubit_gates:    int | None = None
    qubit_encoding:        str        = "jordan_wigner"
    spin_adapted:          bool       = False


class UCCMeasurementConfig(pydantic.BaseModel):
    """Measurement strategy for VQE energy evaluation on quantum hardware.

    SlowQuant uses clique-based grouping (qubit-wise commutativity) to
    reduce the number of distinct measurement circuits.  Pauli-string
    post-selection filters bitstrings that violate particle-number symmetry.

    num_cliques              Distinct commuting groups (measurement circuits).
    postselection_enabled    Filter bitstrings by particle number conservation.
    shots_per_evaluation     Total shots across all cliques per energy call.
    num_pauli_strings        Total Pauli strings in the qubit Hamiltonian.
    """
    num_cliques:          int   | None = None
    postselection_enabled: bool        = True
    shots_per_evaluation: int   | None = None
    num_pauli_strings:    int   | None = None
    error_mitigation:     str   | None = None   # e.g. "measurement_correction"


# ---------------------------------------------------------------------------
# Top-level SlowQuant job record
# ---------------------------------------------------------------------------

class SlowQuantRecord(pydantic.BaseModel):
    """Top-level SlowQuant calculation record.

    Chains together all stages of a SlowQuant UCC/VQE calculation:
      Molecule → Integrals → SCF → WavefunctionConfig →
      Optimization → [LinearResponse] → [QuantumCircuit]

    Populate only the stages actually run.  At minimum, set
    wavefunction_config + optimization_result for a UCC energy record.

    molecule_name    Human-readable molecule identifier (e.g. "H2", "LiH").
    basis_set        Basis set name, mirrors integral_data.basis_set.
    hf_energy        Reference HF energy — set from scf_result.hf_energy or
                     passed directly when SCF was run externally.
    ucc_energy       Final UCC/VQE energy from optimization_result.final_energy.
    correlation_energy  ucc_energy − hf_energy (signed; negative = correlation gain).
    """
    molecule_name:         str | None                   = None
    basis_set:             str | None                   = None

    # --- Stages ---
    integral_data:         UCCIntegralData | None        = None
    scf_result:            UCCSCFResult   | None         = None
    wavefunction_config:   UCCWavefunctionConfig | None  = None
    optimization_result:   UCCOptimizationResult | None  = None
    rdm_data:              UCCRDMData     | None         = None
    linear_response:       UCCLinearResponseResult | None = None
    circuit_spec:          UCCCircuitSpec | None         = None
    measurement_config:    UCCMeasurementConfig | None   = None

    # --- Convenience overrides (populated from stages or set directly) ---
    hf_energy:             float | None  = None
    ucc_energy:            float | None  = None
    extras:                dict[str, Any] = {}

    @property
    def correlation_energy(self) -> float | None:
        """UCC correlation energy (Hartree); negative = stabilization."""
        e_ucc = self.ucc_energy or (
            self.optimization_result.final_energy
            if self.optimization_result else None
        )
        e_hf = self.hf_energy or (
            self.scf_result.hf_energy if self.scf_result else None
        )
        if e_ucc is not None and e_hf is not None:
            return e_ucc - e_hf
        return None

    @property
    def num_qubits(self) -> int | None:
        if self.circuit_spec:
            return self.circuit_spec.num_qubits
        if self.wavefunction_config:
            return self.wavefunction_config.num_qubits
        return None
