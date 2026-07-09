"""A small, real statevector BackendAdapter for the guide/demo/tutorial examples.

`qpubench.StubGateAdapter` returns *random* expectation values — fine for
exercising the runner/store control flow (as tests/test_generic_adapt_vqe.py
does), but useless as the energy oracle for an actual ADAPT-VQE run: the
optimizer would be chasing noise, not the Hamiltonian, and a "chemical
accuracy achieved" result would be meaningless. `AerAdapter` / `IBMAdapter` /
`IQMAdapter` / `QrackAdapter` are real but all raise `NotImplementedError`
today (stub adapters with TODOs — see docs/backends.md).

`ToyStatevectorAdapter` is a genuine (if minimal, dense-matrix, small-n-only)
statevector simulator — not random, not a stub — restricted to the fixed
gate vocabulary integrations/generic_adapt_vqe/circuit_synthesis.py emits:
`qubit[n] q;` declaration, `x`, `h`, `rx(theta)`, `rz(theta)`, `cx`. That
narrow scope is what keeps this honest to implement correctly in a few dozen
lines; it is not a general-purpose QASM3 interpreter.
"""
from __future__ import annotations

import re

from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.primitives import ComputingModel, JobStatus
from qpubench.schemas.result import ExpectationResult, QuantumResult, ShotResult

from .toy_hamiltonians import observable_matrix

_GATE_LINE = re.compile(
    r"^(?P<gate>x|h|rx|rz|cx)"
    r"(?:\((?P<angle>[-0-9.eE]+)\))?"
    r"\s+q\[(?P<a>\d+)\](?:\s*,\s*q\[(?P<b>\d+)\])?\s*;$"
)
_DECL_LINE = re.compile(r"^(?:qubit\[(\d+)\]\s*q|qreg\s+q\[(\d+)\])\s*;$")


def _parse_instructions(serialized: str) -> tuple[int, list[tuple[str, tuple[int, ...], float | None]]]:
    """Parse the fixed gate vocabulary this repo's examples emit.

    Returns (num_qubits, [(gate_name, qubit_indices, angle_or_None), ...]).
    """
    num_qubits = 0
    instructions: list[tuple[str, tuple[int, ...], float | None]] = []
    for raw_line in serialized.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("OPENQASM", "include")):
            continue
        decl = _DECL_LINE.match(line)
        if decl:
            num_qubits = int(decl.group(1) or decl.group(2))
            continue
        gate = _GATE_LINE.match(line)
        if not gate:
            raise ValueError(f"ToyStatevectorAdapter: unsupported QASM line: {line!r}")
        name  = gate.group("gate")
        angle = float(gate.group("angle")) if gate.group("angle") is not None else None
        qubits = (int(gate.group("a")),)
        if gate.group("b") is not None:
            qubits = (qubits[0], int(gate.group("b")))
        instructions.append((name, qubits, angle))
    return num_qubits, instructions


def _gate_matrix(name: str, angle: float | None):
    import numpy as np

    if name == "x":
        return np.array([[0, 1], [1, 0]], dtype=complex)
    if name == "h":
        return (1 / np.sqrt(2)) * np.array([[1, 1], [1, -1]], dtype=complex)
    if name == "rx":
        c, s = np.cos(angle / 2), np.sin(angle / 2)
        return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)
    if name == "rz":
        return np.array([[np.exp(-1j * angle / 2), 0], [0, np.exp(1j * angle / 2)]], dtype=complex)
    if name == "cx":
        return np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], dtype=complex
        )
    raise ValueError(f"ToyStatevectorAdapter: unsupported gate {name!r}")


def _apply_gate(state, gate_matrix, qubits: tuple[int, ...], n: int):
    import numpy as np

    k = len(qubits)
    gate_tensor = gate_matrix.reshape((2,) * k + (2,) * k)
    state = np.tensordot(gate_tensor, state, axes=(list(range(k, 2 * k)), list(qubits)))
    remaining = [ax for ax in range(n) if ax not in qubits]
    new_order = list(qubits) + remaining
    inverse = np.argsort(new_order)
    return np.transpose(state, inverse)


def statevector(circuit: CircuitSpec):
    """Simulate `circuit` and return the final statevector as a flat numpy array."""
    import numpy as np

    n, instructions = _parse_instructions(circuit.serialized or "")
    n = n or circuit.num_qubits
    state = np.zeros((2,) * n, dtype=complex)
    state[(0,) * n] = 1.0   # |0...0>
    for name, qubits, angle in instructions:
        state = _apply_gate(state, _gate_matrix(name, angle), qubits, n)
    return state.reshape(-1)


class ToyStatevectorAdapter:
    """Exact statevector simulator for the fixed gate set this repo's
    ADAPT-VQE examples emit. Estimator path only (circuit.observables
    populated) plus a sampler path built from measurement probabilities.
    """

    def __init__(self, seed: int | None = None) -> None:
        self._seed = seed

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(
            name="toy_statevector",
            provider="qpubench_examples",
            simulator=True,
            computing_model=ComputingModel.GATE_BASED,
        )

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append("ToyStatevectorAdapter expects GATE_BASED circuits")
        return warnings

    def run(self, circuit: CircuitSpec, options: ExecutionOptions) -> QuantumResult:
        import numpy as np

        psi = statevector(circuit)

        if circuit.observables:
            evs = []
            for i, obs in enumerate(circuit.observables):
                mat = observable_matrix(obs)
                value = complex(np.conj(psi) @ mat @ psi).real
                evs.append(ExpectationResult(observable_index=i, value=value, std_error=0.0))
            return QuantumResult(
                computing_model=ComputingModel.GATE_BASED,
                expectation_values=evs,
                status=JobStatus.SUCCEEDED,
            )

        shots = options.shots or 1024
        probs = np.abs(psi) ** 2
        probs = probs / probs.sum()
        n = circuit.num_qubits
        rng = np.random.default_rng(self._seed)
        outcomes = rng.choice(len(probs), size=shots, p=probs)
        counts: dict[str, int] = {}
        for outcome in outcomes:
            key = format(outcome, f"0{n}b")
            counts[key] = counts.get(key, 0) + 1
        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            shots=ShotResult(num_qubits=n, num_shots=shots, counts=counts),
            status=JobStatus.SUCCEEDED,
        )
