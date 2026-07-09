"""Tests for qpubench.hamiltonian_sources.qvszp.

The parser tests are offline and always run — real excerpts of q-vSZP's
own `basisq`/`ecpq` files (H, Li blocks), captured verbatim in this
session by downloading https://raw.githubusercontent.com/grimme-lab/
qvSZP/main/q-vSZP_basis/{basisq,ecpq}, hardcoded as fixtures so no network
is needed to verify the parsing logic itself — same pattern as
`test_hamiltonian_sources.py`'s HamLib regex-parser test.

The live-download tests are network-dependent and opt-in via
QPUBENCH_NETWORK_TESTS=1, consistent with the rest of this test suite.
"""
from __future__ import annotations

import os

import pytest

from qpubench.hamiltonian_sources.qvszp import (
    element_z,
    parse_qvszp_ecp_core_electrons,
    parse_qvszp_shells,
)

_NETWORK_TESTS_ENABLED = os.environ.get("QPUBENCH_NETWORK_TESTS") == "1"

# H (Z=1) and Li (Z=3) blocks, captured verbatim from the real
# q-vSZP_basis/basisq in this session.
_REAL_BASISQ_EXCERPT = """\
*
  1      0.423798991900      0.227246065500     -0.148223538300
           8 s
    337.005012218500      0.000879795140      0.000529639723
     53.310531051500      0.006917416526      0.001149545963
     12.208253481400      0.034245408476      0.016233460796
      3.418826909800      0.143386442786      0.042006873944
      1.108790125800      0.386719184972      0.197553361888
      0.478717798300      0.505046100202      0.000287838095
      0.212137087700      0.651854283196      0.000158775612
      0.069058108600      0.385592605553     -0.871138655487
           3 p
      1.483583936100      0.213774144408      0.120100634399
      0.337258894300      0.518242823860      0.010250658900
      0.086416701100      0.828085134935     -1.988602951617
*
*
  3      0.727359952200     -0.816221921100      0.012905021000
           5 s
      3.491059767100      0.009160162772     -0.000030892129
      0.572703873400     -0.169272897932     -0.128794911692
      0.141966537200      0.007790972530      0.150277379528
      0.072336256200      0.408674567210      0.002291385065
      0.030480987400      0.896764838911     -0.584091945575
           5 p
      4.737937160600      0.002123430307      0.001161437281
      1.500912988700      0.035800007944      0.003521313433
      0.447197269200      0.098451586448      0.067756296813
      0.152139308500      0.376526927941     -0.001121507655
      0.057782090300      0.920461084531     -0.516723662026
           2 d
      0.365942514500      0.094157075529      0.073520577638
      0.091687463000      0.995557354012     -0.496093649274
*
"""

# Li (Z=3) ECP block, captured verbatim from the real q-vSZP_basis/ecpq.
_REAL_ECPQ_EXCERPT = """\
*
       3
ncore =        2 lmax =        2
d
    0.00000000        2     1.00000000
s-d
    5.78600000        2     1.27600000
p-d
   -1.06500000        2     1.60700000
*
"""


class TestParseQvszpShells:
    def test_h_shell_composition(self) -> None:
        shells = parse_qvszp_shells(_REAL_BASISQ_EXCERPT)
        assert shells[1] == ["s", "p"]

    def test_li_shell_composition(self) -> None:
        shells = parse_qvszp_shells(_REAL_BASISQ_EXCERPT)
        assert shells[3] == ["s", "p", "d"]

    def test_h_function_count(self) -> None:
        """1 s-type (1) + 1 p-type (3 spherical components) = 4."""
        shells = parse_qvszp_shells(_REAL_BASISQ_EXCERPT)
        l_map = {"s": 0, "p": 1, "d": 2}
        assert sum(2 * l_map[s] + 1 for s in shells[1]) == 4

    def test_li_function_count(self) -> None:
        """1 s + 1 p (3) + 1 d (5) = 9 — NOT the 5 a minimal-basis guess
        (1s+2s+2p) would give; q-vSZP's single explicit s-shell covers the
        ECP-reduced valence, plus one p and one d polarization shell."""
        shells = parse_qvszp_shells(_REAL_BASISQ_EXCERPT)
        l_map = {"s": 0, "p": 1, "d": 2}
        assert sum(2 * l_map[s] + 1 for s in shells[3]) == 9


class TestParseQvszpEcpCoreElectrons:
    def test_li_has_ncore_2(self) -> None:
        """Li's 1s core is replaced by an ECP — confirmed real, and NOT
        limited to f-block elements as an earlier docstring wrongly
        claimed."""
        ncore = parse_qvszp_ecp_core_electrons(_REAL_ECPQ_EXCERPT)
        assert ncore[3] == 2

    def test_hydrogen_absent_means_all_electron(self) -> None:
        ncore = parse_qvszp_ecp_core_electrons(_REAL_ECPQ_EXCERPT)
        assert 1 not in ncore


class TestElementZ:
    def test_known_elements(self) -> None:
        assert element_z("H") == 1
        assert element_z("Li") == 3
        assert element_z("O") == 8

    def test_unknown_element_raises(self) -> None:
        with pytest.raises(ValueError):
            element_z("Uuo")


@pytest.mark.skipif(not _NETWORK_TESTS_ENABLED, reason="requires QPUBENCH_NETWORK_TESTS=1 and network access")
class TestQvszpNetwork:
    """Live downloads from github.com/grimme-lab/qvSZP — real per-molecule
    qubit counts for every (molecule, qvSZP) row in
    data/IBM_VQE_Test_Benchmark.csv, replacing the earlier
    unverified/incorrect draft values."""

    def test_h2_matches_csv(self, tmp_path: object) -> None:
        pytest.importorskip("requests")
        from qpubench.hamiltonian_sources.qvszp import count_basis_functions

        per_atom = count_basis_functions("H", cache_dir=tmp_path)
        assert per_atom == 4
        h2_spin_orbitals = 2 * (2 * per_atom)   # 2 atoms, JW = 2x spatial
        assert h2_spin_orbitals == 16

    def test_li2_matches_corrected_value(self, tmp_path: object) -> None:
        """The original draft CSV said 34 for Li2/qvSZP — impossible for a
        homonuclear diatomic (would require 17 spatial orbitals, odd,
        split unevenly across two chemically-equivalent atoms). Real value
        is 36."""
        pytest.importorskip("requests")
        from qpubench.hamiltonian_sources.qvszp import count_basis_functions

        per_atom = count_basis_functions("Li", cache_dir=tmp_path)
        assert per_atom == 9
        li2_spin_orbitals = 2 * (2 * per_atom)   # 2 atoms, JW = 2x spatial
        assert li2_spin_orbitals == 36

    def test_h2o_matches_csv(self, tmp_path: object) -> None:
        pytest.importorskip("requests")
        from qpubench.hamiltonian_sources.qvszp import count_basis_functions

        n = 2 * (count_basis_functions("O", cache_dir=tmp_path) + 2 * count_basis_functions("H", cache_dir=tmp_path))
        assert n == 34

    def test_cp2k_format_downloads(self, tmp_path: object) -> None:
        pytest.importorskip("requests")
        from qpubench.hamiltonian_sources.qvszp import get_cp2k_format_text

        text = get_cp2k_format_text(cache_dir=tmp_path)
        assert "qvSZP" in text
        assert text.startswith("#")
