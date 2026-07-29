"""Quantum Subspace Expansion / Krylov Quantum Diagonalization schemas.

Covers the algorithm families implemented in MQSdk/qse:

  1. Krylov Quantum Diagonalization (KQD) via Hadamard test
       Ref: Stair et al., J. Chem. Theory Comput. 16, 2236 (2020)
       Modified Hadamard test circuits measure ⟨ψ_{I,m}|O|ψ_{J,n}⟩ for each
       (reference I/J, Krylov power m/n) pair.  S and H matrices are assembled
       from these expectation values, then a regularized generalized eigenvalue
       problem H e = λ S e is solved.

  2. Sample-based Krylov Quantum Diagonalization (SKQD / SQD)
       Ref: Yu et al., arXiv:2501.09702 (2025)
       Krylov circuits U^k|Φ⟩ are measured in the computational basis.
       Bitstrings are post-selected by particle number, pooled cumulatively,
       then used to project H onto the observed subspace (SQD diagonalization).

  3. Multi-reference variants of both above
       Ref: Stair et al. (2020); O'Leary et al., Quantum 9, 1726 (2025)
       d_refs reference states {|Φ_I⟩} each seed their own Krylov series;
       the combined subspace is { U^m|Φ_I⟩ : I=0..d-1, m=0..s }.

  All three variants share: Trotter time evolution, reference state prep
  (Néel states or Slater determinants), and regularization of the S matrix.

Schema version: 1.7.0
"""
from __future__ import annotations

import enum

import pydantic

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class KQDMethod(str, enum.Enum):
    """Krylov Quantum Diagonalization algorithm variant."""
    HADAMARD_TEST            = "hadamard_test"             # modified Hadamard test, full expectation values
    SAMPLE_BASED_SQD         = "sample_based_sqd"          # SQD: measure in Fock basis, project H
    MULTI_REF_HADAMARD       = "multi_ref_hadamard"        # multi-reference Hadamard test
    MULTI_REF_SQD            = "multi_ref_sqd"             # multi-reference SQD


class KQDReferenceStateType(str, enum.Enum):
    """Type of reference state (initial vector seeding the Krylov series)."""
    NEEL             = "neel"              # alternating 1010… product state (spin chains)
    SLATER_DET       = "slater_det"        # single Slater determinant (chemistry, JW encoding)
    COMPUTATIONAL    = "computational"     # arbitrary computational-basis bitstring
    ENTANGLED        = "entangled"         # custom entangled circuit (not a product state)


class KrylovTimeEvolutionVariant(str, enum.Enum):
    """Implementation of U = e^{-iHdt} in the Krylov circuit."""
    LIE_TROTTER            = "lie_trotter"             # Qiskit PauliEvolutionGate + LieTrotter
    EFFICIENT_ALTERNATING  = "efficient_alternating"   # alternating forward/reverse Rxyz blocks


class EigensolverMethod(str, enum.Enum):
    """Classical eigensolver used for the generalized eigenvalue problem."""
    SCIPY_EIGH   = "scipy_eigh"    # scipy.linalg.eigh (dense, regularized)
    SCIPY_EIGSH  = "scipy_eigsh"   # scipy.sparse.linalg.eigsh (sparse, k eigenvalues)
    NUMPY_EIGVALSH = "numpy_eigvalsh"   # np.linalg.eigvalsh (fallback for tiny subspaces)


# ---------------------------------------------------------------------------
# Reference state specification
# ---------------------------------------------------------------------------

class NeelStateSpec(pydantic.BaseModel):
    """Néel (alternating spin) product state for spin-chain Hamiltonians.

    shift=0 → 1010…  (qubits 0, 2, 4, … set to |1⟩)
    shift=1 → 0101…  (qubits 1, 3, 5, … set to |1⟩)
    The two shifts together span both Néel sectors — used as the default
    two-reference set for antiferromagnetic chain benchmarks.
    """
    num_spins:  int
    shift:      int = 0   # 0 or 1


