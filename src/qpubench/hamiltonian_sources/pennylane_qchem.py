"""PennyLane qchem dataset loader — pennylane.ai/datasets/collection/qchem

Install: pip install 'qpubench[pennylane]'   (pennylane + aiohttp + fsspec + h5py)

Real, verified usage (downloaded a real H2 dataset in this repo's own
sandbox, not guessed): ``qml.data.load("qchem", molname="H2",
basis="STO-3G", bondlength=0.5)`` returns a list of ``Dataset`` objects
with (among others) ``.hamiltonian`` (a `LinearCombination`),
``.fci_energy``, ``.vqe_energy`` (both real numeric reference values —
unlike HamLib, PennyLane ships these), and ``.molecule`` (symbols/
coordinates/charge/basis_name/n_electrons/n_orbitals). There is no
``hf_energy`` attribute on the dataset — left ``None`` rather than
fabricated.

``H.terms()`` returns ``(coeffs, ops)``; each op is either a bare
``PauliX``/``PauliY``/``PauliZ``/``Identity`` (single-qubit, `.wires`
gives the qubit) or a ``Prod`` of several such operators (`.operands`
gives the tensor factors) — verified against real output, including the
identity term (`0.38 * I(0)` style constant offset).

Real available `molname` values (fetched via
``qml.data.list_datasets()["qchem"]``, current as of this session):
BH3, BeH2, C2, C2H2, C2H4, C2H6, CH2, CH2O, CH4, CO, CO2, H10, H2, H2O,
H2O2, H3+, H4, H5, H6, H7, H8, HCN, HF, He2, HeH+, Li2, LiH, N2, N2H2,
N2H4, NH3, NeH+, O2, O3, OH-. Larger ones (e.g. NH3 at STO-3G: 16 qubits,
2371 terms) are real and loadable but may be too large for this repo's
dense-matrix reference tooling (`examples/common/toy_statevector_backend.py`)
to run through ADAPT-VQE in reasonable time — confirmed empirically: a
12-qubit/631-term LiH Hamiltonian already timed out at 2+ minutes for just
2 truncated iterations. Use a real SDK-backed simulator (Aer, Qrack) as
the energy backend for anything beyond ~4-8 qubits.
"""
from __future__ import annotations

from typing import Any

from ..schemas.hamiltonian_library import HamiltonianLibraryRecord, HamiltonianSource
from ..schemas.observable import PauliTerm, SparsePauliObservable
from ..schemas.primitives import ComplexNumber, PauliLabel

_PAULI_NAME_TO_LABEL = {"PauliX": "X", "PauliY": "Y", "PauliZ": "Z"}


def _op_to_term(op: Any, coeff: complex) -> PauliTerm:
    factors = op.operands if hasattr(op, "operands") else (op,)
    indices: list[int] = []
    labels: list[str] = []
    for factor in factors:
        if factor.name == "Identity":
            continue
        indices.append(int(factor.wires[0]))
        labels.append(_PAULI_NAME_TO_LABEL[factor.name])
    return PauliTerm(
        qubit_indices=tuple(indices),
        pauli_ops=tuple(PauliLabel(label) for label in labels),
        coefficient=ComplexNumber(re=float(coeff.real), im=float(getattr(coeff, "imag", 0.0))),
    )


def hamiltonian_to_observable(hamiltonian: Any, num_qubits: int) -> SparsePauliObservable:
    """Convert a PennyLane `LinearCombination`/`Hamiltonian` into a
    `SparsePauliObservable` — verified against real `H.terms()` output,
    including bare single-Pauli terms, `Prod` tensor factors, and the
    identity term.
    """
    coeffs, ops = hamiltonian.terms()
    terms = [_op_to_term(op, coeff) for op, coeff in zip(ops, coeffs)]
    return SparsePauliObservable(num_qubits=num_qubits, terms=terms)


def load_pennylane_qchem(
    molname: str,
    *,
    basis: str = "STO-3G",
    bondlength: float | str | None = None,
    **params: Any,
) -> tuple[SparsePauliObservable, HamiltonianLibraryRecord]:
    """Load a real chemistry Hamiltonian from PennyLane's qchem dataset collection.

    Parameters
    ----------
    molname:
        PennyLane's own molecule label, e.g. ``"H2"``, ``"LiH"``, ``"NH3"``.
        See module docstring for the real available set.
    basis:
        Basis set name, e.g. ``"STO-3G"``.
    bondlength:
        Bond length parameter (Angstrom) — required for most diatomics;
        polyatomics may use a different geometry-scan parameter (check
        ``qml.data.list_datasets()["qchem"][molname]`` for the real axis).
    **params:
        Forwarded to ``qml.data.load`` for any dataset-specific parameter.
    """
    import pennylane as qml

    load_kwargs: dict[str, Any] = {"molname": molname, "basis": basis, **params}
    if bondlength is not None:
        load_kwargs["bondlength"] = bondlength

    datasets = qml.data.load("qchem", **load_kwargs)
    dataset = datasets[0]

    num_qubits = len(dataset.hamiltonian.wires)
    observable = hamiltonian_to_observable(dataset.hamiltonian, num_qubits)

    molecule = dataset.molecule
    record = HamiltonianLibraryRecord(
        source=HamiltonianSource.PENNYLANE_QCHEM,
        molecule_name=molname,
        num_qubits=num_qubits,
        basis=basis,
        bond_length=float(bondlength) if bondlength is not None else None,
        encoding="JW",
        num_electrons=int(molecule.n_electrons),
        num_terms=len(observable.terms),
        fci_energy=float(dataset.fci_energy) if hasattr(dataset, "fci_energy") else None,
        vqe_energy=float(dataset.vqe_energy) if hasattr(dataset, "vqe_energy") else None,
        extras={
            "symbols": list(molecule.symbols),
            "n_orbitals": int(molecule.n_orbitals),
        },
    )
    return observable, record


__all__ = [
    "hamiltonian_to_observable",
    "load_pennylane_qchem",
]
