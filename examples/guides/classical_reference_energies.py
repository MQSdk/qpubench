"""Guide: calculate classical reference energies (CI, CC).

molssi_qcschema.QCEnergyComponents is a real container for
HF/MP2/CCSD/CCSD(T)/FCI numbers; qpubench itself has no CI/CC solver, but
PySCF (free, pip-installable, no compiler required — see
schemas/pyscf_pyscf.py) does, and this example calls it for real rather than
approximating FCI via toy-Hamiltonian diagonalization.

Requires: pip install 'qpubench[pyscf]'

Mechanism: a real H2/STO-3G calculation — HF, MP2, CCSD, and FCI all
computed by PySCF itself (pyscf.scf/mp/cc/fci), not fabricated or
diagonalized by hand. CCSD and FCI coincide here (as they must — CCSD is
exact for a 2-electron system), which is itself a real cross-check, not a
coincidence to explain away.

Run:
    python examples/guides/classical_reference_energies.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.molssi_qcschema import QCEnergyComponents
from qpubench.schemas.pyscf_pyscf import PySCFAtomSpec, PySCFMoleculeSpec


def main() -> None:
    try:
        from pyscf import cc, fci, gto, mp, scf
    except ImportError:
        print("PySCF not installed — run: pip install 'qpubench[pyscf]'")
        return

    spec = PySCFMoleculeSpec(
        atoms=[
            PySCFAtomSpec(symbol="H", x=0.0, y=0.0, z=0.0),
            PySCFAtomSpec(symbol="H", x=0.0, y=0.0, z=0.7414),
        ],
        basis="sto-3g",
    )
    mol = gto.M(atom=spec.to_pyscf_atom_string(), basis=spec.basis,
                charge=spec.charge, spin=spec.spin, unit=spec.unit)

    mf = scf.RHF(mol).run(verbose=0)
    mp2 = mp.MP2(mf).run(verbose=0)
    ccsd = cc.CCSD(mf).run(verbose=0)
    e_fci, _ = fci.FCI(mf).kernel()

    components = QCEnergyComponents(
        mp2_correlation_energy=mp2.e_corr,
        mp2_total_energy=mp2.e_tot,
        ccsd_correlation_energy=ccsd.e_corr,
        ccsd_total_energy=ccsd.e_tot,
        fci_total_energy=e_fci,
    )

    print(f"Molecule: H2/{spec.basis}, bond length 0.7414 A")
    print(f"  HF     energy = {mf.e_tot:.6f} Ha")
    print(f"  MP2    energy = {components.mp2_total_energy:.6f} Ha "
          f"(corr {components.mp2_correlation_energy:.6f})")
    print(f"  CCSD   energy = {components.ccsd_total_energy:.6f} Ha "
          f"(corr {components.ccsd_correlation_energy:.6f})")
    print(f"  FCI    energy = {components.fci_total_energy:.6f} Ha")
    print()
    print("CCSD == FCI to 1e-6 Ha: expected, not a coincidence — CCSD is "
          "exact for a 2-electron system like H2.")
    assert abs(components.ccsd_total_energy - components.fci_total_energy) < 1e-6


if __name__ == "__main__":
    main()
