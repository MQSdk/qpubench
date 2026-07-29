"""QCSchema / QCElemental interoperability schemas.

Harmonizes qpubench with the MolSSI QCSchema standard (v2) and the
PennyLane qchem molecule dataset format.

QCSchema defines: Molecule, AtomicInput, AtomicResult, OptimizationInput,
OptimizationResult, WavefunctionProperties, and common energy/property blocks.
QCElemental (qcelemental.models) is the Python reference implementation.
PennyLane qchem datasets provide molecular Hamiltonians, basis sets, energies,
and wavefunction data for standard benchmark molecules.

Schema version: 1.9.0
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class QCDriver(str, enum.Enum):
    """Computation type — matches QCElemental DriverEnum."""
    ENERGY     = "energy"      # scalar energy, derivative order 0
    GRADIENT   = "gradient"    # first derivatives, order 1
    HESSIAN    = "hessian"     # second derivatives, order 2
    PROPERTIES = "properties"  # molecular properties, order 0


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class QCProvenance(pydantic.BaseModel):
    """Source record for a computation or data object.

    Mirrors qcelemental.models.common_models.Provenance.
    creator is the program, library, or person that produced the data.
    """
    creator: str
    version: str | None = None
    routine: str | None = None


# ---------------------------------------------------------------------------
# Molecule (QCSchema v2)
# ---------------------------------------------------------------------------

class QCMolecule(pydantic.BaseModel):
    """QCSchema v2 molecule format.

    geometry is a flat list of 3*nat Cartesian coordinates in Bohr
    (row-major: x0,y0,z0, x1,y1,z1, …).  symbols has nat entries.
    Connectivity entries are (atom_i, atom_j, bond_order) tuples.
    Fragments are lists of atom indices; charges and multiplicities
    per fragment must match the number of fragment groups.

    This mirrors qcelemental.models.Molecule field conventions and
    complements MoleculeStructureSpec (which uses Angström XYZ atoms).
    """
    symbols:                  list[str]
    geometry:                 list[float]              # 3*nat, Bohr
    molecular_charge:         float = 0.0
    molecular_multiplicity:   int   = 1                # 2S+1
    masses:                   list[float]        = []  # nat; inferred if absent
    real:                     list[bool]         = []  # nat; ghost-atom flags
    connectivity:             list[tuple[int, int, float]] = []  # (i,j,bond_order)
    fragments:                list[list[int]]    = []  # atom-index groups
    fragment_charges:         list[float]        = []
    fragment_multiplicities:  list[int]          = []
    fix_com:                  bool = False
    fix_orientation:          bool = False
    name:                     str | None = None
    comment:                  str | None = None
    provenance:               QCProvenance | None = None
    extras:                   dict[str, Any] = {}

    @pydantic.model_validator(mode="after")
    def _check_geometry(self) -> QCMolecule:
        nat = len(self.symbols)
        if len(self.geometry) != 3 * nat:
            raise ValueError(
                f"geometry has {len(self.geometry)} values, "
                f"expected 3*{nat}={3 * nat}"
            )
        return self

    @property
    def num_atoms(self) -> int:
        return len(self.symbols)

    @property
    def formula(self) -> str:
        from collections import Counter
        counts = Counter(self.symbols)
        return "".join(
            f"{sym}{cnt if cnt > 1 else ''}"
            for sym, cnt in sorted(counts.items())
        )


# ---------------------------------------------------------------------------
# Method / basis
# ---------------------------------------------------------------------------

class QCModel(pydantic.BaseModel):
    """Quantum chemistry method + basis set specification.

    method — any string recognized by QCEngine: "hf", "b3lyp", "mp2",
             "ccsd", "ccsd(t)", "fci".
    basis  — Gaussian basis set name ("sto-3g", "cc-pvdz", …) or None.
    """
    method: str
    basis:  str | None = None


# ---------------------------------------------------------------------------
# Calculation metadata
# ---------------------------------------------------------------------------

class QCCalcInfo(pydantic.BaseModel):
    """Count metadata from a completed atomic calculation."""
    nbasis: int | None = None   # AO basis functions
    nmo:    int | None = None   # molecular orbitals
    nalpha: int | None = None   # alpha electrons
    nbeta:  int | None = None   # beta electrons
    natom:  int | None = None


# ---------------------------------------------------------------------------
# Energy components
# ---------------------------------------------------------------------------

class QCEnergyComponents(pydantic.BaseModel):
    """Decomposed energy contributions in Hartree.

    Field names match QCElemental AtomicResultProperties conventions.
    Populate only the levels actually computed; leave others None.
    """
    nuclear_repulsion_energy:   float | None = None
    scf_one_electron_energy:    float | None = None
    scf_two_electron_energy:    float | None = None
    scf_xc_energy:              float | None = None   # DFT XC functional
    mp2_correlation_energy:     float | None = None
    mp2_total_energy:           float | None = None
    ccsd_correlation_energy:    float | None = None
    ccsd_total_energy:          float | None = None
    ccsd_t_correlation_energy:  float | None = None
    ccsd_t_total_energy:        float | None = None
    ccsdt_total_energy:         float | None = None
    ccsdtq_total_energy:        float | None = None
    fci_total_energy:           float | None = None   # FCI reference for QPU benchmarking


# ---------------------------------------------------------------------------
# Atomic result properties
# ---------------------------------------------------------------------------

class QCAtomicResultProperties(pydantic.BaseModel):
    """Computed properties from a single-point atomic calculation.

    Mirrors QCElemental AtomicResultProperties (key fields only).
    All energies in Hartree; multipole moments in atomic units.
    return_energy is the primary energy result for the requested driver/model.
    gradient and hessian are flattened arrays (3*nat and 9*nat² entries).
    """
    calcinfo:           QCCalcInfo = pydantic.Field(default_factory=QCCalcInfo)
    return_energy:      float | None = None
    energy_components:  QCEnergyComponents = pydantic.Field(
        default_factory=QCEnergyComponents
    )
    # Multipole moments (a.u.)
    scf_dipole_moment:      list[float] = []   # [dx, dy, dz]
    scf_quadrupole_moment:  list[float] = []   # 9 entries (3×3)
    mp2_dipole_moment:      list[float] = []
    ccsd_dipole_moment:     list[float] = []
    # Gradient / Hessian as flat lists
    return_gradient: list[float] = []          # 3*nat
    return_hessian:  list[float] = []          # 9*nat²


# ---------------------------------------------------------------------------
# Wavefunction data
# ---------------------------------------------------------------------------

class QCWavefunctionData(pydantic.BaseModel):
    """SCF wavefunction storage as flat (JSON-safe) float lists.

    All matrices are stored column-major and flattened:
      orbital coefficients (nao × nmo) → length nao*nmo
      density / Fock / overlap (nao × nao) → length nao²
    Eigenvalue / occupation arrays have length nmo.

    Alpha (spin-up) and beta (spin-down) variants follow the
    QCElemental spin-unrestricted convention.  For restricted SCF,
    populate only the _a fields.

    two_electron_integrals (nao⁴) is included for completeness but
    omitted in practice for systems with more than ~10 AOs.
    """
    basis_name:   str | None = None
    nao:          int | None = None   # AO basis functions
    nmo:          int | None = None   # molecular orbitals

    # Orbital coefficient matrices (nao × nmo, column-major, flat)
    scf_orbitals_a: list[float] = []
    scf_orbitals_b: list[float] = []

    # Density matrices (nao × nao)
    scf_density_a: list[float] = []
    scf_density_b: list[float] = []

    # Fock matrices (nao × nao)
    scf_fock_a: list[float] = []
    scf_fock_b: list[float] = []

    # Eigenvalues and occupations (length nmo)
    scf_eigenvalues_a:  list[float] = []
    scf_eigenvalues_b:  list[float] = []
    scf_occupations_a:  list[float] = []
    scf_occupations_b:  list[float] = []

    # Overlap and core Hamiltonian (nao × nao)
    overlap_matrix:     list[float] = []
    core_hamiltonian_a: list[float] = []
    core_hamiltonian_b: list[float] = []

    # Two-electron integrals (nao⁴) — omit for large systems
    two_electron_integrals: list[float] = []


# ---------------------------------------------------------------------------
# Atomic input / result
# ---------------------------------------------------------------------------

class QCAtomicInput(pydantic.BaseModel):
    """Single-point QCSchema computation input.

    Mirrors QCElemental AtomicInput.  molecule + driver + model are
    the three required fields in the QCSchema standard.
    """
    schema_name:    str    = "qcschema_input"
    schema_version: int    = 1
    molecule:       QCMolecule
    driver:         QCDriver = QCDriver.ENERGY
    model:          QCModel
    keywords:       dict[str, Any] = {}
    id:             str | None = None
    extras:         dict[str, Any] = {}
    provenance:     QCProvenance | None = None


class QCAtomicResult(pydantic.BaseModel):
    """Single-point QCSchema computation result.

    Mirrors QCElemental AtomicResult — input fields mirrored plus
    result fields.  return_result holds the primary output: a scalar
    for driver=energy, flat list for gradient/hessian, or dict for
    properties.
    """
    schema_name:    str    = "qcschema_output"
    schema_version: int    = 1
    # Input (mirrored)
    molecule:   QCMolecule
    driver:     QCDriver    = QCDriver.ENERGY
    model:      QCModel
    keywords:   dict[str, Any] = {}
    # Result
    return_result:  float | list[float] | dict[str, Any] | None = None
    properties:     QCAtomicResultProperties = pydantic.Field(
        default_factory=QCAtomicResultProperties
    )
    wavefunction:   QCWavefunctionData | None = None
    success:        bool = True
    error_message:  str | None = None
    stdout:         str | None = None
    provenance:     QCProvenance | None = None
    extras:         dict[str, Any] = {}
    id:             str | None = None


# ---------------------------------------------------------------------------
# Geometry optimization
# ---------------------------------------------------------------------------

class QCOptimizationInput(pydantic.BaseModel):
    """Geometry optimization QCSchema input.

    input_specification provides the per-step driver + model (energy
    or gradient).  initial_molecule is the starting geometry.
    """
    schema_name:         str    = "qcschema_optimization_input"
    schema_version:      int    = 1
    input_specification: QCAtomicInput
    initial_molecule:    QCMolecule
    keywords:            dict[str, Any] = {}
    id:                  str | None = None
    provenance:          QCProvenance | None = None


class QCOptimizationResult(pydantic.BaseModel):
    """Geometry optimization QCSchema result.

    trajectory holds per-step AtomicResult records (one per gradient
    evaluation).  energies is a convenience list extracted from each
    step.  final_molecule holds the converged geometry.
    """
    schema_name:         str    = "qcschema_optimization_output"
    schema_version:      int    = 1
    # Input (mirrored)
    input_specification: QCAtomicInput
    initial_molecule:    QCMolecule
    keywords:            dict[str, Any] = {}
    # Result
    final_molecule:  QCMolecule | None        = None
    trajectory:      list[QCAtomicResult]     = []
    energies:        list[float]              = []   # one per step
    success:         bool = True
    error_message:   str | None = None
    provenance:      QCProvenance | None = None
    extras:          dict[str, Any] = {}
    id:              str | None = None

    @property
    def num_steps(self) -> int:
        return len(self.energies)

    @property
    def converged_energy(self) -> float | None:
        return self.energies[-1] if self.energies else None


# ---------------------------------------------------------------------------
# PennyLane qchem dataset descriptor
# ---------------------------------------------------------------------------

class PennyLaneMolDataset(pydantic.BaseModel):
    """Metadata descriptor for a PennyLane qchem molecule dataset entry.

    PennyLane hosts molecular Hamiltonians, energies, and wavefunction
    data for common quantum chemistry benchmark molecules at various
    bond lengths and basis sets (HDF5 format via pennylane.data).

    molname        Molecule identifier (H2, LiH, H2O, BeH2, N2, …)
    basis          Basis set name (STO-3G, 6-31G, cc-pVDZ, …)
    bondlength     Primary bond length in Angstrom (None for poly-atomic)
    hf_energy      Hartree-Fock reference energy (Hartree)
    fci_energy     FCI full-CI energy — quantum chemistry ground truth (Hartree)
    ccsd_energy    CCSD(T) energy where available (Hartree)
    num_electrons  Total electron count (sets active space)
    num_qubits     Jordan-Wigner mapped qubit count
    pauli_terms    Number of Pauli terms in the qubit Hamiltonian
    dataset_tag    PennyLane dataset identifier string
    """
    molname:       str
    basis:         str
    bondlength:    float | None = None
    hf_energy:     float | None = None
    fci_energy:    float | None = None
    ccsd_energy:   float | None = None
    num_electrons: int   | None = None
    num_qubits:    int   | None = None
    pauli_terms:   int   | None = None
    dataset_tag:   str   | None = None
    extra_properties: dict[str, Any] = {}

    @property
    def correlation_energy(self) -> float | None:
        """FCI correlation energy (FCI − HF) in Hartree."""
        if self.fci_energy is not None and self.hf_energy is not None:
            return self.fci_energy - self.hf_energy
        return None


# ---------------------------------------------------------------------------
# Top-level record
# ---------------------------------------------------------------------------

class QCSchemaRecord(pydantic.BaseModel):
    """Top-level QCSchema record — bridges to qpubench QuantumResult.

    Holds one or more of:
      atomic_result       — single-point energy/gradient/hessian/properties
      optimization_result — geometry optimization trajectory
      pennylane_dataset   — PennyLane qchem dataset reference metadata

    reference_energy returns the best available classical reference energy
    regardless of which record is populated (used for QPU error benchmarking).
    """
    atomic_result:       QCAtomicResult      | None = None
    optimization_result: QCOptimizationResult | None = None
    pennylane_dataset:   PennyLaneMolDataset  | None = None

    @property
    def reference_energy(self) -> float | None:
        """Best available classical reference energy in Hartree."""
        if self.atomic_result is not None:
            return self.atomic_result.properties.return_energy
        if self.optimization_result is not None:
            return self.optimization_result.converged_energy
        if self.pennylane_dataset is not None:
            return self.pennylane_dataset.fci_energy
        return None
