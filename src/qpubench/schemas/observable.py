from __future__ import annotations

from typing import Any

import pydantic

from .primitives import ComplexNumber, PauliLabel


class PauliTerm(pydantic.BaseModel):
    """One term in a sparse Pauli sum.

    Compatible with:
      - Qrack: PauliExpectation(qubits[], paulis[]) via to_qrack_arrays()
      - Qiskit C: QkObsTerm {coeff, bit_terms[], indices[]} via to_qiskit_c_arrays()
      - Cebule: "X0 Y1 Z3" token strings via SparsePauliObservable.from_cebule_operators()

    Hand-written terms are usually shorter through the Pauli() factory at the
    bottom of this module; these constructors are for generated ones.
    """

    qubit_indices: tuple[int, ...]
    pauli_ops: tuple[PauliLabel, ...]
    coefficient: ComplexNumber = pydantic.Field(default_factory=lambda: ComplexNumber(re=1.0))

    @pydantic.model_validator(mode="after")
    def _lengths_match(self) -> PauliTerm:
        if len(self.qubit_indices) != len(self.pauli_ops):
            raise ValueError(
                f"qubit_indices length {len(self.qubit_indices)} != "
                f"pauli_ops length {len(self.pauli_ops)}"
            )
        return self

    def to_qrack_arrays(self) -> tuple[list[int], list[int]]:
        """Parallel (qubit_indices, pauli_ints) for Qrack PauliExpectation C call.

        Qrack Pauli int encoding: I=0, X=1, Z=2, Y=3 (Q# convention).
        """
        return (
            list(self.qubit_indices),
            [op.to_qrack_int() for op in self.pauli_ops],
        )

    def to_qiskit_c_arrays(self) -> tuple[list[int], list[int]]:
        """Parallel (qubit_indices, bit_terms) for Qiskit C API QkObsTerm."""
        return (
            list(self.qubit_indices),
            [op.to_qiskit_c_bit_term() for op in self.pauli_ops],
        )


