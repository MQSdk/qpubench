"""qoqo / roqoqo — circuit representation, measurements and device models (HQS).

qoqo ("Quantum Operation Quantum Operation") is deliberately narrow: it
represents circuits and the classical post-processing that turns raw readout
into expectation values, and nothing else.  It has no transpiler, no
optimiser and no algorithm library — those are other packages' jobs.  Two
parts of it have no equivalent in qpubench's core and are the reason this
mirror exists.

**1. The measurement is part of the program, not the result.**
``CircuitSpec.observables`` says *what* to measure; it says nothing about how
the raw counts become that number.  qoqo makes that explicit: a
``PauliZProduct`` measurement bundles the basis-rotation circuits, a qubit
mask per Pauli product, and a linear or symbolic combination rule mapping
product expectation values onto named observables.  That rule is the missing
link between ``ShotResult.counts`` and ``ExpectationResult.value`` — today a
qpubench record shows both but never says how one produced the other.

**2. PRAGMAs.**  qoqo puts simulator- and hardware-specific directives *in
the circuit* as first-class operations: ``PragmaGetStateVector``,
``PragmaRepeatedMeasurement``, ``PragmaDamping``, ``PragmaSleep``,
``PragmaConditional``.  qpubench splits the same information between
``ExecutionOptions`` and the QASM string, which loses ordering — "damp for
20 µs *after gate 4*" is not expressible as an execution option.

Symbolic parameters
-------------------
qoqo gate angles are ``CalculatorFloat``: a number or an expression string.
A circuit with free parameters is a valid qoqo object that simply cannot be
executed until ``QuantumProgram`` substitutes values by name.  This is a
strictly richer contract than ``circuit.ParameterBinding`` (name → float),
and ``QoqoQuantumProgramSpec.input_parameter_names`` is the *ordered* list
that makes positional substitution well defined.

Naming
------
``hqslang`` is qoqo's own gate vocabulary (``RotateX``, ``CNOT``,
``PhaseShiftedControlledZ``, …), used verbatim in device gate-time tables and
noise models.  It is not OpenQASM's vocabulary — see ``hqs_qoqo_qasm`` for
the translation and its limits.

References
----------
qoqo        https://github.com/HQSquantumsimulations/qoqo
User docs   https://hqsquantumsimulations.github.io/qoqo/
roqoqo      https://docs.rs/roqoqo/
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic

from ..backend import BackendSpec, GateCharacteristics, QubitCharacteristics
from ..circuit import CircuitSpec
from ..primitives import ComplexNumber

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

class QoqoVersionMeta(pydantic.BaseModel):
    """qoqo's per-object version pair.

    Every serialisable qoqo type exposes ``current_version()`` (the library
    that wrote the object) and ``min_supported_version()`` (the oldest
    library that can read it).  Storing both alongside a benchmark record
    lets a reader decide whether it can rehydrate a payload, rather than
    discovering it cannot at deserialisation time.
    """
    current_version:       str = "1.0.0"
    min_supported_version: str = "1.0.0"


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

class QoqoOperationCategory(str, enum.Enum):
    """The five kinds of thing that can appear in a qoqo ``Circuit``.

    The distinction matters for translation: only GATE operations have an
    OpenQASM equivalent in general, DEFINITION operations become classical
    register declarations, and PRAGMA operations are the ones
    ``hqs_qoqo_qasm`` may have to drop or emit as dialect-specific comments.
    """
    GATE        = "gate"          # unitary single-/two-/multi-qubit gate
    DEFINITION  = "definition"    # DefinitionBit / Float / Complex / Usize
    MEASUREMENT = "measurement"   # MeasureQubit
    PRAGMA      = "pragma"        # simulator/hardware directive or annotation
    INPUT       = "input"         # InputSymbolic / InputBit


class QoqoPragma(str, enum.Enum):
    """PRAGMA operations, grouped by what they do.

    Listed exhaustively because which PRAGMAs a payload uses determines
    whether it can round-trip: a circuit containing ``PragmaGetStateVector``
    is simulator-only, and one containing ``PragmaDamping`` carries a noise
    model that a noiseless backend must be told it is silently ignoring.
    """
    # Readout — simulator only; extract the full state rather than sampling
    GET_STATE_VECTOR            = "PragmaGetStateVector"
    GET_DENSITY_MATRIX          = "PragmaGetDensityMatrix"
    GET_OCCUPATION_PROBABILITY  = "PragmaGetOccupationProbability"
    GET_PAULI_PRODUCT           = "PragmaGetPauliProduct"
    REPEATED_MEASUREMENT        = "PragmaRepeatedMeasurement"
    SET_NUMBER_OF_MEASUREMENTS  = "PragmaSetNumberOfMeasurements"
    # State preparation — simulator only
    SET_STATE_VECTOR            = "PragmaSetStateVector"
    SET_DENSITY_MATRIX          = "PragmaSetDensityMatrix"
    # Noise — in-circuit Lindblad channels, positioned between gates
    DAMPING                     = "PragmaDamping"
    DEPOLARISING                = "PragmaDepolarising"
    DEPHASING                   = "PragmaDephasing"
    RANDOM_NOISE                = "PragmaRandomNoise"
    GENERAL_NOISE               = "PragmaGeneralNoise"
    BOOST_NOISE                 = "PragmaBoostNoise"
    OVERROTATION                = "PragmaOverrotation"
    # Control flow
    CONDITIONAL                 = "PragmaConditional"
    LOOP                        = "PragmaLoop"
    REPEAT_GATE                 = "PragmaRepeatGate"
    CONTROLLED_CIRCUIT          = "PragmaControlledCircuit"
    # Scheduling & annotation
    SLEEP                       = "PragmaSleep"
    ACTIVE_RESET                = "PragmaActiveReset"
    GLOBAL_PHASE                = "PragmaGlobalPhase"
    STOP_PARALLEL_BLOCK         = "PragmaStopParallelBlock"
    START_DECOMPOSITION_BLOCK   = "PragmaStartDecompositionBlock"
    STOP_DECOMPOSITION_BLOCK    = "PragmaStopDecompositionBlock"
    CHANGE_DEVICE               = "PragmaChangeDevice"
    ANNOTATED_OP                = "PragmaAnnotatedOp"


class QoqoParameter(pydantic.BaseModel):
    """A gate argument — qoqo's ``CalculatorFloat``.

    Exactly one of ``value`` (bound) and ``expression`` (free) is set.  A
    circuit with any free expression cannot execute; ``QuantumProgram``
    substitutes them positionally from ``input_parameter_names``.
    """
    value:      float | None = None
    expression: str | None   = None

    @pydantic.model_validator(mode="after")
    def _exactly_one(self) -> QoqoParameter:
        if (self.value is None) == (self.expression is None):
            raise ValueError(
                "QoqoParameter needs exactly one of value / expression"
            )
        return self

    @property
    def is_symbolic(self) -> bool:
        return self.value is None


class QoqoOperation(pydantic.BaseModel):
    """One entry of a qoqo ``Circuit``.

    name       hqslang operation name — ``RotateX``, ``CNOT``,
               ``PragmaDamping``, ``DefinitionBit``, … (not OpenQASM names)
    category   which of the five kinds this is
    qubits     involved qubit indices, in the operation's own argument order
               (control first for controlled gates)
    parameters named arguments; angles, rates, durations
    readout    classical register this operation writes to, for measurement
               and readout-PRAGMA operations
    """
    name:       str
    category:   QoqoOperationCategory = QoqoOperationCategory.GATE
    qubits:     list[int]             = []
    parameters: dict[str, QoqoParameter] = {}
    readout:    str | None            = None

    @property
    def is_symbolic(self) -> bool:
        return any(p.is_symbolic for p in self.parameters.values())


class QoqoCircuitSpec(pydantic.BaseModel):
    """A qoqo ``Circuit`` — an ordered list of operations plus its registers.

    Unlike ``circuit.CircuitSpec`` this is a structured operation list rather
    than a serialised string, which is what makes in-circuit PRAGMAs
    positionable.  ``to_circuit_spec`` produces the core type for records that
    only need the shape; the structure is preserved in
    ``CircuitSpec.vendor_circuit`` style via the returned spec's
    ``gate_counts`` and this model stored alongside.

    definitions   classical registers declared by Definition* operations,
                  name → length
    """
    operations:  list[QoqoOperation] = []
    definitions: dict[str, int]      = {}
    version:     QoqoVersionMeta     = pydantic.Field(default_factory=QoqoVersionMeta)

    @property
    def num_qubits(self) -> int:
        """Highest qubit index used, plus one.

        qoqo circuits carry no declared width — a Circuit is just a list of
        operations, and its size is whatever the operations imply.
        """
        highest = -1
        for op in self.operations:
            if op.qubits:
                highest = max(highest, max(op.qubits))
        return highest + 1

    @property
    def is_parametric(self) -> bool:
        return any(op.is_symbolic for op in self.operations)

    @property
    def free_parameters(self) -> list[str]:
        """Distinct symbolic expression strings appearing in gate arguments.

        These are expressions, not variable names: an argument of
        ``"2 * theta"`` appears as-is.  The authoritative *variable* list is
        ``QoqoQuantumProgramSpec.input_parameter_names``.
        """
        seen: list[str] = []
        for op in self.operations:
            for param in op.parameters.values():
                if param.expression is not None and param.expression not in seen:
                    seen.append(param.expression)
        return seen

    @property
    def pragmas(self) -> list[str]:
        """Names of every PRAGMA operation used, in circuit order."""
        return [
            op.name for op in self.operations
            if op.category == QoqoOperationCategory.PRAGMA
        ]

    def gate_counts(self) -> dict[str, int]:
        """hqslang gate name → occurrence count, PRAGMAs excluded."""
        counts: dict[str, int] = {}
        for op in self.operations:
            if op.category == QoqoOperationCategory.GATE:
                counts[op.name] = counts.get(op.name, 0) + 1
        return counts

    def to_circuit_spec(self, **kwargs: Any) -> CircuitSpec:
        """Build a core ``CircuitSpec`` shell for this circuit.

        No ``serialized`` payload is produced: converting to OpenQASM is
        ``hqs_qoqo_qasm``'s job and is lossy for PRAGMA-carrying circuits.
        What survives here is the width, the classical register total and
        the gate histogram — enough for a record to compare circuit sizes
        across packages without claiming a portable serialisation.
        """
        return CircuitSpec(
            num_qubits=self.num_qubits,
            num_classical_bits=sum(self.definitions.values()) or None,
            gate_counts=self.gate_counts(),
            parameters=self.free_parameters,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------

class QoqoMeasurementType(str, enum.Enum):
    """Which of qoqo's four measurement strategies a program uses.

    The pairing of "real" and "cheated" variants is the useful part: the same
    observable can be evaluated by basis rotation and sampling
    (PAULI_Z_PRODUCT) or read straight off a simulator's state
    (CHEATED_PAULI_Z_PRODUCT), and a benchmark comparing the two is
    comparing shot noise against the exact value with everything else held
    fixed.
    """
    PAULI_Z_PRODUCT         = "PauliZProduct"          # basis rotation + sampling
    CHEATED_PAULI_Z_PRODUCT = "CheatedPauliZProduct"   # exact products from a simulator
    CHEATED                 = "Cheated"                # arbitrary operator on the state
    CLASSICAL_REGISTER      = "ClassicalRegister"       # raw registers, no post-processing


class QoqoPauliProductMask(pydantic.BaseModel):
    """One measured Pauli-Z product: which qubits of which register it spans.

    After the basis-rotation circuit has run, every observable is diagonal, so
    a Pauli product is fully described by the set of qubits whose measured
    bits are XORed together — that set is ``qubit_mask``.  ``index`` is the
    position this product occupies in the input's product list; the
    combination rules below refer to products by that index.
    """
    readout:     str
    index:       int
    qubit_mask:  list[int]


class QoqoExpectationRule(pydantic.BaseModel):
    """How one named expectation value is built from Pauli-product values.

    Exactly one of ``linear`` / ``symbolic`` is set.

    linear    {product_index: coefficient} — the value is Σ c_i ⟨P_i⟩.  This
              is the post-processing step that turns sampled counts into an
              energy, and it is precisely what a qpubench record currently
              does not store.
    symbolic  an expression string over the hardcoded variables
              ``pauli_product_0``, ``pauli_product_1``, … — used when the
              combination is not linear (ratios, normalisations).
    """
    name:     str
    linear:   dict[int, float] | None = None
    symbolic: str | None              = None

    @pydantic.model_validator(mode="after")
    def _exactly_one(self) -> QoqoExpectationRule:
        if (self.linear is None) == (self.symbolic is None):
            raise ValueError(
                "QoqoExpectationRule needs exactly one of linear / symbolic"
            )
        return self


class QoqoPauliZProductInput(pydantic.BaseModel):
    """qoqo ``PauliZProductInput`` / ``CheatedPauliZProductInput``.

    number_qubits            width of the measurement
    use_flipped_measurement  also run each basis-rotation circuit with every
                             qubit flipped, and average.  This cancels
                             readout asymmetry (p(1|0) ≠ p(0|1)) at the cost
                             of doubling the circuit count — a mitigation
                             technique expressed as measurement structure
                             rather than as a post-processing pass, which is
                             why it has no ``ErrorMitigationStrategy`` value.
    cheated                  True for ``CheatedPauliZProductInput``, whose
                             products come from a simulator's exact state and
                             therefore carry no qubit mask.
    """
    number_qubits:           int
    use_flipped_measurement: bool                      = False
    cheated:                 bool                      = False
    pauli_products:          list[QoqoPauliProductMask] = []
    expectation_rules:       list[QoqoExpectationRule]  = []

    @pydantic.model_validator(mode="after")
    def _check_rule_indices(self) -> QoqoPauliZProductInput:
        known = {p.index for p in self.pauli_products}
        for rule in self.expectation_rules:
            if rule.linear is None:
                continue
            unknown = set(rule.linear) - known
            if unknown and self.pauli_products:
                raise ValueError(
                    f"expectation rule {rule.name!r} references Pauli-product "
                    f"indices {sorted(unknown)} not present in pauli_products"
                )
        return self

    @property
    def num_circuits_per_evaluation(self) -> int:
        """Distinct basis-rotation circuits one evaluation needs.

        Doubled by ``use_flipped_measurement`` — the honest number to compare
        against another package's measurement cost.
        """
        readouts = {p.readout for p in self.pauli_products}
        base = len(readouts) or 1
        return base * 2 if self.use_flipped_measurement else base


class QoqoCheatedOperatorEntry(pydantic.BaseModel):
    """One sparse matrix entry (row, col, value) of a ``Cheated`` observable.

    ``Cheated`` measurements evaluate an arbitrary operator against a
    simulator's statevector or density matrix, so the observable is given as
    a sparse matrix in the computational basis rather than as a Pauli sum —
    the one observable form in this repo that is not Pauli-decomposed.
    """
    row:   int
    col:   int
    value: ComplexNumber


class QoqoCheatedInput(pydantic.BaseModel):
    """qoqo ``CheatedInput`` — named observables as sparse matrices.

    operators   expectation-value name → its sparse operator entries
    readouts    expectation-value name → the register holding the state
    """
    number_qubits: int
    operators:     dict[str, list[QoqoCheatedOperatorEntry]] = {}
    readouts:      dict[str, str]                            = {}


class QoqoMeasurementSpec(pydantic.BaseModel):
    """A complete qoqo measurement: circuits plus the rule that reads them.

    constant_circuit   state preparation run before every basis rotation;
                       factored out so it is not duplicated per circuit
    circuits           one per measurement basis
    pauli_input        set for PAULI_Z_PRODUCT / CHEATED_PAULI_Z_PRODUCT
    cheated_input      set for CHEATED
    """
    measurement_type: QoqoMeasurementType
    constant_circuit: QoqoCircuitSpec | None      = None
    circuits:         list[QoqoCircuitSpec]       = []
    pauli_input:      QoqoPauliZProductInput | None = None
    cheated_input:    QoqoCheatedInput | None     = None

    @pydantic.model_validator(mode="after")
    def _check_input_matches_type(self) -> QoqoMeasurementSpec:
        needs_pauli = self.measurement_type in (
            QoqoMeasurementType.PAULI_Z_PRODUCT,
            QoqoMeasurementType.CHEATED_PAULI_Z_PRODUCT,
        )
        if needs_pauli and self.pauli_input is None:
            raise ValueError(
                f"{self.measurement_type.value} requires pauli_input"
            )
        if self.measurement_type == QoqoMeasurementType.CHEATED and self.cheated_input is None:
            raise ValueError("Cheated measurement requires cheated_input")
        if self.measurement_type == QoqoMeasurementType.CLASSICAL_REGISTER and (
            self.pauli_input is not None or self.cheated_input is not None
        ):
            raise ValueError(
                "ClassicalRegister returns raw registers and takes no "
                "measurement input"
            )
        return self


class QoqoQuantumProgramSpec(pydantic.BaseModel):
    """qoqo ``QuantumProgram`` — a measurement plus its free-parameter signature.

    This is qoqo's answer to "what is the callable unit of quantum work": a
    measurement whose circuits contain symbolic angles, plus the *ordered*
    names those angles are substituted from.  ``run(backend, parameters)``
    then behaves like an ordinary function call returning expectation values.

    The ordering is the load-bearing part.  ``circuit.ParameterBinding`` is
    name-keyed and therefore order-free, which is fine for a single bind but
    cannot express "this is the same function, called with a different
    vector" — the shape every variational outer loop actually has.
    ``input_parameter_names`` gives that vector a stable meaning.
    """
    measurement:           QoqoMeasurementSpec
    input_parameter_names: list[str]        = []
    version:               QoqoVersionMeta  = pydantic.Field(default_factory=QoqoVersionMeta)

    @property
    def num_free_parameters(self) -> int:
        return len(self.input_parameter_names)


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

class QoqoDeviceTopology(str, enum.Enum):
    """Which qoqo device class describes the connectivity.

    ALL_TO_ALL and SQUARE_LATTICE are generated from a rule (and so need no
    stored edge list); GENERIC carries an explicit edge list.
    """
    ALL_TO_ALL    = "AllToAllDevice"
    SQUARE_LATTICE = "SquareLatticeDevice"
    GENERIC       = "GenericDevice"


class QoqoDeviceSpec(pydantic.BaseModel):
    """A qoqo abstract device: connectivity, gate times and decoherence rates.

    qoqo's device model is unusual in being *time-based rather than
    error-rate-based*: instead of a per-gate error probability it stores a
    gate duration and a per-qubit Lindblad rate matrix, and lets the noise
    follow from their product.  That is a physically stronger statement — it
    predicts the error of a gate the device has never been characterised on,
    which an error-rate table cannot — and it is why ``to_backend_spec``
    below fills ``duration_s`` but leaves ``error_rate`` unset rather than
    inventing one.

    Units: qoqo recommends nanoseconds and inverse nanoseconds, so that gate
    times and rates scale inversely and any consistent unit works.  This model
    stores gate times in seconds to match ``GateCharacteristics.duration_s``;
    ``time_unit_s`` records what the upstream object used.

    rows / columns are set for SQUARE_LATTICE only.
    """
    name:               str
    topology:           QoqoDeviceTopology
    number_qubits:      int
    single_qubit_gates: list[str] = []   # hqslang names
    two_qubit_gates:    list[str] = []   # hqslang names
    multi_qubit_gates:  list[str] = []   # hqslang names
    rows:               int | None = None
    columns:            int | None = None
    two_qubit_edges:    list[tuple[int, int]] = []
    #: (hqslang gate name, qubit or qubit pair as a tuple) → duration in seconds
    single_qubit_gate_times: dict[str, dict[int, float]] = {}
    two_qubit_gate_times:    dict[str, dict[str, float]] = {}   # key "control-target"
    #: per qubit, the 3×3 Lindblad rate matrix M_ij over (σ⁺, σ⁻, σᶻ), in s⁻¹
    decoherence_rates:  dict[int, list[list[float]]] = {}
    time_unit_s:        float = 1.0e-9   # qoqo's recommended nanosecond unit

    @pydantic.model_validator(mode="after")
    def _check_topology_fields(self) -> QoqoDeviceSpec:
        if self.topology == QoqoDeviceTopology.SQUARE_LATTICE:
            if self.rows is None or self.columns is None:
                raise ValueError("SquareLatticeDevice requires rows and columns")
            if self.rows * self.columns != self.number_qubits:
                raise ValueError(
                    f"rows * columns = {self.rows * self.columns} != "
                    f"number_qubits {self.number_qubits}"
                )
        for qubit, matrix in self.decoherence_rates.items():
            if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
                raise ValueError(
                    f"decoherence rate matrix for qubit {qubit} must be 3x3 "
                    "over the (sigma+, sigma-, sigma^z) Lindblad operators"
                )
        return self

    def damping_rate(self, qubit: int) -> float | None:
        """M₀₀ — the σ⁺ channel, i.e. the amplitude-damping rate (s⁻¹).

        ``t1_s`` on ``QubitCharacteristics`` is its reciprocal; see
        ``to_backend_spec``.
        """
        matrix = self.decoherence_rates.get(qubit)
        return matrix[0][0] if matrix else None

    def dephasing_rate(self, qubit: int) -> float | None:
        """M₂₂ — the σᶻ channel, i.e. the pure-dephasing rate (s⁻¹)."""
        matrix = self.decoherence_rates.get(qubit)
        return matrix[2][2] if matrix else None

    def to_backend_spec(self, provider: str = "qoqo") -> BackendSpec:
        """Project onto the core ``BackendSpec``.

        Lossy in one direction that matters: ``BackendSpec`` has T1/T2 times
        and per-gate error rates, qoqo has a Lindblad rate matrix and gate
        durations.  T1 is recovered as 1/M₀₀ and T2 as 1/M₂₂ — the diagonal
        entries only.  Any off-diagonal M_ij (coherence between decay
        channels) has no ``BackendSpec`` representation and is dropped, so
        keep this model alongside the projection rather than instead of it.
        """
        qubit_chars: list[QubitCharacteristics] = []
        for qubit in range(self.number_qubits):
            damping = self.damping_rate(qubit)
            dephasing = self.dephasing_rate(qubit)
            if damping is None and dephasing is None:
                continue
            qubit_chars.append(
                QubitCharacteristics(
                    qubit_index=qubit,
                    t1_s=1.0 / damping if damping else None,
                    t2_s=1.0 / dephasing if dephasing else None,
                )
            )
        gate_chars: list[GateCharacteristics] = []
        for gate, per_qubit in self.single_qubit_gate_times.items():
            for qubit, duration in per_qubit.items():
                gate_chars.append(
                    GateCharacteristics(
                        gate_name=gate,
                        qubit_indices=(qubit,),
                        duration_s=duration,
                    )
                )
        for gate, per_pair in self.two_qubit_gate_times.items():
            for pair_key, duration in per_pair.items():
                control, target = (int(x) for x in pair_key.split("-"))
                gate_chars.append(
                    GateCharacteristics(
                        gate_name=gate,
                        qubit_indices=(control, target),
                        duration_s=duration,
                    )
                )
        return BackendSpec(
            name=self.name,
            provider=provider,
            num_qubits=self.number_qubits,
            simulator=True,
            native_gates=[
                *self.single_qubit_gates, *self.two_qubit_gates, *self.multi_qubit_gates,
            ],
            coupling_map=list(self.two_qubit_edges),
            qubit_characteristics=qubit_chars,
            gate_characteristics=gate_chars,
        )


# ---------------------------------------------------------------------------
# Noise models
# ---------------------------------------------------------------------------

class QoqoNoiseModelType(str, enum.Enum):
    """qoqo's five noise models, distinguished by *when* the noise applies.

    That axis — continuous, on-gate, on-idle, at-readout — is the one
    qpubench's core lacks entirely: ``BackendSpec`` records characteristics a
    device *has*, with no way to say a simulation should apply them.
    """
    CONTINUOUS_DECOHERENCE     = "ContinuousDecoherenceModel"
    IMPERFECT_READOUT          = "ImperfectReadoutModel"
    DECOHERENCE_ON_GATE        = "DecoherenceOnGateModel"
    DECOHERENCE_ON_IDLE        = "DecoherenceOnIdleModel"
    SINGLE_QUBIT_OVERROTATION  = "SingleQubitOverrotationOnGate"


class QoqoImperfectReadout(pydantic.BaseModel):
    """``ImperfectReadoutModel`` — asymmetric readout error, per qubit.

    Same two numbers as ``QubitCharacteristics.prob_meas1_prep0`` /
    ``prob_meas0_prep1``, but as an instruction to a simulator rather than a
    measured device property.
    """
    prob_detect_0_as_1: dict[int, float] = {}
    prob_detect_1_as_0: dict[int, float] = {}

    @classmethod
    def uniform(
        cls,
        number_qubits: int,
        prob_detect_0_as_1: float,
        prob_detect_1_as_0: float,
    ) -> QoqoImperfectReadout:
        """Mirror of ``ImperfectReadoutModel.new_with_uniform_error``."""
        return cls(
            prob_detect_0_as_1={q: prob_detect_0_as_1 for q in range(number_qubits)},
            prob_detect_1_as_0={q: prob_detect_1_as_0 for q in range(number_qubits)},
        )


class QoqoOverrotationDescription(pydantic.BaseModel):
    """``SingleQubitOverrotationDescription`` — a miscalibrated rotation gate.

    The applied angle is the intended one plus a draw from
    N(theta_mean, theta_std).  A coherent error, not a stochastic channel:
    it does not decohere the state, it rotates it wrongly, and it accumulates
    over repetitions instead of averaging out.  No Lindblad rate expresses
    this, which is why it is a separate model rather than another entry in
    the decoherence matrix.
    """
    gate:       str     # hqslang name, e.g. "RotateX"
    theta_mean: float
    theta_std:  float


class QoqoNoiseModelSpec(pydantic.BaseModel):
    """One qoqo noise model attached to a device or simulation.

    lindblad_noise    the ``PlusMinusLindbladNoiseOperator`` behind a
                      CONTINUOUS_DECOHERENCE or DECOHERENCE_ON_GATE /
                      DECOHERENCE_ON_IDLE model, as a
                      ``hqs_struqture.StruqtureNoiseOperator`` dump.  Stored
                      as a plain dict so this mirror does not import another
                      mirror; rehydrate with
                      ``StruqtureNoiseOperator.model_validate``.
    gates             for the on-gate models: which hqslang gates the noise
                      is attached to
    """
    model_type:      QoqoNoiseModelType
    lindblad_noise:  dict[str, Any] | None          = None
    readout:         QoqoImperfectReadout | None    = None
    overrotation:    QoqoOverrotationDescription | None = None
    gates:           list[str]                      = []

    @pydantic.field_validator("lindblad_noise", mode="before")
    @classmethod
    def _dump_model(cls, v: Any) -> Any:
        return v.model_dump() if isinstance(v, pydantic.BaseModel) else v

    @pydantic.model_validator(mode="after")
    def _check_payload(self) -> QoqoNoiseModelSpec:
        if self.model_type == QoqoNoiseModelType.IMPERFECT_READOUT and self.readout is None:
            raise ValueError("ImperfectReadoutModel requires readout")
        if (
            self.model_type == QoqoNoiseModelType.SINGLE_QUBIT_OVERROTATION
            and self.overrotation is None
        ):
            raise ValueError("SingleQubitOverrotationOnGate requires overrotation")
        return self
