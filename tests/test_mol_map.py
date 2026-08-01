"""Tests for qpubench.hamiltonian_sources.mol_map.

Fully offline and always run — the module is arithmetic, with no SDK or
network dependency.

The point of these tests is to pin the *inferred* constraint-encoding
formula to every real MOL_MAP qubit count this project knows about. If
Cebule's encoding changes, or a new real run contradicts the formula,
`test_reproduces_every_confirmed_count` is what should fail.
"""
from __future__ import annotations

import pytest

from qpubench.hamiltonian_sources.mol_map import (
    CONFIRMED_QUBIT_COUNTS,
    count_determinants,
    count_qubits,
    is_confirmed,
    jordan_wigner_qubits,
)


class TestConfirmedCounts:
    # (molecule/basis label, n_orbitals, n_alpha, n_beta, real MOL_MAP qubits)
    REAL_RUNS = [
        ("H2/sto-3g",     2, 1, 1,  2),
        ("H2/6-31G",      4, 1, 1,  4),
        ("H2/cc-pVDZ",   10, 1, 1,  7),
        ("H2/def2-SVP",  10, 1, 1,  7),
        ("H2/def2-TZVP", 12, 1, 1,  8),
        ("H2/cc-pVTZ",   28, 1, 1, 10),
        ("H2O/sto-3g",    7, 5, 5,  9),
        ("Li2/sto-3g",   10, 3, 3, 14),
    ]

    @pytest.mark.parametrize("label,n_orb,n_a,n_b,expected", REAL_RUNS)
    def test_reproduces_every_confirmed_count(
        self, label: str, n_orb: int, n_a: int, n_b: int, expected: int
    ) -> None:
        assert count_qubits(n_orb, n_a, n_b) == expected, label

    def test_same_active_space_different_basis_agrees(self) -> None:
        """H2/cc-pVDZ and H2/def2-SVP are different basis sets with the
        same (n_orb, n_a, n_b) and the same reported count — the check
        that the count follows the active space, not the basis name."""
        assert count_qubits(10, 1, 1) == count_qubits(10, 1, 1) == 7

    def test_same_orbital_count_different_electrons_diverges(self) -> None:
        """Li2/sto-3g and H2/cc-pVDZ share n_orb=10 but not electron
        count, and really do differ (14 vs 7)."""
        assert count_qubits(10, 3, 3) == 14
        assert count_qubits(10, 1, 1) == 7

    def test_confirmed_table_is_self_consistent(self) -> None:
        for (n_orb, n_a, n_b), expected in CONFIRMED_QUBIT_COUNTS.items():
            assert count_qubits(n_orb, n_a, n_b) == expected

    def test_is_confirmed_distinguishes_real_from_predicted(self) -> None:
        assert is_confirmed(10, 3, 3)          # Li2/sto-3g, a real run
        assert not is_confirmed(20, 3, 3)      # Li2/6-31G, formula only

    def test_known_only_withholds_predictions(self) -> None:
        assert count_qubits(10, 3, 3, known_only=True) == 14
        assert count_qubits(20, 3, 3, known_only=True) is None


class TestDeterminantCounting:
    def test_closed_shell_squares_the_alpha_count(self) -> None:
        # H2O/sto-3g: C(7,5) = 21 alpha strings, same for beta.
        assert count_determinants(7, 5, 5) == 21 * 21 == 441

    def test_full_occupation_leaves_one_determinant(self) -> None:
        assert count_determinants(5, 5, 5) == 1
        assert count_qubits(5, 5, 5) == 0

    @pytest.mark.parametrize("n_a,n_b", [(-1, 1), (1, -1), (3, 1), (1, 3)])
    def test_rejects_out_of_range_occupations(self, n_a: int, n_b: int) -> None:
        with pytest.raises(ValueError):
            count_determinants(2, n_a, n_b)

    def test_rejects_negative_orbital_count(self) -> None:
        with pytest.raises(ValueError):
            count_determinants(-1, 0, 0)


class TestAgainstJordanWigner:
    @pytest.mark.parametrize(
        "n_orb,n_a,n_b", [(2, 1, 1), (10, 1, 1), (7, 5, 5), (10, 3, 3), (28, 1, 1)]
    )
    def test_never_exceeds_jordan_wigner(self, n_orb: int, n_a: int, n_b: int) -> None:
        """docs.mqs.dk's one hard claim about the encoding: fewer than 2N
        qubits."""
        assert count_qubits(n_orb, n_a, n_b) < jordan_wigner_qubits(n_orb)

    def test_ceil_log2_is_exact_at_powers_of_two(self) -> None:
        """H2/6-31G lands on exactly 16 determinants; a float log2 here
        rounds the wrong way often enough to be worth pinning."""
        assert count_determinants(4, 1, 1) == 16
        assert count_qubits(4, 1, 1) == 4
        assert count_qubits(2, 1, 1) == 2       # exactly 4 determinants
