"""Demo: polarizable embedding — the frame.

CPPE (github.com/maxscheurer/cppe) and PyFraME
(github.com/FraME-projects/PyFraME) are both pip-installable and run for
real here, bridged through PySCF's own ``pyscf.solvent.PE``
(``pyscf.solvent.pol_embed``). See ``qpubench.schemas.catalogs.polarizable_embedding``
for the schema.

Mechanism: a real PE-embedded Hartree-Fock calculation on water, with one
explicit water molecule as the polarizable "environment" (3 sites: O, H, H),
using real PE-library force-field values (charges + isotropic dipole
polarizabilities) verified against PySCF's own test suite
(``pyscf/solvent/test/test_pol_embed.py``, not fabricated), at the same
water-dimer geometry that test uses. Compared against the real gas-phase
energy — both numbers come from PySCF itself.

PyFraME's real role: for anything beyond a single hand-placed environment
molecule — a full protein/solvent-box "Frame" around a QM region — PyFraME
is the tool that fragments the environment and emits the potfile this demo
writes by hand below. Sketched (not executed — needs a real PDB/fragment
library, out of scope for a demo):

    import pyframe
    project = pyframe.Project()
    project.create_super_system(pdb_file="system.pdb")
    project.create_embedding_potential()  # writes a potfile like the one below
    system = project.get_qm_system(qm_region_indices=[...])

Requires: pip install 'qpubench[pyscf]' cppe pyframe

Run:
    python examples/demos/polarizable_embedding_frame.py
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.catalogs.polarizable_embedding import (
    PolarizableEmbeddingConfig,
    PolarizableEmbeddingResult,
    PolarizableEmbeddingSite,
)


def _water_environment_site() -> PolarizableEmbeddingConfig:
    """One water molecule as the polarizable environment (3 sites: O, H, H).

    Coordinates and force-field values (charges, isotropic dipole
    polarizabilities) taken verbatim from PySCF's own
    ``pyscf/solvent/test/test_pol_embed.py`` potfile fixture — a real,
    validated PE-library water force field, not fabricated numbers.
    """
    return PolarizableEmbeddingConfig(sites=[
        PolarizableEmbeddingSite(
            site_index=1, element="O", x=3.533, y=2.996, z=0.887,
            charge=-0.67444,
            polarizability_xx=5.73935, polarizability_yy=5.73935, polarizability_zz=5.73935,
            excluded_sites=[2, 3],
        ),
        PolarizableEmbeddingSite(
            site_index=2, element="H", x=4.111, y=3.132, z=1.638,
            charge=0.33722,
            polarizability_xx=2.30839, polarizability_yy=2.30839, polarizability_zz=2.30839,
            excluded_sites=[1, 3],
        ),
        PolarizableEmbeddingSite(
            site_index=3, element="H", x=4.105, y=2.642, z=0.206,
            charge=0.33722,
            polarizability_xx=2.30839, polarizability_yy=2.30839, polarizability_zz=2.30839,
            excluded_sites=[1, 2],
        ),
    ])


def main() -> None:
    try:
        from pyscf import gto, scf
        from pyscf.solvent import PE
    except ImportError:
        print("PySCF not installed — run: pip install 'qpubench[pyscf]'")
        return
    try:
        import cppe  # noqa: F401
    except ImportError:
        print("CPPE not installed — run: pip install cppe")
        return

    config = _water_environment_site()

    mol = gto.M(
        atom="O 0 0 0; H 0 0.757 0.587; H 0 -0.757 0.587",
        basis="sto-3g",
        verbose=0,
    )

    gas_phase_energy = scf.RHF(mol).run(verbose=0).e_tot

    with tempfile.NamedTemporaryFile("w", suffix=".pot", delete=False) as f:
        f.write(config.to_potfile_string())
        potfile_path = f.name

    mf = PE(scf.RHF(mol), config.to_pe_options(potfile_path))
    mf.run(verbose=0)

    polarization = dict(mf.with_solvent.cppe_state.energies["Polarization"])

    result = PolarizableEmbeddingResult(
        energy=mf.e_tot,
        converged=mf.converged,
        gas_phase_energy=gas_phase_energy,
        polarization_energy=polarization.get("Electronic"),
    )

    print("Molecule: H2O/sto-3g")
    print("Environment: 1 explicit water molecule (3 polarizable sites)")
    print(f"  gas-phase energy    = {result.gas_phase_energy:.8f} Ha")
    print(f"  PE-embedded energy  = {result.energy:.8f} Ha")
    print(f"  embedding shift     = {result.embedding_shift:.8f} Ha "
          f"({result.embedding_shift * 627.509:.4f} kcal/mol)")
    if result.polarization_energy is not None:
        print(f"  polarization energy = {result.polarization_energy:.8f} Ha")
    print(f"  converged           = {result.converged}")


if __name__ == "__main__":
    main()
