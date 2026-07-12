"""Qrack GPU/CPU simulator adapter (PyQrack ctypes interface).

Install: pip install 'qpubench[qrack]'

Key PyQrack data-type notes (see schemas/primitives.py):
  - Simulator handle:    c_ulonglong (uintq)
  - Qubit indices:       c_ulonglong scalars or POINTER(c_ulonglong) arrays
  - Gate matrices:       8 c_double values (4 complex as interleaved re/im)
  - Pauli ints:          I=0, X=1, Z=2, Y=3  (Q# convention — non-sequential)
  - Amplitude precision: real1_type = c_float (QRACK_FPPOW<6) or c_double (≥6)
  - MeasureShots output: POINTER(c_ulonglong) buffer, outcomes as integers

The Qrack circuit API (QrackCircuit) can pre-compile circuits to a .qgc
file and replay them efficiently — useful for VQE parameter sweeps where
the structure is fixed but angles change.
"""
from __future__ import annotations

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.primitives import (
    CircuitFormat,
    ComputingModel,
)
from ..schemas.result import (
    QuantumResult,
)


class QrackAdapter:
    """PyQrack simulator adapter.

    Parameters
    ----------
    num_qubits:
        Fixed qubit count.  Required because Qrack allocates the full state
        vector at init_count() time.
    gpu:
        Use GPU acceleration (default True).  Set False for CPU-only.
    stabilizer_hybrid:
        Enable stabilizer-hybrid mode (efficient for near-Clifford circuits).
    near_clifford:
        Enable near-Clifford tableau mode (fastest for Clifford + few T gates).
    """

    def __init__(
        self,
        num_qubits: int,
        *,
        gpu:               bool = True,
        stabilizer_hybrid: bool = False,
        near_clifford:     bool = False,
    ) -> None:
        self._num_qubits       = num_qubits
        self._gpu              = gpu
        self._stabilizer_hybrid = stabilizer_hybrid
        self._near_clifford    = near_clifford
        self._spec = BackendSpec.qrack(num_qubits, gpu=gpu)

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append(
                f"QrackAdapter expects GATE_BASED; got {circuit.computing_model}"
            )
        if circuit.num_qubits != self._num_qubits:
            warnings.append(
                f"QrackAdapter was initialised for {self._num_qubits} qubits "
                f"but circuit has {circuit.num_qubits}"
            )
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QGC):
            warnings.append(
                f"QrackAdapter supports QASM2 or QGC; got {circuit.format}"
            )
        return warnings

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Execute on Qrack simulator via the PyQrack ctypes interface.

        NOT IMPLEMENTED — this adapter is a stub. The implementation plan
        (Estimator + Sampler paths) and the Qrack-specific gotchas (Pauli
        int encoding, MeasureShots outcome format, fidelity accumulator
        reset, QRACK_FPPOW precision, .qgc pre-compilation) are documented
        in integrations/qrack/IMPLEMENTATION_NOTES.md.
        """
        raise NotImplementedError(
            "QrackAdapter.run is a stub — see integrations/qrack/IMPLEMENTATION_NOTES.md"
        )
