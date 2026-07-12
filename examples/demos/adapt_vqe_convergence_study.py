"""Demo: an ADAPT-VQE convergence study.

Energy vs. a convergence knob (the gradient threshold).

Mechanism: registers IBMQiskitAdaptVQEAdapter (a thin AlgorithmAdapter
wrapper over the real generic_adapt_vqe engine) with BenchmarkRunner and
uses runner.sweep() to vary AdaptVQEConfig.gradient_threshold — the
idiomatic qpubench way to run a convergence study, as opposed to calling
GenericAdaptVQEEngine directly (see examples/guides/vqe_calculator.py).

Requires: pip install 'qpubench[adapt_vqe]'

Run:
    python examples/demos/adapt_vqe_convergence_study.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench import AlgorithmSpec, BenchmarkRunner, CircuitSpec, ExecutionOptions
from qpubench.schemas.execution import AdaptVQEConfig
from qpubench.schemas.primitives import AlgorithmFamily, CircuitFormat

from examples.common.toy_hamiltonians import (
    NUM_ELECTRONS,
    NUM_QUBITS,
    exact_ground_state_energy,
    toy_hamiltonian,
)
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.ibm_qiskit_adapt_vqe.adapter import IBMQiskitAdaptVQEAdapter


def main() -> None:
    hamiltonian = toy_hamiltonian()
    exact = exact_ground_state_energy(hamiltonian)

    problem = CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized=json.dumps({
            "num_qubits": NUM_QUBITS,
            "num_electrons": NUM_ELECTRONS,
            "hamiltonian": hamiltonian.model_dump(),
        }),
    )

    runner = BenchmarkRunner()
    runner.register(
        IBMQiskitAdaptVQEAdapter(energy_backend=ToyStatevectorAdapter()),
        name="adapt_vqe",
    )

    thresholds = [10.0, 2.0, 1.5, 1.0, 1e-3]
    options_list = [
        ExecutionOptions(
            algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
            adapt_vqe_config=AdaptVQEConfig(
                gradient_threshold=t, max_macro_iterations=15, max_micro_iterations=200,
            ),
        )
        for t in thresholds
    ]

    records = runner.sweep(
        circuits=[problem],
        backend_names=["adapt_vqe"],
        options_list=options_list,
        run_id="adapt_vqe_convergence_study",
    )

    print(f"Exact energy: {exact:.6f}\n")
    print(f"{'gradient_threshold':>20s}  {'energy':>10s}  {'error':>10s}  {'macro_iters':>12s}")
    for threshold, record in zip(thresholds, records):
        vqa = record.vqa
        n_iters = len(record.result.adapt_history or [])
        print(f"{threshold:>20g}  {vqa.final_eigenvalue:>10.6f}  "
              f"{abs(vqa.final_eigenvalue - exact):>10.2e}  {n_iters:>12d}")


if __name__ == "__main__":
    main()
