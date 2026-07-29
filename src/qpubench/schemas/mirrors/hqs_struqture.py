"""struqture — operator, Hamiltonian and open-quantum-system algebra (HQS).

struqture is not a simulator and not a circuit library: it is a *typed
serialisation format for operators*.  A struqture object is a sparse map from
an index (a product of single-site operators) to a coefficient, plus enough
type information to say what algebra the index lives in.  Four algebras are
supported, each in its own struqture-py submodule:

    spins           qubit / Pauli operators
    bosons          bosonic creation & annihilation operators
    fermions        fermionic creation & annihilation operators
    mixed_systems   arbitrary tensor products of the three above

and each algebra has the same four-layer stack:

    Product          the index — a single normal-ordered product of operators
    Operator         sum of products, arbitrary (non-Hermitian) coefficients
    Hamiltonian      sum of products, constrained Hermitian
    LindbladNoiseOperator / LindbladOpenSystem
                     the incoherent (dissipative) part, and coherent +
                     incoherent together

Why qpubench mirrors it
-----------------------
``observable.SparsePauliObservable`` covers exactly one cell of that grid —
qubit operators with numeric coefficients — because that is all a benchmark
*measures*.  struqture covers the rest, and two of its capabilities have no
representation anywhere else in this package:

  * **Second-quantised operators before a qubit mapping is chosen.**  A
    ``FermionHamiltonian`` plus ``jordan_wigner()`` is the provenance of a
    ``SparsePauliObservable``; recording only the mapped result throws away
    which mapping produced it.  ``VQAConfig.mapper`` names the mapping but
    has nothing to name it *on*.
  * **Lindblad dissipators as first-class data.**  A LindbladNoiseOperator is
    keyed by an ordered *pair* of products (L_i, L_j) — the double-index
    structure of the master equation — not by a single product.  No core
    qpubench type has that shape.

Symbolic coefficients
---------------------
struqture coefficients are ``CalculatorComplex``: either a number or a
symbolic expression string ("theta", "2 * omega + 1").  A Hamiltonian with
free parameters is therefore a first-class struqture object, whereas
``SparsePauliObservable`` coefficients are always numeric.  ``StruqtureValue``
below carries both cases so a parametric Hamiltonian round-trips.

Versioning
----------
Every serialised struqture object embeds a ``StruqtureSerialisationMeta``
{type_name, min_version, version} — see ``StruqtureSerialisationMeta`` below —
and rejects a load when the reader is older than the writer's declared
minimum.  qpubench records only a single monotone ``SCHEMA_VERSION``; the
struqture scheme is the stricter one and is mirrored faithfully here.

struqture 2.0 renamed the 1.x ``*System`` types (``SpinSystem`` →
``PauliOperator``, ``FermionHamiltonianSystem`` → ``FermionHamiltonian``, …)
and dropped the fixed particle-number layer.  ``StruqtureType`` uses the 2.0
names; ``STRUQTURE_1_TO_2_NAMES`` maps the old ones for records written
against struqture 1.x.

References
----------
struqture       https://github.com/HQSquantumsimulations/struqture
API docs        https://hqsquantumsimulations.github.io/struqture/
Migration 1→2   https://github.com/HQSquantumsimulations/struqture/blob/main/Migration_Guide.md
"""
from __future__ import annotations

import enum

import pydantic

from ..observable import PauliTerm, SparsePauliObservable
from ..primitives import ComplexNumber, PauliLabel

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

#: struqture's own compiled-in constants (struqture/src/lib.rs), recorded so a
#: stored qpubench record says which struqture contract it was written against
#: even when struqture is not installed.
CURRENT_STRUQTURE_VERSION = (2, 0, 0)
MINIMUM_STRUQTURE_VERSION = (2, 0, 0)

