"""Package-agnostic fermionic singles+doubles ADAPT-VQE operator pool.

Pure Python + qpubench schemas — no vendor SDK dependency. Builds the
Jordan-Wigner-mapped Pauli decomposition of the anti-Hermitian fermionic
excitation generators used by UCC-style ansätze, so the same pool can drive
an ADAPT-VQE loop regardless of which package ultimately executes the
circuit (evangelistalab/qforte, raw Qiskit, QDK/Azure Quantum, ...).

Spin-orbital convention
------------------------
Qubit index == spin-orbital index. The reference (HF) state occupies the
lowest `num_electrons` spin-orbitals — callers supply the actual
occupied/virtual index sets from their own orbital ordering (interleaved
alpha/beta, blocked, etc.); this module only needs "which indices are
occupied" and "which are virtual" as plain integers.

Jordan-Wigner mapping
----------------------
Single excitation generator (p virtual, q occupied, p > q):
    a_p^dagger a_q - a_q^dagger a_p
      = (i/2) [ X_p Z(q+1..p-1) Y_q  -  Y_p Z(q+1..p-1) X_q ]

Double excitation generator (p > q virtual, r > s occupied, non-interleaved
— every virtual index sorts above every occupied index, see
double_excitation_observable):
    a_p^dagger a_q^dagger a_r a_s - a_s^dagger a_r^dagger a_q a_p
      = -(i/8) Σ_k sign_k · [P_p P_q P_r P_s]_k · Z(q+1..p-1) · Z(s+1..r-1)
    summed over the 8 X/Y assignments to (p,q,r,s) with an odd number of Y
    operators (4 with one Y, 4 with three Y's); sign_k is the pattern in
    _DOUBLE_SIGNS below. Rather than trust a textbook formula from memory
    (published sources disagree with each other on sign convention), this
    was derived empirically — projecting the exact operator onto the Pauli
    basis via Tr(ref @ P)/2^n for a dense Jordan-Wigner creation/
    annihilation-operator matrix construction (numpy) — and is verified
    exactly (max|diff| = 0) against that same construction in tests/,
    for both adjacent and spread-out index quadruples.
"""
from __future__ import annotations

import itertools

from qpubench.schemas.observable import PauliTerm, SparsePauliObservable
from qpubench.schemas.primitives import ComplexNumber, PauliLabel


def single_excitation_observable(p: int, q: int, num_qubits: int) -> SparsePauliObservable:
    """a_p^dagger a_q - a_q^dagger a_p, Jordan-Wigner mapped. Requires p > q."""
    if p <= q:
        raise ValueError(f"single_excitation_observable requires p > q; got p={p}, q={q}")
    z_range = tuple(range(q + 1, p))

    def term(head_pauli: PauliLabel, tail_pauli: PauliLabel, coeff_im: float) -> PauliTerm:
        indices = (p, *z_range, q)
        paulis = (head_pauli, *([PauliLabel.Z] * len(z_range)), tail_pauli)
        return PauliTerm(
            qubit_indices=indices,
            pauli_ops=paulis,
            coefficient=ComplexNumber(re=0.0, im=coeff_im),
        )

    terms = [
        term(PauliLabel.X, PauliLabel.Y, 0.5),
        term(PauliLabel.Y, PauliLabel.X, -0.5),
    ]
    return SparsePauliObservable(num_qubits=num_qubits, terms=terms)


# UCCSD/JW double-excitation sign table — 4 single-Y and 4 triple-Y terms
# over (p, q, r, s). See module docstring for how this was derived/verified.
_DOUBLE_SIGNS: tuple[tuple[str, float], ...] = (
    ("XXXY", +1.0),
    ("XXYX", +1.0),
    ("XYXX", -1.0),
    ("YXXX", -1.0),
    ("XYYY", +1.0),
    ("YXYY", +1.0),
    ("YYXY", -1.0),
    ("YYYX", -1.0),
)


