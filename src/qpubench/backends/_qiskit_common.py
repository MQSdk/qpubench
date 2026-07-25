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
        qc = qasm3.loads(circuit.serialized or "")
    elif circuit.format == CircuitFormat.QASM2:
        qc = QuantumCircuit.from_qasm_str(circuit.serialized or "")
    else:
        raise ValueError(
            f"Expected a QASM2/QASM3 circuit; got {circuit.format}"
        )

    # Apply parameter_bindings from CircuitSpec.bind() by matching on name, so
    # a parametric ansatz + separate bindings (the plain-VQE pattern) actually
    # runs. Qiskit's own free Parameters carry the QASM input names.
    if circuit.parameter_bindings:
        values = {pb.name: pb.value for pb in circuit.parameter_bindings}
        mapping = {p: values[p.name] for p in qc.parameters if p.name in values}
        if mapping:
            qc = qc.assign_parameters(mapping)
    return qc
