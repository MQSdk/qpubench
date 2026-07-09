"""Pauli-string exponential circuit synthesis: exp(-i * angle * P) -> QASM3.

Standard construction (basis change, CNOT staircase, RZ, inverse CNOT
staircase, inverse basis change) — verified against scipy.linalg.expm for
representative multi-qubit Pauli strings before being written here (see
qubit-index gaps, X/Y/Z mixes, and multi-term ansätze in
tests/test_generic_adapt_vqe.py).

Convention: qubit index == QASM3 qubit register index; RZ angle is 2*angle
(standard factor-of-2 between a Pauli rotation gate and the operator
exponential it implements).
"""
from __future__ import annotations

import math

from qpubench.schemas.observable import PauliTerm

_PAULI_VALUE = {"X": "X", "Y": "Y", "Z": "Z"}


def _label(pauli) -> str:
    return pauli.value if hasattr(pauli, "value") else str(pauli)


def pauli_exponential_qasm3_lines(
    qubit_indices: tuple[int, ...],
    pauli_labels: tuple,
    angle: float,
    qubit_register: str = "q",
) -> list[str]:
    """QASM3 instruction lines implementing exp(-i * angle * P).

    P is the Pauli string with pauli_labels[k] acting on qubit_indices[k]
    (all other qubits implicitly identity). Non-Pauli (identity) qubits in
    a term are simply absent from qubit_indices/pauli_labels.
    """
    if not qubit_indices:
        return []  # identity term contributes no gates

    lines: list[str] = []
    reg = qubit_register

    def q(i: int) -> str:
        return f"{reg}[{i}]"

    # 1. basis change: X -> H, Y -> Rx(pi/2)
    for qi, p in zip(qubit_indices, pauli_labels):
        label = _label(p)
        if label == "X":
            lines.append(f"h {q(qi)};")
        elif label == "Y":
            lines.append(f"rx({math.pi / 2}) {q(qi)};")
        # Z: no basis change needed

    # 2. CNOT staircase over sorted qubit indices, entangling parity onto the last
    sorted_qubits = sorted(qubit_indices)
    for a, b in zip(sorted_qubits[:-1], sorted_qubits[1:]):
        lines.append(f"cx {q(a)}, {q(b)};")

    # 3. RZ(2*angle) on the last qubit
    lines.append(f"rz({2 * angle}) {q(sorted_qubits[-1])};")

    # 4. inverse CNOT staircase
    for a, b in zip(sorted_qubits[:-1][::-1], sorted_qubits[1:][::-1]):
        lines.append(f"cx {q(a)}, {q(b)};")

    # 5. inverse basis change: H is self-inverse, Rx(pi/2) inverse is Rx(-pi/2)
    for qi, p in zip(qubit_indices, pauli_labels):
        label = _label(p)
        if label == "X":
            lines.append(f"h {q(qi)};")
        elif label == "Y":
            lines.append(f"rx({-math.pi / 2}) {q(qi)};")

    return lines


def operator_trotter_step_qasm3(
    term: PauliTerm,
    parameter: float,
    qubit_register: str = "q",
) -> list[str]:
    """QASM3 lines for exp(-i * (coefficient.im * parameter) * P) for one Pauli term.

    Excitation-generator Pauli terms carry a purely imaginary coefficient
    (coefficient.im); the physical rotation angle exponentiated by the
    circuit is coefficient.im * parameter (parameter is the UCC amplitude
    for this operator, shared across all of the operator's Pauli terms).
    """
    angle = term.coefficient.im * parameter
    return pauli_exponential_qasm3_lines(
        term.qubit_indices, term.pauli_ops, angle, qubit_register=qubit_register
    )
