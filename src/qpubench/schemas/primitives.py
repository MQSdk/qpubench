from __future__ import annotations

import enum

import pydantic


class ComputingModel(str, enum.Enum):
    """Computational paradigm — how the program is expressed and controlled.

    Orthogonal to QubitModality, but not a full cross product: a paradigm
    is not intrinsically tied to one QPU modality (e.g. GATE_BASED runs on
    superconducting, trapped-ion, silicon-spin, or photonic hardware), yet
    not every paradigm/modality pairing is realized — FUSION_BASED and GBS
    are photonic-only today. QPE and KQD are algorithmic techniques layered
    on top of GATE_BASED — see qdk_chemistry.QPEMethod / qse.KQDMethod —
    not separate paradigms.
    """
    GATE_BASED   = "gate_based"     # circuit model
    MBQC         = "mbqc"           # measurement-based / cluster-state
    FUSION_BASED = "fusion_based"   # FBQC: resource states + fusion gates
    ADIABATIC    = "adiabatic"      # continuous-time Hamiltonian evolution (e.g. Rydberg AHS)
    ANNEALING    = "annealing"      # quantum annealing (Ising/QUBO ground-state search)
    GBS          = "gbs"            # Gaussian Boson Sampling
    SAMPLING     = "sampling"       # general sampling paradigms (boson sampling, IQP, RCS)


class QubitModality(str, enum.Enum):
    """QPU modality that realizes the qubits/modes.

    Orthogonal to ComputingModel. None on BackendSpec/CircuitSpec means no
    fixed QPU modality applies (abstract simulator, classical
    emulation/FPGA control logic).
    """
    SUPERCONDUCTING = "superconducting"
    TRAPPED_ION     = "trapped_ion"
    NEUTRAL_ATOM    = "neutral_atom"
    PHOTONIC        = "photonic"
    SILICON_SPIN    = "silicon_spin"


class CircuitFormat(str, enum.Enum):
    QASM2                = "qasm2"
    QASM3                = "qasm3"
    QGC                  = "qgc"                  # Qrack native serialisation
    MEASUREMENT_PATTERN  = "measurement_pattern"  # MBQC
    JSON                 = "json"
    MOLECULE_JSON        = "molecule_json"         # algorithm-driven: problem spec not a circuit
    FOCK_STATE_CIRCUIT   = "fock_state_circuit"   # photonic: phase vector + Fock in/out spec
    LINEAR_OPTICS_UNITARY = "linear_optics_unitary"  # photonic: raw M×M unitary matrix
    QMOD                 = "qmod"                 # Classiq native high-level functional model source


class PauliLabel(str, enum.Enum):
    I = "I"
    X = "X"
    Y = "Y"
    Z = "Z"

    def to_qrack_int(self) -> int:
        """Q# / Qrack convention: I=0, X=1, Z=2, Y=3 (non-sequential)."""
        return {"I": 0, "X": 1, "Z": 2, "Y": 3}[self.value]

    def to_qiskit_c_bit_term(self) -> int:
        """Qiskit C API QkBitTerm bit-packed encoding."""
        return {"I": 0, "X": 0b0010, "Z": 0b0001, "Y": 0b0011}[self.value]


class ErrorMitigationStrategy(str, enum.Enum):
    NONE       = "none"
    DD         = "dynamical_decoupling"
    TREX       = "trex"
    ZNE        = "zne"
    PEC        = "pec"
    QESEM      = "qesem"
    FIRE_OPAL  = "fire_opal"    # Q-CTRL Fire Opal noise suppression service
    MITIQ_ZNE  = "mitiq_zne"   # Mitiq zero-noise extrapolation
    MITIQ_PEC  = "mitiq_pec"   # Mitiq probabilistic error cancellation
    MITIQ_CDR  = "mitiq_cdr"   # Mitiq Clifford data regression
    MITIQ_REM  = "mitiq_rem"   # Mitiq readout error mitigation
    MITIQ_DDD  = "mitiq_ddd"   # Mitiq dynamical decoupling
    HAIQU      = "haiqu"       # Haiqu Rivet transpilation middleware
    PARITY_QC  = "parity_qc"   # ParityQC parity-encoded compilation
    QMATTER    = "qmatter"     # QMatter quantum problem compression


