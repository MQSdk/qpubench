"""Ab initio Hamiltonian construction — PySCF + OpenFermion, any geometry.

Install: pip install 'qpubench[openfermion]'   (openfermion + openfermionpyscf + pyscf)

Unlike `hamlib.py`/`pennylane_qchem.py` (both load a *pre-built* Hamiltonian
from an external repository), this module computes one directly from a
molecular geometry — for any molecule, not just what a library happens to
ship. Real, verified pipeline (run for real in this repo's own sandbox):

    openfermion.chem.MolecularData(geometry, basis, multiplicity, charge)
    -> openfermionpyscf.run_pyscf(..., run_scf=True)      # real PySCF HF
    -> MolecularData.get_molecular_hamiltonian(occupied_indices, active_indices)
       # real frozen-core active-space reduction (both None = full space)
    -> openfermion.transforms.jordan_wigner(fermion_hamiltonian)
    -> str(qubit_operator)

`str(qubit_operator)` is confirmed **byte-identical in format** to
HamLib's own stored strings (`"(coeff+0j) [X0 Y1 ...] +\\n..."`) — so
`hamlib.parse_hamlib_qubit_operator()` is reused as-is here, not
reimplemented.

Active-space sizing matters for what's downstream-tractable: this repo's
reference ADAPT-VQE engine (`examples/common/toy_statevector_backend.py`)
rebuilds a dense `2**n x 2**n` matrix from scratch on every energy
evaluation — confirmed fast up to ~4 qubits / ~30 terms (H2-sized), but a
12-qubit/631-term real LiH Hamiltonian already timed out at 2+ minutes for
2 truncated iterations. Building a larger Hamiltonian here is still fast
(a real 16-qubit/5793-term butyronitrile active space built in 0.26s) —
it's *running ADAPT-VQE on it through the toy engine* that isn't
tractable beyond a handful of qubits. Use a real simulator (Aer, Qrack) as
the energy backend for anything larger.
"""
from __future__ import annotations

from ..schemas.hamiltonian_library import HamiltonianLibraryRecord, HamiltonianSource
from ..schemas.observable import SparsePauliObservable
from .hamlib import parse_hamlib_qubit_operator


def build_qubit_hamiltonian(
    geometry: list[tuple[str, tuple[float, float, float]]],
    *,
    basis: str = "sto-3g",
    charge: int = 0,
    multiplicity: int = 1,
    active_electrons: int | None = None,
    active_orbitals: int | None = None,
    molecule_name: str | None = None,
) -> tuple[SparsePauliObservable, HamiltonianLibraryRecord]:
    """Compute a real ab initio qubit Hamiltonian for `geometry`.

    Parameters
    ----------
    geometry:
        ``[(symbol, (x, y, z)), ...]`` in Angstrom — the real
        ``openfermion.chem.MolecularData`` geometry format.
    basis:
        Basis set name, e.g. ``"sto-3g"``, ``"cc-pvdz"``.
    charge, multiplicity:
        Total charge and spin multiplicity (2S+1).
    active_electrons, active_orbitals:
        Frozen-core active-space size. Both `None` uses the full space
        (only reasonable for very small molecules — H2/HeH+ scale).
        Core orbitals are the lowest-energy occupied ones (standard
        frozen-core convention); the remaining electrons/orbitals not in
        the active space are frozen at the HF reference.
    molecule_name:
        Label for the returned record; defaults to a formula-like string
        built from `geometry`.

    Returns
    -------
    (observable, record) — `record.hf_energy` is real (computed here,
    unlike the other two Hamiltonian sources).
    """
    from openfermion.chem import MolecularData  # type: ignore[attr-defined]
    from openfermion.transforms import jordan_wigner  # type: ignore[attr-defined]
    from openfermionpyscf import run_pyscf

    molecule = MolecularData(geometry, basis, multiplicity, charge)  # type: ignore[no-untyped-call]
    molecule = run_pyscf(molecule, run_scf=True, run_fci=False)

    if active_electrons is not None and active_orbitals is not None:
        n_core = (molecule.n_electrons - active_electrons) // 2
        occupied_indices: list[int] | None = list(range(n_core))
        active_indices: list[int] | None = list(range(n_core, n_core + active_orbitals))
        num_qubits = 2 * active_orbitals
    else:
        occupied_indices = None
        active_indices = None
        num_qubits = 2 * molecule.n_orbitals

    fermion_hamiltonian = molecule.get_molecular_hamiltonian(
        occupied_indices=occupied_indices, active_indices=active_indices
    )
    qubit_hamiltonian = jordan_wigner(fermion_hamiltonian)  # type: ignore[no-untyped-call]
    observable = parse_hamlib_qubit_operator(str(qubit_hamiltonian), num_qubits)

    name = molecule_name or "".join(f"{sym}{i}" for i, (sym, _) in enumerate(geometry))
    record = HamiltonianLibraryRecord(
        source=HamiltonianSource.AB_INITIO_PYSCF,
        molecule_name=name,
        num_qubits=num_qubits,
        basis=basis,
        encoding="JW",
        num_electrons=active_electrons if active_electrons is not None else molecule.n_electrons,
        num_terms=len(observable.terms),
        hf_energy=float(molecule.hf_energy),
        extras={
            "charge": charge,
            "multiplicity": multiplicity,
            "full_n_orbitals": molecule.n_orbitals,
            "full_n_electrons": molecule.n_electrons,
            "active_orbitals": active_orbitals,
            "active_electrons": active_electrons,
        },
    )
    return observable, record


__all__ = [
    "build_qubit_hamiltonian",
]
