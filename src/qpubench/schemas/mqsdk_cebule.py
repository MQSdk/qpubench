"""Cebule SDK (MQS) task input/output schemas.

Maps Cebule task types to typed Pydantic models that slot cleanly into
qpubench CircuitSpec / QuantumResult / VQAConfig records.

This module was revised 2026-07-08 after checking docs.mqs.dk and the
Cebule Python SDK source directly (gitlab.com/mqsdk/python-sdk,
particularly ``mqsdk/core/cebule.py``, ``mqsdk/utils/tasks.py``, and the
``notebooks/`` examples). Two groups of task types now live here:

Confirmed against ``mqsdk/core/cebule.py``'s ``TaskType`` enum
------------------------------------------------------------------
COSMO                  continuum solvation (dielectric + VDW radii)
SIGMA                  COSMO-SAC/-RS sigma profile
SOLUBILITY             solubility from sigma profile(s)
CAR_PARRINELLO_MD      ab initio MD, QE-backed (periodic-capable)
BORN_OPPENHEIMER_MD    ab initio MD, QE-backed (periodic-capable)
FORCE_FIELD_MD         classical MD (mixture/solvent box)
GEOMETRY_OPT           force-field + semi-empirical geometry optimisation
PERIODIC_GEOMETRY_OPT  geometry optimisation under periodic boundary conditions
GROUP_CONTRIBUTION     group-contribution property estimation for mixtures
ATOM_ORDER             canonical atom ordering for a SMILES (+ optional geometry)
ACTIVITY_COEFFICIENT   confirmed to exist; no usage example found in source checked
GNN_DATASET_CREATE / _EXTEND / _GET / _DELETE, GNN_TRAIN, GNN_PREDICT
                       property-prediction GNN dataset/model lifecycle
TN_QC_OPT              tensor-network + quantum circuit hybrid VQE optimisation
COVO                   correlation-optimised virtual orbital pre-processing

NOT found in that TaskType enum (kept, flagged — see CebuleTaskType docstring)
-------------------------------------------------------------------------------
MOL_MAP    molecular geometry -> qubit Hamiltonian (constraint-based encoding)
QASM_GEN   Hamiltonian -> OpenQASM measurement circuits + post-processing table

SDK session pattern
--------------------
    import mqsdk, os
    session = mqsdk.Cebule(os.environ['EMAIL'], os.environ['PASSWORD'])
    task = session.cebule.create_task(name, TaskType.*, **kwargs)
    # or, for BORN_OPPENHEIMER_MD / CAR_PARRINELLO_MD specifically:
    task = session.cebule.create_task(name, TaskType.*, input=qe_input_text)

Every task accepts a common envelope of parameters
(``max_processors``, ``connected_task_id``, ``connected_model_id``,
``connected_dataset_id``, ``notification_minutes_threshold``) confirmed
directly against ``MQSCebule.create_task()``'s signature — see
``CebuleTaskEnvelope``. Tasks chain into a DAG via ``connected_task_id``
(e.g. GEOMETRY_OPT -> COSMO -> SIGMA -> SOLUBILITY), the same shape as this
framework's own ``integrations/kubeflow/`` Cebule DAG example.
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic

from .circuit import CircuitSpec
from .primitives import CebuleTaskType, CircuitFormat
from .observable import SparsePauliObservable


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

class MolecularGeometry(pydantic.BaseModel):
    """Cartesian molecular geometry shared by MOL_MAP and COVO inputs.

    geometry is a flat 1-D list of Cartesian coordinates in Angstroms,
    ordered as (x0, y0, z0, x1, y1, z1, ...).
    """
    geometry:     list[float]
    symbols:      list[str]
    basis:        str = "sto3g"
    multiplicity: int = 1
    charge:       int = 0

    @pydantic.model_validator(mode="after")
    def _check_geometry(self) -> MolecularGeometry:
        if len(self.geometry) != 3 * len(self.symbols):
            raise ValueError(
                f"geometry length {len(self.geometry)} must be 3 × "
                f"len(symbols) = {3 * len(self.symbols)}"
            )
        return self


class CebuleTaskEnvelope(pydantic.BaseModel):
    """Common ``create_task()`` parameters, confirmed directly against
    ``mqsdk/core/cebule.py``'s ``MQSCebule.create_task()`` signature — every
    Cebule task in this module accepts these alongside its own
    task-specific fields (the task's own fields become ``**kwargs``;
    ``name``/``type`` are passed separately by the caller, not modeled here).

    max_processors                   max processor count for the task
    connected_task_id                ID (or list of IDs) of a prior task
                                      this one chains from
    connected_model_id               ID of a GNN model to connect (GNN_PREDICT)
    connected_dataset_id             ID of a GNN dataset to connect
                                      (GNN_* dataset tasks)
    notification_minutes_threshold   minutes-before-completion notification
                                      trigger
    """
    max_processors:                  int | None              = None
    connected_task_id:                str | list[str] | None  = None
    connected_model_id:                str | None              = None
    connected_dataset_id:              str | None              = None
    notification_minutes_threshold:   int | None              = None


# ---------------------------------------------------------------------------
# MOL_MAP  (unconfirmed against current SDK source — see module docstring)
# ---------------------------------------------------------------------------

class MolMapInput(pydantic.BaseModel):
    """Input for the Cebule MOL_MAP task."""
    task_type: CebuleTaskType = CebuleTaskType.MOL_MAP
    molecule:  MolecularGeometry


class MolMapResult(pydantic.BaseModel):
    """Output of the Cebule MOL_MAP task.

    mapped_hamiltonian  sparse matrix (2-D) of the qubit Hamiltonian after
                        constraint-based encoding; rows/cols = qubit basis states
    hf_state            Hartree-Fock ground state in the mapped qubit basis
    mapping_matrix      bijective mapping operator D (2-D)
    num_qubits          qubit count after encoding (< 2N for constraint encoding)
    """
    mapped_hamiltonian: list[list[float]]
    hf_state:           list[int]
    mapping_matrix:     list[list[float]]
    num_qubits:         int | None = None

    def to_sparse_pauli_observable(
        self,
        num_qubits: int,
        operators: list[str],
        coefficients: list[float],
    ) -> SparsePauliObservable:
        """Convert qubit operator strings + coefficients to a SparsePauliObservable.

        operators and coefficients come from a follow-up TN_QC_OPT result
        (qubit_operators / h_tn_opt_qubit).
        """
        return SparsePauliObservable.from_cebule_operators(
            operators, coefficients, num_qubits
        )


# ---------------------------------------------------------------------------
# QASM_GEN  (unconfirmed against current SDK source — see module docstring)
# ---------------------------------------------------------------------------

class QASMGenInput(pydantic.BaseModel):
    """Input for the Cebule QASM_GEN task.

    operator is a Hermitian sparse matrix (2-D list) whose expectation value
    is to be measured.  Either state_vector or state_circuit (OpenQASM string)
    may be supplied for state preparation; both are optional.
    """
    task_type:             CebuleTaskType = CebuleTaskType.QASM_GEN
    operator:              list[list[float]]
    state_vector:          list[float] | None = None
    state_circuit:         str | None         = None
    include_state_circuit: bool               = True


class QASMGenResult(pydantic.BaseModel):
    """Output of the Cebule QASM_GEN task.

    circuit_files             one OpenQASM 2.0 string per Pauli grouping
    postprocessing_instructions  2-D table: each row encodes how to combine
                              measurement outcomes for that circuit into the
                              final expectation value (sign/coefficient data)
    state_circuit             state preparation sub-circuit (OpenQASM 2.0)
    """
    circuit_files:               list[str]
    postprocessing_instructions: list[list[float]]
    state_circuit:               str | None = None

    def to_circuit_specs(self, num_qubits: int) -> list[CircuitSpec]:
        """Wrap each circuit_file as a CircuitSpec with format=QASM2."""
        return [
            CircuitSpec(
                num_qubits=num_qubits,
                format=CircuitFormat.QASM2,
                serialized=src,
            )
            for src in self.circuit_files
        ]

    def to_openqasm3_circuit_specs(
        self,
        num_qubits: int,
        qasm3_sources: list[str],
    ) -> list[CircuitSpec]:
        """Wrap caller-supplied OpenQASM 3.0 transpilations of each circuit.

        Use this when a downstream transpiler (e.g. Qiskit) has converted the
        QASM_GEN output circuits to OpenQASM 3.0 format.
        """
        if len(qasm3_sources) != len(self.circuit_files):
            raise ValueError(
                f"qasm3_sources length {len(qasm3_sources)} != "
                f"circuit_files length {len(self.circuit_files)}"
            )
        return [
            CircuitSpec.from_openqasm3(src, num_qubits=num_qubits)
            for src in qasm3_sources
        ]


# ---------------------------------------------------------------------------
# TN_QC_OPT
# ---------------------------------------------------------------------------

class TNQCOptInput(pydantic.BaseModel):
    """Input for the Cebule TN_QC_OPT task.

    h_operators accepts three operator formats (as in the SDK):
      Fermionic:    ((site, bool), ...)
      Qubit tuple:  ((qubit, 'X'|'Y'|'Z'), ...)
      Qubit string: "X0 Y1 Z3"

    Store the raw SDK value here; use SparsePauliObservable.from_cebule_operators()
    on the TNQCOptResult output for a typed representation.
    """
    task_type:        CebuleTaskType  = CebuleTaskType.TN_QC_OPT
    h_coeff_values:   list[float]
    h_operators:      list[Any]
    n_iterations:     int
    n_layers_network: int
    qasm_ansatz:      str | None     = None
    n_layers_circuit: int            = 3
    three_para_tn:    bool           = True
    theta_init:       list[float]    = []
    phi_init:         list[float]    = []
    conv_tol:         float | None   = None
    opt_method:       str            = "BFGS"
    backend:          str            = "lightning.qubit"   # or "qiskit.aer"


class TNQCOptResult(pydantic.BaseModel):
    """Output of the Cebule TN_QC_OPT task.

    qubit_operators uses space-separated PauliLabel+index tokens ("X0 Y1 Z3").
    Use SparsePauliObservable.from_cebule_operators(qubit_operators,
    h_tn_opt_qubit, num_qubits) to get a typed observable.
    """
    vqe_energy:      float
    phi:             list[float]   # optimised circuit parameters U(φ)
    theta:           list[float]   # optimised TN parameters U(θ)
    h_tn_opt_qubit:  list[float]   # optimised Hamiltonian coefficients
    qubit_operators: list[str]     # "X0 Y1 Z3" format, parallel to h_tn_opt_qubit

    def to_sparse_pauli_observable(self, num_qubits: int) -> SparsePauliObservable:
        return SparsePauliObservable.from_cebule_operators(
            self.qubit_operators, self.h_tn_opt_qubit, num_qubits
        )


# ---------------------------------------------------------------------------
# COVO
# ---------------------------------------------------------------------------

class COVOInput(pydantic.BaseModel):
    """Input for the Cebule COVO task (plane-wave periodic systems)."""
    task_type:          CebuleTaskType = CebuleTaskType.COVO
    geometry:           list[float]    # Cartesian coordinates in Angstroms (flat)
    symbols:            list[str]
    cell_size:          float          # simulation box side length (Å)
    periodic:           bool           = False
    cutoff:             float          # plane-wave energy cutoff (Hartree)
    n_virtual_orbitals: int
    charge:             int            = 0
    multiplicity:       int            = 1
    tolerance:          float          = 1.0e-6   # SCF convergence threshold

    @pydantic.model_validator(mode="after")
    def _check_geometry(self) -> COVOInput:
        if len(self.geometry) != 3 * len(self.symbols):
            raise ValueError(
                f"geometry length {len(self.geometry)} must be 3 × "
                f"len(symbols) = {3 * len(self.symbols)}"
            )
        return self


class COVOResult(pydantic.BaseModel):
    """Output of the Cebule COVO task.

    one_electron_integrals  N×N kinetic + nuclear attraction matrix
    two_electron_integrals  N⁴ electron repulsion tensor (N×N×N×N)
    hf_energy               Hartree-Fock energy (Hartree)
    fci_energy              Full CI energy (Hartree); reference for VQE error
    vqe_energy              VQE-optimised energy (Hartree)
    hamiltonian              full electronic Hamiltonian matrix (2-D)
    """
    one_electron_integrals: list[list[float]]
    two_electron_integrals: list[list[list[list[float]]]]
    hf_energy:              float
    fci_energy:              float
    vqe_energy:              float
    hamiltonian:             list[list[float]]

    @property
    def correlation_energy(self) -> float:
        """FCI correlation energy relative to Hartree-Fock."""
        return self.fci_energy - self.hf_energy

    @property
    def vqe_error(self) -> float:
        """VQE error vs FCI ground truth (absolute value)."""
        return abs(self.vqe_energy - self.fci_energy)


# ---------------------------------------------------------------------------
# GEOMETRY_OPT / PERIODIC_GEOMETRY_OPT
# ---------------------------------------------------------------------------

class GeometryOptForceField(str, enum.Enum):
    """Confirmed choices from scripts/geometry.py's argparse (--force_field)."""
    MMFF94   = "mmff94"
    GHEMICAL = "ghemical"


