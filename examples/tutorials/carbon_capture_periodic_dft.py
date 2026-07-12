"""Tutorial: carbon capture (periodic DFT + CO2 binding site).

Real periodic DFT (the framework/reference piece), plus the molecular half
of the CO2-binding chemistry — a simplified stand-in for the full COF-999
covalent organic framework. PySCF's ``pbc`` module gives real periodic
Gamma-point/k-point Kohn-Sham DFT, using PySCF's bundled GTH basis sets and
pseudopotentials (``gth-szv``/``gth-pade`` — no download needed).

Mechanism: real periodic PBE-DFT on a diamond-carbon unit cell (a
covalent, all-carbon periodic framework — thematically the closest simple
stand-in for a carbon-based COF's periodic lattice, not COF-999 itself,
which has a much larger unit cell and a much more complex binding-site
chemistry). Compares the Gamma-point-only energy against a 2x2x2 k-point
mesh to show a real periodic-DFT convergence effect (the energy per cell
shifts by about 1 Hartree going from 1 to 8 k-points here) — exactly the
kind of periodicity/BZ-sampling consideration a real COF-999 study would
need to converge before adding a CO2-binding-site embedded treatment on
top.

Revised: added a second section computing the real molecular half of that
binding-site chemistry — CO2 + NH3, an amine attacking the electrophilic
CO2 carbon (the first step of carbamate formation, the mechanism
amine-functionalized CO2 sorbents like COF-999 use at their pore surface)
— via `qpubench.hamiltonian_sources.ab_initio.build_qubit_hamiltonian` and
ADAPT-VQE, the same real-ab-initio-Hamiltonian mechanism as the other
tutorials. This CO2+NH3 model is a simplified, illustrative stand-in for
the real amine-CO2 binding chemistry, not COF-999's own binding site.

What's still missing for a full treatment: COF-999's actual (much larger)
periodic unit cell and a real embedded/DMET treatment combining both
halves (see ``examples/demos/dmet_embedding_demo.py`` — DMET schema
exists, libDMET isn't on PyPI). Cebule's Quantum-ESPRESSO-backed
``PERIODIC_GEOMETRY_OPT`` task (``schemas/mqsdk_cebule.py``) is a
plane-wave alternative that likely scales better for a COF-999-sized cell
than PySCF's Gaussian-basis PBC approach — a performance tradeoff between
two free options, not a "need InQuanto" situation.

Requires:
    pip install 'qpubench[pyscf]'
    pip install 'qpubench[adapt_vqe]'    # scipy + numpy, for the CO2+NH3 section
    pip install 'qpubench[openfermion]'  # openfermion + openfermionpyscf + pyscf

Run:
    python examples/tutorials/carbon_capture_periodic_dft.py
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.execution import AdaptVQEConfig
from qpubench.schemas.pyscf_pyscf import PySCFAtomSpec, PySCFCellSpec, PySCFMeanFieldConfig, PySCFMeanFieldMethod

from examples.common.real_molecules import (
    BOUND_CN_DISTANCE,
    CARBON_CAPTURE_ACTIVE_ELECTRONS,
    CARBON_CAPTURE_ACTIVE_ORBITALS,
    CARBON_CAPTURE_BASIS,
    UNBOUND_CN_DISTANCE,
    carbon_capture_geometry,
)
from examples.common.toy_hamiltonians import exact_ground_state_energy
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine


def _diamond_cell_spec() -> PySCFCellSpec:
    """Two-atom diamond-carbon primitive cell (Angstrom), real GTH-compatible geometry."""
    return PySCFCellSpec(
        atoms=[
            PySCFAtomSpec(symbol="C", x=0.0, y=0.0, z=0.0),
            PySCFAtomSpec(symbol="C", x=0.89169, y=0.89169, z=0.89169),
        ],
        basis="gth-szv",
        lattice_vectors=(
            (0.0, 1.78339, 1.78339),
            (1.78339, 0.0, 1.78339),
            (1.78339, 1.78339, 0.0),
        ),
        dimension=3,
    )


def main() -> None:
    try:
        from pyscf.pbc import dft as pbcdft
        from pyscf.pbc import gto as pbcgto
    except ImportError:
        print("PySCF not installed — run: pip install 'qpubench[pyscf]'")
        return

    spec = _diamond_cell_spec()
    config = PySCFMeanFieldConfig(method=PySCFMeanFieldMethod.RKS, xc="pbe")

    cell = pbcgto.Cell()
    cell.atom = spec.to_pyscf_atom_string()
    cell.a = spec.lattice_vectors
    cell.basis = spec.basis
    cell.pseudo = "gth-pade"
    cell.verbose = 0
    cell.build()

    print(f"Cell: diamond carbon, {spec.basis} + gth-pade pseudopotential")
    print(f"XC functional: {config.xc}\n")

    results: dict[tuple[int, int, int], float] = {}
    for kmesh in [(1, 1, 1), (2, 2, 2)]:
        t0 = time.perf_counter()
        kpts = cell.make_kpts(list(kmesh))
        mf = pbcdft.KRKS(cell, kpts)
        mf.xc = config.xc
        energy = mf.kernel()
        elapsed = time.perf_counter() - t0
        results[kmesh] = energy
        print(f"  k-mesh {kmesh}: energy/cell = {energy:.6f} Ha  "
              f"converged={mf.converged}  ({elapsed:.1f}s)")

    shift = results[(2, 2, 2)] - results[(1, 1, 1)]
    print(f"\nGamma-point -> 2x2x2 k-mesh shift: {shift:.6f} Ha "
          f"({shift * 627.509:.2f} kcal/mol per cell)")
    print("A real COF-999 study would need this same k-point convergence "
          "check on its (much larger) unit cell before adding an embedded "
          "CO2-binding-site treatment on top.")

    print("\n-- CO2 + NH3 binding-site model (real ab initio, ADAPT-VQE) --")
    try:
        from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian
    except ImportError:
        print("openfermion/openfermionpyscf/pyscf not installed — run: "
              "pip install 'qpubench[openfermion]'")
        return

    def solve(c_n_distance: float) -> tuple[float, float]:
        hamiltonian, record = build_qubit_hamiltonian(
            carbon_capture_geometry(c_n_distance), basis=CARBON_CAPTURE_BASIS,
            active_electrons=CARBON_CAPTURE_ACTIVE_ELECTRONS,
            active_orbitals=CARBON_CAPTURE_ACTIVE_ORBITALS,
        )
        engine = GenericAdaptVQEEngine(
            hamiltonian=hamiltonian,
            num_qubits=record.num_qubits,
            num_electrons=CARBON_CAPTURE_ACTIVE_ELECTRONS,
            energy_backend=ToyStatevectorAdapter(),
            config=AdaptVQEConfig(max_macro_iterations=15, gradient_threshold=1e-5,
                                   max_micro_iterations=200),
        )
        _, vqa = engine.run()
        return vqa.final_eigenvalue, exact_ground_state_energy(hamiltonian)

    bound_energy, bound_exact = solve(BOUND_CN_DISTANCE)
    unbound_energy, unbound_exact = solve(UNBOUND_CN_DISTANCE)
    binding_energy = bound_energy - unbound_energy

    print(f"{'state':10s}  {'N...C (A)':>10s}  {'ADAPT-VQE (Ha)':>16s}  {'exact (Ha)':>12s}")
    print(f"{'bound':10s}  {BOUND_CN_DISTANCE:>10.2f}  {bound_energy:>16.6f}  {bound_exact:>12.6f}")
    print(f"{'unbound':10s}  {UNBOUND_CN_DISTANCE:>10.2f}  {unbound_energy:>16.6f}  {unbound_exact:>12.6f}")
    print(f"\nbinding energy (bound - unbound) = {binding_energy:.6f} Ha")
    print("(real CO2+NH3/STO-3G, 2-orbital/2-electron active space — a "
          "simplified, illustrative stand-in for the real amine-CO2 binding "
          "chemistry, not COF-999's own binding site)")


if __name__ == "__main__":
    main()
