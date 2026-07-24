from __future__ import annotations

from typing import Any

import pydantic

from .primitives import ComplexNumber, PauliLabel


class PauliTerm(pydantic.BaseModel):
    """One term in a sparse Pauli sum.

    Compatible with:
      - Qrack: PauliExpectation(qubits[], paulis[]) via to_qrack_arrays()
      - Qiskit C: QkObsTerm {coeff, bit_terms[], indices[]} via to_qiskit_c_arrays()
      - Legacy sparse-dict: dict["X1,Z3", float] via SparsePauliObservable.from_legacy_dict()
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
    """

    num_qubits: int
    terms: list[PauliTerm]

    @classmethod
    def from_legacy_dict(
        cls,
        obs: dict[str, float],
        num_qubits: int,
    ) -> SparsePauliObservable:
        """Convert a legacy sparse-dict observable format ('X1,Z3' -> float).

        Each key is a comma-separated list of single-character Pauli followed
        by a 0-based qubit index.  Example: {"X1,Z3": 0.5, "Z0": -1.0}.
        """
        terms: list[PauliTerm] = []
        for pauli_str, coeff in obs.items():
            indices, ops = [], []
            for part in pauli_str.split(","):
                ops.append(PauliLabel(part[0]))
                indices.append(int(part[1:]))
            terms.append(
                PauliTerm(
                    qubit_indices=tuple(indices),
                    pauli_ops=tuple(ops),
                    coefficient=ComplexNumber(re=float(coeff)),
                )
            )
        return cls(num_qubits=num_qubits, terms=terms)

    @classmethod
    def from_cebule_operators(
        cls,
        operators: list[str],
        coefficients: list[float],
        num_qubits: int,
    ) -> SparsePauliObservable:
        """Convert Cebule TN_QC_OPT qubit_operators to a SparsePauliObservable.

        Each operator string uses space-separated PauliLabel+index tokens,
        e.g. "X0 Y1 Z3".  The parallel coefficients list provides the weight
        for each term (from h_coeff_values or h_tn_opt_qubit).
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
