"""Guide: create an estimator and a sampler.

Mechanism: ibm_runtime_v2.IBMEstimatorPUB / IBMSamplerPUB are pure pydantic
containers modeling the real Qiskit Runtime V2 PUB (Primitive Unified Bloc)
format — no SDK required to construct and inspect them. Every qpubench
BackendAdapter also follows the same Estimator/Sampler-path convention:
circuit.observables populated -> Estimator path (expectation_values);
circuit.observables empty -> Sampler path (shots).

Run:
    python examples/guides/estimator_and_sampler.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from qpubench import CircuitSpec, Pauli
from qpubench.schemas.mirrors.ibm_runtime_v2 import IBMEstimatorPUB, IBMSamplerPUB

# QASM3 (not QASM2) — ToyStatevectorAdapter only speaks the fixed gate
# vocabulary integrations/generic_adapt_vqe emits (see that module's
# docstring); this is the same Bell circuit in that dialect.
BELL_QASM3 = """\
OPENQASM 3.0;
qubit[2] q;
h q[0];
cx q[0], q[1];
"""
ZZ = Pauli("Z0 Z1")


def main() -> None:
    from qpubench.schemas.execution import ExecutionOptions

    # An Estimator PUB: (circuit, observables, parameter_values?, precision?)
    # The circuit itself travels alongside the PUB (as CircuitSpec below);
    # IBMEstimatorPUB models the observable/parameter/precision metadata IBM
    # Runtime actually keys the PUB tuple on.
    estimator_pub = IBMEstimatorPUB(observable_labels=["ZZ"], precision=0.01)
    print(f"IBMEstimatorPUB: observables={estimator_pub.observable_labels}, "
          f"precision={estimator_pub.precision}")

    # A Sampler PUB: (circuit, parameter_values?, shots?)
    sampler_pub = IBMSamplerPUB(shots=4096)
    print(f"IBMSamplerPUB: shots={sampler_pub.shots}")

    # The same Estimator-path / Sampler-path convention every qpubench
    # BackendAdapter follows: observables populated -> Estimator path.
    # ToyStatevectorAdapter is a real (not random) simulator that
    # implements both paths — see toy_statevector_backend.py.
    adapter = ToyStatevectorAdapter(seed=3)
    estimator_circuit = CircuitSpec(num_qubits=2, serialized=BELL_QASM3, observables=[ZZ])
    estimator_result = adapter.run(estimator_circuit, ExecutionOptions(shots=None))
    ev = estimator_result.expectation_values[0]
    print(f"\nEstimator path -> <ZZ> = {ev.value:.4f} "
          f"(expectation_values populated: {estimator_result.expectation_values is not None})")

    # observables empty -> Sampler path.
    sampler_circuit = CircuitSpec(num_qubits=2, serialized=BELL_QASM3)
    sampler_result = adapter.run(sampler_circuit, ExecutionOptions(shots=1024))
    print(f"Sampler path   -> counts = {sampler_result.shots.counts} "
          f"(shots populated: {sampler_result.shots is not None})")


if __name__ == "__main__":
    main()
