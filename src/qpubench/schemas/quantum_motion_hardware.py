"""Quantum Motion hardware schemas.

Quantum Motion fabricates spin-qubit processors in standard CMOS
foundries and exposes their QPU via Qiskit- or Cirq-compatible backends.
"""

from __future__ import annotations

import pydantic


class QuantumMotionDeviceSpec(pydantic.BaseModel):
    """Hardware characterisation for a Quantum Motion silicon CMOS spin-qubit QPU.

    Quantum Motion fabricates spin-qubit processors in standard CMOS foundries
    and exposes their QPU via Qiskit- or Cirq-compatible backends.

    fabrication_node   CMOS process node, e.g. "22nm", "28nm".
    gate_access        "qiskit" | "cirq"
    """

    device_name: str
    qubit_technology: str = "silicon_cmos_spin_qubit"
    fabrication_node: str | None = None
    num_qubits: int | None = None
    gate_access: str = "qiskit"  # "qiskit" | "cirq"
    t1_us: float | None = None  # T1 energy relaxation (µs)
    t2_us: float | None = None  # T2 dephasing (µs)
    single_qubit_fidelity: float | None = None
    two_qubit_fidelity: float | None = None
    readout_fidelity: float | None = None
