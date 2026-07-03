from __future__ import annotations

import enum

import pydantic


class QPUModality(str, enum.Enum):
    GATE_BASED              = "gate_based"
    MBQC                    = "mbqc"
    ANNEALING               = "annealing"
    PHOTONIC_LINEAR_OPTICS  = "photonic_linear_optics"   # linear-optics Fock-state chip
    FUSION_BASED            = "fusion_based"             # FBQC with resource states + fusion gates
    QPE                     = "qpe"                      # Quantum Phase Estimation (gate-based QPE/IQPE)
    GBS                     = "gbs"                      # Gaussian Boson Sampling (squeezed states + interferometer)
    KQD                     = "kqd"                      # Krylov Quantum Diagonalization (QSE / SQD)
    NEUTRAL_ATOM            = "neutral_atom"             # Analog Hamiltonian Simulation on Rydberg atoms


class CircuitFormat(str, enum.Enum):
    QASM2                = "qasm2"
    QASM3                = "qasm3"
    QGC                  = "qgc"                  # Qrack native serialisation
    MEASUREMENT_PATTERN  = "measurement_pattern"  # MBQC
    JSON                 = "json"
    MOLECULE_JSON        = "molecule_json"         # algorithm-driven: problem spec not a circuit
    FOCK_STATE_CIRCUIT   = "fock_state_circuit"   # photonic: phase vector + Fock in/out spec
    LINEAR_OPTICS_UNITARY = "linear_optics_unitary"  # photonic: raw M×M unitary matrix


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
    MOL_MAP    = "mol_map"     # molecular-to-qubit Hamiltonian mapping
    QASM_GEN   = "qasm_gen"    # OpenQASM measurement circuit generation
    TN_QC_OPT  = "tn_qc_opt"  # tensor-network + quantum circuit VQE
    COVO       = "covo"        # correlation-optimised virtual orbitals


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