class SparsePauliObservable(pydantic.BaseModel):
    """Sparse Pauli sum observable in coordinate (COO) format.

    The internal representation is modality-agnostic; backend adapters convert
    to their own encoding via the helper methods.

    Sums and scalar multiples compose with the usual operators, so a
    Hamiltonian written with the :func:`Pauli` shorthand reads like maths::

        H = 0.39 * Pauli("Z0") - 0.39 * Pauli("Z1") + 0.18 * Pauli("X0 X1")
    """

    num_qubits: int
    terms: list[PauliTerm]

    # ── Arithmetic ────────────────────────────────────────────────────────
    # Sums concatenate term lists; like terms are deliberately *not* merged
    # (Qiskit's SparsePauliOp behaves the same way).  Every expectation value
    # is linear in the terms, so an unmerged duplicate is only a wasted
    # measurement, never a wrong answer — call .simplify() to collapse them.

    def __add__(self, other: SparsePauliObservable) -> SparsePauliObservable:
        if not isinstance(other, SparsePauliObservable):
            raise TypeError(
                f"cannot add {type(other).__name__} to a SparsePauliObservable; "
                "wrap the scalar as a coefficient on the identity, e.g. "
                'Pauli("", 1.5)'
            )
        return SparsePauliObservable(
            num_qubits=max(self.num_qubits, other.num_qubits),
            terms=[*self.terms, *other.terms],
        )

    def __radd__(self, other: int) -> SparsePauliObservable:
        """Make ``sum(...)`` work — it starts from the integer 0."""
        if other != 0:
            raise TypeError(
                f"cannot add a SparsePauliObservable to {type(other).__name__}"
            )
        return self

    def __sub__(self, other: SparsePauliObservable) -> SparsePauliObservable:
        return self + (-other)

    def __neg__(self) -> SparsePauliObservable:
        return self * -1

    def __mul__(self, scalar: complex) -> SparsePauliObservable:
        if not isinstance(scalar, (int, float, complex)):
            raise TypeError(
                f"can only scale a SparsePauliObservable by a number, not "
                f"{type(scalar).__name__}"
            )
        return SparsePauliObservable(
            num_qubits=self.num_qubits,
            terms=[
                term.model_copy(
                    update={
                        "coefficient": ComplexNumber.from_complex(
                            term.coefficient.value * scalar
                        )
                    }
                )
                for term in self.terms
            ],
        )

    def __rmul__(self, scalar: complex) -> SparsePauliObservable:
        return self * scalar

    def __truediv__(self, scalar: complex) -> SparsePauliObservable:
        return self * (1 / scalar)

    def simplify(self, *, atol: float = 1e-12) -> SparsePauliObservable:
        """Merge terms acting with the same Paulis on the same qubits.

        Coefficients are summed and terms below ``atol`` are dropped; the
        surviving terms keep the order of their first appearance.  Factors
        within a term are order-independent (each acts on its own qubit), so
        'X0 Z1' and 'Z1 X0' merge.
        """
        merged: dict[tuple[tuple[int, PauliLabel], ...], complex] = {}
        for term in self.terms:
            key = tuple(
                sorted(
                    (q, op)
                    for q, op in zip(term.qubit_indices, term.pauli_ops)
                    if op != PauliLabel.I
                )
            )
            merged[key] = merged.get(key, 0j) + term.coefficient.value
        return SparsePauliObservable(
            num_qubits=self.num_qubits,
            terms=[
                PauliTerm(
                    qubit_indices=tuple(q for q, _ in key),
                    pauli_ops=tuple(op for _, op in key),
                    coefficient=ComplexNumber.from_complex(coeff),
                )
                for key, coeff in merged.items()
                if abs(coeff) > atol
            ],
        )

    @classmethod
    def from_cebule_operators(
        cls,
        operators: list[str],
        coefficients: list[float],
        num_qubits: int,
    ) -> SparsePauliObservable:
        """Convert Cebule Pauli operator strings to a SparsePauliObservable.

        Each operator string uses space-separated PauliLabel+index tokens,
        e.g. "X0 Y1 Z3".  The parallel coefficients list provides the weight
        for each term.

        Deliberately takes the two lists separately rather than
        TN_QC_OPT's own ``h_tn_opt_qubit`` 2-tuple: this is a general
        "labels + coefficients" constructor with more than one caller
        (``h_coeff_values`` arrives as a plain parallel list).  Use
        ``TNQCOptResult.to_sparse_pauli_observable()`` to go straight from
        a task result, which unpacks the tuple for you.
        """
        if len(operators) != len(coefficients):
            raise ValueError(
                f"operators length {len(operators)} != coefficients length {len(coefficients)}"
            )
        terms: list[PauliTerm] = []
        for op_str, coeff in zip(operators, coefficients):
            indices: list[int] = []
            ops: list[PauliLabel] = []
            for token in op_str.split():
                ops.append(PauliLabel(token[0]))
                indices.append(int(token[1:]))
            terms.append(
                PauliTerm(
                    qubit_indices=tuple(indices),
                    pauli_ops=tuple(ops),
                    coefficient=ComplexNumber(re=float(coeff)),
                )
            )
        return cls(num_qubits=num_qubits, terms=terms)

    def to_dense_matrix(
        self,
        *,
        real: bool = True,
        atol: float = 1e-10,
        max_qubits: int = 10,
    ) -> list[list[float]] | list[list[complex]]:
        """Expand the sparse Pauli sum into a dense 2**n x 2**n matrix.

        Standard Pauli tensor-product expansion: sum_i coeff_i * P_i, where
        each Pauli string is applied via its one-nonzero-per-column action
        (O(len(terms) * 2**n), no 4**n kron chain).

        real=True (default) validates that every imaginary part is below
        ``atol`` and returns plain floats — the shape Cebule's
        ``QASMGenInput.operator`` expects. A Hermitian sum can still have
        complex entries (odd Y counts); pass real=False to get them.

        Both conversions here are exponential by nature — ``max_qubits``
        (default 10) guards against accidental use on large observables.
        """
        if self.num_qubits > max_qubits:
            raise ValueError(
                f"to_dense_matrix on {self.num_qubits} qubits produces a "
                f"{2**self.num_qubits}x{2**self.num_qubits} matrix; raise "
                f"max_qubits= explicitly if you really want this"
            )
        dim = 2 ** self.num_qubits
        matrix: list[list[complex]] = [[0j] * dim for _ in range(dim)]
        for term in self.terms:
            coeff = term.coefficient.value
            for col in range(dim):
                row, phase = col, 1 + 0j
                for q, op in zip(term.qubit_indices, term.pauli_ops):
                    bit = (col >> q) & 1
                    if op == PauliLabel.X:
                        row ^= 1 << q
                    elif op == PauliLabel.Y:
                        row ^= 1 << q
                        phase *= 1j if bit == 0 else -1j
                    elif op == PauliLabel.Z:
                        phase *= 1 - 2 * bit
                matrix[row][col] += coeff * phase
        if not real:
            return matrix
        for r in matrix:
            for entry in r:
                if abs(entry.imag) > atol:
                    raise ValueError(
                        f"Matrix entry {entry!r} has imaginary part > atol="
                        f"{atol}; pass real=False for the complex matrix"
                    )
        return [[entry.real for entry in r] for r in matrix]

    @classmethod
    def from_dense_matrix(
        cls,
        matrix: list[list[float]] | list[list[complex]],
        num_qubits: int | None = None,
        *,
        atol: float = 1e-10,
        max_qubits: int = 8,
    ) -> SparsePauliObservable:
        """Decompose a dense 2**n x 2**n matrix into a sparse Pauli sum.

        Standard Pauli decomposition: coeff_P = Tr(P @ H) / 2**n for each
        of the 4**n Pauli strings, keeping only |coeff_P| > atol. Each
        trace uses the string's one-nonzero-per-column structure, so the
        total cost is O(8**n) — ``max_qubits`` (default 8) guards against
        accidental use on large matrices.

        The input need not be Hermitian, but non-Hermitian parts produce
        complex coefficients; round-trips with to_dense_matrix() exactly.
        """
        dim = len(matrix)
        if num_qubits is None:
            num_qubits = dim.bit_length() - 1
        if dim != 2 ** num_qubits or any(len(r) != dim for r in matrix):
            raise ValueError(
                f"matrix must be square with 2**num_qubits rows; got "
                f"{dim} rows for num_qubits={num_qubits}"
            )
        if num_qubits > max_qubits:
            raise ValueError(
                f"from_dense_matrix on {num_qubits} qubits scans "
                f"{4**num_qubits} Pauli strings; raise max_qubits= "
                f"explicitly if you really want this"
            )
        pauli_order = (PauliLabel.I, PauliLabel.X, PauliLabel.Y, PauliLabel.Z)
        terms: list[PauliTerm] = []
        for string_index in range(4 ** num_qubits):
            ops_all: list[PauliLabel] = []
            rest = string_index
            for _ in range(num_qubits):
                ops_all.append(pauli_order[rest % 4])
                rest //= 4
            # Tr(P @ H) via P's one-nonzero-per-column action: P|col> =
            # phase * |col ^ xmask>, so Tr(P H) = sum_col phase * H[col][col ^ xmask]
            trace = 0j
            for col in range(dim):
                row, phase = col, 1 + 0j
                for q, op in enumerate(ops_all):
                    bit = (col >> q) & 1
                    if op == PauliLabel.X:
                        row ^= 1 << q
                    elif op == PauliLabel.Y:
                        row ^= 1 << q
                        phase *= 1j if bit == 0 else -1j
                    elif op == PauliLabel.Z:
                        phase *= 1 - 2 * bit
                trace += phase * complex(matrix[col][row])
            coeff = trace / dim
            if abs(coeff) <= atol:
                continue
            indices = tuple(q for q, op in enumerate(ops_all) if op != PauliLabel.I)
            ops = tuple(op for op in ops_all if op != PauliLabel.I)
            terms.append(
                PauliTerm(
                    qubit_indices=indices,
                    pauli_ops=ops,
                    coefficient=ComplexNumber(re=coeff.real, im=coeff.imag),
                )
            )
        return cls(num_qubits=num_qubits, terms=terms)

    def to_qiskit_pauli_list(self, num_qubits: int) -> list[tuple[str, complex]]:
        """(pauli_label, coefficient) pairs for ``SparsePauliOp.from_list()``.

        Labels are full-length (one character per qubit, 'I'-padded).
        Qiskit's own convention has the rightmost character as qubit 0
        (verified: ``SparsePauliOp.from_list([("IZ", 1.0)])`` evaluates to
        -1.0 on a circuit with only ``x(0)`` applied — qubit 0 is the last
        character).
        """
        pairs: list[tuple[str, complex]] = []
        for term in self.terms:
            chars = ["I"] * num_qubits
            for idx, op in zip(term.qubit_indices, term.pauli_ops):
                chars[idx] = op.value
            label = "".join(reversed(chars))
            pairs.append((label, term.coefficient.value))
        return pairs

    def to_pennylane_observable(self) -> Any:
        """Build a `pennylane.Hamiltonian` equivalent to this observable.

        Requires `pennylane` to be installed (imported lazily). Coefficients
        must be real — a Hermitian observable's Pauli-sum coefficients are
        real by construction; a non-zero imaginary part means the sum isn't
        Hermitian and raises rather than silently discarding it.
        """
        import pennylane as qml

        pauli_factory = {
            PauliLabel.X: qml.PauliX,
            PauliLabel.Y: qml.PauliY,
            PauliLabel.Z: qml.PauliZ,
        }
        coeffs: list[float] = []
        observables: list[Any] = []
        for term in self.terms:
            if abs(term.coefficient.im) > 1e-12:
                raise ValueError(
                    f"Non-Hermitian term coefficient {term.coefficient.value!r} "
                    "has no real PennyLane Hamiltonian equivalent"
                )
            factors = [
                pauli_factory[op](idx)
                for idx, op in zip(term.qubit_indices, term.pauli_ops)
                if op != PauliLabel.I
            ]
            observable = factors[0] if factors else qml.Identity(0)
            for factor in factors[1:]:
                observable = observable @ factor
            coeffs.append(term.coefficient.re)
            observables.append(observable)
        return qml.Hamiltonian(coeffs, observables)

    def to_qrack_flat_arrays(self) -> tuple[list[int], list[int]]:
        """Flatten all terms into a single (qubits, paulis) pair for Qrack.

        Used with the multi-term variant of PauliExpectation.  Terms are
        concatenated; the caller must also supply the per-term coefficients
        separately (Qrack handles summation internally).
        """
        qubits: list[int] = []
        paulis: list[int] = []
        for term in self.terms:
            q, p = term.to_qrack_arrays()
            qubits.extend(q)
            paulis.extend(p)
        return qubits, paulis


