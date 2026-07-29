"""QuEST v4 — high-performance state-vector and density-matrix simulator.

QuEST is a C/C++ simulator, not a framework: there is no circuit object, no
transpiler and no job queue.  A program is a sequence of C calls mutating a
``Qureg`` in place, and the "circuit" exists only as the order in which the
host program made them.  That has one consequence worth stating up front —
**a QuEST run has no serialisable circuit**, so a benchmark record for it
carries the circuit in whatever form the host program used (usually OpenQASM
handed to a translation layer such as qoqo-quest or pyQuEST) and QuEST's own
contribution is the *deployment and precision* the numbers were produced at.

That deployment axis is what this mirror is mostly for.  ``BackendSpec`` says
which simulator ran; it does not say whether the run was distributed over 64
MPI nodes in single precision or single-threaded in quad.  Those choices
change both the runtime and the *answer*, and QuEST is unusually explicit
about all of them:

    deployment   OpenMP multithreading × CUDA/HIP GPU × MPI distribution ×
                 cuQuantum, chosen independently and combinable
    precision    ``FLOAT_PRECISION`` 1/2/4 → float / double / long double,
                 a compile-time choice (and quad precision is unavailable on GPU)
    memory       state-vector vs density matrix, which is a 2ⁿ vs 4ⁿ decision

Density matrices and noise
--------------------------
QuEST simulates open systems directly: a density-matrix ``Qureg`` accepts
``mixDephasing``/``mixDepolarising``/``mixDamping``/``mixKrausMap``, applied
positionally between gates.  This is the same capability qoqo expresses as
in-circuit noise PRAGMAs and struqture expresses as a Lindblad operator — see
``hqs_struqture.StruqtureOpenSystem``.  The three are complementary rather
than duplicates: struqture is the continuous-time generator, QuEST is a
discrete channel applied at a point in the program, and qoqo is the same
channel positioned within a portable circuit.

References
----------
QuEST       https://github.com/QuEST-Kit/QuEST
API docs    https://quest-kit.github.io/QuEST/
Bindings    pyQuEST (Cython) · PyQuEST-cffi · QuEST.jl · qoqo-quest (Rust)
"""
from __future__ import annotations

import enum

import pydantic

from ..backend import BackendSpec
from ..observable import SparsePauliObservable
from ..primitives import ComplexNumber, PauliLabel

# ---------------------------------------------------------------------------
# Deployment and precision
# ---------------------------------------------------------------------------

class QuESTPrecision(int, enum.Enum):
    """``FLOAT_PRECISION`` — the compile-time width of ``qreal`` / ``qcomp``.

    Compile-time, not run-time: a QuEST build is single, double or quad
    precision and cannot switch.  Recording it matters because it bounds the
    accuracy claim a benchmark can make — a single-precision run reporting
    agreement to 1e-8 is reporting noise.

    QUAD is CPU-only; QuEST refuses to build it against CUDA.
    """
    SINGLE = 1   # float
    DOUBLE = 2   # double — QuEST's default
    QUAD   = 4   # long double; incompatible with GPU deployment

    @property
    def epsilon(self) -> float:
        """Approximate machine epsilon for this precision.

        A convergence threshold tighter than this is unreachable regardless
        of how long the run is given.
        """
        return {1: 1.2e-7, 2: 2.2e-16, 4: 1.1e-19}[self.value]


class QuESTDeployment(pydantic.BaseModel):
    """``QuESTEnv`` — which acceleration backends a run actually used.

    The four flags are independent and combinable, and QuEST probes hardware
    at runtime to enable them automatically unless ``initCustomQuESTEnv``
    forces a choice.  ``num_nodes`` > 1 means the state vector was split
    across MPI ranks; every amplitude-touching operation then carries
    communication cost, which is why a distributed run's timing is not
    comparable to a single-node one at the same qubit count.

    ``cuquantum`` is a build-time capability (it cannot be toggled after
    compilation), unlike the other three.
    """
    multithreaded:  bool = False   # OpenMP
    gpu_accelerated: bool = False  # CUDA / HIP
    distributed:    bool = False   # MPI
    cuquantum:      bool = False   # NVIDIA cuQuantum backend; build-time only
    gpu_sharing:    bool = False   # multiple ranks per GPU
    num_nodes:      int  = 1
    rank:           int  = 0

    @pydantic.model_validator(mode="after")
    def _check_nodes(self) -> QuESTDeployment:
        if self.num_nodes < 1:
            raise ValueError(f"num_nodes must be >= 1, got {self.num_nodes}")
        if self.distributed and self.num_nodes == 1:
            raise ValueError(
                "distributed=True with num_nodes=1 is not a distributed run; "
                "set num_nodes to the MPI world size"
            )
        if self.num_nodes > 1 and not self.distributed:
            raise ValueError(
                f"num_nodes={self.num_nodes} requires distributed=True"
            )
        if self.rank >= self.num_nodes:
            raise ValueError(f"rank {self.rank} outside {self.num_nodes} nodes")
        return self

    @property
    def is_accelerated(self) -> bool:
        return self.multithreaded or self.gpu_accelerated or self.distributed

    @property
    def summary(self) -> str:
        """Compact label for a results table, e.g. ``"gpu+mpi(4)"``."""
        parts = []
        if self.multithreaded:
            parts.append("omp")
        if self.gpu_accelerated:
            parts.append("cuquantum" if self.cuquantum else "gpu")
        if self.distributed:
            parts.append(f"mpi({self.num_nodes})")
        return "+".join(parts) or "serial"