class GeometryOptMethod(str, enum.Enum):
    """Confirmed choices from scripts/geometry.py's argparse (--optimization_method)."""
    G_XTB    = "g_xtb"
    GFN2_XTB = "gfn2_xtb"
    AM1      = "am1"
    UMA      = "uma"


class GeometryOptInput(CebuleTaskEnvelope):
    """Input for TaskType.GEOMETRY_OPT — force-field-then-semi-empirical
    geometry optimisation. Confirmed against scripts/geometry.py and
    mqsdk/utils/tasks.py's optimize_geometry(), which submits
    smiles_list=[smiles] (a single-element list per call).
    """
    task_type:            CebuleTaskType      = CebuleTaskType.GEOMETRY_OPT
    smiles_list:           list[str]
    force_field:            GeometryOptForceField
    optimization_method:    GeometryOptMethod


class GeometryOptResult(pydantic.BaseModel):
    """Output of TaskType.GEOMETRY_OPT.

    coordinates_list  one flat Cartesian coordinate list (Angstroms) per
                       input SMILES, same order as GeometryOptInput.smiles_list
    """
    coordinates_list: list[list[float]]


class PeriodicGeometryOptInput(CebuleTaskEnvelope):
    """Input for TaskType.PERIODIC_GEOMETRY_OPT — geometry optimisation
    under periodic boundary conditions.

    Confirmed to exist in mqsdk/core/cebule.py's TaskType enum; no usage
    example (notebook or script) was found during this check. The fields
    below are inferred by analogy to GEOMETRY_OPT (force-field / method
    choice) plus the periodic-cell parameters this module's own COVOInput
    already uses for plane-wave periodic systems — treat as a reasonable
    starting point, not a confirmed field set, and verify against the live
    SDK before relying on exact names.
    """
    task_type:             CebuleTaskType         = CebuleTaskType.PERIODIC_GEOMETRY_OPT
    smiles_list:            list[str] | None       = None
    geometry:               list[float] | None     = None   # flat Cartesian, if not SMILES-derived
    symbols:                list[str] | None       = None
    cell_lengths:            tuple[float, float, float] | None = None   # a, b, c (Å)
    cell_angles:             tuple[float, float, float] | None = None   # alpha, beta, gamma (degrees)
    force_field:             GeometryOptForceField | None      = None
    optimization_method:     GeometryOptMethod | None          = None


