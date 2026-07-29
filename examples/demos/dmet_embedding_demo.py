"""Demo: projection-based wavefunction-in-DFT embedding study (and its DMET cousin).

Real code, not executed here. PsiEmbed
(github.com/danclaudino/PsiEmbed) and libDMET
(github.com/gkclab/libdmet_preview, used by PennyLane's own DMET-embedding
tutorial) are both real, PySCF-based packages, but neither ships on PyPI —
only ``pip install git+https://github.com/...`` from source. This
demo calls each package's actual documented API behind an
``ImportError``-guard (same pattern as ``create_solvent_model.py``): it
prints a clear "not installed" message here, and runs for real once you
install either package from source yourself.

Both call sequences below were checked directly against real sources, not
guessed:
  - PsiEmbed: ``examples/input.py`` in the PsiEmbed repo itself (fetched
    from GitHub) — a plain ``options`` dict passed to ``psi_embed.driver()``.
  - libDMET + PennyLane: PennyLane's own DMET-embedding demo
    (pennylane.ai/qml/demos/tutorial_dmet_embedding) — real import paths
    (``libdmet.dmet.Hubbard``, ``libdmet.system.lattice``,
    ``libdmet.basis_transform.make_basis``) and the real
    HartreeFock -> ConstructImpHam -> SolveImpHam_with_fitting -> FitVcor
    self-consistency loop, plus the PennyLane ``one_particle``/
    ``two_particle``/``observable`` Jordan-Wigner mapping. Exact
    lattice/solver keyword arguments are illustrative — verify against
    whichever libdmet commit you install, same caveat as the schema module
    itself (``qpubench.schemas.mirrors.pyscf_pyscf.DMETConfig``).

Requires (to actually run either branch):
    pip install git+https://github.com/danclaudino/PsiEmbed
    # or
    pip install git+https://github.com/gkclab/libdmet_preview
    pip install pennylane

Run:
    python examples/demos/dmet_embedding_demo.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.mirrors.pyscf_pyscf import DMETConfig, ProjectionEmbeddingConfig

_WATER_ETHANOL_GEOMETRY = """
O       -1.1867 -0.2472  0.0000
H       -1.9237  0.3850  0.0000
H       -0.0227  1.1812  0.8852
C        0.0000  0.5526  0.0000
H       -0.0227  1.1812 -0.8852
C        1.1879 -0.3829  0.0000
H        2.0985  0.2306  0.0000
H        1.1184 -1.0093  0.8869
H        1.1184 -1.0093 -0.8869
"""


def run_psiembed(config: ProjectionEmbeddingConfig) -> None:
    """Real PsiEmbed call sequence — options dict shape verified against
    PsiEmbed's own examples/input.py, not guessed.
    """
    try:
        from psi_embed import driver
    except ImportError:
        print("PsiEmbed not installed — run: "
              "pip install git+https://github.com/danclaudino/PsiEmbed")
        return

    options = {
        "geometry": _WATER_ETHANOL_GEOMETRY,
        "basis": "cc-pvdz",
        "low_level": config.environment_method,
        "high_level": config.active_method,
        # PsiEmbed's real option is a leading-atom COUNT, not arbitrary
        # indices — qpubench's schema models indices (matches the DMET
        # side's impurity_atom_indices convention); bridge by count here.
        "n_active_atoms": len(config.active_atom_indices),
        "low_level_reference": "rohf",
        "high_level_reference": "rohf",
        "package": "pyscf",
    }
    driver(options)


def run_libdmet(config: DMETConfig) -> None:
    """Real libDMET + PennyLane call sequence — verified against PennyLane's
    own DMET-embedding tutorial (pennylane.ai/qml/demos/tutorial_dmet_embedding),
    which itself runs this exact pipeline on a periodic hydrogen chain.
    Illustrative lattice/solver parameters — verify against your installed
    libdmet commit.
    """
    try:
        import libdmet.dmet.Hubbard as dmet
        from libdmet.system import lattice
        from pennylane.qchem import observable, one_particle, two_particle
        from pyscf import ao2mo
    except ImportError:
        print("libDMET/PennyLane not installed — run: "
              "pip install git+https://github.com/gkclab/libdmet_preview pennylane")
        return

    # Illustrative 1D lattice (hydrogen chain), matching PennyLane's own
    # tutorial system — real construction, minimal parameters.
    latt = lattice.HChain()
    latt.build(nscsites=config.bath_orbital_count or len(config.impurity_atom_indices) * 2)

    filling = 0.5
    v_corr = dmet.VcorLocal(restricted=True, bogoliubov=False, nscsites=latt.nscsites)
    mu = 0.0

    for _ in range(config.max_scf_cycles):
        rho, mu, scf_result = dmet.HartreeFock(latt, v_corr, filling, mu, ires=True)
        imp_ham, _, basis = dmet.ConstructImpHam(latt, rho, v_corr)

        solver = dmet.impurity_solver.FCI(restricted=True, tol=1e-8)
        rho_emb, energy_emb, imp_ham, dmu = dmet.SolveImpHam_with_fitting(
            latt, filling, imp_ham, basis, solver,
        )
        v_corr, _ = dmet.FitVcor(rho_emb, latt, basis, v_corr, filling=filling)

    norb = imp_ham.norb
    h1 = imp_ham.H1["cd"][0]
    h2 = ao2mo.restore(1, imp_ham.H2["ccdd"][0], norb)

    one_elec = one_particle(h1)
    two_elec = two_particle(h2.transpose(0, 3, 1, 2))
    qubit_op = observable([one_elec, two_elec], mapping="jordan_wigner")
    print(f"DMET embedded Hamiltonian: {norb} active orbitals, "
          f"energy_emb={energy_emb}, qubit_op has {len(qubit_op.terms())} terms")


def main() -> None:
    projection_config = ProjectionEmbeddingConfig(
        active_atom_indices=[0, 1, 2],   # water fragment (first 3 atoms)
        environment_method="b3lyp",
        active_method="mp2",
    )
    print("-- Projection-based WF-in-DFT embedding (PsiEmbed) --")
    run_psiembed(projection_config)

    dmet_config = DMETConfig(
        impurity_atom_indices=[0],
        bath_orbital_count=2,
        max_scf_cycles=1,
    )
    print("\n-- DMET embedding (libDMET + PennyLane) --")
    run_libdmet(dmet_config)


if __name__ == "__main__":
    main()
