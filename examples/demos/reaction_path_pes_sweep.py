"""Demo: performing a reaction-path potential energy surface (PES) study.

This exercises schemas/catalogs/reactions.py: a sweep of point calculations tied
together as one ReactionCoordinateSpec / ReactionPathResult, rather than a
bare list of unrelated BenchmarkRecords.

Mechanism: builds one CircuitSpec (MOLECULE_JSON) per bond length from
examples/common/toy_hamiltonians.toy_bond_hamiltonian(r), runs each through
IBMQiskitAdaptVQEAdapter via BenchmarkRunner, then assembles a
ReactionPathResult.

Requires: pip install 'qpubench[adapt_vqe]'

Run:
    python examples/demos/reaction_path_pes_sweep.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench import AlgorithmSpec, BenchmarkRunner, CircuitSpec, ExecutionOptions
from qpubench.schemas.execution import AdaptVQERunConfig
from qpubench.schemas.primitives import AlgorithmFamily, CircuitFormat
from qpubench.schemas.catalogs.reactions import ReactionCoordinateSpec, ReactionPathResult

from examples.common.toy_hamiltonians import NUM_ELECTRONS, NUM_QUBITS, toy_bond_hamiltonian
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.ibm_qiskit_adapt_vqe.adapter import IBMQiskitAdaptVQEAdapter


def _problem_at(r: float) -> CircuitSpec:
    return CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized=json.dumps({
            "num_qubits": NUM_QUBITS,
            "num_electrons": NUM_ELECTRONS,
            "hamiltonian": toy_bond_hamiltonian(r).model_dump(),
        }),
    )


def main() -> None:
    bond_lengths = [0.5, 0.6, 0.74, 0.9, 1.1, 1.4, 1.8, 2.4, 3.2]

    spec = ReactionCoordinateSpec(
        label="toy 4-qubit bond dissociation",
        coordinate_name="bond_length_angstrom",
        coordinate_values=bond_lengths,
        problems=[_problem_at(r) for r in bond_lengths],
        reactant_index=2,   # near-equilibrium point (r=0.74)
        product_index=len(bond_lengths) - 1,   # last point (most dissociated)
    )

    runner = BenchmarkRunner()
    runner.register(
        IBMQiskitAdaptVQEAdapter(energy_backend=ToyStatevectorAdapter()),
        name="adapt_vqe",
    )
    options = ExecutionOptions(
        algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
        adapt_vqe_run_config=AdaptVQERunConfig(max_macro_iterations=15, gradient_threshold=1e-5,
                                        max_micro_iterations=200),
    )
    records = runner.sweep(
        circuits=spec.problems,
        backend_names=["adapt_vqe"],
        options_list=[options],
        run_id="reaction_path_pes_sweep",
    )
    # runner.sweep()'s cartesian product preserves circuit order for a
    # single-backend, single-options sweep, so records line up with
    # spec.coordinate_values one-to-one.
    result = ReactionPathResult(spec=spec, records=records)

    print(f"{'r (A)':>8s}  {'energy':>10s}")
    for r, e in zip(spec.coordinate_values, result.energies):
        print(f"{r:>8.2f}  {e:>10.6f}")

    print(f"\nreaction_energy (product - reactant) = {result.reaction_energy:.6f}")


if __name__ == "__main__":
    main()