# ---------------------------------------------------------------------------
# Qureg
# ---------------------------------------------------------------------------

class QuESTQuregSpec(pydantic.BaseModel):
    """A ``Qureg`` — the simulated register, and what it cost to hold.

    is_density_matrix is the decision that dominates everything else: a
    density matrix stores 4ⁿ amplitudes against a state vector's 2ⁿ, halving
    the reachable qubit count for the same memory.  It is also the only mode
    in which QuEST's ``mix*`` decoherence functions are defined — noise
    simulation is not an option on a state vector.

    The memory properties below are derived rather than stored so they can
    never disagree with the flags that determine them.
    """
    num_qubits:         int
    is_density_matrix:  bool             = False
    precision:          QuESTPrecision   = QuESTPrecision.DOUBLE
    deployment:         QuESTDeployment  = pydantic.Field(default_factory=QuESTDeployment)

    @pydantic.model_validator(mode="after")
    def _check(self) -> QuESTQuregSpec:
        if self.num_qubits < 1:
            raise ValueError(f"num_qubits must be >= 1, got {self.num_qubits}")
        if self.precision == QuESTPrecision.QUAD and self.deployment.gpu_accelerated:
            raise ValueError(
                "QuEST does not support quad precision (FLOAT_PRECISION=4) "
                "with GPU deployment"
            )
        return self

    @property
    def num_amplitudes(self) -> int:
        """2ⁿ for a state vector, 4ⁿ for a density matrix (QuEST's ``numAmps``)."""
        exponent = 2 * self.num_qubits if self.is_density_matrix else self.num_qubits
        return int(2 ** exponent)

    @property
    def bytes_per_amplitude(self) -> int:
        """A ``qcomp`` is two ``qreal``s."""
        qreal_bytes: dict[int, int] = {1: 4, 2: 8, 4: 16}
        return 2 * qreal_bytes[self.precision.value]

    @property
    def state_bytes(self) -> int:
        """Total memory for the amplitudes, across all nodes.

        Excludes QuEST's communication buffer, which distributed runs
        allocate at the same size again — so a distributed run's true
        footprint is roughly twice this.
        """
        return self.num_amplitudes * self.bytes_per_amplitude

    @property
    def bytes_per_node(self) -> int:
        return self.state_bytes // self.deployment.num_nodes

    def to_backend_spec(self, name: str | None = None) -> BackendSpec:
        """Project onto the core ``BackendSpec``.

        The deployment and precision have no ``BackendSpec`` fields of their
        own, so they go into ``auth`` — which is documented as a credentials
        map, and is the only free-form one on that model.  That is a
        workaround, not a design: see finding A3 in docs/schema_review.md.
        """
        return BackendSpec(
            name=name or f"quest_{self.deployment.summary}",
            provider="quest",
            simulator=True,
            num_qubits=self.num_qubits,
            auth={
                "precision":         str(self.precision.value),
                "density_matrix":    str(self.is_density_matrix),
                "deployment":        self.deployment.summary,
                "num_nodes":         str(self.deployment.num_nodes),
            },
        )


# ---------------------------------------------------------------------------
# Observables
# ---------------------------------------------------------------------------