#: struqture 1.x type name → struqture 2.0 type name.  The 1.x ``System``
#: layer bundled an operator with a fixed maximum particle count; 2.0 removed
#: it, so the rename is also a semantic simplification, not just a spelling.
STRUQTURE_1_TO_2_NAMES: dict[str, str] = {
    "SpinSystem":                  "PauliOperator",
    "SpinHamiltonianSystem":       "PauliHamiltonian",
    "SpinLindbladNoiseSystem":     "PauliLindbladNoiseOperator",
    "SpinLindbladOpenSystem":      "PauliLindbladOpenSystem",
    "BosonSystem":                 "BosonOperator",
    "BosonHamiltonianSystem":      "BosonHamiltonian",
    "BosonLindbladNoiseSystem":    "BosonLindbladNoiseOperator",
    "FermionSystem":               "FermionOperator",
    "FermionHamiltonianSystem":    "FermionHamiltonian",
    "FermionLindbladNoiseSystem":  "FermionLindbladNoiseOperator",
    "MixedSystem":                 "MixedOperator",
    "MixedHamiltonianSystem":      "MixedHamiltonian",
    "MixedLindbladNoiseSystem":    "MixedLindbladNoiseOperator",
}


class StruqtureAlgebra(str, enum.Enum):
    """Which struqture-py submodule an object belongs to."""
    SPINS  = "spins"
    BOSONS = "bosons"
    FERMIONS = "fermions"
    MIXED  = "mixed_systems"


class StruqtureType(str, enum.Enum):
    """Concrete struqture 2.0 type names, as written into the serialisation
    metadata ``type_name`` field.

    Deserialisation is type-checked on this string: struqture refuses to load
    a ``PauliOperator`` payload into a ``PauliHamiltonian`` even though the
    two have the same wire shape, because the Hermiticity constraint differs.
    """
    # spins
    PAULI_OPERATOR                   = "PauliOperator"
    PAULI_HAMILTONIAN                = "PauliHamiltonian"
    PAULI_LINDBLAD_NOISE_OPERATOR    = "PauliLindbladNoiseOperator"
    PAULI_LINDBLAD_OPEN_SYSTEM       = "PauliLindbladOpenSystem"
    PLUS_MINUS_OPERATOR              = "PlusMinusOperator"
    PLUS_MINUS_LINDBLAD_NOISE_OPERATOR = "PlusMinusLindbladNoiseOperator"
    # bosons
    BOSON_OPERATOR                   = "BosonOperator"
    BOSON_HAMILTONIAN                = "BosonHamiltonian"
    BOSON_LINDBLAD_NOISE_OPERATOR    = "BosonLindbladNoiseOperator"
    BOSON_LINDBLAD_OPEN_SYSTEM       = "BosonLindbladOpenSystem"
    # fermions
    FERMION_OPERATOR                 = "FermionOperator"
    FERMION_HAMILTONIAN              = "FermionHamiltonian"
    FERMION_LINDBLAD_NOISE_OPERATOR  = "FermionLindbladNoiseOperator"
    FERMION_LINDBLAD_OPEN_SYSTEM     = "FermionLindbladOpenSystem"
    # mixed systems
    MIXED_OPERATOR                   = "MixedOperator"
    MIXED_HAMILTONIAN                = "MixedHamiltonian"
    MIXED_LINDBLAD_NOISE_OPERATOR    = "MixedLindbladNoiseOperator"
    MIXED_LINDBLAD_OPEN_SYSTEM       = "MixedLindbladOpenSystem"
    MIXED_PLUS_MINUS_OPERATOR        = "MixedPlusMinusOperator"


class StruqtureSerialisationMeta(pydantic.BaseModel):
    """Per-object serialisation header (struqture's ``StruqtureSerialisationMeta``).

    type_name    the exact struqture type the payload was written from; kept
                 as a free string rather than ``StruqtureType`` so a payload
                 from a *newer* struqture still parses (struqture keeps it a
                 String for the same reason).
    min_version  oldest struqture that can read this object, (major, minor, patch)
    version      the struqture that wrote it, semver string

    A reader accepts the object when its own major version equals
    ``min_version[0]`` and its minor version is at least ``min_version[1]``.
    This is a stronger contract than a single library-wide schema version: an
    object only demands the version *it* needs, so adding a new field to one
    type does not invalidate stored payloads of every other type.
    """
    type_name:   str
    min_version: tuple[int, int, int] = MINIMUM_STRUQTURE_VERSION
    version:     str                  = "2.0.0"

    def can_be_read_by(self, reader_version: tuple[int, int, int]) -> bool:
        """Apply struqture's ``check_can_be_deserialised`` version rule."""
        major, minor, _ = reader_version
        if major != self.min_version[0]:
            return False
        return minor >= self.min_version[1]


