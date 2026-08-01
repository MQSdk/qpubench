"""Qubit counts for Cebule's MOL_MAP constraint-based encoding.

No install required — this is arithmetic, not a Hamiltonian build.

MOL_MAP encodes a molecular Hamiltonian by indexing only the
determinants that satisfy the particle-number and spin constraints,
rather than assigning one qubit per spin orbital the way Jordan-Wigner
does.  The qubit count is therefore set by how many such determinants
exist, not by the basis-set size directly:

    n_qubits = ceil(log2( C(n_orbitals, n_alpha) * C(n_orbitals, n_beta) ))

**Inferred, not taken from Cebule documentation.**  docs.mqs.dk states
only that the encoding uses "< 2N" qubits and that the real count is an
output of a MOL_MAP run.  The formula above was reverse-engineered from
the eight real MOL_MAP qubit counts known to this project, and reproduces
every one of them exactly (see `tests/test_mol_map.py`):

    molecule / basis     (n_orb, n_a, n_b)   determinants   qubits
    H2   / sto-3g            (2, 1, 1)                  4        2
    H2   / 6-31G             (4, 1, 1)                 16        4
    H2   / cc-pVDZ          (10, 1, 1)                100        7
    H2   / def2-SVP         (10, 1, 1)                100        7
    H2   / def2-TZVP        (12, 1, 1)                144        8
    H2   / cc-pVTZ          (28, 1, 1)                784       10
    H2O  / sto-3g            (7, 5, 5)                441        9
    Li2  / sto-3g           (10, 3, 3)             14,400       14

Two independent checks that this is the real rule and not a coincidental
fit: H2/cc-pVDZ and H2/def2-SVP have different basis sets but the same
(n_orb, n_a, n_b) and the same reported count (7), which a basis-size
formula would not predict; and Li2/sto-3g and H2/cc-pVDZ share n_orb=10
but differ in electron count, giving 14 vs 7 as the formula requires.

Treat predictions from this function as *estimates* — good enough to size
a circuit and cost a batch, not a substitute for a real MOL_MAP run when
the exact number matters.  `count_qubits(..., known_only=True)` returns
only the confirmed values.
"""
from __future__ import annotations

from math import comb, log2

# Real MOL_MAP qubit counts, keyed by (n_orbitals, n_alpha, n_beta).
# Sources: the project's own MOL_MAP runs, reported 2026-08-01.  Every
# entry is reproduced exactly by `count_qubits()`.
CONFIRMED_QUBIT_COUNTS: dict[tuple[int, int, int], int] = {
    (2, 1, 1):  2,    # H2  / sto-3g
    (4, 1, 1):  4,    # H2  / 6-31G
    (10, 1, 1): 7,    # H2  / cc-pVDZ, def2-SVP
    (12, 1, 1): 8,    # H2  / def2-TZVP
    (28, 1, 1): 10,   # H2  / cc-pVTZ
    (7, 5, 5):  9,    # H2O / sto-3g
    (10, 3, 3): 14,   # Li2 / sto-3g
}


def count_determinants(n_orbitals: int, n_alpha: int, n_beta: int) -> int:
    """Number of determinants conserving particle number and Sz.

    This is the dimension of the space MOL_MAP has to index: choose
    `n_alpha` of the `n_orbitals` spatial orbitals for the spin-up
    electrons, independently the same for spin-down.
    """
    if n_orbitals < 0:
        raise ValueError(f"n_orbitals must be non-negative, got {n_orbitals}")
    for name, n in (("n_alpha", n_alpha), ("n_beta", n_beta)):
        if not 0 <= n <= n_orbitals:
            raise ValueError(
                f"{name}={n} out of range for n_orbitals={n_orbitals}"
            )
    return comb(n_orbitals, n_alpha) * comb(n_orbitals, n_beta)


def count_qubits(
    n_orbitals: int,
    n_alpha: int,
    n_beta: int,
    *,
    known_only: bool = False,
) -> int | None:
    """Qubits MOL_MAP's constraint encoding needs for this active space.

    `known_only=True` returns a count only for the (n_orbitals, n_alpha,
    n_beta) combinations in `CONFIRMED_QUBIT_COUNTS` and None otherwise —
    use it when a predicted value would be indistinguishable from a
    measured one downstream.
    """
    key = (n_orbitals, n_alpha, n_beta)
    if known_only:
        return CONFIRMED_QUBIT_COUNTS.get(key)
    n_determinants = count_determinants(n_orbitals, n_alpha, n_beta)
    if n_determinants <= 1:
        return 0
    return _ceil_log2(n_determinants)


def is_confirmed(n_orbitals: int, n_alpha: int, n_beta: int) -> bool:
    """True when a real MOL_MAP run has reported this active space's count."""
    return (n_orbitals, n_alpha, n_beta) in CONFIRMED_QUBIT_COUNTS


def jordan_wigner_qubits(n_orbitals: int) -> int:
    """Qubits Jordan-Wigner needs for the same active space, for contrast."""
    return 2 * n_orbitals


def _ceil_log2(n: int) -> int:
    """Exact ceil(log2(n)) — `math.log2` alone misrounds near powers of 2."""
    bits = (n - 1).bit_length()
    assert bits >= log2(n) - 1e-9, f"ceil(log2({n})) sanity check"
    return bits
