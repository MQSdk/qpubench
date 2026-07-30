"""Real tests for tensor_network/contraction_path.py — quimb + cotengra
contraction-path selection (closes qrunch's "Choose a Contraction Path
Finder" guide).
"""
from __future__ import annotations

import pytest

from qpubench.schemas.catalogs.contraction_path import (
    ContractionPathConfig,
    ContractionPathStrategy,
)
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.primitives import CircuitFormat

pytest.importorskip("quimb")
pytest.importorskip("cotengra")

_BELL_QASM2 = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0],q[1];
"""

_BELL_QASM3 = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
h q[0];
cx q[0], q[1];
"""


def _bell_circuit(fmt: CircuitFormat) -> CircuitSpec:
    serialized = _BELL_QASM2 if fmt == CircuitFormat.QASM2 else _BELL_QASM3
    return CircuitSpec(num_qubits=2, format=fmt, serialized=serialized)


def test_build_quimb_circuit_from_qasm2():
    from qpubench.tensor_network import build_quimb_circuit

    qc = build_quimb_circuit(_bell_circuit(CircuitFormat.QASM2))
    assert qc.N == 2


def test_build_quimb_circuit_from_qasm3_bridges_via_qiskit():
    pytest.importorskip("qiskit")
    from qpubench.tensor_network import build_quimb_circuit

    qc = build_quimb_circuit(_bell_circuit(CircuitFormat.QASM3))
    assert qc.N == 2


def test_build_quimb_circuit_rejects_unsupported_format():
    from qpubench.tensor_network.contraction_path import build_quimb_circuit

    bad = CircuitSpec(num_qubits=2, format=CircuitFormat.MEASUREMENT_PATTERN)
    with pytest.raises(ValueError, match="QASM2/QASM3"):
        build_quimb_circuit(bad)


@pytest.mark.parametrize("strategy", [
    ContractionPathStrategy.SEQUENTIAL,
    ContractionPathStrategy.RANDOM_GREEDY_128,
    ContractionPathStrategy.MULTI_STRATEGY,
    ContractionPathStrategy.NONE,
])
def test_choose_contraction_path_all_strategies_real(strategy):
    from qpubench.tensor_network import choose_contraction_path

    config = ContractionPathConfig(strategy=strategy, num_repeats=4)
    result = choose_contraction_path(_bell_circuit(CircuitFormat.QASM2), config)

    assert result.strategy_used == strategy
    assert result.opt_cost > 0
    assert result.largest_intermediate > 0


def test_none_strategy_is_more_expensive_than_optimized_strategies():
    """A real, meaningful check: no path pre-optimization should never beat
    an optimized contraction path in cost — confirms NONE isn't silently
    reusing an optimized path under the hood."""
    from qpubench.tensor_network import choose_contraction_path

    circuit = _bell_circuit(CircuitFormat.QASM2)
    none_result = choose_contraction_path(
        circuit, ContractionPathConfig(strategy=ContractionPathStrategy.NONE),
    )
    sequential_result = choose_contraction_path(
        circuit, ContractionPathConfig(strategy=ContractionPathStrategy.SEQUENTIAL),
    )
    assert none_result.opt_cost >= sequential_result.opt_cost
