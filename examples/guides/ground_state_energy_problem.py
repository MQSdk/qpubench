"""qrunch guide: "Construct a Ground State Energy Problem"

Verdict: Yes — real, runnable qpubench mechanism.
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
    hamiltonian = toy_hamiltonian()

    # 1. The ground-state energy *problem*: what we're solving and against
    #    what reference — this is qrunch's "Ground State Energy Problem"
    #    object, expressed as qpubench's package-agnostic VQAConfig.
    problem = VQAConfig(
        problem_type="chemistry",
        molecule="toy-4q",
        num_electrons=NUM_ELECTRONS,
        ground_truth=exact_ground_state_energy(hamiltonian),
    )
    print(f"Problem: {problem.molecule}, target energy = {problem.ground_truth:.6f}")

    # 2. Solve it with ADAPT-VQE (the FAST-VQE/BEAST-VQE substitute), scored
    #    by a real statevector simulator — StubGateAdapter would return
    #    random numbers and the optimizer would chase noise instead of the
    #    Hamiltonian, so it's not used here (see toy_statevector_backend.py).
    engine = GenericAdaptVQEEngine(
        hamiltonian=hamiltonian,
        num_qubits=NUM_QUBITS,
        num_electrons=NUM_ELECTRONS,
        energy_backend=ToyStatevectorAdapter(),
        config=AdaptVQEConfig(max_macro_iterations=15, gradient_threshold=1e-5, max_micro_iterations=200),
    )
    result, vqa = engine.run()

    # 3. Attach the ground truth after the fact and report chemical accuracy —
    #    same VQAConfig object qrunch's guide would populate.
    problem.final_eigenvalue = vqa.final_eigenvalue
    print(f"ADAPT-VQE energy       = {problem.final_eigenvalue:.6f}")
    print(f"|error|                 = {problem.energy_error:.6f} Hartree-equivalent")
    print(f"Chemical accuracy       = {problem.chemical_accuracy}")


if __name__ == "__main__":
    main()
