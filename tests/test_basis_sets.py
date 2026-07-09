"""Tests for qpubench.schemas.basis_sets + hamiltonian_sources.basis_set_exchange.

Real, offline, fast — `basis_set_exchange` bundles its data locally (no
network access, unlike `hamlib.py`/`pennylane_qchem.py`). Expected function
counts are cross-checked against real `pyscf.gto.M(...).nao` values in this
session (see `hamiltonian_sources/basis_set_exchange.py`'s module docstring)
for every (element, basis) pair appearing in
`data/IBM_VQE_Test_Benchmark.csv`.
"""
from __future__ import annotations

import pytest

pytest.importorskip("basis_set_exchange")

from qpubench.hamiltonian_sources.basis_set_exchange import (
    count_basis_functions,
    get_basis_set_entry,
    list_available_elements,
)
from qpubench.schemas.basis_sets import (
    BASIS_SET_CATALOG,
    BasisSetSource,
)


class TestBasisSetCatalog:
    def test_six_bse_bases_present(self) -> None:
        bse_names = {
            k for k, v in BASIS_SET_CATALOG.items()
            if v.source is BasisSetSource.BASIS_SET_EXCHANGE
        }
        assert bse_names == {"sto-3g", "6-31g", "cc-pvdz", "cc-pvtz", "def2-svp", "def2-tzvp"}

    def test_qvszp_catalog_entry(self) -> None:
        """requires_external_tool is False: element/function counts are
        real and offline-computable via hamiltonian_sources.qvszp — only
        molecule-specific charge-adapted *coefficients* need the real CLI,
        see schemas.basis_sets.QvSZPRunConfig."""
        entry = BASIS_SET_CATALOG["qvszp"]
        assert entry.source is BasisSetSource.GRIMME_QVSZP
        assert entry.requires_external_tool is False
        assert entry.cardinality is None


class TestGetBasisSetEntry:
    def test_confirms_against_real_bse_metadata(self) -> None:
        entry = get_basis_set_entry("cc-pvdz")
        assert entry.name == "cc-pvdz"

    def test_rejects_qvszp(self) -> None:
        with pytest.raises(ValueError, match="no Python API"):
            get_basis_set_entry("qvszp")

    def test_rejects_unknown_name(self) -> None:
        with pytest.raises(ValueError):
            get_basis_set_entry("not-a-real-basis")


class TestListAvailableElements:
    def test_sto3g_covers_first_row(self) -> None:
        elements = list_available_elements("sto-3g")
        assert {"H", "Li", "O"}.issubset(set(elements))


class TestCountBasisFunctions:
    # (element, basis) -> expected spatial AO function count, matching
    # real pyscf.gto.M(...).nao exactly (verified in this session for every
    # molecule/basis combination in data/IBM_VQE_Test_Benchmark.csv).
    @pytest.mark.parametrize(
        "element,basis,expected",
        [
            ("H", "sto-3g", 1), ("H", "6-31g", 2), ("H", "cc-pvdz", 5),
            ("H", "cc-pvtz", 14), ("H", "def2-svp", 5), ("H", "def2-tzvp", 6),
            ("Li", "sto-3g", 5), ("Li", "6-31g", 9), ("Li", "cc-pvdz", 14),
            ("Li", "cc-pvtz", 30), ("Li", "def2-svp", 9), ("Li", "def2-tzvp", 14),
            ("O", "sto-3g", 5), ("O", "6-31g", 9), ("O", "cc-pvdz", 14),
            ("O", "cc-pvtz", 30), ("O", "def2-svp", 14), ("O", "def2-tzvp", 31),
        ],
    )
    def test_matches_real_pyscf_nao(self, element: str, basis: str, expected: int) -> None:
        assert count_basis_functions(basis, element) == expected

    def test_rejects_qvszp(self) -> None:
        with pytest.raises(ValueError, match="no Python API"):
            count_basis_functions("qvszp", "H")
