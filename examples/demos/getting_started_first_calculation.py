"""Demo: your first quantum-chemistry calculation.

This narrates the getting-started arc without any external
quantum-chemistry package: build a problem, build a calculator, solve it,
check the answer — using examples/guides/ground_state_energy_problem.py and
vqe_calculator.py's building blocks. For a real-molecule version,
examples/qforte_vqe_benchmark.py runs QForte's ADAPT-VQE/UCCNVQE on
He/cc-pVDZ (needs `pip install qforte`).

Requires: pip install 'qpubench[adapt_vqe]'

Run:
    python examples/demos/getting_started_first_calculation.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from examples.common.toy_hamiltonians import (
    NUM_ELECTRONS,
    NUM_QUBITS,
    exact_ground_state_energy,
    toy_hamiltonian,
)
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine
from qpubench.schemas.execution import AdaptVQERunConfig
from qpubench.schemas.record import VQAConfig


def main() -> None:
    print("Step 1 — define the problem")
    print("-" * 40)
    hamiltonian = toy_hamiltonian()
    problem = VQAConfig(
        problem_type="chemistry",
        molecule="toy-4q",
        num_electrons=NUM_ELECTRONS,
    )
    reference_energy = exact_ground_state_energy(hamiltonian)
    print(f"  problem: {problem.molecule} ({problem.problem_type})")
    print(f"  {NUM_QUBITS} qubits, {NUM_ELECTRONS} electrons")
    print(f"  target (exact) energy = {reference_energy:.6f}")

    print("\nStep 2 — choose a calculator (ADAPT-VQE)")
    print("-" * 40)
    calculator = GenericAdaptVQEEngine(
        hamiltonian=hamiltonian,
        num_qubits=NUM_QUBITS,
        num_electrons=NUM_ELECTRONS,
        energy_backend=ToyStatevectorAdapter(),
        config=AdaptVQERunConfig(gradient_threshold=1e-5, max_macro_iterations=15,
                               max_micro_iterations=200),
    )
    print(f"  operator pool: {len(calculator.pool)} candidates")

    print("\nStep 3 — run it")
    print("-" * 40)
    result, vqa, vqa_result = calculator.run()
    for it in result.adapt_history or []:
        print(f"  iter {it.iteration}: E = {it.energy:.6f}")

    print("\nStep 4 — check the answer")
    print("-" * 40)
    # Computed values live in VQAResult, never in the config: the run
    # produced final_eigenvalue, and the exact reference is computed too.
    vqa_result.ground_truth = reference_energy
    print(f"  ADAPT-VQE energy = {vqa_result.final_eigenvalue:.6f}")
    print(f"  exact energy     = {vqa_result.ground_truth:.6f}")
    print(f"  chemical accuracy achieved: {vqa_result.chemical_accuracy}")

    print("\nFor a real molecule instead of this illustrative Hamiltonian, "
          "see examples/qforte_vqe_benchmark.py (needs `pip install qforte`).")


if __name__ == "__main__":
    main()
