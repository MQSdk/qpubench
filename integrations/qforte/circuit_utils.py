"""QForte QuantumCircuit → QASM2 conversion.

QForte has no native QASM export.  This module interprets each gate
object defensively — trying multiple attribute name conventions — so it
stays compatible across QForte versions.

Gate ID reference (from QForte quantum_gate.cc / qforte_pybind.cc):
  1-qubit no-param:   I, X, Y, Z, H, S, T, Sd (S†), Td (T†), V (√X)
  1-qubit parametric: Rx, Ry, Rz, R (phase)
  2-qubit no-param:   cX/CNOT, cY, cZ, SWAP, aCNOT (anti-CNOT)
  2-qubit parametric: cRx, cRy, cRz, cR (controlled phase)
"""
from __future__ import annotations

from typing import Any

# (n_qubits, has_param, qasm2_template)
# {q0}=target, {q1}=control, {p}=parameter
_GATE_MAP: dict[str, tuple[int, bool, str]] = {
    # 1-qubit, no param
    "I":     (1, False, "id q[{q0}];"),
    "X":     (1, False, "x q[{q0}];"),
    "Y":     (1, False, "y q[{q0}];"),
    "Z":     (1, False, "z q[{q0}];"),
    "H":     (1, False, "h q[{q0}];"),
    "S":     (1, False, "s q[{q0}];"),
    "T":     (1, False, "t q[{q0}];"),
    "Sd":    (1, False, "sdg q[{q0}];"),
    "Td":    (1, False, "tdg q[{q0}];"),
    "V":     (1, False, "sx q[{q0}];"),     # √X  (OpenQASM 3 sx)
    # 1-qubit, parametric
    "Rx":    (1, True,  "rx({p}) q[{q0}];"),
    "Ry":    (1, True,  "ry({p}) q[{q0}];"),
    "Rz":    (1, True,  "rz({p}) q[{q0}];"),
    "R":     (1, True,  "p({p}) q[{q0}];"),  # phase gate
    # 2-qubit, no param — QForte: gate("cX", target, control)
    "cX":    (2, False, "cx q[{q1}],q[{q0}];"),
    "CNOT":  (2, False, "cx q[{q1}],q[{q0}];"),
    "cY":    (2, False, "cy q[{q1}],q[{q0}];"),
    "cZ":    (2, False, "cz q[{q1}],q[{q0}];"),
    "SWAP":  (2, False, "swap q[{q0}],q[{q1}];"),
    "aCNOT": (2, False, "cx q[{q1}],q[{q0}];"),  # anti-CNOT ≡ CNOT up to local ops
    # 2-qubit, parametric
    "cRx":   (2, True,  "crx({p}) q[{q1}],q[{q0}];"),
    "cRy":   (2, True,  "cry({p}) q[{q1}],q[{q0}];"),
    "cRz":   (2, True,  "crz({p}) q[{q1}],q[{q0}];"),
    "cR":    (2, True,  "cp({p}) q[{q1}],q[{q0}];"),
}


def _get_gate_attrs(gate: Any) -> tuple[str, int, int | None, float | None]:
    """Extract (gate_id, target, control, param) from a QForte gate object."""
    gate_id = gate.gate_id()
    target  = int(gate.target())

    control: int | None = None
    for meth in ("control", "get_control"):
        try:
            val = getattr(gate, meth)()
            if isinstance(val, int) and val >= 0:
                control = val
            break
        except (AttributeError, TypeError, RuntimeError):
            pass

    param: float | None = None
    for meth in ("parameter", "theta", "angle", "param", "get_parameter"):
        try:
            raw = getattr(gate, meth)()
            if raw is not None:
                param = float(raw)
            break
        except (AttributeError, TypeError, RuntimeError):
            pass

    return gate_id, target, control, param


def gate_to_qasm2(gate: Any) -> str:
    """Convert one QForte gate to a QASM2 instruction line."""
    gate_id, target, control, param = _get_gate_attrs(gate)
    entry = _GATE_MAP.get(gate_id)
    if entry is None:
        return f"// unsupported gate: {gate_id} on q[{target}]"
    _, has_param, template = entry
    p_str = f"{param:.17g}" if param is not None else "0"
    return template.format(
        q0=target,
        q1=control if control is not None else 0,
        p=p_str,
    )


def hf_prep_lines(ref: list[int]) -> list[str]:
    """QASM2 lines that flip each occupied orbital qubit from |0⟩ to |1⟩.

    ref[i] == 1 means the i-th spin-orbital is occupied in the HF reference.
    """
    return [f"x q[{i}];" for i, occ in enumerate(ref) if occ == 1]


def qforte_circuit_to_qasm2(
    circuit: Any,
    n_qubits: int,
    ref: list[int] | None = None,
) -> str:
    """Convert a QForte QuantumCircuit to a complete QASM2 string.

    Parameters
    ----------
    circuit:
        QForte QuantumCircuit (e.g. from build_Uvqc()).
    n_qubits:
        Total qubit count (alg._nqb).
    ref:
        HF reference state bitstring (alg._ref).  If provided, X gates are
        prepended so that the QASM circuit starts from the all-zeros state
        |0...0⟩ and produces the ansatz applied to the HF reference.
        If not provided, HF prep is omitted — only safe if the backend
        initialises qubits to the HF state externally.
    """
    header_lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        f"qreg q[{n_qubits}];",
    ]
    prep_lines = hf_prep_lines(ref) if ref is not None else []

    ansatz_lines: list[str] = []
    try:
        for gate in circuit.gates():
            ansatz_lines.append(gate_to_qasm2(gate))
    except Exception as exc:
        ansatz_lines.append(f"// gate iteration error: {exc}")

    return "\n".join(header_lines + prep_lines + ansatz_lines)