class AlgorithmFamily(str, enum.Enum):
    """Package-agnostic algorithm identity — what the algorithm *is*,
    independent of which library implements it.

    Distinct from ComputingModel: a family is an algorithmic strategy
    (e.g. "grow an ansatz operator-by-operator, driven by gradients")
    that several packages can each implement in their own way — QForte's
    native C++ ADAPTVQE, a from-scratch Qiskit-circuit implementation, a
    QDK/Azure Quantum variational pipeline — all under AlgorithmFamily.ADAPT_VQE.
    AlgorithmSpec.name stays the library-specific label; family is what
    lets a caller compare runs of "the same algorithm" across adapters.
    """
    ADAPT_VQE         = "adapt_vqe"          # adaptive derivative-assembled pseudo-Trotterized VQE
    UCC_VQE           = "ucc_vqe"            # disentangled / fixed-pool UCC VQE
    UCC_PQE           = "ucc_pqe"            # UCC projective quantum eigensolver
    SPQE              = "spqe"               # selected projective quantum eigensolver
    EXCITATION_SOLVE  = "excitation_solve"   # Fourier-series VQE parameter optimizer
    TN_QC_OPT         = "tn_qc_opt"          # tensor-network + circuit hybrid VQE (Cebule)
    GA_CIRCUIT_SEARCH = "ga_circuit_search"  # evolutionary circuit search (Xenakis)


class FidelityMetric(str, enum.Enum):
    UNITARY      = "unitary_fidelity"   # Qrack GetUnitaryFidelity()
    FUBINI_STUDY = "fubini_study"       # MBQC-FPGA qsl::fubiniStudy()
    TRACE        = "trace_distance"
    PROCESS      = "process_fidelity"


class JobStatus(str, enum.Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCEEDED = "succeeded"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class CebuleTaskType(str, enum.Enum):
    """Cebule (MQS) task types.

    Confirmed directly against ``mqsdk/core/cebule.py``'s ``TaskType`` enum
    at github.com/mqsdk/python-sdk (checked 2026-07-08): every member below
    except ``MOL_MAP``/``QASM_GEN`` matches that source exactly.

    ``MOL_MAP``/``QASM_GEN`` do NOT appear in that enum. They are kept here
    rather than removed because docs.mqs.dk and this framework's own
    Kubeflow integration (``integrations/kubeflow/``) describe them as part
    of a documented "mol_map -> tn_qc_opt -> qasm_gen -> execute_circuits"
    pipeline — they may live in a newer/enterprise API surface not yet
    reflected in the public SDK repo snapshot checked here, rather than
    being simply wrong. Treat them as unconfirmed against source, not as
    verified the way every other member is.
    """
    # Confirmed in the public SDK's TaskType enum.
    COSMO                 = "cosmo"                  # continuum solvation (dielectric + VDW radii)
    SIGMA                 = "sigma"                   # COSMO-SAC/-RS sigma profile
    SOLUBILITY             = "solubility"              # solubility from sigma profiles
    CAR_PARRINELLO_MD      = "car_parrinello_md"       # ab initio MD, QE-backed (periodic-capable)
    BORN_OPPENHEIMER_MD    = "born_oppenheimer_md"     # ab initio MD, QE-backed (periodic-capable)
    FORCE_FIELD_MD          = "force_field_md"          # classical MD (mixture/solvent box)
    GEOMETRY_OPT            = "geometry_opt"            # force-field + semi-empirical geometry optimisation
    PERIODIC_GEOMETRY_OPT   = "periodic_geometry_opt"   # geometry optimisation under periodic boundary conditions
    GROUP_CONTRIBUTION      = "group_contribution"      # group-contribution property estimation for mixtures
    ATOM_ORDER              = "atom_order"              # canonical atom ordering for a SMILES (+ optional geometry)
    ACTIVITY_COEFFICIENT    = "activity_coefficient"    # confirmed to exist; no usage example found in source checked
    GNN_DATASET_CREATE      = "gnn:dataset:create"
    GNN_DATASET_DELETE      = "gnn:dataset:delete"
    GNN_DATASET_EXTEND      = "gnn:dataset:extend"
    GNN_DATASET_GET         = "gnn:dataset:get"
    GNN_TRAIN                = "gnn:train"
    GNN_PREDICT              = "gnn:predict"
    TN_QC_OPT  = "tn_qc_opt"  # tensor-network + quantum circuit VQE
    COVO       = "covo"        # correlation-optimised virtual orbitals
    # Not found in the public SDK's TaskType enum — see class docstring.
    MOL_MAP    = "mol_map"     # molecular-to-qubit Hamiltonian mapping (unconfirmed)
    QASM_GEN   = "qasm_gen"    # OpenQASM measurement circuit generation (unconfirmed)


class ComplexNumber(pydantic.BaseModel):
    """JSON-serialisable complex number.

    Avoids pydantic v2's default "1+2j" string encoding so records remain
    parseable without importing Python's complex literal syntax.
    """
    re: float
    im: float = 0.0

    @property
    def value(self) -> complex:
        return complex(self.re, self.im)

    @classmethod
    def from_complex(cls, c: complex) -> ComplexNumber:
        return cls(re=c.real, im=c.imag)
