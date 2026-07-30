"""Demo: running ADAPT-VQE on quantum computers.

ADAPT-VQE's energy evaluations routed through a real quantum-hardware
BackendAdapter instead of a local simulator.

Mechanism: IBMQiskitAdaptVQEAdapter(energy_backend=IBMAdapter(...)) is the
exact construction integrations/ibm_qiskit_adapt_vqe/README.md documents —
every ADAPT-VQE energy evaluation would be dispatched to
IBMAdapter.run() (Estimator path). IBMAdapter.run() is a documented stub
(see docs/backends.md); this demo shows the real wiring, then falls back to
ToyStatevectorAdapter as the runnable stand-in, same pattern as
examples/guides/quantum_computers.py.

Requires: pip install 'qpubench[adapt_vqe]'

Run:
    python examples/demos/adapt_vqe_on_quantum_computer.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from examples.common.toy_hamiltonians import NUM_ELECTRONS, NUM_QUBITS, toy_hamiltonian
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.ibm_qiskit_adapt_vqe.adapter import IBMQiskitAdaptVQEAdapter
from qpubench import AlgorithmSpec, BenchmarkRunner, CircuitSpec, ExecutionOptions
from qpubench.backends.ibm_adapter import IBMAdapter
from qpubench.schemas.execution import AdaptVQERunConfig
from qpubench.schemas.primitives import AlgorithmFamily, CircuitFormat


def main() -> None:
    hamiltonian = toy_hamiltonian()
    problem = CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized=json.dumps({
            "num_qubits": NUM_QUBITS,
            "num_electrons": NUM_ELECTRONS,
            "hamiltonian": hamiltonian.model_dump(),
        }),
    )
    options = ExecutionOptions(
        algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
        adapt_vqe_run_config=AdaptVQERunConfig(max_macro_iterations=15, gradient_threshold=1e-3),
    )

    print("Wiring ADAPT-VQE energy evaluations through IBMAdapter (real hardware oracle)...")
    runner = BenchmarkRunner()
    runner.register(
        IBMQiskitAdaptVQEAdapter(energy_backend=IBMAdapter(backend_name="ibm_brisbane")),
        name="adapt_vqe+ibm",
    )
    record = runner.run(problem, "adapt_vqe+ibm", options)

    if record.result.status.value == "failed":
        # IBMAdapter.run() is a documented stub — see
        # examples/guides/quantum_computers.py for the same caveat.
        print(f"IBMAdapter.run() is a stub: {record.result.error_message}")
        print("Re-running with ToyStatevectorAdapter as the runnable stand-in "
              "(same AdaptVQERunConfig, same problem):")
        runner.register(
            IBMQiskitAdaptVQEAdapter(energy_backend=ToyStatevectorAdapter()),
            name="adapt_vqe+toy",
        )
        record = runner.run(problem, "adapt_vqe+toy", options)

    print(f"status = {record.result.status}")
    print(f"final energy = {record.vqa_result.final_eigenvalue:.6f}")
    print(f"hook backend = {record.backend.name}")


if __name__ == "__main__":
    main()
