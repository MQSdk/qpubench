"""Real tests for generic_adapt_vqe/gate_selector.py — FastGateSelector
(gradient screen, extracted from the engine unchanged) and
BruteForceGateSelector (full re-optimization per candidate), closing
qrunch's "Create a FAST/Brute Force Gate Selector" guides.
"""
from __future__ import annotations

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from examples.common.toy_hamiltonians import exact_ground_state_energy, toy_hamiltonian
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine
from integrations.generic_adapt_vqe.gate_selector import (
    BruteForceGateSelector,
    FastGateSelector,
    GateSelector,
)
from qpubench.schemas.execution import AdaptVQERunConfig


@pytest.fixture
def h2_hamiltonian():
    return toy_hamiltonian()


def test_fast_and_brute_force_both_satisfy_gate_selector_protocol():
    assert isinstance(FastGateSelector(), GateSelector)
    assert isinstance(BruteForceGateSelector(), GateSelector)


def test_fast_gate_selector_converges_to_exact_ground_state(h2_hamiltonian):
    num_qubits, num_electrons = 4, 2
    exact = exact_ground_state_energy(h2_hamiltonian)

    engine = GenericAdaptVQEEngine(
        hamiltonian=h2_hamiltonian, num_qubits=num_qubits, num_electrons=num_electrons,
        energy_backend=ToyStatevectorAdapter(), gate_selector=FastGateSelector(),
    )
    result, _vqa, _vqa_result = engine.run()
    assert math.isclose(result.expectation_values[0].value, exact, abs_tol=1.0e-6)


def test_brute_force_gate_selector_converges_to_exact_ground_state(h2_hamiltonian):
    num_qubits, num_electrons = 4, 2
    exact = exact_ground_state_energy(h2_hamiltonian)

    engine = GenericAdaptVQEEngine(
        hamiltonian=h2_hamiltonian, num_qubits=num_qubits, num_electrons=num_electrons,
        energy_backend=ToyStatevectorAdapter(), gate_selector=BruteForceGateSelector(),
    )
    result, _vqa, _vqa_result = engine.run()
    assert math.isclose(result.expectation_values[0].value, exact, abs_tol=1.0e-6)


def test_default_gate_selector_is_fast_and_preserves_original_behavior(h2_hamiltonian):
    """GenericAdaptVQEEngine's default (no gate_selector passed) must be
    unchanged from before the GateSelector refactor."""
    num_qubits, num_electrons = 4, 2
    engine = GenericAdaptVQEEngine(
        hamiltonian=h2_hamiltonian, num_qubits=num_qubits, num_electrons=num_electrons,
        energy_backend=ToyStatevectorAdapter(),
    )
    assert isinstance(engine.gate_selector, FastGateSelector)


def test_brute_force_selector_converged_flag_uses_energy_threshold(h2_hamiltonian):
    num_qubits, num_electrons = 4, 2
    selector = BruteForceGateSelector()
    engine = GenericAdaptVQEEngine(
        hamiltonian=h2_hamiltonian, num_qubits=num_qubits, num_electrons=num_electrons,
        energy_backend=ToyStatevectorAdapter(), config=AdaptVQERunConfig(),
        gate_selector=selector,
    )
    best_idx, improvement, converged = selector.select(
        engine.pool, [], [], engine._energy, engine.config,
    )
    assert best_idx >= 0
    assert improvement > engine.config.energy_threshold
    assert converged is False


def test_brute_force_selector_overrides_optimizer_and_max_iterations(h2_hamiltonian):
    selector = BruteForceGateSelector(optimizer="Nelder-Mead", max_micro_iterations=5)
    assert selector._optimizer_override == "Nelder-Mead"
    assert selector._max_micro_iterations_override == 5