class SlaterDeterminantRef(pydantic.BaseModel):
    """Slater determinant reference state in the JW spin-orbital encoding.

    The bitstring layout is: alpha block [0..ncas-1] then beta block [ncas..2ncas-1].
    occ_alpha / occ_beta list zero-based orbital indices of occupied spin-orbitals.
    Used for molecular Hamiltonians (H2, LiH, N2 active spaces).
    """
    ncas:       int         # number of active orbitals (spatial)
    occ_alpha:  list[int]   # occupied α spin-orbital indices (0-based, length = n_α)
    occ_beta:   list[int]   # occupied β spin-orbital indices (0-based, length = n_β)

    @property
    def num_qubits(self) -> int:
        return 2 * self.ncas

    @property
    def bitstring(self) -> str:
        """Produce the JW bitstring: alpha block ++ beta block."""
        bits = ["0"] * self.num_qubits
        for p in self.occ_alpha:
            bits[p] = "1"
        for p in self.occ_beta:
            bits[self.ncas + p] = "1"
        return "".join(bits)

    @property
    def num_electrons(self) -> int:
        return len(self.occ_alpha) + len(self.occ_beta)


class KQDReferenceSpec(pydantic.BaseModel):
    """Specification for one reference state seeding the Krylov series.

    bitstring  The computational-basis bitstring |Φ_I⟩ used in the SQD path
               and as the controlled-preparation target in the Hadamard test.
    neel       Populated when state_type = NEEL.
    slater_det Populated when state_type = SLATER_DET.
    """
    state_type:  KQDReferenceStateType    = KQDReferenceStateType.NEEL
    bitstring:   str                      = ""     # pre-computed bitstring (all paths)
    neel:        NeelStateSpec | None     = None
    slater_det:  SlaterDeterminantRef | None = None
    label:       str | None              = None    # human-readable label, e.g. "ref0"


# ---------------------------------------------------------------------------
# Time evolution configuration (KQD-specific)
# ---------------------------------------------------------------------------

class KQDTimeEvolutionSpec(pydantic.BaseModel):
    """Time evolution U = e^{-iHdt} configuration for KQD circuits.

    dt          Total evolution time per Krylov step.  Typically set to
                π / ‖H‖₂ (spectral norm) so that the Krylov basis spans
                the full phase range in krylov_dim steps.
    dt_circ     Time step per Trotter repetition: dt / num_trotter_steps.
    num_trotter_steps  Number of Trotter repetitions per Krylov step.
    variant     Circuit implementation choice.
    """
    dt:                    float
    num_trotter_steps:     int              = 6
    variant:               KrylovTimeEvolutionVariant = KrylovTimeEvolutionVariant.EFFICIENT_ALTERNATING

    @property
    def dt_circ(self) -> float:
        return self.dt / max(self.num_trotter_steps, 1)


# ---------------------------------------------------------------------------
# Krylov circuit family specification
# ---------------------------------------------------------------------------

class KrylovCircuitFamilySpec(pydantic.BaseModel):
    """Metadata about the full family of Krylov measurement circuits.

    Hadamard test (single-ref): krylov_dim circuits.
    Hadamard test (multi-ref):  d_refs² × krylov_dim² circuits (I, J, m, n tuples).
    SQD (single-ref):           krylov_dim circuits (each measured in Fock basis).
    SQD (multi-ref):            d_refs × krylov_dim circuits.

    circuit_labels  Tuples encoding which (ref_index, krylov_power) or
                    (I, J, m, n) each circuit corresponds to.
    total_shots     Total measurement budget across all circuits.
    shots_per_circuit  Shots allocated to each circuit (uniform budget).
    ancilla_qubits  1 for Hadamard test; 0 for SQD (no ancilla needed).
    """
    method:             KQDMethod
    num_qubits_system:  int
    krylov_dim:         int
    num_references:     int              = 1
    num_circuits:       int              = 0    # filled in after build
    circuit_labels:     list[list[int]]  = []   # each entry: [I, rep] or [I, J, m, n]
    shots_per_circuit:  int | None       = None
    total_shots:        int | None       = None
    ancilla_qubits:     int              = 0    # 1 for Hadamard test