_PAULI_LETTERS = frozenset("IXYZ")


def _parse_pauli_term(spec: str, coefficient: complex) -> PauliTerm:
    """Parse one Pauli string into a PauliTerm.

    Factors are separated by spaces, commas, or both; each is a Pauli letter
    followed by a 0-based qubit index ('X0', 'z3').  The empty string is the
    identity term.
    """
    indices: list[int] = []
    ops: list[PauliLabel] = []
    for token in spec.replace(",", " ").split():
        letter, digits = token[0].upper(), token[1:]
        if letter not in _PAULI_LETTERS or not digits.isdigit():
            raise ValueError(
                f"Malformed Pauli factor {token!r} in {spec!r}: expected a Pauli "
                "letter (I/X/Y/Z) followed by a 0-based qubit index, e.g. "
                "'X0 Y1' or 'Z0,Z1'"
            )
        index = int(digits)
        if index in indices:
            raise ValueError(
                f"Qubit {index} carries more than one factor in {spec!r}; give "
                "their product as a single factor instead"
            )
        indices.append(index)
        ops.append(PauliLabel(letter))
    # Sort by qubit index so that 'X0 Y1' and 'Y1 X0' — the same operator,
    # since each factor acts on its own qubit — also serialise identically.
    ordered = sorted(zip(indices, ops))
    return PauliTerm(
        qubit_indices=tuple(index for index, _ in ordered),
        pauli_ops=tuple(op for _, op in ordered),
        coefficient=ComplexNumber.from_complex(coefficient),
    )