# ---------------------------------------------------------------------------
# Coefficients
# ---------------------------------------------------------------------------

class StruqtureValue(pydantic.BaseModel):
    """A struqture coefficient — ``CalculatorComplex`` (qoqo_calculator).

    Exactly one of ``numeric`` / ``symbolic`` is set.  ``symbolic`` holds the
    real and imaginary parts as expression strings in struqture's own syntax
    ("theta", "2 * omega + 1"); the free variables are substituted before the
    operator can be evaluated, which is why a symbolic operator cannot be
    converted to a ``SparsePauliObservable``.
    """
    numeric:       ComplexNumber | None = None
    symbolic_re:   str | None           = None
    symbolic_im:   str | None           = None

    @pydantic.model_validator(mode="after")
    def _exactly_one_form(self) -> StruqtureValue:
        has_symbolic = self.symbolic_re is not None or self.symbolic_im is not None
        if (self.numeric is None) == (not has_symbolic):
            raise ValueError(
                "StruqtureValue needs either numeric or symbolic_re/symbolic_im, "
                "not both and not neither"
            )
        return self

    @property
    def is_symbolic(self) -> bool:
        return self.numeric is None

    @classmethod
    def from_float(cls, value: float) -> StruqtureValue:
        return cls(numeric=ComplexNumber(re=value))

    @classmethod
    def from_complex(cls, value: complex) -> StruqtureValue:
        return cls(numeric=ComplexNumber.from_complex(value))


# ---------------------------------------------------------------------------
# Products — the index types
# ---------------------------------------------------------------------------

class SingleSpinOperator(str, enum.Enum):
    """Single-qubit factor allowed in a ``PauliProduct``.

    Identity is implicit: a qubit absent from the product's index list is
    unacted-on, exactly as in ``observable.PauliTerm``.
    """
    X = "X"
    Y = "Y"
    Z = "Z"


class SingleDecoherenceOperator(str, enum.Enum):
    """Single-qubit factor allowed in a ``DecoherenceProduct``.

    Note ``iY``, not ``Y``: the decoherence basis {X, iY, Z} is real-valued,
    which keeps Lindblad rate matrices real.  This is *not* the same basis as
    ``PauliProduct`` — converting a DecoherenceProduct to a Pauli string
    introduces a factor of i per iY, so the two are not interchangeable even
    though both are "products of Paulis".
    """
    X  = "X"
    IY = "iY"
    Z  = "Z"


class SinglePlusMinusOperator(str, enum.Enum):
    """Single-qubit factor allowed in a ``PlusMinusProduct``.

    σ± = (X ± iY)/2.  This ladder basis is what qoqo's
    ``ContinuousDecoherenceModel`` is expressed in, because damping and
    excitation are single terms there (σ⁻ρσ⁺, σ⁺ρσ⁻) rather than sums.
    """
    PLUS  = "+"
    MINUS = "-"
    Z     = "Z"