# ---------------------------------------------------------------------------
# Krylov S and H matrices
# ---------------------------------------------------------------------------

class KrylovMatrixSpec(pydantic.BaseModel):
    """One of the subspace matrices (S overlap or H Hamiltonian projection).

    Stored as flattened real and imaginary parts; shape is dim × dim where
    dim = num_references × krylov_dim.

    The matrices satisfy:
      S[I*s+m, J*s+n] = ⟨Φ_I|U^†^m U^n|Φ_J⟩
      H[I*s+m, J*s+n] = ⟨Φ_I|U^†^m H U^n|Φ_J⟩
    where s = krylov_dim.
    """
    label:          str          # "S" or "H"
    dim:            int          # = num_references × krylov_dim
    matrix_real:    list[float]  # flattened dim×dim
    matrix_imag:    list[float]  # flattened dim×dim; near-zero for Hermitian H


class KrylovSubspaceMatrices(pydantic.BaseModel):
    """Assembled S (overlap) and H (projected Hamiltonian) matrices.

    assembly_method  How matrix elements were obtained:
      "hadamard_test"  — expectation values from modified Hadamard test circuits
      "stabilizer"     — exact from StabilizerState (small test cases)
    """
    S_matrix:          KrylovMatrixSpec
    H_matrix:          KrylovMatrixSpec
    assembly_method:   str   = "hadamard_test"
    num_references:    int   = 1
    krylov_dim:        int   = 1


# ---------------------------------------------------------------------------
# Hadamard test observables and results
# ---------------------------------------------------------------------------

class HadamardTestObservableSpec(pydantic.BaseModel):
    """One observable measured in a Hadamard test circuit.

    For the S matrix:  ancilla ⊗ I…I → ancilla measures X (real) or Y (imag).
    For the H matrix:  ancilla ⊗ P_j  → ancilla measures X or Y, system measures P_j.

    matrix_type   "S" (overlap) or "H" (Hamiltonian term).
    pauli_string  Full Pauli string of length n_system + 1 (ancilla first or last).
    coeff         Hamiltonian coefficient h_j (only for H-type; 1.0 for S-type).
    quadrature    "real" (X observable on ancilla) or "imag" (Y observable).
    """
    matrix_type:   str     # "S" or "H"
    pauli_string:  str
    coeff:         float   = 1.0
    quadrature:    str     = "real"   # "real" or "imag"


class HadamardTestIterationResult(pydantic.BaseModel):
    """Expectation value result for one (circuit, observable) pair.

    circuit_label  The (I, rep) or (I, J, m, n) index of the circuit.
    matrix_element_index  Flat index into the S or H matrix.
    """
    circuit_label:        list[int]   # [I, rep] or [I, J, m, n]
    observable_index:     int
    real_part:            float
    imag_part:            float = 0.0


# ---------------------------------------------------------------------------
# Regularized generalized eigenvalue problem
# ---------------------------------------------------------------------------

class RegularizationConfig(pydantic.BaseModel):
    """Configuration for regularizing the S matrix before eigenvalue solve.

    The S matrix may be rank-deficient when the Krylov vectors are nearly
    linearly dependent.  Regularization discards eigenmodes with eigenvalue
    below threshold before solving the generalized problem H e = λ S e.

    threshold          Minimum S eigenvalue to retain (ε in the code).
    num_eigenvalues_k  Number of lowest eigenvalues to compute (k in eigsh).
    solver             Classical linear algebra backend.
    """
    threshold:          float              = 1.0e-6
    num_eigenvalues_k:  int                = 2
    solver:             EigensolverMethod  = EigensolverMethod.SCIPY_EIGH