class PeriodicGeometryOptResult(pydantic.BaseModel):
    """Output of TaskType.PERIODIC_GEOMETRY_OPT. Inferred by analogy to
    GeometryOptResult plus cell parameters — not confirmed against a usage
    example (see PeriodicGeometryOptInput)."""
    coordinates:  list[float] | None                     = None
    cell_lengths:  tuple[float, float, float] | None      = None
    cell_angles:   tuple[float, float, float] | None      = None


# ---------------------------------------------------------------------------
# FORCE_FIELD_MD / BORN_OPPENHEIMER_MD / CAR_PARRINELLO_MD
# ---------------------------------------------------------------------------

class ForceFieldMDInput(CebuleTaskEnvelope):
    """Input for TaskType.FORCE_FIELD_MD — classical molecular dynamics of a
    primary molecule (optionally a polymer chain, as a list of unit SMILES)
    in a box together with secondary (e.g. solvent) molecules. Confirmed
    against scripts/md.py's run_md_simulation().

    geometry_primary, if provided, skips RDKit force-field optimisation of
    the primary molecule and uses the supplied coordinates directly.
    """
    task_type:               CebuleTaskType  = CebuleTaskType.FORCE_FIELD_MD
    smiles_primary:            str | list[str]
    copies_primary:             int
    smiles_list_secondary:      list[str]
    copies_list_secondary:      list[int]
    temperature:                 float
    box_length_nm:                float
    time_fs:                     float
    geometry_primary:            list[float] | None = None


