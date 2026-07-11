"""qrunch guide: "Define an Active Space (Complete Active Space)"

Verdict: Yes — revised 2026-07-08. Real AVAS (Atomic Valence Active Space)
selection via ``pyscf.mcscf.avas`` (pip-installable, no compiler needed,
confirmed real by running it on H2O/STO-3G in this sandbox) closes the
"no selection algorithm" gap: three typed containers exist across three
schema modules, and this guide now runs a genuine selection algorithm
feeding all three, rather than only showing hand-picked indices.

Mechanism: ``avas.avas(mf, ao_labels)`` on a real Hartree-Fock reference
picks the active space automatically from AO character (here: oxygen 2p
character in water), then the resulting (active_electrons, active_orbitals)
and core/active MO index blocks are expressed three ways — one per
qrunch-adjacent chemistry package qpubench interoperates with — and fed
into ``generate_singles_doubles_pool()`` to show how an active-space
definition turns into the (num_electrons, num_qubits) pair generic_adapt_vqe
needs.

Requires: pip install 'qpubench[pyscf]'

Run:
    python examples/guides/active_space_spec.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.bestquark_gsopt import ActiveSpaceSpec
from qpubench.schemas.erikkjellgren_slowquant import UCCActiveSpaceConfig
from qpubench.schemas.microsoft_qdk import (
    ActiveSpaceSelectionResult,
    ActiveSpaceSelectorType,
)
from qpubench.schemas.pyscf_pyscf import PySCFAtomSpec, PySCFMoleculeSpec

from integrations.generic_adapt_vqe.pool import generate_singles_doubles_pool


def run_avas() -> tuple[int, int, list[int], list[int]] | None:
    """Real PySCF AVAS active-space selection on water/STO-3G.

    Returns (active_electrons, active_orbitals, occupied_indices,
    active_indices), or None if PySCF isn't installed.
    """
    try:
        from pyscf import gto, scf
        from pyscf.mcscf import avas
    except ImportError:
        print("PySCF not installed — run: pip install 'qpubench[pyscf]'")
        return None

    spec = PySCFMoleculeSpec(
        atoms=[
            PySCFAtomSpec(symbol="O", x=0.0, y=0.0, z=0.0),
            PySCFAtomSpec(symbol="H", x=0.0, y=0.757, z=0.587),
            PySCFAtomSpec(symbol="H", x=0.0, y=-0.757, z=0.587),
        ],
        basis="sto-3g",
    )
    mol = gto.M(atom=spec.to_pyscf_atom_string(), basis=spec.basis, verbose=0)
    mf = scf.RHF(mol).run(verbose=0)

    # Select active orbitals by oxygen 2p + hydrogen 1s AO character — a
    # real, automatic active-space selection algorithm, not hand-picked
    # indices. Includes some virtual character (norb=6, ne=8: not fully
    # occupied) so the ADAPT-VQE pool below is non-trivial.
    active_orbitals, active_electrons, _mo_coeff = avas.avas(
        mf, ["O 2p", "H 1s"], threshold=0.2, verbose=0
    )

    # avas.avas (canonicalize=True, the default) reorders MOs into
    # contiguous core / active / virtual blocks, so the active block's
    # position follows directly from the frozen-core electron count.
    core_orbitals = (mol.nelectron - active_electrons) // 2
    occupied_indices = list(range(core_orbitals))
    active_indices = list(range(core_orbitals, core_orbitals + active_orbitals))

    print(f"AVAS(['O 2p', 'H 1s']) on H2O/STO-3G -> {active_electrons} active "
          f"electrons, {active_orbitals} active orbitals")
    print(f"  core (occupied, frozen): {occupied_indices}")
    print(f"  active:                  {active_indices}\n")
    return active_electrons, active_orbitals, occupied_indices, active_indices


def main() -> None:
    avas_result = run_avas()
    if avas_result is None:
        return
    active_electrons, active_orbitals, occupied_indices, active_indices = avas_result

    # Same real AVAS result, expressed three ways — one per qrunch-adjacent
    # chemistry package qpubench interoperates with.

    gsopt = ActiveSpaceSpec(
        active_electrons=active_electrons,
        active_orbitals=active_orbitals,
        occupied_indices=occupied_indices,
        active_indices=active_indices,
    )
    print("bestquark_gsopt.ActiveSpaceSpec  ", gsopt)

    qdk = ActiveSpaceSelectionResult(
        selector_type=ActiveSpaceSelectorType.QDK_AUTOCAS,
        alpha_indices=active_indices,
        beta_indices=active_indices,
        num_active_electrons=active_electrons,
        num_active_orbitals=active_orbitals,
        num_qubits=2 * active_orbitals,   # Jordan-Wigner
    )
    print("microsoft_qdk.ActiveSpaceSelectionResult", qdk)

    slowquant = UCCActiveSpaceConfig(
        num_active_electrons=active_electrons,
        num_active_orbitals=active_orbitals,
        num_total_electrons=10,
        num_total_orbitals=7,
        frozen_core_orbitals=len(occupied_indices),
    )
    print("erikkjellgren_slowquant.UCCActiveSpaceConfig", slowquant)
    print(f"  -> {slowquant.num_qubits} qubits (2 x active_orbitals, Jordan-Wigner)")

    # All three agree on the same underlying (electrons, qubits) pair —
    # feed it into the ADAPT-VQE pool exactly like vqe_calculator.py does.
    num_qubits    = slowquant.num_qubits
    num_electrons = slowquant.num_active_electrons
    pool = generate_singles_doubles_pool(num_qubits, num_electrons)
    print()
    print(f"Active space -> {num_electrons} electrons / {num_qubits} qubits "
          f"-> ADAPT-VQE pool of {len(pool)} operators")


if __name__ == "__main__":
    main()
