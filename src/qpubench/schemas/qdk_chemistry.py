"""QDK / QuNorth quantum-chemistry pipeline schemas.

Covers the full pipeline implemented in the Microsoft QDK chemistry course
(chapters 1–7): molecular structure → SCF → orbital localisation → active
space selection → MACIS ASCI → Hamiltonian construction → qubit mapping →
state preparation → QPE/IQPE, plus QDK resource estimation and model
Hamiltonians (Ising, Heisenberg, Hubbard, Hückel, PPP).

Schema version: 1.5.0
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class CoordinateUnit(str, enum.Enum):
    ANGSTROM = "angstrom"
    BOHR     = "bohr"


class SCFMethod(str, enum.Enum):
    HF  = "hf"
    DFT = "dft"


class OrbitalLocalizerType(str, enum.Enum):
    MP2_NATURAL_ORBITALS = "mp2_natural_orbitals"
    PIPEK_MEZEY          = "pipek_mezey"
    VVHV                 = "vvhv"
    FOSTER_BOYS          = "foster_boys"


class ActiveSpaceSelectorType(str, enum.Enum):
    QDK_VALENCE      = "qdk_valence"
    PYSCF_AVAS       = "pyscf_avas"
    QDK_AUTOCAS      = "qdk_autocas"
    QDK_AUTOCAS_EOS  = "qdk_autocas_eos"
    QDK_OCCUPATION   = "qdk_occupation"


class MCCalculatorType(str, enum.Enum):
    MACIS_ASCI = "macis_asci"
    MACIS_CAS  = "macis_cas"
    PMC        = "projected_multi_configuration"


class QubitEncodingType(str, enum.Enum):
    JORDAN_WIGNER = "jordan-wigner"
    BRAVYI_KITAEV = "bravyi-kitaev"
    PARITY        = "parity"


class StatePrepMethod(str, enum.Enum):
    SPARSE_ISOMETRY_GF2X    = "sparse_isometry_gf2x"
    QISKIT_REGULAR_ISOMETRY = "qiskit_regular_isometry"


class TimeEvolutionBuilderType(str, enum.Enum):
    TROTTER              = "trotter"
    QDRIFT               = "qdrift"
    PARTIALLY_RANDOMIZED = "partially_randomized"


class QPEMethod(str, enum.Enum):
    ITERATIVE        = "iterative"
    STANDARD_TEXTBOOK = "standard_textbook"


class LatticeTopology(str, enum.Enum):
    CHAIN    = "chain"
    RING     = "ring"
    PATCH    = "patch"
    TORUS    = "torus"


class BoundaryCondition(str, enum.Enum):
    OPEN     = "open"
    PERIODIC = "periodic"


class ModelHamiltonianType(str, enum.Enum):
    ISING          = "ising"
    HEISENBERG_XXX = "heisenberg_xxx"
    HEISENBERG_XXZ = "heisenberg_xxz"
    HEISENBERG_XYZ = "heisenberg_xyz"
    HUBBARD        = "hubbard"
    HUCKEL         = "huckel"
    PPP            = "ppp"


class QubitParamsType(str, enum.Enum):
    """Microsoft QDK resource estimator qubit parameter presets.

    GATE_US_E3/E4  — gate-based µs-timescale qubits (superconducting) with
                     10⁻³ or 10⁻⁴ physical error rate.
    GATE_NS_E3/E4  — gate-based ns-timescale qubits with 10⁻³ or 10⁻⁴ error.
    MAJ_NS_E4/E6   — Majorana-based ns-timescale qubits with 10⁻⁴ or 10⁻⁶.
    """
    GATE_US_E3 = "qubit_gate_us_e3"
    GATE_US_E4 = "qubit_gate_us_e4"
    GATE_NS_E3 = "qubit_gate_ns_e3"
    GATE_NS_E4 = "qubit_gate_ns_e4"
    MAJ_NS_E4  = "qubit_maj_ns_e4"
    MAJ_NS_E6  = "qubit_maj_ns_e6"


class QECScheme(str, enum.Enum):
    SURFACE_CODE = "surface_code"
    FLOQUET_CODE = "floquet_code"


# ---------------------------------------------------------------------------
# Molecular structure
# ---------------------------------------------------------------------------

class AtomSpec(pydantic.BaseModel):
    """Single atom in a molecular geometry."""
    symbol: str
    x:      float
    y:      float
    z:      float


class MoleculeStructureSpec(pydantic.BaseModel):
    """Molecular geometry and charge/spin metadata.

    Mirrors the XYZ file format consumed by Structure.from_xyz_file() in
    qdk_chemistry.data.Structure.  atoms holds one entry per atom; units
    specifies whether coordinates are in Angström (default) or Bohr.
    """
    atoms:            list[AtomSpec]
    charge:           int            = 0
    spin_multiplicity: int           = 1   # 2S+1; 1 = singlet, 2 = doublet, …
    units:            CoordinateUnit = CoordinateUnit.ANGSTROM
    name:             str | None     = None
    xyz_source:       str | None     = None   # filename or label for provenance

    @property
    def num_atoms(self) -> int:
        return len(self.atoms)

    @property
    def formula(self) -> str:
        from collections import Counter
        counts = Counter(a.symbol for a in self.atoms)
        return "".join(f"{sym}{cnt if cnt > 1 else ''}" for sym, cnt in sorted(counts.items()))


# ---------------------------------------------------------------------------
# SCF (Hartree-Fock / DFT)
# ---------------------------------------------------------------------------

class SCFRunConfig(pydantic.BaseModel):
    """SCF solver configuration.

    basis_or_guess  Gaussian basis set string ("cc-pvdz", "sto-3g", …) or
                    initial guess type ("sad", "gwh").
    functional      DFT exchange-correlation functional (method=DFT only).
    convergence     Energy convergence threshold (Hartree).
    """
    method:           SCFMethod = SCFMethod.HF
    basis_or_guess:   str       = "cc-pvdz"
    functional:       str | None = None   # e.g. "b3lyp", "pbe0"
    convergence:      float     = 1.0e-9
    max_cycles:       int       = 200
    stability_check:  bool      = False   # run wavefunction stability analysis


class SCFResult(pydantic.BaseModel):
    """Hartree-Fock / DFT single-point result.

    hf_energy            Total SCF energy (Hartree).
    orbital_energies     Canonical MO eigenvalues (Hartree), ordered by index.
    orbital_occupations  Occupation numbers (0.0, 1.0, or 2.0 for RHF).
    num_basis_functions  Number of AO basis functions (= MO count for RHF).
    stable               True if wavefunction passed stability check.
    """
    hf_energy:              float
    num_alpha:              int
    num_beta:               int
    num_basis_functions:    int
    orbital_energies:       list[float]        = []
    orbital_occupations:    list[float]        = []
    stable:                 bool | None        = None


# ---------------------------------------------------------------------------
# Orbital localisation
# ---------------------------------------------------------------------------

class OrbitalLocalizationConfig(pydantic.BaseModel):
    """Configuration for an orbital localisation step.

    num_active_electrons / num_active_orbitals define the valence window
    passed alongside the localisation request.
    """
    localizer_type:         OrbitalLocalizerType
    num_active_electrons:   int | None = None
    num_active_orbitals:    int | None = None


class OrbitalLocalizationResult(pydantic.BaseModel):
    """Result of orbital localisation.

    alpha_indices / beta_indices are the (zero-based) MO indices of the
    active space after localisation, as returned by
    Orbitals.get_active_space_indices().
    """
    localizer_type:    OrbitalLocalizerType
    alpha_indices:     list[int]
    beta_indices:      list[int]
    num_active_electrons: int
    num_active_orbitals:  int


# ---------------------------------------------------------------------------
# Active space selection
# ---------------------------------------------------------------------------

class OrbitalEntanglementEntropies(pydantic.BaseModel):
    """Single-orbital and pairwise entanglement entropies from 1-RDM / 2-RDM.

    single_orbital_entropies  s₁(i) for each active orbital — the primary
                               autoCAS selection criterion.
    mutual_info_matrix        I(i,j) pairwise mutual information — stored as
                               a flattened list in row-major order (n×n).
    """
    single_orbital_entropies: list[float]
    mutual_info_matrix:       list[float] = []   # flattened n×n; empty = not computed
    num_orbitals:             int


class ActiveSpaceSelectionConfig(pydantic.BaseModel):
    """Configuration for an active space selector.

    ao_labels  Atomic orbital labels for AVAS ("N 2s", "N 2p", …).
    entropy_threshold  autoCAS cutoff on s₁(i) — below this → frozen.
    num_active_electrons / num_active_orbitals  Manual override for
    qdk_valence; ignored by entropy-based selectors.
    """
    selector_type:          ActiveSpaceSelectorType
    ao_labels:              list[str]   = []
    entropy_threshold:      float | None = None
    num_active_electrons:   int | None  = None
    num_active_orbitals:    int | None  = None


class ActiveSpaceSelectionResult(pydantic.BaseModel):
    """Result of active space selection."""
    selector_type:          ActiveSpaceSelectorType
    alpha_indices:          list[int]
    beta_indices:           list[int]
    num_active_electrons:   int
    num_active_orbitals:    int
    num_qubits:             int   # = 2 × num_active_orbitals (Jordan-Wigner)
    entanglement_entropies: OrbitalEntanglementEntropies | None = None


# ---------------------------------------------------------------------------
# Multi-configuration (SCI / MACIS / PMC)
# ---------------------------------------------------------------------------

class DeterminantSpec(pydantic.BaseModel):
    """A single Slater determinant with its CI coefficient.

    alpha_occupations / beta_occupations are the zero-based orbital indices
    of the occupied spin-orbitals (the "string" representation).
    """
    alpha_occupations: list[int]   # sorted occupied α spin-orbital indices
    beta_occupations:  list[int]   # sorted occupied β spin-orbital indices
    coefficient:       float


class SCIWavefunctionSpec(pydantic.BaseModel):
    """Selected-configuration-interaction wavefunction.

    Stores the most important determinants (up to max_stored_dets) and
    summary statistics.  Full RDMs are described by their shape only —
    storing them inline would make records impractically large.

    sci_energy              Variational SCI energy (Hartree).
    has_one_rdm / has_two_rdm  Whether 1-RDM / 2-RDM were computed
                                (required by autoCAS-EOS).
    """
    calculator_type:          MCCalculatorType
    sci_energy:               float
    num_determinants:         int
    num_active_electrons_alpha: int
    num_active_electrons_beta:  int
    num_active_orbitals:      int
    has_one_rdm:              bool = False
    has_two_rdm:              bool = False
    top_determinants:         list[DeterminantSpec] = []   # subset for QPE state prep
    core_selection_strategy:  str | None = None   # e.g. "fixed", "dynamic"


# ---------------------------------------------------------------------------
# Fermionic Hamiltonian
# ---------------------------------------------------------------------------

class FermionicHamiltonianSpec(pydantic.BaseModel):
    """Fermionic (second-quantised) active-space Hamiltonian metadata.

    Stores size information rather than the full integral tensors —
    one-body integrals are an n×n matrix (n² entries), two-body integrals
    are an n×n×n×n tensor (n⁴ entries, dominant scaling term).

    core_energy   Energy of frozen electrons + nuclear repulsion (Hartree);
                  added as the identity term when building the qubit Hamiltonian.
    schatten_norm ‖H‖₁ = Σ|hᵢⱼ|; sets QPE evolution time T_max = π/‖H‖₁.
    """
    num_active_orbitals:          int
    num_active_electrons_alpha:   int
    num_active_electrons_beta:    int
    core_energy:                  float
    num_one_body_integrals:       int          # = n²
    num_two_body_integrals:       int          # = n⁴
    schatten_norm:                float | None = None


# ---------------------------------------------------------------------------
# Model Hamiltonians (Chapter 7 — Ising, Heisenberg, Hubbard, Hückel, PPP)
# ---------------------------------------------------------------------------

class LatticeGraphSpec(pydantic.BaseModel):
    """Lattice geometry for model Hamiltonians.

    coupling_matrix  Optional explicit J-matrix (flattened, row-major) for
                     non-uniform couplings; if empty, uniform coupling from
                     model params is assumed.
    """
    topology:          LatticeTopology
    num_sites:         int
    boundary_condition: BoundaryCondition = BoundaryCondition.OPEN
    coupling_matrix:   list[float]        = []   # flattened n×n; empty = uniform


class IsingParams(pydantic.BaseModel):
    """Transverse-field Ising model: H = -J Σ ZᵢZⱼ - h Σ Xᵢ."""
    J:   float   # ZZ coupling strength (Hartree or dimensionless)
    h:   float   # transverse field strength
    J_2: float = 0.0   # next-nearest-neighbour coupling


class HeisenbergParams(pydantic.BaseModel):
    """Heisenberg model: H = J Σ (Jx XᵢXⱼ + Jy YᵢYⱼ + Jz ZᵢZⱼ) - Σ hα Sᵢα.

    For XXX: Jx = Jy = Jz = J.
    For XXZ: Jx = Jy = J, Jz = Delta * J.
    """
    J:    float
    Jx:   float = 1.0   # relative x coupling (normalised to J)
    Jy:   float = 1.0   # relative y coupling
    Jz:   float = 1.0   # relative z coupling (Delta for XXZ)
    h_x:  float = 0.0   # external field x-component
    h_y:  float = 0.0
    h_z:  float = 0.0


class HubbardParams(pydantic.BaseModel):
    """Fermi-Hubbard model: H = -t Σ cᵢ†cⱼ + U Σ nᵢ↑nᵢ↓ - μ Σ nᵢ."""
    t:  float          # hopping amplitude
    U:  float          # on-site Coulomb repulsion
    mu: float = 0.0    # chemical potential


class HuckelParams(pydantic.BaseModel):
    """Hückel (tight-binding) model for π electrons.

    alpha  Coulomb integral (on-site energy, Hartree).
    t      Resonance integral / hopping (off-diagonal, Hartree).
    """
    alpha: float = 0.0
    t:     float = -1.0   # convention: negative for bonding


class PPPParams(pydantic.BaseModel):
    """Pariser-Parr-Pople model (extended Hückel with Ohno potential).

    Includes Coulomb interactions between π electrons via the Ohno
    interpolation: γᵢⱼ = e² / √(rᵢⱼ² + (e²/U)²).

    ohno_z  Atomic number parameter in the Ohno potential (often Z=1 for C).
    V       Nearest-neighbour Coulomb repulsion (Hartree).
    """
    alpha:  float = 0.0
    t:      float = -1.0
    U:      float = 11.13    # on-site repulsion (eV-equivalent, Hartree units)
    V:      float = 0.0      # nearest-neighbour repulsion
    ohno_z: float = 1.0


class ModelHamiltonianSpec(pydantic.BaseModel):
    """Parameterised model Hamiltonian specification.

    Exactly one of ising/heisenberg/hubbard/huckel/ppp should be set,
    matching hamiltonian_type.
    """
    hamiltonian_type: ModelHamiltonianType
    lattice:          LatticeGraphSpec
    ising:            IsingParams      | None = None
    heisenberg:       HeisenbergParams | None = None
    hubbard:          HubbardParams    | None = None
    huckel:           HuckelParams     | None = None
    ppp:              PPPParams        | None = None

    @pydantic.model_validator(mode="after")
    def _params_match_type(self) -> ModelHamiltonianSpec:
        present = [
            k for k in ("ising", "heisenberg", "hubbard", "huckel", "ppp")
            if getattr(self, k) is not None
        ]
        expected = self.hamiltonian_type.value.split("_")[0]   # "ising", "heisenberg", …
        if len(present) > 1:
            raise ValueError(f"Only one parameter block should be set; got {present}")
        return self


# ---------------------------------------------------------------------------
# Qubit Hamiltonian
# ---------------------------------------------------------------------------

class PauliStringTerm(pydantic.BaseModel):
    """One term in a qubit Hamiltonian: coefficient × Pauli string.

    pauli_string  e.g. "XZIY" — length equals num_qubits, left-to-right qubit 0→n.
    coefficient   Real-valued coefficient (imaginary parts vanish for Hermitian H).
    """
    pauli_string: str
    coefficient:  float


class QubitHamiltonianSpec(pydantic.BaseModel):
    """Qubit (Pauli-sum) Hamiltonian metadata.

    pauli_terms is optional — omit for very large Hamiltonians where inline
    storage is impractical; use num_pauli_terms + schatten_norm for sizing.
    """
    num_qubits:      int
    num_pauli_terms: int
    schatten_norm:   float               # ‖H‖₁ = Σ|hⱼ| → T_max = π/schatten_norm
    encoding:        QubitEncodingType   = QubitEncodingType.JORDAN_WIGNER
    mapper_impl:     str                 = "qdk"   # "qdk" or "qiskit"
    evolution_time_max: float | None     = None    # π / schatten_norm (precomputed)
    pauli_terms:     list[PauliStringTerm] = []    # populated for small Hamiltonians


# ---------------------------------------------------------------------------
# State preparation
# ---------------------------------------------------------------------------

class StatePrepConfig(pydantic.BaseModel):
    """State preparation method configuration.

    num_determinants  Determinant truncation — only the top-N by |coefficient|
                      are included.  None = full SCI wavefunction.
    use_pmc_refinement  Re-optimise coefficients in the determinant subspace
                        via projected multi-configuration (PMC) before
                        building the circuit.  Increases fidelity.
    """
    method:             StatePrepMethod = StatePrepMethod.SPARSE_ISOMETRY_GF2X
    num_determinants:   int | None      = None
    use_pmc_refinement: bool            = False


class StatePrepCircuitResult(pydantic.BaseModel):
    """Compiled state-preparation circuit metrics.

    fidelity_with_target  |⟨ψ_prep|ψ_sci⟩|² — probability QPE collapses to the
                           ground state on the first shot.  1.0 for exact prep.
    export_formats  List of available export formats ("qasm3", "qsharp", "qir").
    """
    num_qubits:           int
    depth:                int
    cx_count:             int
    total_gate_count:     int
    fidelity_with_target: float | None = None
    export_formats:       list[str]    = []


# ---------------------------------------------------------------------------
# Time evolution
# ---------------------------------------------------------------------------

class TrotterConfig(pydantic.BaseModel):
    """Suzuki-Trotter product formula configuration.

    order  1 = Lie-Trotter (forward pass); 2 = Strang splitting (symmetric,
           lower error).  Order 2 reuses the boundary term between forward
           and reversed passes, giving 2n-1 step terms (not 2n).
    """
    order:          int   = 1
    num_step_terms: int | None = None   # filled in after build


class QDriftConfig(pydantic.BaseModel):
    """qDRIFT random-sampling time evolution.

    Samples Pauli terms proportional to |hⱼ| — error ∝ λ²t²/N where
    λ = Σ|hⱼ|.  Fewer step terms for large Hamiltonians but adds variance.
    """
    num_samples: int   = 100
    seed:        int   = 0


class TimeEvolutionConfig(pydantic.BaseModel):
    """Time evolution builder configuration."""
    builder_type:    TimeEvolutionBuilderType = TimeEvolutionBuilderType.TROTTER
    evolution_time:  float                    = 0.0
    trotter_config:  TrotterConfig            = pydantic.Field(default_factory=TrotterConfig)
    qdrift_config:   QDriftConfig             = pydantic.Field(default_factory=QDriftConfig)
    num_step_terms:  int | None               = None   # summary after build


# ---------------------------------------------------------------------------
# Quantum Phase Estimation
# ---------------------------------------------------------------------------

class QPEConfig(pydantic.BaseModel):
    """Quantum Phase Estimation run configuration.

    iterative (IQPE)
        1 ancilla qubit; num_bits sequential single-qubit measurements.
        Iteration k applies controlled-U^(2^(num_bits-k-1)).
        shots_per_bit majority-votes each bit (≥10 recommended).

    standard_textbook
        num_bits ancilla qubits + inverse QFT.  Produces a single exportable
        circuit (QASM / QIR for hardware).
    """
    method:              QPEMethod             = QPEMethod.ITERATIVE
    evolution_time:      float                 = 0.0   # T_max = π/schatten_norm
    num_bits:            int                   = 8     # phase register bits
    shots_per_bit:       int                   = 10    # IQPE only
    time_evolution:      TimeEvolutionConfig   = pydantic.Field(
        default_factory=TimeEvolutionConfig
    )
    qft_do_swaps:        bool                  = True   # standard QPE: final swap layer


class QPEIterationCircuitInfo(pydantic.BaseModel):
    """Metrics for one IQPE iteration circuit.

    Iteration 1 applies U^(2^(num_bits-1)) and has the greatest depth.
    """
    iteration_index:  int
    power_of_U:       int    # = 2^(num_bits - iteration - 1)
    num_qubits:       int    # 1 ancilla + n_system
    depth:            int
    cx_count:         int


class QPEResult(pydantic.BaseModel):
    """QPE execution result.

    raw_energy         Energy extracted from the measured phase bitstring.
    bitstring_msb_first  MSB-first phase register bitstring (or majority-voted
                          bits for IQPE).
    alias_branches     All energy aliases within the 2π/T_max periodicity window;
                       raw_energy is the selected branch.
    error_mha          |E_raw - E_exact| in milli-Hartree (if exact_reference set).
    quantization_limit_mha  Best achievable error at this num_bits:
                             2π / (T × 2^num_bits) × 1000.
    """
    raw_energy:              float
    bitstring_msb_first:     str
    alias_branches:          list[float]        = []
    error_mha:               float | None       = None
    quantization_limit_mha:  float | None       = None
    num_bits_used:           int                = 8
    evolution_time:          float              = 0.0
    exact_reference_energy:  float | None       = None
    iteration_circuits:      list[QPEIterationCircuitInfo] = []


# ---------------------------------------------------------------------------
# QDK Resource Estimation
# ---------------------------------------------------------------------------

class ErrorBudgetPartition(pydantic.BaseModel):
    """Error budget allocation across failure sources.

    logical_error_rate        Allowed logical error per algorithm round.
    distillation_failure_rate T-factory magic state distillation failure.
    rotation_synthesis_error  Synthesis error for non-Clifford rotations.
    The three rates should sum to the total allowed error budget.
    """
    logical_error_rate:        float = 1.0e-3
    distillation_failure_rate: float = 1.0e-4
    rotation_synthesis_error:  float = 1.0e-4


class ResourceEstimatorConfig(pydantic.BaseModel):
    """Microsoft QDK resource estimator configuration.

    qubit_params  Physical qubit model preset (gate vs. Majorana; µs vs. ns;
                  error rate target).
    qec_scheme    Quantum error correction code (surface code or Floquet code).
    error_budget  Partition of the total algorithmic error budget.
    """
    qubit_params:  QubitParamsType         = QubitParamsType.GATE_NS_E3
    qec_scheme:    QECScheme               = QECScheme.SURFACE_CODE
    error_budget:  ErrorBudgetPartition    = pydantic.Field(
        default_factory=ErrorBudgetPartition
    )


class ResourceEstimationResult(pydantic.BaseModel):
    """Physical resource estimates from the QDK resource estimator.

    num_physical_qubits  Total physical qubits required (data + ancilla + T-factory).
    runtime_seconds      Estimated algorithm wall time in seconds.
    code_distance        Surface/Floquet code distance d.
    t_factory_count      Number of T-state distillation factories.
    t_states_required    Total T gates required by the algorithm.
    """
    num_physical_qubits:  int
    runtime_seconds:      float
    num_logical_qubits:   int
    code_distance:        int
    t_factory_count:      int
    t_states_required:    int
    physical_error_rate:  float | None = None


# ---------------------------------------------------------------------------
# Noise models
# ---------------------------------------------------------------------------

class PauliNoiseSpec(pydantic.BaseModel):
    """Single-qubit Pauli channel error rates."""
    px: float = 0.0
    py: float = 0.0
    pz: float = 0.0


class DepolarizingNoiseSpec(pydantic.BaseModel):
    """Depolarising channel: applies I/X/Y/Z with equal weight p/4."""
    rate: float   # total depolarising rate per gate


class QuantumErrorProfile(pydantic.BaseModel):
    """Noise model for Qiskit Aer / QDK simulator backends.

    Maps to Qiskit NoiseModel or QDK QuantumErrorProfile.
    single_qubit_error / two_qubit_error are average gate error rates.
    """
    single_qubit_error: float | None        = None
    two_qubit_error:    float | None        = None
    readout_error:      float | None        = None
    t1_ns:              float | None        = None
    t2_ns:              float | None        = None
    pauli_noise:        PauliNoiseSpec      | None = None
    depolarizing_noise: DepolarizingNoiseSpec | None = None
    extra_params:       dict[str, Any]      = {}


# ---------------------------------------------------------------------------
# End-to-end pipeline record
# ---------------------------------------------------------------------------

class QChemPipelineSpec(pydantic.BaseModel):
    """Full quantum chemistry pipeline specification and results.

    Chains together each stage from molecular input through QPE:
      Structure → SCF → orbital localisation → active space selection →
      MACIS/SCI → fermionic Hamiltonian → qubit Hamiltonian →
      state preparation → QPE/IQPE.

    Populate only the stages actually run — fields are all optional.
    Typical gate-based QPE experiment uses all fields.
    """
    # --- Molecular input ---
    molecule:                MoleculeStructureSpec | None      = None

    # --- SCF ---
    scf_config:              SCFRunConfig | None               = None
    scf_result:              SCFResult | None                  = None

    # --- Orbital localisation ---
    localization_config:     OrbitalLocalizationConfig | None  = None
    localization_result:     OrbitalLocalizationResult | None  = None

    # --- Active space selection ---
    active_space_config:     ActiveSpaceSelectionConfig | None = None
    active_space_result:     ActiveSpaceSelectionResult | None = None

    # --- Multi-configuration wavefunction ---
    sci_wavefunction:        SCIWavefunctionSpec | None        = None

    # --- Hamiltonians ---
    fermionic_hamiltonian:   FermionicHamiltonianSpec | None   = None
    model_hamiltonian:       ModelHamiltonianSpec | None       = None  # alternative to fermionic
    qubit_hamiltonian:       QubitHamiltonianSpec | None       = None

    # --- State preparation ---
    state_prep_config:       StatePrepConfig | None            = None
    state_prep_result:       StatePrepCircuitResult | None     = None

    # --- QPE ---
    qpe_config:              QPEConfig | None                  = None
    qpe_result:              QPEResult | None                  = None

    # --- Resource estimation ---
    resource_estimator_config:  ResourceEstimatorConfig | None    = None
    resource_estimation_result: ResourceEstimationResult | None   = None

    # --- Noise ---
    noise_profile:           QuantumErrorProfile | None        = None