class PauliProductSpec(pydantic.BaseModel):
    """struqture ``spins.PauliProduct`` — a product of X/Y/Z on named qubits.

    Structurally identical to ``observable.PauliTerm`` minus the coefficient
    (struqture keeps the coefficient in the containing operator's map, not in
    the index), so the two convert losslessly — see ``to_pauli_term``.
    """
    qubit_indices: tuple[int, ...]
    operators:     tuple[SingleSpinOperator, ...]

    @pydantic.model_validator(mode="after")
    def _lengths_match(self) -> PauliProductSpec:
        if len(self.qubit_indices) != len(self.operators):
            raise ValueError(
                f"qubit_indices length {len(self.qubit_indices)} != "
                f"operators length {len(self.operators)}"
            )
        return self

    def to_pauli_term(self, coefficient: ComplexNumber | None = None) -> PauliTerm:
        """Convert to the core ``PauliTerm``, attaching a coefficient."""
        return PauliTerm(
            qubit_indices=self.qubit_indices,
            pauli_ops=tuple(PauliLabel(op.value) for op in self.operators),
            coefficient=coefficient or ComplexNumber(re=1.0),
        )

    @classmethod
    def from_pauli_term(cls, term: PauliTerm) -> PauliProductSpec:
        """Convert a core ``PauliTerm``, dropping its coefficient.

        Identity factors are dropped: struqture has no ``I`` in its
        single-spin basis, an unlisted qubit *is* the identity.
        """
        pairs = [
            (idx, SingleSpinOperator(op.value))
            for idx, op in zip(term.qubit_indices, term.pauli_ops)
            if op != PauliLabel.I
        ]
        return cls(
            qubit_indices=tuple(idx for idx, _ in pairs),
            operators=tuple(op for _, op in pairs),
        )

    def to_struqture_string(self) -> str:
        """struqture's string index form, e.g. ``0X1Z`` for X on 0, Z on 1."""
        return "".join(
            f"{idx}{op.value}" for idx, op in zip(self.qubit_indices, self.operators)
        )


class DecoherenceProductSpec(pydantic.BaseModel):
    """struqture ``spins.DecoherenceProduct`` — product over the {X, iY, Z} basis."""
    qubit_indices: tuple[int, ...]
    operators:     tuple[SingleDecoherenceOperator, ...]

    @pydantic.model_validator(mode="after")
    def _lengths_match(self) -> DecoherenceProductSpec:
        if len(self.qubit_indices) != len(self.operators):
            raise ValueError(
                f"qubit_indices length {len(self.qubit_indices)} != "
                f"operators length {len(self.operators)}"
            )
        return self


class PlusMinusProductSpec(pydantic.BaseModel):
    """struqture ``spins.PlusMinusProduct`` — product over the {σ⁺, σ⁻, Z} basis."""
    qubit_indices: tuple[int, ...]
    operators:     tuple[SinglePlusMinusOperator, ...]

    @pydantic.model_validator(mode="after")
    def _lengths_match(self) -> PlusMinusProductSpec:
        if len(self.qubit_indices) != len(self.operators):
            raise ValueError(
                f"qubit_indices length {len(self.qubit_indices)} != "
                f"operators length {len(self.operators)}"
            )
        return self


class ModeProductSpec(pydantic.BaseModel):
    """struqture ``FermionProduct`` / ``BosonProduct`` and their Hermitian forms.

    A normal-ordered product of creation operators (``creators``) followed by
    annihilation operators (``annihilators``), each a list of mode indices —
    e.g. ``creators=[0], annihilators=[0]`` is the number operator c†₀a₀.

    hermitian=True selects ``HermitianFermionProduct`` /
    ``HermitianBosonProduct``, whose containing operator adds the conjugate
    term implicitly.  struqture requires the leading creator index to be ≤ the
    leading annihilator index for those, so that each Hermitian pair has one
    canonical representative and h.c. is never double-counted.
    """
    creators:     tuple[int, ...] = ()
    annihilators: tuple[int, ...] = ()
    hermitian:    bool            = False

    @pydantic.model_validator(mode="after")
    def _check_hermitian_ordering(self) -> ModeProductSpec:
        if (
            self.hermitian and self.creators and self.annihilators
            and self.creators[0] > self.annihilators[0]
        ):
            raise ValueError(
                "Hermitian mode products require creators[0] <= annihilators[0] "
                f"(got {self.creators[0]} > {self.annihilators[0]}); swap the "
                "two to get the canonical representative of this h.c. pair"
            )
        return self

    @property
    def max_mode_index(self) -> int | None:
        indices = self.creators + self.annihilators
        return max(indices) if indices else None


