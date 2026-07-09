"""qrunch guide: "Create a Solvent Model"

Verdict: Yes — revised 2026-07-08. PySCF's PCM/COSMO continuum solvation
(pyscf.solvent.pcm) is free, pip-installable, and confirmed real in this
example — no InQuanto or Cebule account needed (Cebule's COSMO task type
is a real alternative too, see docs/integrations/cebule.md, but qpubench
has no adapter for it yet; PySCF does the same job directly).

Requires: pip install 'qpubench[pyscf]'

Mechanism: a real PCM-solvated Hartree-Fock calculation on water in water
(eps=78.3553, PySCF's own default), compared against the real gas-phase
energy — both numbers come from PySCF itself.

Run:
    python examples/guides/create_solvent_model.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.pyscf import (
    PCMMethod,
    PySCFAtomSpec,
    PySCFMoleculeSpec,
    PySCFSolvationConfig,
    PySCFSolvationResult,
)


def main() -> None:
    try:
        from pyscf import gto, scf
    except ImportError:
        print("PySCF not installed — run: pip install 'qpubench[pyscf]'")
        return

    spec = PySCFMoleculeSpec(
        atoms=[
            PySCFAtomSpec(symbol="O", x=0.0, y=0.0, z=0.0),
            PySCFAtomSpec(symbol="H", x=0.0, y=0.757, z=0.587),
            PySCFAtomSpec(symbol="H", x=0.0, y=-0.757, z=0.587),
        ],
        basis="sto-3g",
    )
    mol = gto.M(atom=spec.to_pyscf_atom_string(), basis=spec.basis,
                charge=spec.charge, spin=spec.spin, unit=spec.unit)

    # Gas-phase reference.
    gas_phase_energy = scf.RHF(mol).run(verbose=0).e_tot

    # Solvated: PCM continuum solvation, water as its own solvent (eps~78.35).
    solvation_config = PySCFSolvationConfig(method=PCMMethod.C_PCM, eps=78.3553)
    mf = scf.RHF(mol).PCM()
    mf.with_solvent.method = solvation_config.method.value
    mf.with_solvent.eps = solvation_config.eps
    mf.with_solvent.lebedev_order = solvation_config.lebedev_order
    solvated_energy = mf.run(verbose=0).e_tot

    result = PySCFSolvationResult(
        energy=solvated_energy,
        converged=mf.converged,
        gas_phase_energy=gas_phase_energy,
    )

    print(f"Molecule: H2O/{spec.basis}")
    print(f"Solvation model: {solvation_config.method.value}, "
          f"eps={solvation_config.eps} (water)")
    print(f"  gas-phase energy = {result.gas_phase_energy:.6f} Ha")
    print(f"  solvated energy  = {result.energy:.6f} Ha")
    print(f"  solvation energy = {result.solvation_energy:.6f} Ha "
          f"({result.solvation_energy * 627.509:.2f} kcal/mol)")


if __name__ == "__main__":
    main()
