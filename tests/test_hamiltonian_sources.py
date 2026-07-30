"""Tests for qpubench.hamiltonian_sources (HamLib Chemistry + PennyLane qchem).

The regex-parser test is offline and always runs — it's the real HamLib
H2 `ham_JW-4` string captured in this session, hardcoded as a fixture, so
no network or h5py/pennylane install is needed to verify the parsing logic
itself.

The loader tests are network-dependent (real downloads from NERSC /
PennyLane's dataset service) and opt-in via QPUBENCH_NETWORK_TESTS=1 —
consistent with not requiring live egress in CI by default.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from qpubench.hamiltonian_sources.hamlib import parse_hamlib_qubit_operator

_NETWORK_TESTS_ENABLED = os.environ.get("QPUBENCH_NETWORK_TESTS") == "1"

# The real H2 ham_JW-4 string, captured verbatim from HamLib's own H2.hdf5
# (chemistry/electronic/standard/H2.zip) in this session.
_REAL_H2_JW4_STRING = (
    "(-0.44779757933958947+0j) [] +\n"
    "(-0.014034099995004047+0j) [X0 X1 Y2 Y3] +\n"
    "(0.014034099995004047+0j) [X0 Y1 Y2 X3] +\n"
    "(0.014034099995004047+0j) [Y0 X1 X2 Y3] +\n"
    "(-0.014034099995004047+0j) [Y0 Y1 X2 X3] +\n"
    "(0.2823508885110738+0j) [Z0] +\n"
    "(0.16462320552994025+0j) [Z0 Z1] +\n"
    "(0.08211612483661979+0j) [Z0 Z2] +\n"
    "(0.09615022483162383+0j) [Z0 Z3] +\n"
    "(0.28235088851107354+0j) [Z1] +\n"
    "(0.09615022483162383+0j) [Z1 Z2] +\n"
    "(0.08211612483661979+0j) [Z1 Z3] +\n"
    "(-0.003986747692442089+0j) [Z2] +\n"
    "(0.08366738652351666+0j) [Z2 Z3] +\n"
    "(-0.0039867476924421025+0j) [Z3]"
)


class TestParseHamlibQubitOperator:
    def test_term_count_matches_real_file_attrs(self) -> None:
        obs = parse_hamlib_qubit_operator(_REAL_H2_JW4_STRING, num_qubits=4)
        assert len(obs.terms) == 15   # real H2.hdf5's ham_JW-4 attrs['terms']

    def test_identity_term(self) -> None:
        obs = parse_hamlib_qubit_operator(_REAL_H2_JW4_STRING, num_qubits=4)
        identity_terms = [t for t in obs.terms if not t.qubit_indices]
        assert len(identity_terms) == 1
        assert identity_terms[0].coefficient.re == pytest.approx(-0.44779757933958947)

    def test_pauli_term_values(self) -> None:
        obs = parse_hamlib_qubit_operator(_REAL_H2_JW4_STRING, num_qubits=4)
        z0 = next(t for t in obs.terms if t.qubit_indices == (0,))
        assert z0.pauli_ops[0].value == "Z"
        assert z0.coefficient.re == pytest.approx(0.2823508885110738)

    def test_accepts_bytes(self) -> None:
        obs = parse_hamlib_qubit_operator(_REAL_H2_JW4_STRING.encode(), num_qubits=4)
        assert len(obs.terms) == 15

    def test_exact_ground_state_matches_real_dense_diagonalization(self) -> None:
        """Same value independently verified in this session via
        examples.common.toy_hamiltonians.exact_ground_state_energy."""
        import sys
        from pathlib import Path

        pytest.importorskip("numpy")  # dense diagonalization only; parsing needs no deps

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from examples.common.toy_hamiltonians import exact_ground_state_energy

        obs = parse_hamlib_qubit_operator(_REAL_H2_JW4_STRING, num_qubits=4)
        energy = exact_ground_state_energy(obs)
        assert energy == pytest.approx(-1.1314597618973563, abs=1e-9)


@pytest.mark.skipif(not _NETWORK_TESTS_ENABLED, reason="requires QPUBENCH_NETWORK_TESTS=1 and network access")
class TestLoadHamlibChemistryNetwork:
    def test_load_h2(self) -> None:
        h5py = pytest.importorskip("h5py")  # noqa: F841
        pytest.importorskip("requests")
        from qpubench.hamiltonian_sources.hamlib import load_hamlib_chemistry

        with tempfile.TemporaryDirectory() as tmp:
            obs, record = load_hamlib_chemistry("H2", cache_dir=tmp)
            assert record.num_qubits == 4
            assert len(obs.terms) == 15
            assert record.extras["category"] == "standard"


@pytest.mark.skipif(not _NETWORK_TESTS_ENABLED, reason="requires QPUBENCH_NETWORK_TESTS=1 and network access")
class TestLoadPennylaneQchemNetwork:
    def test_load_h2(self) -> None:
        pytest.importorskip("pennylane")
        from qpubench.hamiltonian_sources.pennylane_qchem import load_pennylane_qchem

        obs, record = load_pennylane_qchem("H2", basis="STO-3G", bondlength=0.5)
        assert record.num_qubits == 4
        assert len(obs.terms) == 15
        assert record.fci_energy == pytest.approx(-1.0551607375072107, abs=1e-6)

        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from examples.common.toy_hamiltonians import exact_ground_state_energy

        energy = exact_ground_state_energy(obs)
        assert energy == pytest.approx(record.fci_energy, abs=1e-6)
