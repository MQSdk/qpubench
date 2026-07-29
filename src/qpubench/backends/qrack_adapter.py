"""Qrack GPU/CPU simulator adapter (PyQrack).

Install: pip install 'qpubench[qrack]'   (pyqrack + qiskit — see below)

Supports:
  - Estimator path  (circuit.observables populated) -> expectation_values
  - Sampler path    (no observables)                -> shots / counts

Circuit loading: a QASM2/QASM3 CircuitSpec is parsed with the same Qiskit
parser the Aer/IBM/IQM/Braket adapters use (`_qiskit_common.load_qiskit_circuit`)
and handed to `QrackCircuit.in_from_qiskit_circuit()`, which lowers it to
Qrack's own gate representation. That is why the `qrack` extra pulls in qiskit:
PyQrack has no QASM parser of its own. A `QGC` CircuitSpec instead names a
pre-compiled `.qgc` file, loaded directly with `QrackCircuit.in_from_file()` —
useful for VQE sweeps where the structure is fixed and only angles change.

Verified against pyqrack 2.14.0 (CPU, no OpenCL platform) on a Bell state:
<ZZ> = +1.000000, <XX> = +1.000000, <YY> = -1.000000, <Z0> = 0, unitary
fidelity 1.0, and 4000 shots split 1980/2020 between "00" and "11".

Qrack-specific details that cost real debugging time
----------------------------------------------------
1. Pauli encoding is I=0, X=1, **Z=2, Y=3** (the Q# convention, not
   sequential). `PauliLabel.to_qrack_int()` handles it; never pass raw
   0/1/2/3 in label order. Confirmed against `pyqrack.Pauli`.

2. `pauli_expectation(q, b)` returns the expectation of a **single Pauli
   tensor product** — the product over the listed qubits — not a weighted sum
   over an observable's terms. A multi-term `SparsePauliObservable` therefore
   needs one call per term, each scaled by that term's coefficient, summed
   here. Do not flatten all terms into one call: besides being the wrong
   quantity, repeated qubit indices make Qrack's C++ layer raise
   `std::invalid_argument` from `ExpectationFloatsFactorized()`, which crosses
   the ctypes boundary as an uncatchable `terminate()` and takes the
   interpreter down with it. (`SparsePauliObservable.to_qrack_flat_arrays()`
   exists for a different, multi-term C API entry point; it is deliberately
   not used here.)

3. `measure_shots(q, s)` returns **outcome integers**, not per-qubit bits.
   Bit *i* of the integer is qubit *i*, so `format(outcome, f"0{n}b")` yields
   an MSB-first bitstring whose last character is qubit 0 — the same
   convention Qiskit's counts use, and what `ShotResult.counts` expects.
   Confirmed empirically: `x q[0]` on two qubits yields outcome integer 1.

4. `get_unitary_fidelity()` is only meaningful under approximate simulation
   (Schmidt-decomposition rounding, `set_sdrp`). It is read once at the end of
   the estimator path; `m_all()` resets the accumulator, so reading it after
   sampling would report 1.0 regardless.

5. GPU is opt-in per instance and *not* free: with no OpenCL platform
   installed, constructing with `is_gpu=True` prints "No platforms found" and
   falls back. Use `QrackAdapter(..., gpu=False)` on CPU-only hosts.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.observable import SparsePauliObservable
from ..schemas.primitives import (
    CircuitFormat,
    ComputingModel,
    FidelityMetric,
    JobStatus,
)
from ..schemas.result import (
    ExpectationResult,
    FidelityResult,
    QuantumResult,
    ShotResult,
)

if TYPE_CHECKING:
    from pyqrack import QrackSimulator

# Imaginary parts below this are floating-point noise, not a non-Hermitian
# observable.
_HERMITICITY_TOLERANCE = 1e-12


class QrackAdapter:
    """PyQrack simulator adapter.

    Parameters
    ----------
    num_qubits:
        Fixed qubit count.  Required because Qrack allocates the full state
        vector at construction time.
    gpu:
        Use GPU acceleration (default True).  Set False for CPU-only, or for
        hosts with no OpenCL platform installed.
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
        """Record the simulator configuration; nothing is allocated until run()."""
        self._num_qubits        = num_qubits
        self._gpu               = gpu
        self._stabilizer_hybrid = stabilizer_hybrid
        self._near_clifford     = near_clifford
        self._spec = BackendSpec.qrack(num_qubits, gpu=gpu)

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        """Check the circuit against this adapter's fixed simulator geometry."""
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
        if circuit.format not in (
            CircuitFormat.QASM2, CircuitFormat.QASM3, CircuitFormat.QGC
        ):
            warnings.append(
                f"QrackAdapter supports QASM2, QASM3 or QGC; got {circuit.format}"
            )
        return warnings

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Execute on the Qrack simulator via PyQrack.

        Takes the estimator path when the circuit carries observables and the
        sampler path otherwise, mirroring the Aer and PennyLane adapters.

        Failures propagate, as in every other adapter in this package:
        ``BenchmarkRunner.run()`` catches them and records a FAILED
        QuantumResult, so one bad point still does not abort a sweep, while a
        direct call keeps its traceback.
        """
        simulator = self._new_simulator()
        self._load_circuit(simulator, circuit)

        if circuit.observables:
            return self._run_estimator(simulator, circuit)
        return self._run_sampler(simulator, circuit, options)

    def _new_simulator(self) -> QrackSimulator:
        """Allocate a fresh simulator in this adapter's configuration.

        One instance per run keeps runs independent: Qrack mutates its state in
        place on every gate, so a reused simulator would carry the previous
        circuit's state into the next one.
        """
        from pyqrack import QrackSimulator

        return QrackSimulator(
            qubit_count=self._num_qubits,
            is_gpu=self._gpu,
            is_stabilizer_hybrid=self._stabilizer_hybrid,
            is_near_clifford_tableau_writer=self._near_clifford,
        )

    def _load_circuit(self, simulator: QrackSimulator, circuit: CircuitSpec) -> None:
        """Apply the CircuitSpec's gates to ``simulator``.

        A QGC spec names a pre-compiled ``.qgc`` file on disk; anything else is
        QASM text, parsed by Qiskit and lowered through ``QrackCircuit``.
        """
        from pyqrack import QrackCircuit

        if circuit.format == CircuitFormat.QGC:
            if not circuit.serialized:
                raise ValueError("QGC CircuitSpec has no file path in `serialized`")
            qrack_circuit = QrackCircuit.in_from_file(circuit.serialized)
        else:
            from ._qiskit_common import load_qiskit_circuit

            qrack_circuit = QrackCircuit.in_from_qiskit_circuit(
                load_qiskit_circuit(circuit)
            )
        qrack_circuit.run(simulator)

    def _run_estimator(
        self, simulator: QrackSimulator, circuit: CircuitSpec
    ) -> QuantumResult:
        """Evaluate every observable exactly against the final statevector."""
        values = [
            ExpectationResult(
                observable_index=index,
                value=self._expectation(simulator, observable),
                std_error=0.0,
            )
            for index, observable in enumerate(circuit.observables)
        ]
        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=circuit.qubit_modality,
            expectation_values=values,
            fidelity=FidelityResult(
                fidelity=simulator.get_unitary_fidelity(),
                metric=FidelityMetric.UNITARY,
            ),
            status=JobStatus.SUCCEEDED,
        )

    @staticmethod
    def _expectation(
        simulator: QrackSimulator, observable: SparsePauliObservable
    ) -> float:
        """Sum coefficient-weighted per-term Pauli expectations.

        One ``pauli_expectation`` call per term, because Qrack's returns the
        expectation of a single Pauli *product* — see gotcha 2 in the module
        docstring for why the terms must not be flattened into one call.
        """
        total = 0.0
        for term in observable.terms:
            coefficient = term.coefficient
            if abs(coefficient.im) > _HERMITICITY_TOLERANCE:
                raise ValueError(
                    "Qrack computes real expectation values; observable term "
                    f"{term.pauli_ops} has a complex coefficient "
                    f"({coefficient.re}{coefficient.im:+}j). A Hermitian "
                    "observable has real coefficients."
                )
            qubits, paulis = term.to_qrack_arrays()
            if not qubits:
                total += coefficient.re
                continue
            total += coefficient.re * simulator.pauli_expectation(qubits, paulis)
        return total

    def _run_sampler(
        self,
        simulator: QrackSimulator,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Sample computational-basis bitstrings into a counts histogram."""
        shots = options.require_shots("QrackAdapter")
        outcomes = simulator.measure_shots(list(range(self._num_qubits)), shots)
        bitstrings = [format(o, f"0{self._num_qubits}b") for o in outcomes]

        counts: dict[str, int] = {}
        for bitstring in bitstrings:
            counts[bitstring] = counts.get(bitstring, 0) + 1

        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            qubit_modality=circuit.qubit_modality,
            shots=ShotResult(
                num_qubits=self._num_qubits,
                num_shots=shots,
                counts=counts,
                memory=bitstrings if options.memory else [],
            ),
            status=JobStatus.SUCCEEDED,
        )
