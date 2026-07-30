"""Tutorial: dehalogenase reaction (SN2).

A real mechanism-matched model reaction solved with ADAPT-VQE. The
haloalkane dehalogenase active site is a **carboxylate nucleophile**
(two oxygens) attacking a C-Cl carbon — the Asp-mediated haloalkane
dehalogenase mechanism (ester-intermediate SN2), modeled here by the
smallest real carboxylate.

Mechanism here: CH3Cl + HCOO- (formate — the simplest real carboxylate),
approaching along the real backside-attack SN2 geometry (nucleophile
opposite the leaving halide, same axis), scanned via
`qpubench.hamiltonian_sources.ab_initio.build_qubit_hamiltonian` at each
reaction-progress point — genuine ab initio integrals at every point, not
an invented occupied<->virtual coupling profile. Reduced to a 2-orbital/
2-electron active space around the forming/breaking bonds for
tractability (same active-space-size ceiling established across this
session's other rewrites).

Requires:
    pip install 'qpubench[adapt_vqe]'    # scipy + numpy
    pip install 'qpubench[openfermion]'  # openfermion + openfermionpyscf + pyscf

Run:
    python examples/tutorials/reaction_path_sn2.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from examples.common.real_molecules import (
    DEHALOGENASE_ACTIVE_ELECTRONS,
    DEHALOGENASE_ACTIVE_ORBITALS,
    DEHALOGENASE_BASIS,
    DEHALOGENASE_CHARGE,
    dehalogenase_sn2_geometry,
)
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.ibm_qiskit_adapt_vqe.adapter import IBMQiskitAdaptVQEAdapter
from qpubench import AlgorithmSpec, BenchmarkRunner, CircuitSpec, ExecutionOptions
from qpubench.schemas.catalogs.reactions import ReactionCoordinateSpec, ReactionPathResult
from qpubench.schemas.execution import AdaptVQERunConfig
from qpubench.schemas.primitives import AlgorithmFamily, CircuitFormat


def main() -> None:
    try:
        from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian
    except ImportError:
        print("openfermion/openfermionpyscf/pyscf not installed — run: "
              "pip install 'qpubench[openfermion]'")
        return

    progress = [0.0, 0.15, 0.3, 0.42, 0.5, 0.58, 0.7, 0.85, 1.0]

    problems = []
    for xi in progress:
        obs, record = build_qubit_hamiltonian(
            dehalogenase_sn2_geometry(xi), basis=DEHALOGENASE_BASIS,
            charge=DEHALOGENASE_CHARGE,
            active_electrons=DEHALOGENASE_ACTIVE_ELECTRONS,
            active_orbitals=DEHALOGENASE_ACTIVE_ORBITALS,
        )
        problems.append(CircuitSpec(
            num_qubits=0,
            format=CircuitFormat.MOLECULE_JSON,
            serialized=json.dumps({
                "num_qubits": record.num_qubits,
                "num_electrons": DEHALOGENASE_ACTIVE_ELECTRONS,
                "hamiltonian": obs.model_dump(),
            }),
        ))

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
        circuits=problems, backend_names=["adapt_vqe"], options_list=[options],
        run_id="reaction_path_sn2",
    )

    # Locate the transition state from the computed profile itself (the
    # highest-energy interior point) rather than assuming it sits at
    # xi=0.5 ahead of time.
    raw_energies = [r.vqa_result.final_eigenvalue for r in records]
    interior = range(1, len(progress) - 1)
    ts_index = max(interior, key=lambda i: raw_energies[i])

    spec = ReactionCoordinateSpec(
        label="real CH3Cl + HCOO- carboxylate-mediated SN2 (reduced active space)",
        coordinate_name="reaction_progress",
        coordinate_values=progress,
        problems=problems,
        reactant_index=0,
        transition_state_index=ts_index,
        product_index=len(progress) - 1,
    )
    result = ReactionPathResult(spec=spec, records=records)

    print(f"{'progress':>10s}  {'energy (Ha)':>12s}  {'role':<16s}")
    for i, (xi, e) in enumerate(zip(progress, result.energies)):
        role = ""
        if i == spec.reactant_index:
            role = "reactant"
        elif i == spec.transition_state_index:
            role = "transition state"
        elif i == spec.product_index:
            role = "product"
        print(f"{xi:>10.2f}  {e:>12.6f}  {role:<16s}")

    print(f"\nbarrier_height   = {result.barrier_height:.6f} Ha")
    print(f"reaction_energy  = {result.reaction_energy:.6f} Ha")
    print("(real CH3Cl+HCOO-/STO-3G, 2-orbital/2-electron active space, "
          "linear geometry interpolation rather than a relaxed reaction "
          "path — the profile may not show a pronounced barrier at this "
          "minimal level, same honesty caveat as this repo's other "
          "illustrative-precision real-chemistry examples)")


if __name__ == "__main__":
    main()