class KrylovEigenResult(pydantic.BaseModel):
    """Result of the regularized generalized eigenvalue solve.

    eigenvalues                 All resolved eigenvalues in the Krylov subspace,
                                sorted ascending (Hartree or dimensionless).
    ground_state_energy         Lowest eigenvalue (best ground state estimate).
    S_eigenvalues               Eigenvalues of S before regularization — useful
                                for diagnosing subspace quality and threshold choice.
    num_eigenvalues_discarded   Number of S modes removed by regularization.
    krylov_dim_effective        Number of retained S modes (= dim - discarded).
    """
    eigenvalues:                list[float]
    ground_state_energy:        float
    S_eigenvalues:              list[float]  = []
    num_eigenvalues_discarded:  int          = 0
    krylov_dim_effective:       int          = 0


# ---------------------------------------------------------------------------
# Sample-based KQD (SQD path)
# ---------------------------------------------------------------------------

class SQDPostselectionConfig(pydantic.BaseModel):
    """Particle-number post-selection for the SQD path.

    Bitstrings whose Hamming weight (number of 1s) differs from num_ones
    are discarded.  This enforces particle number conservation and removes
    non-physical Krylov vectors from the subspace.

    num_ones         Expected number of 1-bits per valid bitstring.
                     Typically = total electrons in the active space.
    min_unique       Minimum number of unique post-selected bitstrings
                     required to attempt diagonalization; if fewer are
                     available, the step energy is recorded as NaN.
    """
    num_ones:     int
    min_unique:   int  = 1


class SQDStep(pydantic.BaseModel):
    """SQD energy at one cumulative Krylov step.

    krylov_step       Step index r (0-based: step r uses circuits 0..r).
    num_bitstrings    Unique post-selected bitstrings in the subspace.
    subspace_dim      Projected subspace dimension (= num_bitstrings rows).
    energy_hartree    Ground state energy from subspace diagonalization,
                      or NaN if num_bitstrings < min_unique.
    """
    krylov_step:      int
    num_bitstrings:   int
    subspace_dim:     int
    energy_hartree:   float | None   = None   # None if subspace too small


class SQDConvergenceResult(pydantic.BaseModel):
    """SQD energy convergence across all cumulative Krylov steps.

    steps                One entry per Krylov step (length = krylov_dim).
    final_energy         Energy at the last step (best estimate).
    exact_energy         Exact ground state energy for comparison (if known).
    error_mha            |final_energy - exact_energy| × 1000 (milli-Hartree).
    """
    steps:               list[SQDStep]  = []
    final_energy:        float | None   = None
    exact_energy:        float | None   = None

    @property
    def error_mha(self) -> float | None:
        if self.final_energy is None or self.exact_energy is None:
            return None
        return abs(self.final_energy - self.exact_energy) * 1000.0


# ---------------------------------------------------------------------------
# Cumulative bitstring counts
# ---------------------------------------------------------------------------

class KrylovBitstringCounts(pydantic.BaseModel):
    """Measurement counts from one (reference, Krylov step) circuit.

    counts  Bitstring → integer count dictionary (same format as ShotResult).
    """
    krylov_step:      int
    reference_index:  int             = 0
    counts:           dict[str, int]  = {}
    num_shots:        int             = 0

    @property
    def num_unique_bitstrings(self) -> int:
        return len(self.counts)


class CumulativeKrylovCounts(pydantic.BaseModel):
    """Pooled bitstring counts accumulated across Krylov steps.

    Each entry cumulative_counts[r] is the union of counts from circuits
    0..r for one reference state (single-ref) or all references (multi-ref).

    Pooling strategy: Counter union — each bitstring's count is the sum
    across all contributing circuits.
    """
    cumulative_counts:   list[dict[str, int]]   = []   # length = krylov_dim
    postselection:       SQDPostselectionConfig | None = None
    num_references_pooled: int                  = 1
    raw_counts_per_circuit: list[KrylovBitstringCounts] = []