class MixedProductSpec(pydantic.BaseModel):
    """struqture ``MixedProduct`` / ``HermitianMixedProduct`` / ``MixedDecoherenceProduct``.

    A tensor product across subsystems: some number of spin subsystems, then
    bosonic, then fermionic.  In struqture 2.0 the *count* of subsystems is
    fixed at construction (``MixedHamiltonian(2, 0, 0)``) while the number of
    spins/modes inside each is unbounded — so the three list lengths here are
    the structural signature the containing operator validates against.

    ``spins`` holds ``PauliProductSpec`` for coherent objects and
    ``DecoherenceProductSpec`` for ``MixedDecoherenceProduct``; only one of
    the two is populated.
    """
    spins:            list[PauliProductSpec]       = []
    decoherence_spins: list[DecoherenceProductSpec] = []
    bosons:           list[ModeProductSpec]        = []
    fermions:         list[ModeProductSpec]        = []
    hermitian:        bool                         = False

    @property
    def subsystem_counts(self) -> tuple[int, int, int]:
        """(n_spin_subsystems, n_boson_subsystems, n_fermion_subsystems)."""
        return (
            len(self.spins) or len(self.decoherence_spins),
            len(self.bosons),
            len(self.fermions),
        )


# ---------------------------------------------------------------------------
# Operator containers
# ---------------------------------------------------------------------------

class StruqtureTerm(pydantic.BaseModel):
    """One (index, coefficient) entry of a struqture operator or Hamiltonian.

    Exactly one of the product fields is set, matching the operator's algebra.
    """
    pauli_product:      PauliProductSpec | None      = None
    plus_minus_product: PlusMinusProductSpec | None  = None
    mode_product:       ModeProductSpec | None       = None
    mixed_product:      MixedProductSpec | None      = None
    coefficient:        StruqtureValue

    @pydantic.model_validator(mode="after")
    def _exactly_one_product(self) -> StruqtureTerm:
        set_products = [
            p for p in (
                self.pauli_product, self.plus_minus_product,
                self.mode_product, self.mixed_product,
            )
            if p is not None
        ]
        if len(set_products) != 1:
            raise ValueError(
                f"StruqtureTerm needs exactly one product field set, got {len(set_products)}"
            )
        return self


class StruqtureNoiseTerm(pydantic.BaseModel):
    """One entry of a Lindblad noise operator: a *pair* of indices and a rate.

    The Lindblad master equation's incoherent part is

        dρ/dt = Σ_ij M_ij ( L_i ρ L_j†  −  ½ { L_j† L_i , ρ } )

    so its natural index is the ordered pair (i, j), not a single operator —
    this is the shape no core qpubench type has.  ``left`` is L_i, ``right``
    is L_j, and ``rate`` is M_ij.  Diagonal entries (left == right) are the
    familiar single-channel rates; off-diagonal entries carry the coherences
    between decay channels that a plain rate list cannot express.

    Spin noise uses ``DecoherenceProductSpec`` (the {X, iY, Z} basis) or
    ``PlusMinusProductSpec`` (the {σ±, Z} basis) depending on the operator
    type; mode and mixed noise use the corresponding product types.
    """
    left_decoherence:   DecoherenceProductSpec | None = None
    right_decoherence:  DecoherenceProductSpec | None = None
    left_plus_minus:    PlusMinusProductSpec | None   = None
    right_plus_minus:   PlusMinusProductSpec | None   = None
    left_mode:          ModeProductSpec | None        = None
    right_mode:         ModeProductSpec | None        = None
    left_mixed:         MixedProductSpec | None       = None
    right_mixed:        MixedProductSpec | None       = None
    rate:               StruqtureValue

    @pydantic.model_validator(mode="after")
    def _pairs_match(self) -> StruqtureNoiseTerm:
        pairs = [
            (self.left_decoherence, self.right_decoherence),
            (self.left_plus_minus,  self.right_plus_minus),
            (self.left_mode,        self.right_mode),
            (self.left_mixed,       self.right_mixed),
        ]
        populated = [(lhs, rhs) for lhs, rhs in pairs if lhs is not None or rhs is not None]
        if len(populated) != 1:
            raise ValueError(
                f"StruqtureNoiseTerm needs exactly one left/right product pair, "
                f"got {len(populated)}"
            )
        lhs, rhs = populated[0]
        if lhs is None or rhs is None:
            raise ValueError(
                "StruqtureNoiseTerm needs both sides of the pair: a Lindblad "
                "index is (L_i, L_j), and a missing side is not the identity"
            )
        return self

    @property
    def is_diagonal(self) -> bool:
        """True when left == right — a plain decay channel with rate M_ii."""
        for lhs, rhs in (
            (self.left_decoherence, self.right_decoherence),
            (self.left_plus_minus,  self.right_plus_minus),
            (self.left_mode,        self.right_mode),
            (self.left_mixed,       self.right_mixed),
        ):
            if lhs is not None and rhs is not None:
                return lhs == rhs
        return False


