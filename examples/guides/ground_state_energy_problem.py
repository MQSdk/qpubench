"""Guide: construct a ground-state energy problem.

Mechanism: VQAConfig(problem_type="chemistry", ...) carries the problem
metadata; integrations/generic_adapt_vqe's GenericAdaptVQEEngine (pure
Python + scipy, no vendor SDK) actually solves for the ground state.

Requires: pip install 'qpubench[adapt_vqe]'   (scipy + numpy)

The "molecule" here is examples/common/toy_hamiltonians.py's illustrative
4-qubit Hamiltonian — NOT a real electronic-structure problem. See that
module's docstring for why, and examples/qforte_vqe_benchmark.py for a
real-molecule version (needs QForte).

Run:
    python examples/guides/ground_state_energy_problem.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.execution import AdaptVQERunConfig
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
    hamiltonian = toy_hamiltonian()

    # 1. The ground-state energy *problem*: what we're solving and against
    #    what reference — expressed as qpubench's package-agnostic VQAConfig.
    problem = VQAConfig(
        problem_type="chemistry",
        molecule="toy-4q",
        num_electrons=NUM_ELECTRONS,
    )
    reference_energy = exact_ground_state_energy(hamiltonian)
    print(f"Problem: {problem.molecule}, target energy = {reference_energy:.6f}")

    # 2. Solve it with ADAPT-VQE, scored
    #    by a real statevector simulator — StubGateAdapter would return
    #    random numbers and the optimizer would chase noise instead of the
    #    Hamiltonian, so it's not used here (see toy_statevector_backend.py).
    engine = GenericAdaptVQEEngine(
        hamiltonian=hamiltonian,
        num_qubits=NUM_QUBITS,
        num_electrons=NUM_ELECTRONS,
        energy_backend=ToyStatevectorAdapter(),
        config=AdaptVQERunConfig(max_macro_iterations=15, gradient_threshold=1e-5, max_micro_iterations=200),
    )
    result, vqa, vqa_result = engine.run()

    # 3. Attach the computed reference to the run's VQAResult and report
    #    chemical accuracy — outputs stay out of the problem definition.
    vqa_result.ground_truth = reference_energy
    print(f"ADAPT-VQE energy       = {vqa_result.final_eigenvalue:.6f}")
    print(f"|error|                 = {vqa_result.energy_error:.6f} Hartree-equivalent")
    print(f"Chemical accuracy       = {vqa_result.chemical_accuracy}")


if __name__ == "__main__":
    main()