class ForceFieldMDResult(pydantic.BaseModel):
    """Output of TaskType.FORCE_FIELD_MD. The exact result shape wasn't
    captured in the scripts checked (the caller consumes it as an opaque
    return value) — modeled as a free-form payload; populate as the real
    shape becomes known."""
    result: dict[str, Any] = {}


class AbInitioMDMethod(str, enum.Enum):
    BORN_OPPENHEIMER = "born_oppenheimer_md"
    CAR_PARRINELLO   = "car_parrinello_md"


class AbInitioMDInput(pydantic.BaseModel):
    """Input for TaskType.BORN_OPPENHEIMER_MD / TaskType.CAR_PARRINELLO_MD —
    ab initio molecular dynamics, backed by Quantum ESPRESSO.

    Unlike every other task in this module, the payload is NOT kwargs —
    ``create_task()`` only allows one of ``input`` (raw text) or ``**kwargs``,
    and these two task types use ``input``. Confirmed against
    notebooks/3_BOMD_task_Cebule.ipynb and notebooks/4_CPMD_task_Cebule.ipynb,
    both of which submit real Quantum ESPRESSO ``&control``/``&system``/
    ``&electrons`` (BOMD) or ``&control``/``&system``/``&ions`` (CPMD)
    namelist files — including a periodic 8-water cell in the BOMD example
    (``ibrav``/``celldm`` lattice parameters), confirming genuine periodic
    plane-wave DFT, not just molecular MD.
    """
    method:          AbInitioMDMethod
    qe_input:         str                       # raw Quantum ESPRESSO input file text
    max_processors:   int | None = None


