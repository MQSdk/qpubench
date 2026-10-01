"""What the shared tools in utils/ need to know about this campaign.

Loaded by `utils/_campaign.py`; see its docstring for what each name
means.  Everything here is specific to this campaign: its file layout,
how its Hamiltonian files are named, and facts about its cells that only
its own data establishes.
"""
from __future__ import annotations

import pathlib

DIR = pathlib.Path(__file__).resolve().parent

CSV = DIR / "targeted_screen.csv"
QASM_DIR = DIR / "qasm"
HAMILTONIAN_DIR = DIR / "hamiltonian_data"
RESULTS_DIR = DIR / "results"

# The device this campaign buys QPU time on, in IBM's European data
# centre. qiskit-ibm-runtime ships an offline calibration snapshot for it
# (FakeAachen), so pricing against it needs no credentials.
PRICING_DEVICE = "ibm_aachen"


# --- Hamiltonians ---------------------------------------------------------
#
# Committed per (molecule, basis, mapper). For MolMap_sb they are the only
# source: that encoding is Cebule's, reordered by
# regenerate_spinblock_mol_map.py, so nothing here can derive it.
_FILE_MOLECULE = {"H2": "h2", "H2O": "water"}
_FILE_BASIS = {"sto-3g": "sto3g", "6-31g": "6-31G", "cc-pvdz": "cc-pvdz",
               "cc-pvtz": "cc-pvtz", "def2-tzvp": "def2-tzvp", "qvSZP": "qvSZP"}
_FILE_MAPPER = {"JW": "JW", "MolMap_sb": "MolMap_sb"}


def hamiltonian_file(run: dict[str, str]) -> pathlib.Path | None:
    """The committed Hamiltonian for this run, or None if there is not one."""
    molecule = _FILE_MOLECULE.get(run["Molecule"])
    basis = _FILE_BASIS.get(run["Basis"])
    mapper = _FILE_MAPPER.get(run["Mapper"])
    if molecule is None or basis is None or mapper is None:
        return None
    path = HAMILTONIAN_DIR / f"{molecule}_{basis}_{mapper}.json"
    return path if path.exists() else None


# --- Hartree-Fock states under MolMap_sb ----------------------------------
#
# Bit lists in Pauli-label order (leftmost = highest qubit). The spin-block
# reordering puts HF on the all-zeros determinant index, as
# reorder_mapped_hamiltonian reports when regenerate_spinblock_mol_map.py
# builds these Hamiltonians.
MOL_MAP_SPINBLOCK_HF_STATE: dict[tuple[str, str], list[int]] = {
    ("H2", "6-31g"): [0, 0, 0, 0],
    ("H2O", "6-31g"): [0, 0, 0, 0, 0, 0],
}


def hf_state(run: dict[str, str]) -> list[int]:
    """Hartree-Fock bits for a MolMap_sb row."""
    if run["Mapper"] != "MolMap_sb":
        raise KeyError(f"no Hartree-Fock state rule for mapper {run['Mapper']!r}")
    try:
        return MOL_MAP_SPINBLOCK_HF_STATE[(run["Molecule"], run["Basis"])]
    except KeyError:
        raise KeyError(
            f"no MolMap_sb Hartree-Fock state for {run['Molecule']}/{run['Basis']}; "
            "add it to MOL_MAP_SPINBLOCK_HF_STATE"
        ) from None


# --- Cells that cannot be simulated ---------------------------------------
#
# H2/qvSZP under Jordan-Wigner is 16 qubits, and TN_QC_OPT materialises the
# transformed Hamiltonian as a dense 2^n x 2^n operator: 64 GiB here, set by
# the qubit count alone, so no submission option avoids it. Kept as a record
# even though the matrix no longer generates the cell.
SIMULATION_INFEASIBLE: dict[tuple[str, str, str], str] = {
    ("H2", "qvSZP", "JW"): (
        "16 qubits: the dense 2^16 x 2^16 transformed Hamiltonian is 64 GiB, "
        "65,536x the 8-qubit cells. Measured, not projected -- three runs "
        "died on exactly that allocation, under both measurement methods "
        "and in network mode"
    ),
}


def simulation_infeasible_reason(run: dict[str, str]) -> str | None:
    """Why this run cannot be simulated at all, or None if it can."""
    return SIMULATION_INFEASIBLE.get((run["Molecule"], run["Basis"], run["Mapper"]))