def Pauli(  # noqa: N802 -- reads as a constructor at call sites, not a function
    spec: str | dict[str, complex],
    coefficient: complex = 1.0,
    *,
    num_qubits: int | None = None,
) -> SparsePauliObservable:
    """Build a SparsePauliObservable from a Pauli string — the short spelling.

    ``spec`` is either one Pauli string with an optional coefficient, or a
    ``{pauli_string: coefficient}`` mapping for a multi-term sum::

        Pauli("Z0 Z1")                      # <ZZ> on a two-qubit register
        Pauli("X0", 0.5)                    # 0.5 * X0
        Pauli({"Z0": 0.39, "X0 X1": 0.18})  # a two-term Hamiltonian
        Pauli("")                           # the identity term

    Factors may be separated by spaces or commas, so both the Cebule-style
    "X0 Y1" and the comma-separated "X0,Y1" spellings parse.  Letter case
    and factor order are irrelevant — each factor acts on its own qubit, and
    factors are stored sorted by index so equal operators compare equal — while
    a qubit carrying two factors is rejected rather than silently ordered.

    ``num_qubits`` defaults to one past the highest index mentioned, which is
    what you want whenever the observable spans the whole register.  Pass it
    explicitly for an observable on a register wider than it touches (an
    identity-only term mentions no qubit at all, so it infers 0).

    The results compose, so a Hamiltonian can be written as a sum::

        H = -1.05 * Pauli("") + 0.39 * Pauli("Z0") + 0.18 * Pauli("X0 X1")
    """
    if isinstance(spec, dict):
        if coefficient != 1.0:
            raise ValueError(
                "Pass coefficients in the mapping's values, not as the second "
                "argument, when spec is a dict"
            )
        terms = [_parse_pauli_term(s, c) for s, c in spec.items()]
    else:
        terms = [_parse_pauli_term(spec, coefficient)]
    if num_qubits is None:
        num_qubits = max(
            (index + 1 for term in terms for index in term.qubit_indices),
            default=0,
        )
    return SparsePauliObservable(num_qubits=num_qubits, terms=terms)