class AbInitioMDResult(pydantic.BaseModel):
    """Output of TaskType.BORN_OPPENHEIMER_MD / CAR_PARRINELLO_MD.

    stdout  raw Quantum ESPRESSO stdout log — retrieved via
            get_result(task.id, "stdout"), confirmed against
            notebooks/4_CPMD_task_Cebule.ipynb. Not structured JSON like the
            other tasks in this module; parse energies/forces from this
            text yourself (or with QE-aware tooling).
    """
    stdout: str


# ---------------------------------------------------------------------------
# COSMO / SIGMA / SOLUBILITY
# ---------------------------------------------------------------------------

class CosmoInput(CebuleTaskEnvelope):
    """Input for TaskType.COSMO — continuum solvation (dielectric constant +
    per-atom van der Waals radii). Confirmed against
    mqsdk/utils/tasks.py's compute_cosmo_and_sigma(), which chains from a
    GEOMETRY_OPT task via connected_task_id.

    optimize=True runs a COSMO-solvated geometry optimisation step;
    optimize=False runs a single-point COSMO SCF on the (already optimized)
    connected geometry — tasks.py runs both in sequence (opt, then scf
    chained from opt) to get a fully relaxed solvated single-point energy.
    """
    task_type:               CebuleTaskType = CebuleTaskType.COSMO
    method:                    str            = "dft"
    basis:                      str
    optimize:                    bool           = False
    dielec:                      float                    # solvent dielectric constant
    driver_convergence:            str            = "loose"
    dft_energy_convergence:         float          = 1.0e-6
    xc:                              str | None     = None   # exchange-correlation functional
    disp:                            str | None     = None   # dispersion correction


