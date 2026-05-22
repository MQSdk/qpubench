from __future__ import annotations

import pydantic

from .primitives import ComplexNumber, PauliLabel


class PauliTerm(pydantic.BaseModel):
    """One term in a sparse Pauli sum.

    Compatible with:
      - Qrack: PauliExpectation(qubits[], paulis[]) via to_qrack_arrays()
      - Qiskit C: QkObsTerm {coeff, bit_terms[], indices[]} via to_qiskit_c_arrays()
      - VQEBench legacy: dict["X1,Z3", float] via SparsePauliObservable.from_legacy_dict()
    """
    qubit_indices: tuple[int, ...]
    pauli_ops:     tuple[PauliLabel, ...]
    coefficient:   ComplexNumber = pydantic.Field(
        default_factory=lambda: ComplexNumber(re=1.0)
    )

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
        """Convert VQEBench Observable dict format ('X1,Z3' -> float).

        Each key is a comma-separated list of single-character Pauli followed
        by a 0-based qubit index.  Example: {"X1,Z3": 0.5, "Z0": -1.0}.
        """
        terms: list[PauliTerm] = []
        for pauli_str, coeff in obs.items():
            indices, ops = [], []
            for part in pauli_str.split(","):
                ops.append(PauliLabel(part[0]))
                indices.append(int(part[1:]))
            terms.append(PauliTerm(
                qubit_indices=tuple(indices),
                pauli_ops=tuple(ops),
                coefficient=ComplexNumber(re=float(coeff)),
            ))
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
            terms.append(PauliTerm(
                qubit_indices=tuple(indices),
                pauli_ops=tuple(ops),
                coefficient=ComplexNumber(re=float(coeff)),
            ))
        return cls(num_qubits=num_qubits, terms=terms)

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
