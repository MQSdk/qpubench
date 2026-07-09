"""qrunch tutorial: "Butyronitrile Dissociation" (Kvantify/qrunch_tutorials)

Verdict: Partial — real molecule and real bond, still ADAPT-VQE instead of
BEAST-VQE. Revised: checked the real qrunch notebook directly
(github.com/Kvantify/qrunch_tutorials/butyronitrile-tutorial) rather than
using an invented toy Hamiltonian. Confirmed real: n-butyronitrile
(CH3CH2CH2-C#N), STO-3G, dissociates the nitrile **C#N bond** specifically,
real active space is 8 orbitals/8 electrons = 16 qubits, a 9-frame scan.

That 16-qubit/5793-term Hamiltonian builds in 0.26s via
`qpubench.hamiltonian_sources.ab_initio.build_qubit_hamiltonian` (real,
verified) — printed once below as a capability check — but running
ADAPT-VQE on it through this repo's reference engine isn't tractable
(`examples/common/toy_statevector_backend.py` rebuilds a dense
`2**n x 2**n` matrix from scratch on every energy evaluation; a real
12-qubit/631-term LiH Hamiltonian already timed out at 2+ minutes for 2
truncated iterations). The runnable ADAPT-VQE scan below uses a reduced
2-orbital/2-electron active space around the same C#N bond — the real
molecule and the real dissociation coordinate, at a scale this engine can
actually converge on. A real simulator (Aer, Qrack) as the energy backend
would make the tutorial's own 16-qubit setup runnable too.

Requires:
    pip install 'qpubench[adapt_vqe]'    # scipy + numpy
    pip install 'qpubench[openfermion]'  # openfermion + openfermionpyscf + pyscf

Run:
    python examples/tutorials/bond_dissociation_curve.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench import AlgorithmSpec, BenchmarkRunner, CircuitSpec, ExecutionOptions
from qpubench.schemas.execution import AdaptVQEConfig
from qpubench.schemas.primitives import AlgorithmFamily, CircuitFormat
from qpubench.schemas.reaction import ReactionCoordinateSpec, ReactionPathResult

from examples.common.real_molecules import (
    BUTYRONITRILE_ACTIVE_ELECTRONS,
    BUTYRONITRILE_ACTIVE_ORBITALS,
    BUTYRONITRILE_BASIS,
    BUTYRONITRILE_REAL_ACTIVE_ELECTRONS,
    BUTYRONITRILE_REAL_ACTIVE_ORBITALS,
    butyronitrile_geometry,
)
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.ibm_qiskit_adapt_vqe.adapter import IBMQiskitAdaptVQEAdapter


def capability_check() -> None:
    """Build (don't run) the real qrunch tutorial's own 8orb/8e=16-qubit
    Hamiltonian — confirms the framework can now construct the literal
    setup, even though running ADAPT-VQE on it isn't tractable here."""
    try:
        from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian
    except ImportError:
        print("openfermion/openfermionpyscf/pyscf not installed — run: "
              "pip install 'qpubench[openfermion]'")
        return

    obs, record = build_qubit_hamiltonian(
        butyronitrile_geometry(), basis=BUTYRONITRILE_BASIS,
        active_electrons=BUTYRONITRILE_REAL_ACTIVE_ELECTRONS,
        active_orbitals=BUTYRONITRILE_REAL_ACTIVE_ORBITALS,
        molecule_name="butyronitrile (real tutorial setup)",
    )
    print(f"Real qrunch tutorial setup: {record.num_qubits} qubits, "
          f"{record.num_terms} terms, HF={record.hf_energy:.6f} Ha "
          f"(built for real, not run — too many terms for this repo's "
          f"toy ADAPT-VQE engine)\n")


def main() -> None:
    capability_check()

    try:
        from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian
    except ImportError:
        print("openfermion/openfermionpyscf/pyscf not installed — run: "
              "pip install 'qpubench[openfermion]'")
        return

    # Dense near equilibrium, sparser toward the dissociation limit.
    cn_distances = [0.9, 1.0, 1.16, 1.3, 1.5, 1.8, 2.2, 2.8, 4.0]

    problems = []
    for r in cn_distances:
        obs, record = build_qubit_hamiltonian(
            butyronitrile_geometry(r), basis=BUTYRONITRILE_BASIS,
            active_electrons=BUTYRONITRILE_ACTIVE_ELECTRONS,
            active_orbitals=BUTYRONITRILE_ACTIVE_ORBITALS,
        )
        problems.append(CircuitSpec(
            num_qubits=0,
            format=CircuitFormat.MOLECULE_JSON,
            serialized=json.dumps({
                "num_qubits": record.num_qubits,
                "num_electrons": BUTYRONITRILE_ACTIVE_ELECTRONS,
                "hamiltonian": obs.model_dump(),
            }),
        ))

    spec = ReactionCoordinateSpec(
        label="real n-butyronitrile C#N dissociation (reduced active space)",
        coordinate_name="cn_bond_length_angstrom",
        coordinate_values=cn_distances,
        problems=problems,
        reactant_index=2,                       # near-equilibrium (r=1.16)
        product_index=len(cn_distances) - 1,     # fully dissociated
    )

    runner = BenchmarkRunner()
    runner.register(
        IBMQiskitAdaptVQEAdapter(energy_backend=ToyStatevectorAdapter()),
        name="adapt_vqe",
    )
    options = ExecutionOptions(
        algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
        adapt_vqe_config=AdaptVQEConfig(max_macro_iterations=15, gradient_threshold=1e-5,
                                        max_micro_iterations=200),
    )
    records = runner.sweep(
        circuits=spec.problems, backend_names=["adapt_vqe"], options_list=[options],
        run_id="bond_dissociation_curve",
    )
    result = ReactionPathResult(spec=spec, records=records)

    print("Real butyronitrile C#N dissociation curve (reduced active space):")
    print(f"{'r (A)':>8s}  {'energy (Ha)':>12s}  {'bar':<30s}")
    energies = result.energies
    e_min, e_max = min(energies), max(energies)
    for r, e in zip(cn_distances, energies):
        bar_len = int(30 * (e - e_min) / (e_max - e_min)) if e_max > e_min else 0
        print(f"{r:>8.2f}  {e:>12.6f}  {'#' * bar_len}")

    dissociation_energy = result.reaction_energy
    print(f"\ndissociation energy (product - reactant) = {dissociation_energy:.6f} Ha")
    print("(real n-butyronitrile/STO-3G, 2-orbital/2-electron active space "
          "around the C#N bond — minimal basis, illustrative precision, "
          "genuine ab initio integrals)")


if __name__ == "__main__":
    main()