class CosmoResult(pydantic.BaseModel):
    """Output of TaskType.COSMO, retrieved via get_result(task.id, "cosmo").
    Field names combine the minimal notebook example
    (notebooks/2_COSMO_task_Cebule.ipynb submits geometry/symbols/method/
    basis/dielec/radius directly) with the production chained pipeline in
    tasks.py — energy/charges are the commonly-needed outputs; extend as
    the full result shape becomes known."""
    energy:   float | None       = None
    charges:  list[float] | None = None


class CosmoMethod(str, enum.Enum):
    """Confirmed against mqsdk/utils/tasks.py's compute_cosmo_and_sigma()."""
    COSMO_SAC = "cosmo-sac"
    COSMO_RS  = "cosmo-rs"


class SigmaInput(CebuleTaskEnvelope):
    """Input for TaskType.SIGMA — COSMO sigma-profile calculation, chained
    from a completed COSMO task via connected_task_id. Confirmed against
    mqsdk/utils/tasks.py's compute_cosmo_and_sigma().
    """
    task_type:      CebuleTaskType = CebuleTaskType.SIGMA
    cosmo_method:     CosmoMethod


class SigmaResult(pydantic.BaseModel):
    """Output of TaskType.SIGMA — a sigma profile: the screening-charge-
    density histogram used by COSMO-SAC/-RS activity-coefficient models.
    Exact field names weren't captured in the scripts checked (consumed as
    an opaque payload) — modeled with the field names conventionally used
    for sigma profiles; extend/rename as the real shape becomes known.

    sigma  screening charge density grid points (e/Å²)
    area   surface area at each sigma value (Å²)
    """
    sigma: list[float] | None = None
    area:  list[float] | None = None


class SolubilityInput(CebuleTaskEnvelope):
    """Input for TaskType.SOLUBILITY — solubility of a solute in a solvent
    mixture, computed from one or more sigma profiles. Confirmed against
    mqsdk/utils/tasks.py's _compute_solubility_for_method(); connects to
    SIGMA task(s) via connected_task_id (a list: solute + each solvent
    component, same order as solv_composition).

    change_heat_capacity_melting is required when the connected sigma
    profile(s) used cosmo_method="cosmo-sac" (per the source checked); not
    used for "cosmo-rs".
    """
    task_type:                        CebuleTaskType = CebuleTaskType.SOLUBILITY
    temperature:                        float
    melting_point:                       float
    enthalpy_melting:                     float
    sol_init:                             float
    solv_composition:                     list[float]         # mole fractions of solvent components
    change_heat_capacity_melting:           float | None       = None


class SolubilityResult(pydantic.BaseModel):
    """Output of TaskType.SOLUBILITY. Exact field name for the solubility
    value wasn't captured in the scripts checked (consumed as an opaque
    return value) — modeled as a free-form payload."""
    result: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# GROUP_CONTRIBUTION / ATOM_ORDER / ACTIVITY_COEFFICIENT
# ---------------------------------------------------------------------------

