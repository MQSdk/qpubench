"""Shared Qiskit-circuit loading helper for the Aer/IBM/IQM/Braket adapters.

All four adapters accept a CircuitSpec carrying QASM2/QASM3 text and need
the same qiskit.QuantumCircuit reconstruction step before handing it to
their respective SDK. Kept in one place to avoid four copies drifting.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..schemas.circuit import CircuitSpec
from ..schemas.primitives import CircuitFormat

if TYPE_CHECKING:
    from qiskit import QuantumCircuit


def load_qiskit_circuit(circuit: CircuitSpec) -> "QuantumCircuit":
    from qiskit import QuantumCircuit, qasm3

    if circuit.format == CircuitFormat.QASM3:
        return qasm3.loads(circuit.serialized or "")
    if circuit.format == CircuitFormat.QASM2:
        return QuantumCircuit.from_qasm_str(circuit.serialized or "")
    raise ValueError(
        f"Expected a QASM2/QASM3 circuit; got {circuit.format}"
    )
