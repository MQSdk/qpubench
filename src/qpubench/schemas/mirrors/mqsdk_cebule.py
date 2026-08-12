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

Re-checked 2026-07-09 against the current docs.mqs.dk quantum-computing
section (https://docs.mqs.dk/sections/section_014_quantum_computing/,
which the SDK's own maintainers describe as recently updated) — this did
NOT change the TaskType-enum-membership confidence for MOL_MAP/QASM_GEN
above (that still requires checking the SDK source directly, not done in
this session), but did surface real field-level corrections to
``QASMGenInput``/``TNQCOptInput``/``TNQCOptResult`` below, now updated:
``QASMGenInput.include_state_circuit`` defaults to ``False`` (was
documented as ``True`` previously), ``TNQCOptInput.opt_method`` defaults
to ``"COBYLA"`` (was ``"BFGS"``), and two new ``TNQCOptInput`` fields —
``measurement_method`` (``"pauli"`` vs ``"grouped"`` — ``"grouped"`` is
QASM_GEN's own basis-state-pair-grouping technique, confirming QASM_GEN
is usable *inside* TN_QC_OPT, not just standalone) and
``optimization_mode`` (``"circuit"``/``"network"``/``"both"``) — are now
documented and added here. ``TNQCOptResult`` also gained
``function_calls``/``cost_history``/``param_history``/``metadata``/
``optimize_result`` outputs not previously documented.

Revised again 2026-08-08, this time against the TN-VQE *implementation*
rather than the docs page — cebule-tn_vqe @ dev-kba a760489, with
file:line citations in the affected docstrings. This is the first
revision of the TN_QC_OPT models grounded in the code that actually runs,
and it settles the ``h_tn_opt_qubit`` shape question the previous
revision explicitly left open. Changes: ``qubit_operators`` deleted (the
task never returned it) and ``h_tn_opt_qubit`` retyped as the 2-tuple it
really is; ``h_tn_opt_fermionic`` added; ``tn_ansatz``/``n_shots``/
``opt_options`` added as inputs; ``three_para_tn`` deprecated in favour
of the four-member ``TNAnsatz``; and three wrong defaults corrected
(``backend``, ``conv_tol``, ``n_layers_circuit``).

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

from ..circuit import CircuitSpec
from ..observable import SparsePauliObservable
from ..primitives import CircuitFormat

# ---------------------------------------------------------------------------
# Task types
# ---------------------------------------------------------------------------

class CebuleTaskType(str, enum.Enum):
    """Cebule (MQS) task types.

    Lives in this module, not ``primitives``: it is specific to the
    ``mqsdk_cebule`` project mirror, not a cross-cutting core primitive.

    Confirmed directly against ``mqsdk/core/cebule.py``'s ``TaskType`` enum
    at gitlab.com/mqsdk/python-sdk (re-checked 2026-07-10): every member up
    to and including ``MAP_TO_QASM`` matches that source exactly —
    ``MOL_MAP``/``QASM_GEN`` were flagged "unconfirmed" in an earlier
    revision of this docstring (checked 2026-07-08); the SDK has since
    added them for real, plus a new ``MAP_TO_QASM`` member neither this
    module nor that earlier check knew about.

    ``RXN_OPT``/catalyst-design members below are a different situation:
    real per docs.mqs.dk's "RN Catalyst Design" section, but genuinely
    absent from the public SDK repo — checked directly (2026-07-10)
    against every file in gitlab.com/mqsdk/python-sdk's tree (``cebule.py``,
    ``core.py``, ``data.py``, ``models.py``, ``utils/tasks.py``): zero
    matches for "rxn", "catalyst", "surface", "wulff", or "tof" anywhere.
    Likely a newer/enterprise API surface not yet reflected in the public
    repo snapshot, same situation ``MOL_MAP``/``QASM_GEN`` were in before —
    treat these as unconfirmed against source, not verified the way the
    members above them are.
    """
    # Confirmed in the public SDK's TaskType enum.
    COSMO                 = "cosmo"                  # continuum solvation (dielectric + VDW radii)
    SIGMA                 = "sigma"                   # COSMO-SAC/-RS sigma profile
    SOLUBILITY             = "solubility"              # solubility from sigma profiles
    CAR_PARRINELLO_MD      = "car_parrinello_md"       # ab initio MD, QE-backed (periodic-capable)
    BORN_OPPENHEIMER_MD    = "born_oppenheimer_md"     # ab initio MD, QE-backed (periodic-capable)
    FORCE_FIELD_MD          = "force_field_md"          # classical MD (mixture/solvent box)
    GEOMETRY_OPT            = "geometry_opt"            # force-field + semi-empirical geometry optimisation
    PERIODIC_GEOMETRY_OPT   = "periodic_geometry_opt"   # geometry optimisation under periodic boundary conditions
    GROUP_CONTRIBUTION      = "group_contribution"      # group-contribution property estimation for mixtures
    ATOM_ORDER              = "atom_order"              # canonical atom ordering for a SMILES (+ optional geometry)
    ACTIVITY_COEFFICIENT    = "activity_coefficient"    # confirmed to exist; no usage example found in source checked
    GNN_DATASET_CREATE      = "gnn:dataset:create"
    GNN_DATASET_DELETE      = "gnn:dataset:delete"
    GNN_DATASET_EXTEND      = "gnn:dataset:extend"
    GNN_DATASET_GET         = "gnn:dataset:get"
    GNN_TRAIN                = "gnn:train"
    GNN_PREDICT              = "gnn:predict"
    TN_QC_OPT  = "tn_qc_opt"  # tensor-network + quantum circuit VQE
    COVO       = "covo"        # correlation-optimised virtual orbitals
    MOL_MAP    = "mol_map"     # molecular-to-qubit Hamiltonian mapping — now confirmed, see class docstring
    QASM_GEN   = "qasm_gen"    # OpenQASM measurement circuit generation — now confirmed, see class docstring
    MAP_TO_QASM = "map_to_qasm"  # newly discovered 2026-07-10; exact semantics vs. QASM_GEN not yet confirmed
    # Not found anywhere in the public SDK repo — see class docstring.
    RXN_OPT                    = "rxn_opt"                     # reaction-network flux optimisation (unconfirmed)
    GAS_SPECIES_ENERGY          = "gas_species_energy"           # gas-phase reference energies (unconfirmed)
    SURFACE_REACTION_ENERGIES   = "surface_reaction_energies"    # per-surface adsorption/reaction energies (unconfirmed)
    GAN_TOF                     = "gan_tof"                       # GAN-based catalyst composition search (unconfirmed)
    MAKE_SURF                    = "make_surf"                     # bimetallic alloy surface dataset generation (unconfirmed)
    WULFF_CONSTRUCTION           = "wulff_construction"             # equilibrium crystal shape via Wulff geometry (unconfirmed)


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
    """Input for the Cebule MOL_MAP task.

    Active-space fields added 2026-08-01, reported by the campaign owner
    as newly supported by MOL_MAP; not yet cross-checked against the
    public SDK source, so treat the exact field *names* as provisional
    even though the capability is confirmed.  Field names here follow
    this project's existing cross-vendor vocabulary
    (``bestquark_gsopt.ActiveSpaceSpec``, ``BenchmarkRecord``), not a
    known Cebule signature.

    Leaving both counts None runs the full space, the previous and still
    default behaviour.  Setting them freezes the core electrons and
    restricts the correlated space, which is what makes larger molecules
    and larger basis sets tractable: the constraint encoding's qubit
    count is set by the active space, not the basis set, so
    ``CAS(8,6)`` costs the same whether the underlying basis is sto-3g or
    cc-pVTZ (see ``hamiltonian_sources.mol_map``).

    active_electrons  correlated electrons; None runs all of them
    active_orbitals   spatial orbitals in the active space; None uses all
    frozen_core       freeze the core orbitals PySCF-style, as an
                       alternative to naming the space explicitly
    """
    task_type:        CebuleTaskType      = CebuleTaskType.MOL_MAP
    molecule:         MolecularGeometry
    active_electrons: int | None          = None
    active_orbitals:  int | None          = None
    frozen_core:      bool                = False

    @pydantic.model_validator(mode="after")
    def _check_active_space(self) -> "MolMapInput":
        electrons, orbitals = self.active_electrons, self.active_orbitals
        if electrons is None and orbitals is None:
            return self                      # full space, the default
        if electrons is None or orbitals is None:
            raise ValueError(
                "active_electrons and active_orbitals must be set together "
                "(or both left None to run the full space)"
            )
        if electrons <= 0 or orbitals <= 0:
            raise ValueError(
                f"active space must be positive, got CAS({electrons}, {orbitals})"
            )
        if electrons > 2 * orbitals:
            raise ValueError(
                f"CAS({electrons}, {orbitals}) needs more than the "
                f"{2 * orbitals} spin orbitals {orbitals} spatial orbitals provide"
            )
        return self


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

        operators and coefficients come from a follow-up TN_QC_OPT
        result, whose ``h_tn_opt_qubit`` is one (labels, coefficients)
        2-tuple — unpack it, or use ``TNQCOptResult.
        to_sparse_pauli_observable()``, which does that itself.
        """
        return SparsePauliObservable.from_cebule_operators(
            operators, coefficients, num_qubits
        )


# ---------------------------------------------------------------------------
# QASM_GEN  (unconfirmed against current SDK source — see module docstring)
# ---------------------------------------------------------------------------

class QASMGenInput(pydantic.BaseModel):
    """Input for the Cebule QASM_GEN task — "the measurement method [that]
    efficiently evaluates the expectation value of the mapped Hamiltonian
    using a novel circuit generation scheme that groups terms by
    computational basis state pairs rather than Pauli string
    decomposition" (docs.mqs.dk, checked 2026-07-09). Explicitly
    documented as compatible with the output of either MOL_MAP or
    TN_QC_OPT — a general measurement strategy, not tied to one Hamiltonian
    source.

    operator is a Hermitian sparse matrix (2-D list) whose expectation value
    is to be measured.  Either state_vector or state_circuit (OpenQASM string)
    may be supplied for state preparation; both are optional.

    include_state_circuit defaults to False — corrected 2026-07-09
    against the current docs.mqs.dk table (an earlier revision of this
    module had it defaulting True).
    """
    task_type:             CebuleTaskType = CebuleTaskType.QASM_GEN
    operator:              list[list[float]]
    state_vector:          list[float] | None = None
    state_circuit:         str | None         = None
    include_state_circuit: bool               = False


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

class TNAnsatz(str, enum.Enum):
    """The tensor-network rotation family U(θ) is built from.

    Verified against cebule-tn_vqe @ dev-kba a760489,
    ``src/tn_vqe/functions_U.py:150-161``, whose ``M_ANSATZE`` table has
    four members — not the two (``three_para_tn`` True/False) this mirror
    and the benchmark matrix modelled before 2026-08-08.

    ``parsers.py`` still accepts the older ``three_para_tn`` bool and
    translates it (True -> ``rotation_3param``, False ->
    ``rotation_1param``), so both spellings reach the task; ``tn_ansatz``
    wins when both are given.

    The distinction that matters is ``entangles``: a network built from
    either ``rotation_*`` family factorises across the two wires of every
    M gate, so U(θ) cannot entangle at all — it only rotates each qubit's
    local basis. Sweeping only those two sweeps two variants of "no
    entanglement in U(θ)".
    """
    ROTATION_1PARAM   = "rotation_1param"
    ROTATION_3PARAM   = "rotation_3param"    # the task's own default
    GIVENS            = "givens"
    NUMBER_PRESERVING = "number_preserving"


class TNAnsatzProperties(pydantic.BaseModel):
    """Structural facts about one ``TNAnsatz`` family.

    ``params_per_node`` / ``entangles`` / ``conserves_number`` are literal
    fields on the corresponding ``M_ANSATZE`` entry upstream, not
    inferences from the family's name.

    Why ``conserves_number`` earns a field rather than a comment: under
    Jordan-Wigner on adjacent spin-orbitals ``givens`` is the image of
    exp(θ (a_p† a_q − a_q† a_p)), a single-particle orbital basis
    rotation, so U†HU stays a two-body fermionic Hamiltonian and its
    Pauli-string count *saturates* with the network layer count instead of
    growing. ``number_preserving`` is a strict superset (arbitrary U(2) on
    the singly-occupied subspace plus a free phase on |00> and |11>), is
    not a single-particle transformation, and so picks up higher-body
    terms and many more Pauli strings.
    """
    params_per_node:  int
    entangles:        bool
    conserves_number: bool


TN_ANSATZ_PROPERTIES: dict[TNAnsatz, TNAnsatzProperties] = {
    TNAnsatz.ROTATION_1PARAM:   TNAnsatzProperties(
        params_per_node=1, entangles=False, conserves_number=False),
    TNAnsatz.ROTATION_3PARAM:   TNAnsatzProperties(
        params_per_node=3, entangles=False, conserves_number=False),
    TNAnsatz.GIVENS:            TNAnsatzProperties(
        params_per_node=1, entangles=True,  conserves_number=True),
    TNAnsatz.NUMBER_PRESERVING: TNAnsatzProperties(
        params_per_node=5, entangles=True,  conserves_number=True),
}


def tn_node_count(num_qubits: int) -> int:
    """M-gate nodes in the tensor network over ``num_qubits`` qubits.

    ``(3 * n - 2) // 2``, verbatim from ``functions_U.py:15-17``.
    """
    if num_qubits < 1:
        raise ValueError(f"num_qubits must be >= 1, got {num_qubits}")
    return (3 * num_qubits - 2) // 2


def tn_theta_parameter_count(
    num_qubits: int, n_layers_network: int, tn_ansatz: TNAnsatz | str,
) -> int:
    """Network-side (θ) parameter count — fixed by the inputs alone.

    Unlike the expectation-value count per iteration, this needs no run to
    determine: ``n_layers_network * tn_node_count(n) * params_per_node``.

    It is not just bookkeeping. With COBYLA (the benchmark's optimizer)
    the iteration count scales with the parameter count, so a
    ``number_preserving`` row is 5x the classical optimisation work of a
    ``givens`` row at the same layer count.
    """
    if n_layers_network < 0:
        raise ValueError(f"n_layers_network must be >= 0, got {n_layers_network}")
    props = TN_ANSATZ_PROPERTIES[TNAnsatz(tn_ansatz)]
    return n_layers_network * tn_node_count(num_qubits) * props.params_per_node


def tn_theta_shape(
    num_qubits: int, n_layers_network: int, tn_ansatz: TNAnsatz | str,
) -> tuple[int, ...]:
    """Shape ``theta_init`` must have, per ``theta_shape_for``
    (``functions_U.py:181-190``): ``(n_layers, n_nodes)`` for
    one-parameter families, ``(n_layers, n_nodes, n_params)`` otherwise.
    ``run_TNQCOpt`` raises ``ValueError`` on a mismatch.
    """
    props = TN_ANSATZ_PROPERTIES[TNAnsatz(tn_ansatz)]
    nodes = tn_node_count(num_qubits)
    if props.params_per_node == 1:
        return (n_layers_network, nodes)
    return (n_layers_network, nodes, props.params_per_node)


class TNQCOptInput(pydantic.BaseModel):
    """Input for the Cebule TN_QC_OPT task.

    h_operators accepts three operator formats (as in the SDK):
      Fermionic:    ((site, bool), ...)
      Qubit tuple:  ((qubit, 'X'|'Y'|'Z'), ...)
      Qubit string: "X0 Y1 Z3"

    Store the raw SDK value here; use SparsePauliObservable.from_cebule_operators()
    on the TNQCOptResult output for a typed representation.

    opt_method defaults to "COBYLA" — corrected 2026-07-09 against the
    current docs.mqs.dk table (an earlier revision of this module had it
    defaulting "BFGS").

    measurement_method / optimization_mode — added 2026-07-09, confirmed
    real in the current docs.mqs.dk table (not present in the revision
    this module was originally written against):

    measurement_method   "pauli" (default, per-Pauli-string expectation
                          values) or "grouped" — QASM_GEN's own
                          basis-state-pair-grouping measurement scheme
                          (see QASMGenInput) used *inside* TN_QC_OPT
                          rather than as a separate task.
    optimization_mode     "both" (default, jointly optimize theta/phi —
                          matches the reference paper's own approach) |
                          "circuit" (freeze theta, plain VQE over phi
                          only) | "network" (freeze phi, classical-only
                          parameter search over theta). A "network" run
                          takes no quantum measurements at all, so it
                          costs nothing against a QPU budget and is the
                          classical-only floor a "both" run should be
                          compared against.

    Fields below verified against cebule-tn_vqe @ dev-kba a760489
    (``src/tn_vqe/parsers.py``, ``functions_main.py``), 2026-08-08:

    tn_ansatz             the four-member rotation family (see TNAnsatz).
                          Supersedes three_para_tn, which the task still
                          accepts and translates; tn_ansatz wins when both
                          are given.
    n_shots               None leaves the shot count to the backend —
                          PennyLane simulators then evaluate analytically,
                          Qiskit backends fall back on their own default.
    opt_options           passed straight to scipy.optimize.minimize's
                          ``options``. NOT routed through
                          parse_input_TNQCOpt like the other fields:
                          task_runner_TNQCOpt reads it separately via
                          ``input_data.get("opt_options")``
                          (functions_main.py:50). For COBYLA, ``rhobeg``
                          (the initial trust radius) materially changes
                          both convergence and the number of
                          cost-function evaluations — i.e. the QPU cost of
                          the run — so leaving it unset should be a
                          recorded choice, not an unexamined one.

    Three defaults were wrong before 2026-08-08 and are corrected here:
    ``backend`` is 'default.qubit' (not "lightning.qubit"), ``conv_tol``
    is 1e-6 (not None), and ``n_layers_circuit``'s real default is
    conditional — 3 if ``qasm_ansatz`` is None, else 1 — which pydantic
    cannot express as a field default. The field keeps the unconditional
    3; use ``resolved_n_layers_circuit`` for the value the task will
    really use.
    """
    task_type:           CebuleTaskType  = CebuleTaskType.TN_QC_OPT
    h_coeff_values:      list[float]
    h_operators:         list[Any]
    n_iterations:        int | None     = None
    n_layers_network:    int
    qasm_ansatz:         str | None     = None
    n_layers_circuit:    int            = 3       # conditional upstream — see docstring
    tn_ansatz:           TNAnsatz       = TNAnsatz.ROTATION_3PARAM
    three_para_tn:       bool | None    = None    # DEPRECATED: use tn_ansatz
    # theta_init is (n_layers, n_nodes) for one-parameter families and
    # (n_layers, n_nodes, n_params) otherwise -- see tn_theta_shape().
    # list[float] was wrong for three of the four families.
    theta_init:          list[Any]      = []
    # phi_init: None is upstream's "unset" sentinel -- it randomises
    # (2*pi*random, run_TNQCOpt) only when phi_init is None. [] is NOT
    # that sentinel: an empty list reaches the shape check as a length-0
    # array against a phi_shape of (3n(R+1),), which is neither the
    # documented random init nor a valid one. So the default has to be
    # None, with a pinned vector passed explicitly when a run wants one.
    phi_init:            list[float] | None = None
    conv_tol:            float | None   = 1e-6
    opt_method:          str            = "COBYLA"
    n_shots:             int | None     = None
    opt_options:         dict[str, Any] | None = None
    # get_backend dispatches on the string itself (functions_main.py,
    # cebule-tn_vqe @ dev-kba a760489): the four named simulators
    # ('qasm_simulator', 'statevector_simulator', 'unitary_simulator',
    # 'aer_simulator'), anything prefixed 'fake', and anything prefixed
    # 'ibm' route to Qiskit; EVERYTHING ELSE falls through to
    # qml.device(backend_str), i.e. PennyLane. "qiskit.aer" matches none
    # of the Qiskit branches, so it selects the PennyLane path -- use
    # 'aer_simulator' for a local Aer run and 'ibm*' for hardware.
    backend:             str            = "default.qubit"    # or "aer_simulator", "ibm_brisbane"
    measurement_method:  str            = "pauli"                # "pauli" | "grouped"
    optimization_mode:   str            = "both"                    # "circuit" | "network" | "both"

    @property
    def resolved_n_layers_circuit(self) -> int:
        """``n_layers_circuit`` as the task will really default it.

        A read-only view rather than a validator: rewriting a caller's
        explicit value silently is worse than the mismatch it would hide.
        Only meaningful when the caller left the field at its default.
        """
        if self.qasm_ansatz is not None and self.n_layers_circuit == 3:
            return 1
        return self.n_layers_circuit

    @property
    def resolved_tn_ansatz(self) -> TNAnsatz:
        """``tn_ansatz``, falling back to the deprecated ``three_para_tn``.

        Mirrors ``parsers.py``: True -> rotation_3param, False ->
        rotation_1param, with ``tn_ansatz`` winning when both are given.
        """
        if self.three_para_tn is None:
            return self.tn_ansatz
        if "tn_ansatz" in self.model_fields_set:
            return self.tn_ansatz
        return TNAnsatz.ROTATION_3PARAM if self.three_para_tn else TNAnsatz.ROTATION_1PARAM


class TNQCOptResult(pydantic.BaseModel):
    """Output of the Cebule TN_QC_OPT task.

    Restructured 2026-08-08 against the real return statement —
    ``task_runner_TNQCOpt``, cebule-tn_vqe @ dev-kba a760489,
    ``functions_main.py:59-71`` — which settles the open question this
    docstring used to carry. There is no separate ``qubit_operators``
    key: ``H_TN_opt_qubit`` is one 2-tuple of (labels, coefficients), and
    the docs page's ``zip(*H_TN_opt_qubit)`` idiom was right. That field
    is gone rather than deprecated, per AGENTS.md's mirror exception: the
    API never emitted it.

    h_tn_opt_qubit      (labels, coefficients), labels as space-separated
                        PauliLabel+index tokens ("X0 Y1 Z3")
    h_tn_opt_fermionic  the same operator's reverse Jordan-Wigner, labels
                        in OpenFermion FermionOperator form. A real task
                        output, so the OpenFermion post-processing snippet
                        in the Cebule docs is no longer needed to get it.

    metadata is ABSENT when optimization_mode="network":
    ``optimize_network``'s callback dict (``vqe_optimization.py:359-363``)
    carries only function_calls, cost_history and param_history, because
    that mode makes no quantum measurements. The ``| None`` already
    tolerates it; this is the reason.

    function_calls / cost_history / param_history / metadata /
    optimize_result all arrive merged in from the optimizer callback
    dict, and stay optional since it's unconfirmed whether older API
    versions populate them.
    """
    vqe_energy:      float
    phi:             list[Any]     # optimised circuit parameters U(φ)
    theta:           list[Any]     # optimised TN parameters U(θ), nested — see tn_theta_shape
    h_tn_opt_qubit:  tuple[list[str], list[float]]           # (labels, coefficients)
    h_tn_opt_fermionic: tuple[list[str], list[float]] | None = None
    function_calls:  int | None            = None   # number of cost-function evaluations
    cost_history:    list[float]           = []      # energy value per function evaluation
    param_history:   list[list[Any]]       = []      # theta+phi history per evaluation
    metadata:        dict[str, Any] | list[Any] | None = None   # backend-specific; absent in "network" mode
    optimize_result: dict[str, Any] | None = None   # full scipy.optimize.minimize OptimizeResult, as returned by the API ("OptimizeResult" in the docs)

    @property
    def qubit_operator_labels(self) -> list[str]:
        """Pauli labels alone, for callers that want the two lists apart."""
        return self.h_tn_opt_qubit[0]

    @property
    def qubit_operator_coefficients(self) -> list[float]:
        """Coefficients alone, parallel to ``qubit_operator_labels``."""
        return self.h_tn_opt_qubit[1]

    @classmethod
    def from_task_result(cls, payload: dict[str, Any]) -> TNQCOptResult:
        """Build from a raw TN_QC_OPT job response.

        The task returns its own key spelling (``VQE_energy``,
        ``H_TN_opt_qubit``, ``OptimizeResult``), which matches neither
        this model's snake_case fields nor any single convention. Doing
        that mapping here keeps every caller from re-deriving it, and
        keeps the "metadata is missing in network mode" case in one
        place rather than in each of them.
        """
        key_map = {
            "VQE_energy": "vqe_energy",
            "H_TN_opt_qubit": "h_tn_opt_qubit",
            "H_TN_opt_fermionic": "h_tn_opt_fermionic",
            "OptimizeResult": "optimize_result",
        }
        renamed = {key_map.get(key, key): value for key, value in payload.items()}
        known = {key: value for key, value in renamed.items() if key in cls.model_fields}
        return cls.model_validate(known)

    def to_sparse_pauli_observable(self, num_qubits: int) -> SparsePauliObservable:
        labels, coefficients = self.h_tn_opt_qubit
        return SparsePauliObservable.from_cebule_operators(
            labels, coefficients, num_qubits
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


# ---------------------------------------------------------------------------
# RXN_OPT / catalyst design — real per docs.mqs.dk's "RN Catalyst Design"
# section, but NOT found anywhere in the public python-sdk repo (checked
# 2026-07-10 against every file in gitlab.com/mqsdk/python-sdk's tree — see
# CebuleTaskType's docstring). Likely a newer/enterprise API surface not yet
# reflected in the public SDK snapshot, same situation MOL_MAP/QASM_GEN were
# in before the SDK added them for real.
# ---------------------------------------------------------------------------

class CRNReaction(pydantic.BaseModel):
    """One reaction in a chemical reaction network (CRN), RXN_OPT's own
    `reaction_list` shape.

    fixed_cost   cost incurred if this reaction runs at all (any x_r > 0)
    unit_cost    cost per unit of reaction extent x_r
    low, high    bounds on the reaction extent x_r
    """
    name:       str
    fixed_cost: float
    unit_cost:  float
    low:        float
    high:       float


class CRNSpecies(pydantic.BaseModel):
    """One species in a chemical reaction network, RXN_OPT's own
    `species_list` shape.

    stoich   reaction name -> signed stoichiometric coefficient (negative
             for a reactant consumed, positive for a product formed) —
             RXN_OPT's own mass-balance constraint is
             sum(stoich[r] * x_r for r in reactions) == 0 for each species.
    """
    name:   str
    stoich: dict[str, float]


class RXNOptInput(CebuleTaskEnvelope):
    """Input for the (unconfirmed, see module section header) Cebule
    RXN_OPT task: constrained reaction-network flux optimisation —
    minimize sum(unit_cost*x_r + fixed_cost*[x_r > 0]) subject to mass
    balance (sum(stoich * x) == 0 per species) and low <= x_r <= high.

    time_limit       maximum solver time, seconds
    """
    task_type:     CebuleTaskType = CebuleTaskType.RXN_OPT
    reaction_list: list[CRNReaction]
    species_list:  list[CRNSpecies]
    time_limit:    int


class RXNOptResult(pydantic.BaseModel):
    """Output of the Cebule RXN_OPT task.

    reaction_quantities  reaction name -> optimal extent x_r
    total_cost           minimum total cost achieved
    solve_time           wall-clock solver time, seconds
    optimal              whether the solver certified a global optimum
                         (vs. a time-limited best-effort solution)
    """
    reaction_quantities: dict[str, float]
    total_cost:          float
    solve_time:          float
    optimal:             bool


class GasSpeciesEnergyInput(CebuleTaskEnvelope):
    """Input for the (unconfirmed) Cebule GAS_SPECIES_ENERGY task:
    reference energies for gas-phase molecules in a reaction network."""
    task_type:         CebuleTaskType = CebuleTaskType.GAS_SPECIES_ENERGY
    energy_calculator: str
    optimizer_type:    str
    unitcell_length:   float
    temperature:       float
    pressure:          float
    dataset_tag:       str


class GasSpeciesEnergyResult(pydantic.BaseModel):
    """Output of the Cebule GAS_SPECIES_ENERGY task: molecule name -> energy (eV)."""
    energies_ev: dict[str, float]


class SurfaceReactionEnergiesInput(CebuleTaskEnvelope):
    """Input for the (unconfirmed) Cebule SURFACE_REACTION_ENERGIES task:
    adsorption/reaction energies for all catalyst surfaces in a dataset."""
    task_type:     CebuleTaskType = CebuleTaskType.SURFACE_REACTION_ENERGIES
    reaction_type: str
    temperature:   float
    pressure:      float
    dataset_tag:   str
    uncertainty:   bool | None = None


class SurfaceReactionEnergiesResult(pydantic.BaseModel):
    """Output of the Cebule SURFACE_REACTION_ENERGIES task:
    surface name -> reaction name -> reaction energy delta (eV)."""
    energies_ev: dict[str, dict[str, float]]


class GeneratedCatalyst(pydantic.BaseModel):
    """One catalyst composition generated by the Cebule GAN_TOF task."""
    chemical_formula: str
    atomic_numbers:   list[int]
    run:              int


class GANTOFInput(CebuleTaskEnvelope):
    """Input for the (unconfirmed) Cebule GAN_TOF task: trains a GAN to
    discover high-turnover-frequency catalyst compositions.

    nclass                number of composition classes to generate
    score_max, score_min  optional target-score bounds for generated
                          candidates
    """
    task_type:   CebuleTaskType = CebuleTaskType.GAN_TOF
    reaction_type: str
    dataset_tag: str
    epochs:      int
    nclass:      int
    score_max:   float | None = None
    score_min:   float | None = None


class GANTOFResult(pydantic.BaseModel):
    """Output of the Cebule GAN_TOF task.

    catalysts      generated catalyst compositions
    loss_history   training loss per epoch
    """
    catalysts:    list[GeneratedCatalyst]
    loss_history: list[float] = []


class MakeSurfInput(CebuleTaskEnvelope):
    """Input for the (unconfirmed) Cebule MAKE_SURF task: generates a
    bimetallic alloy surface dataset with randomized atomic compositions.

    element1, element2   the two metals in the bimetallic alloy
    n_surfaces           number of randomized surface configurations to generate
    lattice_const        lattice constant, Angstrom
    vacuum               vacuum spacing above the slab, Angstrom
    supercell             (nx, ny, nz) supercell repetition
    """
    task_type:     CebuleTaskType = CebuleTaskType.MAKE_SURF
    element1:      str
    element2:      str
    surface_type:  str
    n_surfaces:    int
    lattice_const: float
    vacuum:        float | None = None
    supercell:     tuple[int, int, int] | None = None


class MakeSurfResult(pydantic.BaseModel):
    """Output of the Cebule MAKE_SURF task: the resolved surface configuration."""
    lattice_const: float
    surface_type:  str
    n_layers:      int | None = None


class WulffFacet(pydantic.BaseModel):
    """One facet of a Wulff-construction equilibrium crystal shape.

    miller_indices          (h, k, l)
    surface_energy_ev_per_a2  surface energy density, eV/Angstrom^2
    area_fraction            fraction of total surface area this facet occupies
    tof                     turnover frequency for this facet, if computed
    activation_barrier_ev    reaction activation barrier on this facet, if computed
    """
    miller_indices:         tuple[int, int, int]
    surface_energy_ev_per_a2: float
    area_fraction:           float
    tof:                     float | None = None
    activation_barrier_ev:    float | None = None


class WulffConstructionInput(CebuleTaskEnvelope):
    """Input for the (unconfirmed) Cebule WULFF_CONSTRUCTION task:
    determines the thermodynamically stable crystal shape via Wulff
    geometry. Field-level detail beyond `dataset_tag` wasn't confirmed
    against any source — see module section header."""
    task_type:   CebuleTaskType = CebuleTaskType.WULFF_CONSTRUCTION
    dataset_tag: str | None = None


class WulffConstructionResult(pydantic.BaseModel):
    """Output of the Cebule WULFF_CONSTRUCTION task: one entry per stable facet."""
    facets: list[WulffFacet]


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
    "TNAnsatz",
    "TNAnsatzProperties",
    "TN_ANSATZ_PROPERTIES",
    "TNQCOptInput",
    "TNQCOptResult",
    "tn_node_count",
    "tn_theta_parameter_count",
    "tn_theta_shape",
    "CRNReaction",
    "CRNSpecies",
    "RXNOptInput",
    "RXNOptResult",
    "GasSpeciesEnergyInput",
    "GasSpeciesEnergyResult",
    "SurfaceReactionEnergiesInput",
    "SurfaceReactionEnergiesResult",
    "GeneratedCatalyst",
    "GANTOFInput",
    "GANTOFResult",
    "MakeSurfInput",
    "MakeSurfResult",
    "WulffFacet",
    "WulffConstructionInput",
    "WulffConstructionResult",
]
