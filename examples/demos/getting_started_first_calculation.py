"""qrunch demo: "Your First Quantum Chemistry Calculation"

Verdict: Yes — a real, runnable equivalent already ships in this repo:
examples/qforte_vqe_benchmark.py runs QForte's ADAPT-VQE/UCCNVQE on a real
molecule (He/cc-pVDZ), just needs `pip install qforte`.

This version narrates the same getting-started arc without any external
quantum-chemistry package: build a problem, build a calculator, solve it,
check the answer — using examples/guides/ground_state_energy_problem.py and
vqe_calculator.py's building blocks.

Requires: pip install 'qpubench[adapt_vqe]'

Run:
    python examples/demos/getting_started_first_calculation.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.execution import AdaptVQEConfig
from qpubench.schemas.record import VQAConfig

from examples.common.toy_hamiltonians import (
    NUM_ELECTRONS,
    NUM_QUBITS,
    exact_ground_state_energy,
    toy_hamiltonian,
)
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine


def main() -> None:
    print("Step 1 — define the problem")
    print("-" * 40)
    hamiltonian = toy_hamiltonian()
    problem = VQAConfig(
        problem_type="chemistry",
        molecule="toy-4q",
        num_electrons=NUM_ELECTRONS,
        ground_truth=exact_ground_state_energy(hamiltonian),
    )
    print(f"  {NUM_QUBITS} qubits, {NUM_ELECTRONS} electrons")
    print(f"  target (exact) energy = {problem.ground_truth:.6f}")

    print("\nStep 2 — choose a calculator (ADAPT-VQE, this repo's FAST-VQE/"
          "BEAST-VQE substitute)")
    print("-" * 40)
    calculator = GenericAdaptVQEEngine(
        hamiltonian=hamiltonian,
        num_qubits=NUM_QUBITS,
        num_electrons=NUM_ELECTRONS,
        energy_backend=ToyStatevectorAdapter(),
        config=AdaptVQEConfig(gradient_threshold=1e-5, max_macro_iterations=15,
                               max_micro_iterations=200),
    )
    print(f"  operator pool: {len(calculator.pool)} candidates")

    print("\nStep 3 — run it")
    print("-" * 40)
    result, vqa = calculator.run()
    problem.final_eigenvalue = vqa.final_eigenvalue
    for it in result.adapt_history or []:
        print(f"  iter {it.iteration}: E = {it.energy:.6f}")

    print("\nStep 4 — check the answer")
    print("-" * 40)
    print(f"  ADAPT-VQE energy = {problem.final_eigenvalue:.6f}")
    print(f"  exact energy     = {problem.ground_truth:.6f}")
    print(f"  chemical accuracy achieved: {problem.chemical_accuracy}")

    print("\nFor a real molecule instead of this illustrative Hamiltonian, "
          "see examples/qforte_vqe_benchmark.py (needs `pip install qforte`).")


if __name__ == "__main__":
    main()
