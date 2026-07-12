"""PennyLane lightning.qubit backend adapter.

Install: pip install 'qpubench[pennylane]'   (pennylane + pennylane-qiskit)

`lightning.qubit` is PennyLane's C++/BLAS statevector simulator — in
practice noticeably faster than Qiskit Aer for pure statevector work on the
same circuit (no shot-noise sampling overhead needed for the estimator
path), and it's already `BackendSpec.lightning_qubit()`'s namesake backend
(used as Cebule TN_QC_OPT's default). This adapter is the missing piece:
`BackendSpec.lightning_qubit()` described the backend, nothing executed on
it.

Supports:
  - Statevector expectation values  (circuit.observables populated)
  - Shot-based sampling             (no observables -> qml.counts())

CircuitSpec's QASM2/QASM3 text is parsed via the same Qiskit parser the
Aer/IBM/IQM/Braket adapters use (`_qiskit_common.load_qiskit_circuit`) —
PennyLane's own native QASM parser doesn't handle `include "stdgates.inc"`
or qubit-register declarations (`qubit[2] q;`), both of which this repo's
own QASM3 fixtures use (`tests/test_backend_adapters.py`). The resulting
`qiskit.QuantumCircuit` is converted to a PennyLane quantum function via
`qml.from_qiskit()`, which requires the `pennylane-qiskit` plugin — hence
`qiskit` and `pennylane-qiskit` both being needed even though execution
itself never touches Aer.
"""

from __future__ import annotations

from typing import Any

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.primitives import CircuitFormat, ComputingModel, JobStatus
from ..schemas.result import ExpectationResult, QuantumResult, ShotResult
from ._qiskit_common import load_qiskit_circuit as _load_qiskit_circuit


class PennyLaneLightningAdapter:
    """PennyLane `lightning.qubit` statevector simulator adapter."""

    def __init__(self, num_qubits: int | None = None) -> None:
        self._spec = BackendSpec.lightning_qubit(num_qubits=num_qubits)

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append(
                f"PennyLaneLightningAdapter expects GATE_BASED; got {circuit.computing_model}"
            )
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3, CircuitFormat.JSON):
            warnings.append(
                f"PennyLaneLightningAdapter supports QASM2/3 or JSON; got {circuit.format}"
            )
        if circuit.is_parametric() and not circuit.is_bound():
            warnings.append("Circuit has unbound parameters; bind before running")
        return warnings

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Execute circuit on `lightning.qubit`."""
        import pennylane as qml

        qc = _load_qiskit_circuit(circuit)
        quantum_fn = qml.from_qiskit(qc)
        num_qubits = circuit.num_qubits

        if circuit.observables:
            # ---- Estimator path ----
            # lightning.qubit computes exact (analytic) expectation values and
            # variances directly from the statevector — no shot sampling
            # needed for the mean itself. `options.shots`, when given, only
            # sets the *target precision* for std_error (std_error =
            # sqrt(Var/shots)), the same "precision" framing Aer's EstimatorV2
            # path uses (see aer_adapter.py's `precision = 1/sqrt(shots)`).
            observables = [obs.to_pennylane_observable() for obs in circuit.observables]
            dev = qml.device("lightning.qubit", wires=num_qubits)

            @qml.qnode(dev)  # type: ignore[untyped-decorator]  # qml.qnode is untyped
            def estimator_qnode() -> tuple[list[Any], list[Any]]:
                quantum_fn(wires=range(num_qubits))
                return (
                    [qml.expval(obs) for obs in observables],
                    [qml.var(obs) for obs in observables],
                )

            raw_values, raw_variances = estimator_qnode()
            evs = [
                ExpectationResult(
                    observable_index=i,
                    value=float(value),
                    std_error=(float((variance / options.shots) ** 0.5) if options.shots else 0.0),
                    num_shots=options.shots,
                )
                for i, (value, variance) in enumerate(zip(raw_values, raw_variances))
            ]
            return QuantumResult(
                computing_model=ComputingModel.GATE_BASED,
                expectation_values=evs,
                status=JobStatus.SUCCEEDED,
            )

        # ---- Sampler path ----
        shots = options.shots or 1024
        dev = qml.device("lightning.qubit", wires=num_qubits)

        @qml.qnode(dev)  # type: ignore[untyped-decorator]  # qml.qnode is untyped
        def sampler_qnode() -> Any:
            quantum_fn(wires=range(num_qubits))
            return qml.counts()

        sampler_qnode = qml.set_shots(sampler_qnode, shots=shots)
        raw_counts = sampler_qnode()
        counts = {str(bitstring): int(count) for bitstring, count in raw_counts.items()}

        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            shots=ShotResult(
                num_qubits=num_qubits,
                num_shots=shots,
                counts=counts,
            ),
            status=JobStatus.SUCCEEDED,
        )