# ---------------------------------------------------------------------------
# Cholesky / low-rank Hamiltonian decomposition
# ---------------------------------------------------------------------------

class CholeskyDecompositionSpec(pydantic.BaseModel):
    """Cholesky decomposition of the two-electron integral tensor.

    The two-electron integrals V_{prqs} ≈ Σ_γ L_{pr,γ} L_{qs,γ} where
    L is the Cholesky factor matrix.  This low-rank representation reduces
    the Hamiltonian building cost from O(n⁴) to O(n² × n_chol).

    Used in hamiltonians.py build_hamiltonian() for H2, LiH, and N2.

    Ref: Aquilante et al., arXiv:1808.02625; Koch et al., arXiv:2104.08957

    eps            Convergence threshold for the pivoted Cholesky algorithm.
    n_chol         Number of Cholesky vectors retained (n_g in code).
    max_cholesky   Upper bound on n_chol set before the algorithm starts.
    accuracy       max |V - L Lᵀ| achieved (printed by cholesky()).
    """
    num_orbitals:   int
    eps:            float         = 1.0e-6
    n_chol:         int           = 0      # filled after decomposition
    max_cholesky:   int           = 0      # = 20 × num_orbitals
    accuracy:       float | None  = None


# ---------------------------------------------------------------------------
# End-to-end pipeline record
# ---------------------------------------------------------------------------

class KQDConfig(pydantic.BaseModel):
    """Hyperparameters for one KQD / QSE run.

    method           Algorithm variant.
    krylov_dim       Krylov subspace dimension d (number of powers 0..d-1).
    num_references   Number of reference states (1 for single-ref).
    dt               Time-step per Krylov power; typically π/‖H‖₂.
    num_trotter_steps  Trotter repetitions per evolution step.
    shots_per_circuit  Measurement budget per circuit (SQD path).
    regularization   Regularization parameters for the generalized eigenproblem.
    """
    method:              KQDMethod              = KQDMethod.HADAMARD_TEST
    krylov_dim:          int                    = 6
    num_references:      int                    = 1
    dt:                  float                  = 0.0
    num_trotter_steps:   int                    = 6
    shots_per_circuit:   int | None             = None
    regularization:      RegularizationConfig   = pydantic.Field(
        default_factory=RegularizationConfig
    )


class KQDPipelineSpec(pydantic.BaseModel):
    """Full KQD / QSE pipeline specification and results.

    Populate only the stages run; all fields are optional.  A complete
    single-reference SQD run on a spin chain would use:
      num_qubits, kqd_config, time_evolution, reference_states,
      cumulative_counts, sqd_result.

    A full Hadamard-test KQD run would additionally populate:
      krylov_matrices, hadamard_results, eigen_result.
    """
    # --- Problem ---
    num_qubits:           int | None                     = None
    hamiltonian_label:    str | None                     = None   # e.g. "heisenberg_chain_10"

    # --- Algorithm configuration ---
    kqd_config:           KQDConfig                      = pydantic.Field(
        default_factory=KQDConfig
    )
    time_evolution:       KQDTimeEvolutionSpec | None    = None
    reference_states:     list[KQDReferenceSpec]         = []

    # --- Circuit family ---
    circuit_family:       KrylovCircuitFamilySpec | None = None

    # --- Hadamard test path ---
    krylov_matrices:      KrylovSubspaceMatrices | None  = None
    hadamard_results:     list[HadamardTestIterationResult] = []
    eigen_result:         KrylovEigenResult | None       = None

    # --- SQD path ---
    cumulative_counts:    CumulativeKrylovCounts | None  = None
    sqd_result:           SQDConvergenceResult | None    = None

    # --- Reference comparison ---
    exact_energy:         float | None                   = None   # from dense diagonalization
    hf_energy:            float | None                   = None
    cholesky_spec:        CholeskyDecompositionSpec | None = None
