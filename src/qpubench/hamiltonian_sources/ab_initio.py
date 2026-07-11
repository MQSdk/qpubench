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
    -> mapper: jordan_wigner | bravyi_kitaev | parity | a custom callable
    -> str(qubit_operator)

`str(qubit_operator)` is confirmed **byte-identical in format** to
HamLib's own stored strings (`"(coeff+0j) [X0 Y1 ...] +\\n..."`) — so
`hamlib.parse_hamlib_qubit_operator()` is reused as-is here, not
reimplemented, regardless of which mapper produced the qubit operator.

`mapper="parity"` calls OpenFermion's `symmetry_conserving_bravyi_kitaev`
(arXiv:1701.08213) — the same particle-number/spin-parity two-qubit
reduction that Qiskit Nature's `ParityMapper` implements, just under
OpenFermion's name for it. It removes 2 qubits relative to `jordan_wigner`/
`bravyi_kitaev` and needs the active electron count (real fermions in the
active space), so it raises if neither `active_electrons` nor a full-space
electron count is resolvable.

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

from typing import Any, Callable, Literal

from ..schemas.hamiltonian_library import HamiltonianLibraryRecord, HamiltonianSource
from ..schemas.observable import SparsePauliObservable
from .hamlib import parse_hamlib_qubit_operator

MapperName = Literal["jordan_wigner", "bravyi_kitaev", "parity"]

_ENCODING_LABELS: dict[str, str] = {
    "jordan_wigner": "JW",
    "bravyi_kitaev": "BK",
    "parity": "parity",
}


def build_qubit_hamiltonian(
    geometry: list[tuple[str, tuple[float, float, float]]],
    *,
    basis: str = "sto-3g",
    charge: int = 0,
    multiplicity: int = 1,
    active_electrons: int | None = None,
    active_orbitals: int | None = None,
    molecule_name: str | None = None,
    mapper: MapperName | Callable[[Any], Any] = "jordan_wigner",
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
    mapper:
        Fermion-to-qubit mapping. ``"jordan_wigner"`` (default) or
        ``"bravyi_kitaev"`` keep every spin-orbital as a qubit.
        ``"parity"`` uses OpenFermion's `symmetry_conserving_bravyi_kitaev`
        (arXiv:1701.08213) to remove 2 qubits via particle-number/spin
        symmetry — the same reduction Qiskit Nature's `ParityMapper`
        performs — and requires the active electron count to be known
        (`active_electrons`, or the molecule's full electron count when
        no active space is selected). Any callable
        ``FermionOperator -> QubitOperator`` may be passed instead to use
        an external mapper (e.g. from `qiskit_nature` or a custom scheme);
        `num_qubits` is then left at the full/active spin-orbital count,
        since only the built-in mappers are known to change qubit count.

    Returns
    -------
    (observable, record) — `record.hf_energy` is real (computed here,
    unlike the other two Hamiltonian sources).
    """
    from openfermion.chem import MolecularData  # type: ignore[attr-defined]
    from openfermion.transforms import (  # type: ignore[attr-defined]
        bravyi_kitaev,
        get_fermion_operator,
        jordan_wigner,
        symmetry_conserving_bravyi_kitaev,
    )
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

    if mapper == "jordan_wigner":
        qubit_hamiltonian = jordan_wigner(fermion_hamiltonian)  # type: ignore[no-untyped-call]
        encoding = _ENCODING_LABELS["jordan_wigner"]
    elif mapper == "bravyi_kitaev":
        qubit_hamiltonian = bravyi_kitaev(fermion_hamiltonian)  # type: ignore[no-untyped-call]
        encoding = _ENCODING_LABELS["bravyi_kitaev"]
    elif mapper == "parity":
        n_fermions = active_electrons if active_electrons is not None else molecule.n_electrons
        fermion_operator = get_fermion_operator(fermion_hamiltonian)  # type: ignore[no-untyped-call]
        qubit_hamiltonian = symmetry_conserving_bravyi_kitaev(  # type: ignore[no-untyped-call]
            fermion_operator, num_qubits, n_fermions
        )
        num_qubits -= 2
        encoding = _ENCODING_LABELS["parity"]
    elif callable(mapper):
        qubit_hamiltonian = mapper(fermion_hamiltonian)
        encoding = getattr(mapper, "__name__", "custom")
    else:
        raise ValueError(
            f"Unknown mapper {mapper!r} — expected 'jordan_wigner', 'bravyi_kitaev', "
            "'parity', or a callable FermionOperator -> QubitOperator"
        )

    observable = parse_hamlib_qubit_operator(str(qubit_hamiltonian), num_qubits)

    name = molecule_name or "".join(f"{sym}{i}" for i, (sym, _) in enumerate(geometry))
    record = HamiltonianLibraryRecord(
        source=HamiltonianSource.AB_INITIO_PYSCF,
        molecule_name=name,
        num_qubits=num_qubits,
        basis=basis,
        encoding=encoding,
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