class GroupContributionInput(CebuleTaskEnvelope):
    """Input for TaskType.GROUP_CONTRIBUTION — group-contribution property
    estimation, batchable across multiple mixtures in one task. Confirmed
    against mqsdk/utils/tasks.py's compute_mixture_group_contribution().

    smiles_list is a list of mixtures, each itself a list of component
    SMILES; batch=True processes all mixtures in the one task.
    """
    task_type:    CebuleTaskType  = CebuleTaskType.GROUP_CONTRIBUTION
    smiles_list:    list[list[str]]
    gc_type:         str
    batch:            bool           = True


class GroupContributionResult(pydantic.BaseModel):
    """Output of TaskType.GROUP_CONTRIBUTION — one result dict per input
    mixture, same order as GroupContributionInput.smiles_list."""
    results: list[dict[str, Any]] = []


class AtomOrderInput(CebuleTaskEnvelope):
    """Input for TaskType.ATOM_ORDER — canonical atom ordering for a SMILES
    string, or for a polymer chain's unit SMILES with geometry. Confirmed
    against mqsdk/utils/tasks.py's get_atom_order() (single molecule, no
    geometry) and get_atom_order_for_polymer() (list of SMILES + geometry).
    """
    task_type:  CebuleTaskType    = CebuleTaskType.ATOM_ORDER
    smiles:       str | list[str]
    geometry:      list[float] | None = None


class AtomOrderResult(pydantic.BaseModel):
    """Output of TaskType.ATOM_ORDER — the canonical atom order. Exact
    element type (index list vs. symbol list) wasn't confirmed in the
    scripts checked."""
    atom_order: list[Any] = []


class ActivityCoefficientInput(CebuleTaskEnvelope):
    """Input for TaskType.ACTIVITY_COEFFICIENT.

    Confirmed only to exist in mqsdk/core/cebule.py's TaskType enum ("used
    by a quick-poll-period" grouping alongside SIGMA/SOLUBILITY, implying
    it's related to the same solvation/activity workflow) — no usage
    example (notebook or script) was found during this check, so no
    task-specific fields are modeled beyond the common envelope. Extend
    this once a real call site is found.
    """
    task_type: CebuleTaskType = CebuleTaskType.ACTIVITY_COEFFICIENT


class ActivityCoefficientResult(pydantic.BaseModel):
    """Output of TaskType.ACTIVITY_COEFFICIENT — not modeled, see
    ActivityCoefficientInput."""
    result: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# GNN dataset / model lifecycle
# ---------------------------------------------------------------------------

class GNNDatasetCreateInput(CebuleTaskEnvelope):
    """Input for TaskType.GNN_DATASET_CREATE. Confirmed against
    notebooks/6_GNN_task_HLGap_GeometryOpt.ipynb."""
    task_type:            CebuleTaskType = CebuleTaskType.GNN_DATASET_CREATE
    dataset_name:            str
    includes_target_val:      bool
    target_property:            str


class GNNDatasetCreateResult(pydantic.BaseModel):
    """Output of TaskType.GNN_DATASET_CREATE, confirmed against the same
    notebook (result key "result", field "dataset_id")."""
    dataset_id: str


class GNNMoleculeChunk(pydantic.BaseModel):
    """One batch of molecules added to a dataset via GNN_DATASET_EXTEND.
    target_val is omitted for prediction-only datasets (confirmed by the
    prediction-dataset cell in notebooks/6_GNN_task_HLGap_GeometryOpt.ipynb,
    which extends without a target_val key)."""
    smiles:      list[str]
    coords:       list[list[float]]
    target_val:    list[float] | None = None


class GNNDatasetExtendInput(CebuleTaskEnvelope):
    """Input for TaskType.GNN_DATASET_EXTEND. Confirmed against
    notebooks/6_GNN_task_HLGap_GeometryOpt.ipynb (dataset built in chunks)."""
    task_type:              CebuleTaskType = CebuleTaskType.GNN_DATASET_EXTEND
    connected_dataset_id:     str
    molecule_chunk:             GNNMoleculeChunk


