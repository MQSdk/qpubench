"""Tests for qpubench.hamiltonian_sources.ab_initio.

Real, offline, fast (STO-3G, no network — pyscf/openfermion run locally):
builds H2 from geometry via the real PySCF -> OpenFermion -> Jordan-Wigner
pipeline and cross-checks it against independently-known real values
(same H2/STO-3G/0.74A system whose exact ground state was already
verified via HamLib/PennyLane in earlier sessions).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("openfermion")
pytest.importorskip("openfermionpyscf")
pytest.importorskip("pyscf")

from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian  # noqa: E402


class TestBuildQubitHamiltonian:
    def test_h2_full_space(self) -> None:
        obs, record = build_qubit_hamiltonian(
            [("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.74))], basis="sto-3g",
        )
        assert record.num_qubits == 4
        assert len(obs.terms) == 15
        assert record.hf_energy == pytest.approx(-1.1167593073964255, abs=1e-8)

    def test_h2_exact_ground_state(self) -> None:
        from examples.common.toy_hamiltonians import exact_ground_state_energy

        obs, record = build_qubit_hamiltonian(
            [("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.74))], basis="sto-3g",
        )
        energy = exact_ground_state_energy(obs)
        # Real FCI energy for this exact system, independently confirmed via
        # openfermionpyscf's own run_fci in this session.
        assert energy == pytest.approx(-1.1372838344885028, abs=1e-8)

    def test_bravyi_kitaev_mapper(self) -> None:
        """BK keeps the same qubit count as JW, same physics, different terms."""
        obs, record = build_qubit_hamiltonian(
            [("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.74))],
            basis="sto-3g",
            mapper="bravyi_kitaev",
        )
        assert record.num_qubits == 4
        assert record.encoding == "BK"
        assert record.hf_energy == pytest.approx(-1.1167593073964255, abs=1e-8)

    def test_parity_mapper_reduces_qubit_count(self) -> None:
        """parity (symmetry_conserving_bravyi_kitaev) removes 2 qubits and
        still reaches the same exact ground state as JW."""
        from examples.common.toy_hamiltonians import exact_ground_state_energy

        obs_jw, record_jw = build_qubit_hamiltonian(
            [("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.74))],
            basis="sto-3g",
            active_electrons=2,
            active_orbitals=2,
        )
        obs_parity, record_parity = build_qubit_hamiltonian(
            [("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.74))],
            basis="sto-3g",
            active_electrons=2,
            active_orbitals=2,
            mapper="parity",
        )
        assert record_parity.num_qubits == record_jw.num_qubits - 2
        assert record_parity.encoding == "parity"
        assert exact_ground_state_energy(obs_parity) == pytest.approx(
            exact_ground_state_energy(obs_jw), abs=1e-8
        )

    def test_custom_callable_mapper(self) -> None:
        """An external mapper callable (e.g. from another package) works too."""
        from openfermion.transforms import bravyi_kitaev

        obs, record = build_qubit_hamiltonian(
            [("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.74))],
            basis="sto-3g",
            mapper=bravyi_kitaev,
        )
        assert record.num_qubits == 4
        assert record.encoding == "bravyi_kitaev"

    def test_unknown_mapper_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown mapper"):
            build_qubit_hamiltonian(
                [("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.74))],
                basis="sto-3g",
                mapper="not_a_real_mapper",  # type: ignore[arg-type]
            )

    def test_active_space_reduction(self) -> None:
        """A bigger molecule (LiH, 12 orbitals*... actually 6 spin orbitals
        full space) reduced to a small active space stays small and real."""
        obs, record = build_qubit_hamiltonian(
            [("Li", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 1.57))],
            basis="sto-3g",
            active_electrons=2,
            active_orbitals=2,
        )
        assert record.num_qubits == 4
        assert record.extras["full_n_electrons"] == 4
        assert record.extras["active_electrons"] == 2
        assert len(obs.terms) > 0

    def test_adapt_vqe_matches_exact_diagonalization(self) -> None:
        """End-to-end: real ab initio Hamiltonian through the existing,
        unmodified GenericAdaptVQEEngine."""
        pytest.importorskip("scipy")
        from examples.common.toy_hamiltonians import exact_ground_state_energy
        from examples.common.toy_statevector_backend import ToyStatevectorAdapter
        from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine
        from qpubench.schemas.execution import AdaptVQERunConfig

        obs, record = build_qubit_hamiltonian(
            [("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.74))], basis="sto-3g",
        )
        exact = exact_ground_state_energy(obs)
        engine = GenericAdaptVQEEngine(
            hamiltonian=obs,
            num_qubits=record.num_qubits,
            num_electrons=2,
            energy_backend=ToyStatevectorAdapter(),
            config=AdaptVQERunConfig(max_macro_iterations=15, gradient_threshold=1e-5, max_micro_iterations=200),
        )
        _, _vqa, vqa_result = engine.run()
        assert vqa_result.final_eigenvalue == pytest.approx(exact, abs=1e-6)