class QuESTPauliStr(pydantic.BaseModel):
    """A ``PauliStr`` — one Pauli string over the register.

    QuEST packs a Pauli string as a pair of base-4 numerals split across two
    machine integers (``lowPaulis`` / ``highPaulis``), which caps the number
    of Paulis a single string can carry.  This mirror stores the string in the
    same index/label form as ``observable.PauliTerm`` and offers
    ``to_base4_masks`` for the packed form.
    """
    qubit_indices: tuple[int, ...]
    pauli_ops:     tuple[PauliLabel, ...]

    @pydantic.model_validator(mode="after")
    def _lengths_match(self) -> QuESTPauliStr:
        if len(self.qubit_indices) != len(self.pauli_ops):
            raise ValueError(
                f"qubit_indices length {len(self.qubit_indices)} != "
                f"pauli_ops length {len(self.pauli_ops)}"
            )
        return self

    def to_base4_masks(self, split_at: int = 32) -> tuple[int, int]:
        """Pack into QuEST's (lowPaulis, highPaulis) base-4 numerals.

        Encoding is I=0, X=1, Y=2, Z=3 — sequential, unlike the Q#/Qrack
        ordering ``PauliLabel.to_qrack_int`` produces (I=0, X=1, Z=2, Y=3).
        Two digits per qubit; qubits below ``split_at`` go in the low word.
        """
        order = {PauliLabel.I: 0, PauliLabel.X: 1, PauliLabel.Y: 2, PauliLabel.Z: 3}
        low = high = 0
        for idx, op in zip(self.qubit_indices, self.pauli_ops):
            digit = order[op]
            if idx < split_at:
                low |= digit << (2 * idx)
            else:
                high |= digit << (2 * (idx - split_at))
        return low, high


class QuESTPauliStrSum(pydantic.BaseModel):
    """A ``PauliStrSum`` — QuEST's observable type, the argument to
    ``calcExpecPauliStrSum``.

    ``is_approx_hermitian`` mirrors QuEST's lazily-evaluated tri-state flag
    (0 / 1 / -1 for unknown): QuEST only checks Hermiticity when a function
    that requires it is called, and a non-Hermitian sum must go through
    ``calcExpecNonHermitianPauliStrSum`` instead, which returns a complex
    value.  None here is QuEST's "unknown".
    """
    terms:               list[QuESTPauliStr]
    coefficients:        list[ComplexNumber]
    is_approx_hermitian: bool | None = None

    @pydantic.model_validator(mode="after")
    def _lengths_match(self) -> QuESTPauliStrSum:
        if len(self.terms) != len(self.coefficients):
            raise ValueError(
                f"terms length {len(self.terms)} != coefficients length "
                f"{len(self.coefficients)}"
            )
        return self

    @property
    def num_terms(self) -> int:
        return len(self.terms)

    @classmethod
    def from_sparse_pauli_observable(
        cls,
        observable: SparsePauliObservable,
    ) -> QuESTPauliStrSum:
        """Build from the core observable type."""
        return cls(
            terms=[
                QuESTPauliStr(
                    qubit_indices=term.qubit_indices,
                    pauli_ops=term.pauli_ops,
                )
                for term in observable.terms
            ],
            coefficients=[term.coefficient for term in observable.terms],
        )

    def to_sparse_pauli_observable(self, num_qubits: int) -> SparsePauliObservable:
        """Convert back to the core observable type."""
        from ..observable import PauliTerm

        return SparsePauliObservable(
            num_qubits=num_qubits,
            terms=[
                PauliTerm(
                    qubit_indices=term.qubit_indices,
                    pauli_ops=term.pauli_ops,
                    coefficient=coeff,
                )
                for term, coeff in zip(self.terms, self.coefficients)
            ],
        )


# ---------------------------------------------------------------------------
# Decoherence
# ---------------------------------------------------------------------------

class QuESTChannelType(str, enum.Enum):
    """QuEST's ``mix*`` decoherence channels.

    All require a density-matrix ``Qureg``.  The named channels take a
    probability; KRAUS_MAP and SUPER_OP take an explicit operator, and are
    the general case the named ones are shorthand for.
    """
    DEPHASING             = "mixDephasing"
    TWO_QUBIT_DEPHASING   = "mixTwoQubitDephasing"
    DEPOLARISING          = "mixDepolarising"
    TWO_QUBIT_DEPOLARISING = "mixTwoQubitDepolarising"
    DAMPING               = "mixDamping"
    PAULIS                = "mixPaulis"          # independent X/Y/Z probabilities
    QUREG                 = "mixQureg"           # mix in another density matrix
    KRAUS_MAP             = "mixKrausMap"
    SUPER_OP              = "mixSuperOp"