class GNNDatasetGetInput(CebuleTaskEnvelope):
    """Input for TaskType.GNN_DATASET_GET — retrieve dataset rows
    [start, end). Confirmed against notebooks/6_GNN_task_HLGap_GeometryOpt.ipynb."""
    task_type:              CebuleTaskType = CebuleTaskType.GNN_DATASET_GET
    connected_dataset_id:     str
    start:                      int
    end:                         int


class GNNDatasetDeleteInput(CebuleTaskEnvelope):
    """Input for TaskType.GNN_DATASET_DELETE. Confirmed against
    notebooks/6_GNN_task_HLGap_GeometryOpt.ipynb."""
    task_type:              CebuleTaskType = CebuleTaskType.GNN_DATASET_DELETE
    connected_dataset_id:     str


class GNNTrainInput(CebuleTaskEnvelope):
    """Input for TaskType.GNN_TRAIN — fine-tune a property-prediction GNN on
    a dataset. Confirmed against notebooks/6_GNN_task_HLGap_GeometryOpt.ipynb
    (hyperparameters={"epochs": ...} in that example)."""
    task_type:              CebuleTaskType = CebuleTaskType.GNN_TRAIN
    connected_dataset_id:     str
    model_name:                 str
    hyperparameters:             dict[str, Any] = {}


class GNNTrainResult(pydantic.BaseModel):
    """Output of TaskType.GNN_TRAIN.

    model_id              trained model identifier — feeds GNN_PREDICT's
                           connected_model_id
    mean_absolute_error    training metric named in the SDK's own notebook
                           comment ("view the training result: mean
                           absolute error"); exact key name not confirmed
    """
    model_id:              str | None   = None
    mean_absolute_error:     float | None = None


class GNNPredictInput(CebuleTaskEnvelope):
    """Input for TaskType.GNN_PREDICT. Confirmed against
    notebooks/6_GNN_task_HLGap_GeometryOpt.ipynb."""
    task_type:              CebuleTaskType = CebuleTaskType.GNN_PREDICT
    connected_dataset_id:     str
    connected_model_id:        str


class GNNPredictResult(pydantic.BaseModel):
    """Output of TaskType.GNN_PREDICT. The SDK's own notebook comment
    describes the predicted quantity as "effective hamiltonians" — kept as
    a generic list since the exact structured shape wasn't confirmed."""
    predictions: list[Any] = []


__all__ = [
    "ActivityCoefficientInput",
    "ActivityCoefficientResult",
    "AbInitioMDInput",
    "AbInitioMDMethod",
    "AbInitioMDResult",
    "AtomOrderInput",
    "AtomOrderResult",
    "CebuleTaskEnvelope",
    "CosmoInput",
    "CosmoMethod",
    "CosmoResult",
    "COVOInput",
    "COVOResult",
    "ForceFieldMDInput",
    "ForceFieldMDResult",
    "GeometryOptForceField",
    "GeometryOptInput",
    "GeometryOptMethod",
    "GeometryOptResult",
    "GNNDatasetCreateInput",
    "GNNDatasetCreateResult",
    "GNNDatasetDeleteInput",
    "GNNDatasetExtendInput",
    "GNNDatasetGetInput",
    "GNNMoleculeChunk",
    "GNNPredictInput",
    "GNNPredictResult",
    "GNNTrainInput",
    "GNNTrainResult",
    "GroupContributionInput",
    "GroupContributionResult",
    "MolMapInput",
    "MolMapResult",
    "MolecularGeometry",
    "PeriodicGeometryOptInput",
    "PeriodicGeometryOptResult",
    "QASMGenInput",
    "QASMGenResult",
    "SigmaInput",
    "SigmaResult",
    "SolubilityInput",
    "SolubilityResult",
    "TNQCOptInput",
    "TNQCOptResult",
]