class StruqtureOperator(pydantic.BaseModel):
    """A struqture Operator or Hamiltonian — the coherent part.

    One model covers both because the wire shape is identical; ``meta.type_name``
    is what distinguishes them, and struqture enforces the difference on load
    (a Hamiltonian additionally guarantees Hermiticity).  ``hermitian`` mirrors
    that constraint for readers that never touch struqture itself.

    number_subsystems is set for mixed objects only: struqture 2.0's mixed
    constructors take the subsystem counts (``MixedHamiltonian(2, 0, 0)``)
    while spin/boson/fermion objects take nothing at all.
    """
    meta:              StruqtureSerialisationMeta
    algebra:           StruqtureAlgebra
    terms:             list[StruqtureTerm] = []
    hermitian:         bool                = False
    number_subsystems: tuple[int, int, int] | None = None   # mixed only

    @property
    def is_symbolic(self) -> bool:
        """True when any coefficient is a symbolic expression."""
        return any(t.coefficient.is_symbolic for t in self.terms)

    @property
    def current_number_spins(self) -> int:
        """Highest qubit index touched, plus one (struqture's
        ``current_number_spins``) — 0 when the operator touches no spins.

        "Current", not "number": struqture 2.0 removed the fixed particle
        count, so this is a property of the terms present right now and grows
        as terms are added.
        """
        highest = -1
        for term in self.terms:
            if term.pauli_product is not None and term.pauli_product.qubit_indices:
                highest = max(highest, max(term.pauli_product.qubit_indices))
            if term.plus_minus_product is not None and term.plus_minus_product.qubit_indices:
                highest = max(highest, max(term.plus_minus_product.qubit_indices))
        return highest + 1

    def to_sparse_pauli_observable(
        self,
        num_qubits: int | None = None,
    ) -> SparsePauliObservable:
        """Convert a spin operator to the core ``SparsePauliObservable``.

        Raises when the operator is not a spin operator, or when any
        coefficient is symbolic — an unbound parameter has no numeric value
        for an expectation-value computation to use.  Bind the free variables
        in struqture first, then convert.
        """
        if self.algebra != StruqtureAlgebra.SPINS:
            raise ValueError(
                f"Only spin operators map onto SparsePauliObservable; this is "
                f"{self.algebra.value}. Apply a fermion-to-qubit mapping "
                "(struqture's jordan_wigner()) first."
            )
        if self.is_symbolic:
            raise ValueError(
                "Symbolic coefficients have no numeric value; substitute the "
                "free variables in struqture before converting"
            )
        terms: list[PauliTerm] = []
        for term in self.terms:
            if term.pauli_product is None:
                raise ValueError(
                    "Only PauliProduct-indexed terms convert directly; the "
                    "PlusMinus basis must be rewritten in X/Y/Z first"
                )
            assert term.coefficient.numeric is not None   # is_symbolic checked above
            terms.append(term.pauli_product.to_pauli_term(term.coefficient.numeric))
        if num_qubits is None:
            num_qubits = self.current_number_spins
        return SparsePauliObservable(num_qubits=num_qubits, terms=terms)

    @classmethod
    def from_sparse_pauli_observable(
        cls,
        observable: SparsePauliObservable,
        *,
        hermitian: bool = True,
    ) -> StruqtureOperator:
        """Build a spin ``PauliOperator`` / ``PauliHamiltonian`` from the core type."""
        type_name = (
            StruqtureType.PAULI_HAMILTONIAN if hermitian
            else StruqtureType.PAULI_OPERATOR
        )
        return cls(
            meta=StruqtureSerialisationMeta(type_name=type_name.value),
            algebra=StruqtureAlgebra.SPINS,
            hermitian=hermitian,
            terms=[
                StruqtureTerm(
                    pauli_product=PauliProductSpec.from_pauli_term(term),
                    coefficient=StruqtureValue(numeric=term.coefficient),
                )
                for term in observable.terms
            ],
        )


