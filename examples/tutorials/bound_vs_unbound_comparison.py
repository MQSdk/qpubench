"""Tutorial: covalent ligand binding.

A real mechanism-matched model reaction solved with ADAPT-VQE. The target
is **cathepsin K**; its real covalent warheads are **nitrile groups
reacting with the catalytic cysteine thiol** (thioimidate formation),
modeled here by the smallest real nitrile + thiol pair.

Mechanism here: CH3-C#N (nitrile warhead) + CH3-SH (cysteine thiol
surrogate), compared at a bonded (thioimidate-forming, ~1.85 A
C(nitrile)...S) vs. well-separated (~4.5 A) distance, via
`qpubench.hamiltonian_sources.ab_initio.build_qubit_hamiltonian` — genuine
ab initio integrals at both points, not two points on an invented
occupied<->virtual coupling curve. Reduced to a 2-orbital/2-electron
active space for tractability.

Requires:
    pip install 'qpubench[adapt_vqe]'    # scipy + numpy
    pip install 'qpubench[openfermion]'  # openfermion + openfermionpyscf + pyscf

Run:
    python examples/tutorials/bound_vs_unbound_comparison.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from examples.common.real_molecules import (
    BOUND_CS_DISTANCE,
    COVALENT_LIGAND_ACTIVE_ELECTRONS,
    COVALENT_LIGAND_ACTIVE_ORBITALS,
    COVALENT_LIGAND_BASIS,
    UNBOUND_CS_DISTANCE,
    covalent_ligand_geometry,
)
from examples.common.toy_hamiltonians import exact_ground_state_energy
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine
from qpubench.schemas.execution import AdaptVQERunConfig


def solve(c_s_distance: float) -> tuple[float, float]:
    """Returns (ADAPT-VQE energy, exact energy) for the real nitrile+thiol
    Hamiltonian at the given C(nitrile)...S distance."""
    from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian

    hamiltonian, record = build_qubit_hamiltonian(
        covalent_ligand_geometry(c_s_distance), basis=COVALENT_LIGAND_BASIS,
        active_electrons=COVALENT_LIGAND_ACTIVE_ELECTRONS,
        active_orbitals=COVALENT_LIGAND_ACTIVE_ORBITALS,
    )
    engine = GenericAdaptVQEEngine(
        hamiltonian=hamiltonian,
        num_qubits=record.num_qubits,
        num_electrons=COVALENT_LIGAND_ACTIVE_ELECTRONS,
        energy_backend=ToyStatevectorAdapter(),
        config=AdaptVQERunConfig(max_macro_iterations=15, gradient_threshold=1e-5,
                               max_micro_iterations=200),
    )
    _, _vqa, vqa_result = engine.run()
    return vqa_result.final_eigenvalue, exact_ground_state_energy(hamiltonian)


def main() -> None:
    try:
        import qpubench.hamiltonian_sources.ab_initio  # noqa: F401
    except ImportError:
        print("openfermion/openfermionpyscf/pyscf not installed — run: "
              "pip install 'qpubench[openfermion]'")
        return

    bound_energy, bound_exact = solve(BOUND_CS_DISTANCE)
    unbound_energy, unbound_exact = solve(UNBOUND_CS_DISTANCE)

    binding_energy = bound_energy - unbound_energy

    print(f"{'state':10s}  {'C...S (A)':>10s}  {'ADAPT-VQE (Ha)':>16s}  {'exact (Ha)':>12s}")
    print(f"{'bound':10s}  {BOUND_CS_DISTANCE:>10.2f}  {bound_energy:>16.6f}  {bound_exact:>12.6f}")
    print(f"{'unbound':10s}  {UNBOUND_CS_DISTANCE:>10.2f}  {unbound_energy:>16.6f}  {unbound_exact:>12.6f}")
    print(f"\nbinding energy (bound - unbound) = {binding_energy:.6f} Ha")
    print("(real CH3CN+CH3SH/STO-3G, cathepsin K's real nitrile-cysteine "
          "covalent mechanism, 2-orbital/2-electron active space — "
          "negative = binding favorable. At this minimal basis/active-space "
          "level the sign may not match literature binding thermodynamics; "
          "the point is the real ab initio pipeline + ADAPT-VQE mechanism, "
          "not a publication-accurate binding energy.)")


if __name__ == "__main__":
    main()