class QuESTNoiseChannel(pydantic.BaseModel):
    """One decoherence channel applied at a point in the program.

    position     index into the host program's gate sequence after which the
                 channel is applied.  QuEST has no circuit object, so this
                 ordering is the only place the channel's placement is
                 recorded — and placement is not a detail: the same channel
                 before and after an entangling gate gives different states.
    probability  for the named channels; each has its own validity bound
                 (damping and dephasing accept [0, 1], depolarising is capped
                 below 1 because the maximally mixed state is reached early),
                 which QuEST checks at call time and this model does not
                 duplicate.
    kraus_operators  for KRAUS_MAP: a list of matrices, each a list of rows
                 of complex entries.  Must be trace-preserving; QuEST
                 validates that separately.
    """
    channel:         QuESTChannelType
    targets:         list[int]
    probability:     float | None = None
    prob_x:          float | None = None    # mixPaulis
    prob_y:          float | None = None
    prob_z:          float | None = None
    kraus_operators: list[list[list[ComplexNumber]]] = []
    position:        int | None = None

    @pydantic.model_validator(mode="after")
    def _check_payload(self) -> QuESTNoiseChannel:
        named = {
            QuESTChannelType.DEPHASING,
            QuESTChannelType.TWO_QUBIT_DEPHASING,
            QuESTChannelType.DEPOLARISING,
            QuESTChannelType.TWO_QUBIT_DEPOLARISING,
            QuESTChannelType.DAMPING,
            QuESTChannelType.QUREG,
        }
        if self.channel in named and self.probability is None:
            raise ValueError(f"{self.channel.value} requires probability")
        if self.channel == QuESTChannelType.PAULIS and None in (
            self.prob_x, self.prob_y, self.prob_z
        ):
            raise ValueError("mixPaulis requires prob_x, prob_y and prob_z")
        if self.channel == QuESTChannelType.KRAUS_MAP and not self.kraus_operators:
            raise ValueError("mixKrausMap requires kraus_operators")
        return self


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class QuESTCalculation(str, enum.Enum):
    """QuEST's ``calc*`` family — what a run measured.

    Listed as an enum because these are the *only* things a QuEST run
    returns: there is no job object and no result bundle, just a scalar per
    call.  Recording which call produced a number is what makes it
    interpretable — ``calcFidelity`` against a reference state and
    ``calcPurity`` are both "a number near 1" and mean entirely different
    things.
    """
    EXPEC_PAULI_STR             = "calcExpecPauliStr"
    EXPEC_PAULI_STR_SUM         = "calcExpecPauliStrSum"
    EXPEC_FULL_STATE_DIAG_MATR  = "calcExpecFullStateDiagMatr"
    EXPEC_NON_HERMITIAN_SUM     = "calcExpecNonHermitianPauliStrSum"
    PROB_OF_BASIS_STATE         = "calcProbOfBasisState"
    PROB_OF_QUBIT_OUTCOME       = "calcProbOfQubitOutcome"
    PROB_OF_MULTI_QUBIT_OUTCOME = "calcProbOfMultiQubitOutcome"
    TOTAL_PROB                  = "calcTotalProb"
    PURITY                      = "calcPurity"
    FIDELITY                    = "calcFidelity"
    DISTANCE                    = "calcDistance"
    INNER_PRODUCT               = "calcInnerProduct"
    PARTIAL_TRACE               = "calcPartialTrace"


class QuESTCalculationResult(pydantic.BaseModel):
    """One ``calc*`` return value.

    QuEST's real-valued calls return ``qreal`` and its complex ones ``qcomp``;
    ``value`` carries both as a ``ComplexNumber`` so the two shapes share one
    model.  There is no standard error: QuEST computes exactly (to the
    precision it was built at), so an uncertainty here would be invented.
    A shot-sampled comparison belongs in ``result.ShotResult`` instead.
    """
    calculation:      QuESTCalculation
    value:            ComplexNumber
    qubits:           list[int] = []
    reference_label:  str | None = None   # for FIDELITY / DISTANCE / INNER_PRODUCT

    @property
    def real_value(self) -> float:
        return self.value.re


class QuESTRunRecord(pydantic.BaseModel):
    """A complete QuEST run: register, applied noise, and everything measured.

    Attach to ``result.QuantumResult.vendor_results`` under the key
    ``"quest_run"``.

    total_gate_calls is the closest QuEST offers to a circuit depth — the
    host program's call count.  It is supplied by the caller, since QuEST
    itself never sees a circuit to count.
    """
    qureg:            QuESTQuregSpec
    observable:       QuESTPauliStrSum | None      = None
    noise_channels:   list[QuESTNoiseChannel]      = []
    calculations:     list[QuESTCalculationResult] = []
    total_gate_calls: int | None                   = None
    wall_seconds:     float | None                 = None
    quest_version:    str                          = "4.0.0"

    @pydantic.model_validator(mode="after")
    def _check_noise_needs_density_matrix(self) -> QuESTRunRecord:
        if self.noise_channels and not self.qureg.is_density_matrix:
            raise ValueError(
                "QuEST's mix* decoherence channels require a density-matrix "
                "Qureg; set qureg.is_density_matrix=True (at 4^n amplitudes "
                "rather than 2^n)"
            )
        return self

    def result_for(self, calculation: QuESTCalculation) -> QuESTCalculationResult | None:
        """First recorded result of the given ``calc*`` call, if any."""
        for entry in self.calculations:
            if entry.calculation == calculation:
                return entry
        return None
