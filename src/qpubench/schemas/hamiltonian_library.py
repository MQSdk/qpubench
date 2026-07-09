"""Hamiltonian library metadata — pre-built libraries + ab initio construction.

Three real Hamiltonian sources (chemistry problems ready to drop into any
`AlgorithmAdapter`/`BackendAdapter` Estimator path as a
`SparsePauliObservable`), none of them quantum SDKs — but this module
still stays free of any import of `pennylane`/`h5py`/`requests`/
`openfermion`/`pyscf`, matching the core-never-imports-a-quantum-library
invariant. The code that actually fetches/computes data lives in
`qpubench.hamiltonian_sources` (lazy imports, optional extras
`hamlib`/`pennylane`/`openfermion`).

- **PennyLane qchem** (pennylane.ai/datasets/collection/qchem) — real
  molecule Hamiltonians, `.fci_energy`/`.vqe_energy` reference values.
- **HamLib Chemistry** (portal.nersc.gov/cfs/m888/dcamps/hamlib/chemistry/)
  — static HDF5 files, four real qubit encodings per molecule
  (`JW`/`BK`/`parity`/`molec`), no reference energies shipped.
- **Ab initio (PySCF + OpenFermion)** — compute a real qubit Hamiltonian
  directly from a geometry (any molecule, not just what a pre-built
  library ships) via `hamiltonian_sources/ab_initio.py`: real HF energy is
  filled in (the only source that does), optional frozen-core active-space
  reduction, Jordan-Wigner mapping.

Schema version: 2.6.0
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic


class HamiltonianSource(str, enum.Enum):
    PENNYLANE_QCHEM = "pennylane_qchem"
    HAMLIB_CHEMISTRY = "hamlib_chemistry"
    AB_INITIO_PYSCF = "ab_initio_pyscf"


class HamiltonianLibraryRecord(pydantic.BaseModel):
    """Metadata for one Hamiltonian loaded from an external library.

    Pairs with a `SparsePauliObservable` returned alongside it by the
    loader functions in `qpubench.hamiltonian_sources` — this record never
    carries the Hamiltonian terms itself (that's what
    `schemas.observable.SparsePauliObservable` already models).

    Only `source`/`molecule_name`/`num_qubits` are guaranteed; neither
    source supplies every other field (HamLib ships no reference energies
    at all; PennyLane exposes no `hf_energy`) — left `None` rather than
    fabricated.

    encoding        qubit mapping: "JW" | "BK" | "parity" | "molec"
                    (HamLib's four real encodings) — PennyLane datasets are
                    always Jordan-Wigner internally, recorded as "JW" too.
    one_norm        sum of absolute term coefficients (HamLib metadata;
                    an upper bound on the Hamiltonian's spectral norm).
    extras          escape hatch — e.g. HamLib's category
                    ("standard"/"bond_breaking"/...) or the exact HDF5
                    dataset key used.
    """
    source: HamiltonianSource
    molecule_name: str
    num_qubits: int
    basis: str | None = None
    bond_length: float | None = None
    encoding: str | None = None
    num_electrons: int | None = None
    num_terms: int | None = None
    one_norm: float | None = None
    fci_energy: float | None = None
    hf_energy: float | None = None
    vqe_energy: float | None = None
    extras: dict[str, Any] = {}


__all__ = [
    "HamiltonianLibraryRecord",
    "HamiltonianSource",
]