def double_excitation_observable(
    p: int, q: int, r: int, s: int, num_qubits: int,
) -> SparsePauliObservable:
    """a_p^dagger a_q^dagger a_r a_s - h.c., Jordan-Wigner mapped.

    Requires p > q (virtual pair) and r > s (occupied pair), AND the two
    pairs non-interleaved — min(p, q) > max(r, s) — i.e. every virtual
    index sorts above every occupied index. This always holds for pools
    built by generate_singles_doubles_pool() (occupied = low indices,
    virtual = high indices), which is the only caller in this module.
    Z-strings fill each pair's own span (q+1..p-1 and s+1..r-1); the
    formula does not extend a Z-string across the gap between the pairs,
    which is only valid in this non-interleaved regime (see module
    docstring and the numpy cross-check in tests/).
    """
    if not (p > q and r > s):
        raise ValueError(
            f"double_excitation_observable requires p>q and r>s; got p={p}, q={q}, r={r}, s={s}"
        )
    if len({p, q, r, s}) != 4:
        raise ValueError(f"p,q,r,s must be distinct; got {(p, q, r, s)}")
    if q <= max(r, s):
        raise ValueError(
            "double_excitation_observable requires the virtual pair (p,q) to sort "
            f"entirely above the occupied pair (r,s); got p={p}, q={q}, r={r}, s={s}"
        )

    z_pq = tuple(range(q + 1, p))
    z_rs = tuple(range(s + 1, r))
    _LABEL = {"X": PauliLabel.X, "Y": PauliLabel.Y}

    terms: list[PauliTerm] = []
    for pattern, sign in _DOUBLE_SIGNS:
        pauli_p, pauli_q, pauli_r, pauli_s = (_LABEL[c] for c in pattern)
        indices = (p, *z_pq, q, r, *z_rs, s)
        paulis = (
            pauli_p, *([PauliLabel.Z] * len(z_pq)), pauli_q,
            pauli_r, *([PauliLabel.Z] * len(z_rs)), pauli_s,
        )
        # Overall factor i/8; sign table already carries the +-1.
        terms.append(PauliTerm(
            qubit_indices=indices,
            pauli_ops=paulis,
            coefficient=ComplexNumber(re=0.0, im=-sign / 8.0),
        ))
    return SparsePauliObservable(num_qubits=num_qubits, terms=terms)


class PoolOperator:
    """One ADAPT-VQE pool entry: a labeled excitation generator."""

    def __init__(self, label: str, observable: SparsePauliObservable, indices: tuple[int, ...]):
        self.label      = label
        self.observable = observable
        self.indices    = indices

    def __repr__(self) -> str:
        return f"PoolOperator({self.label!r}, {len(self.observable.terms)} Pauli terms)"


def generate_singles_doubles_pool(
    num_qubits: int,
    num_electrons: int,
) -> list[PoolOperator]:
    """Spin-orbital singles + doubles excitation pool ("SD" in AdaptVQERunConfig.pool_type).

    occupied = [0, num_electrons)   virtual = [num_electrons, num_qubits)
    Matches the ADAPT-VQE convention of screening single and double
    excitations out of the reference determinant (Grimsley et al., Nat.
    Commun. 10, 3007 (2019)).
    """
    occupied = list(range(num_electrons))
    virtual  = list(range(num_electrons, num_qubits))
    pool: list[PoolOperator] = []

    for q in occupied:
        for p in virtual:
            pool.append(PoolOperator(
                label=f"single_{p}_{q}",
                observable=single_excitation_observable(p, q, num_qubits),
                indices=(p, q),
            ))

    for r, s in itertools.combinations(sorted(occupied, reverse=True), 2):
        for p, q in itertools.combinations(sorted(virtual, reverse=True), 2):
            pool.append(PoolOperator(
                label=f"double_{p}_{q}_{r}_{s}",
                observable=double_excitation_observable(p, q, r, s, num_qubits),
                indices=(p, q, r, s),
            ))

    return pool