class StruqtureNoiseOperator(pydantic.BaseModel):
    """A struqture LindbladNoiseOperator — the incoherent part alone."""
    meta:              StruqtureSerialisationMeta
    algebra:           StruqtureAlgebra
    terms:             list[StruqtureNoiseTerm] = []
    number_subsystems: tuple[int, int, int] | None = None   # mixed only

    @property
    def is_symbolic(self) -> bool:
        return any(t.rate.is_symbolic for t in self.terms)

    @property
    def has_off_diagonal_rates(self) -> bool:
        """True when any L_i ρ L_j† term with i ≠ j is present.

        Worth checking before handing the model to a simulator that only
        accepts a list of independent decay channels — those can represent
        the diagonal of M but silently drop the rest.
        """
        return any(not t.is_diagonal for t in self.terms)


class StruqtureOpenSystem(pydantic.BaseModel):
    """A struqture LindbladOpenSystem — coherent Hamiltonian plus dissipators.

    struqture 2.0 kept the ``*OpenSystem`` name where it dropped ``*System``
    elsewhere, because an open system genuinely is two objects (a Hamiltonian
    and a noise operator) rather than an operator with a particle count
    attached.

    An open system is the natural home for a *noisy simulation* benchmark
    problem: the pair (system, noise) is what a master-equation solver
    integrates, and what ``questkit_quest.QuESTKrausMap`` or a qoqo
    ``ContinuousDecoherenceModel`` approximate.
    """
    meta:   StruqtureSerialisationMeta
    system: StruqtureOperator
    noise:  StruqtureNoiseOperator

    @pydantic.model_validator(mode="after")
    def _algebras_match(self) -> StruqtureOpenSystem:
        if self.system.algebra != self.noise.algebra:
            raise ValueError(
                f"open-system halves must share an algebra: system is "
                f"{self.system.algebra.value}, noise is {self.noise.algebra.value}"
            )
        return self


# ---------------------------------------------------------------------------
# Fermion-to-qubit mapping provenance
# ---------------------------------------------------------------------------

class StruqtureMapping(str, enum.Enum):
    """Mode-to-qubit mapping struqture can apply.

    struqture exposes ``jordan_wigner()`` on every spin/fermion object (and
    the inverse on spin objects).  The other values are listed because
    ``record.VQAConfig.mapper`` accepts them and other packages in this repo
    implement them; only JORDAN_WIGNER is struqture's own.
    """
    JORDAN_WIGNER = "JordanWigner"
    BRAVYI_KITAEV = "BravyiKitaev"
    PARITY        = "Parity"


class StruqtureMappedHamiltonian(pydantic.BaseModel):
    """A qubit Hamiltonian together with the fermionic one it came from.

    This is the record that makes ``VQAConfig.mapper`` verifiable rather than
    decorative: it keeps the pre-mapping operator, the mapping applied, and
    the resulting qubit operator in one object, so two benchmarks that report
    "the same molecule under Jordan-Wigner" can be checked to mean it.

    ``source`` is the fermionic (or bosonic/mixed) operator; ``mapped`` is the
    spin operator ``source`` maps onto.  Both are full struqture objects, so
    the coefficients — symbolic or numeric — survive the round trip.
    """
    source:  StruqtureOperator
    mapping: StruqtureMapping = StruqtureMapping.JORDAN_WIGNER
    mapped:  StruqtureOperator

    @pydantic.model_validator(mode="after")
    def _check_algebras(self) -> StruqtureMappedHamiltonian:
        if self.mapped.algebra != StruqtureAlgebra.SPINS:
            raise ValueError(
                f"mapped operator must be a spin operator, got {self.mapped.algebra.value}"
            )
        if self.source.algebra == StruqtureAlgebra.SPINS:
            raise ValueError(
                "source operator is already a spin operator; there is no "
                "mode-to-qubit mapping to record"
            )
        return self
