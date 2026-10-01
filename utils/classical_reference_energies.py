"""Guide: calculate classical reference energies (HF, MP2, CCSD, FCI).

molssi_qcschema.QCEnergyComponents is a real container for
HF/MP2/CCSD/CCSD(T)/FCI numbers; qpubench itself has no CI/CC solver, but
PySCF (free, pip-installable, no compiler required — see
schemas/mirrors/pyscf_pyscf.py) does, and this calls it for real rather than
approximating FCI via toy-Hamiltonian diagonalization.

Requires: pip install 'qpubench[pyscf]'

Any molecule a campaign runs: pass its `Geometry` column (Angstrom, in the
"H 0 0 0; H 0 0 0.74144" form the campaign matrices use) and its basis. A
reference energy is only comparable against a run computed at the same
nuclear positions. Full space, no active-space restriction, so FCI is
only practical for small molecules and bases. Defaults to H2/STO-3G, where
CCSD and FCI must coincide (CCSD is exact for two electrons) -- a real
cross-check.

Run:
    python utils/classical_reference_energies.py
    python utils/classical_reference_energies.py --geometry "H 0 0 0; H 0 0 0.74144" --basis 6-31g
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from qpubench.schemas.mirrors.molssi_qcschema import QCEnergyComponents
from qpubench.schemas.mirrors.pyscf_pyscf import PySCFAtomSpec, PySCFMoleculeSpec


def parse_geometry(spec: str) -> list[PySCFAtomSpec]:
    atoms = []
    for atom in spec.split(";"):
        symbol, x, y, z = atom.split()
        atoms.append(PySCFAtomSpec(symbol=symbol, x=float(x), y=float(y), z=float(z)))
    return atoms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--geometry", default="H 0 0 0; H 0 0 0.74144",
                        help="atoms in Angstrom, ';'-separated (default: H2 at 0.74144)")
    parser.add_argument("--basis", default="sto-3g")
    parser.add_argument("--charge", type=int, default=0)
    parser.add_argument("--spin", type=int, default=0, help="2S, as PySCF takes it")
    args = parser.parse_args()

    try:
        from pyscf import cc, fci, gto, mp, scf
    except ImportError:
        print("PySCF not installed — run: pip install 'qpubench[pyscf]'")
        return

    spec = PySCFMoleculeSpec(
        atoms=parse_geometry(args.geometry), basis=args.basis,
        charge=args.charge, spin=args.spin,
    )
    mol = gto.M(atom=spec.to_pyscf_atom_string(), basis=spec.basis,
                charge=spec.charge, spin=spec.spin, unit=spec.unit)

    mf = (scf.RHF if spec.spin == 0 else scf.ROHF)(mol).run(verbose=0)
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

    print(f"Geometry: {args.geometry}   basis: {spec.basis}")
    print(f"  HF     energy = {mf.e_tot:.6f} Ha")
    print(f"  MP2    energy = {components.mp2_total_energy:.6f} Ha "
          f"(corr {components.mp2_correlation_energy:.6f})")
    print(f"  CCSD   energy = {components.ccsd_total_energy:.6f} Ha "
          f"(corr {components.ccsd_correlation_energy:.6f})")
    print(f"  FCI    energy = {components.fci_total_energy:.6f} Ha")

    if mol.nelectron == 2:
        # CCSD is exact for two electrons, so a mismatch means a broken setup.
        assert abs(components.ccsd_total_energy - components.fci_total_energy) < 1e-6
        print("\nCCSD == FCI to 1e-6 Ha, as it must be for a 2-electron system.")


if __name__ == "__main__":
    main()
