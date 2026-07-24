"""Guide: build a VQE calculator.

A VQE "calculator" is the assembly that turns a problem into an energy:
integrations/generic_adapt_vqe's GenericAdaptVQEEngine wires together the
Hamiltonian, the operator pool, the energy backend, and the optimizer
config. ADAPT-VQE is the adaptive-ansatz VQE this framework ships.

Requires: pip install 'qpubench[adapt_vqe]'

Run:
    python examples/guides/vqe_calculator.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.execution import AdaptVQERunConfig

from examples.common.toy_hamiltonians import (
    NUM_ELECTRONS,
    NUM_QUBITS,
    exact_ground_state_energy,
    toy_hamiltonian,
)
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine


def main() -> None:
    hamiltonian = toy_hamiltonian()

    # "Assembling" the calculator: Hamiltonian + occupied/virtual split +
    # energy oracle + hyperparameters — the four pieces a VQE calculator
    # always wires together (problem, ansatz/pool, backend, optimizer config).
    calculator = GenericAdaptVQEEngine(
        hamiltonian=hamiltonian,
        num_qubits=NUM_QUBITS,
        num_electrons=NUM_ELECTRONS,
        energy_backend=ToyStatevectorAdapter(),
        config=AdaptVQERunConfig(
            pool_type="SD",
            optimizer="BFGS",
            gradient_threshold=1e-5,
            max_macro_iterations=15,
            max_micro_iterations=200,
        ),
    )
    print(f"Operator pool: {len(calculator.pool)} candidates")
    for op in calculator.pool:
        print(f"  {op}")

    result, vqa, vqa_result = calculator.run()

    print()
    print("Ansatz growth:")
    for it in result.adapt_history or []:
        print(f"  iter {it.iteration}: energy={it.energy:.6f}  "
              f"|grad|={it.grad_norm:.2e}  n_operators={it.n_operators}  n_cnot={it.n_cnot}")

    print()
    print(f"Final energy    = {vqa_result.final_eigenvalue:.6f}")
    print(f"Exact energy    = {exact_ground_state_energy(hamiltonian):.6f}")
    print(f"Parameters used = {vqa_result.num_parameters}")
    print(f"CNOTs in ansatz = {vqa_result.n_cnot}")


if __name__ == "__main__":
    main()
