"""quantum-fragment-methods — fragment-based embedding with quantum solvers.

Upstream: https://github.com/qiskit-community/quantum-fragment-methods
(Apache-2.0), an IBM Quantum × Cleveland Clinic collaboration implementing
Shajan et al., *Molecular Quantum Computations on a Protein*
(arXiv:2512.17130, 2025).

Why this one matters for distributed quantum computing
------------------------------------------------------
It is the piece that actually connects fragmentation to a QPU.  A protein is
partitioned into fragments; each fragment gets a solver by *rule-based
assignment* on priority order — quantum (SQD, ext-SQD) where the fragment fits
the hardware, classical (FCI, CCSD) everywhere else — and the fragment
energies are recombined.  The per-fragment quantum subproblems are independent,
so they are the natural unit of distribution across QPUs, and each one's
circuit can itself be partitioned or cut (see ``distributed_execution``).

Configuration is YAML-driven
----------------------------
The upstream entry point is a ``config.yaml`` with ``workflow`` / ``embedder``
/ ``qpu`` / ``sqd`` / ``ext_sqd`` blocks.  ``QFMWorkflowConfig`` mirrors it
field-for-field, so::

    QFMWorkflowConfig.from_config_dict(yaml.safe_load(text))

round-trips a real config file.

Credentials are deliberately absent
-----------------------------------
The upstream ``qpu.credentials`` block holds an API token and a CRN instance
id.  ``QFMQPUConfig`` mirrors ``channel`` and ``instance`` (they identify
*which* service was used, which a benchmark record should state) but has **no
token field** — a benchmark record is meant to be stored and shared, and
``from_config_dict`` drops the token rather than carrying it into a record.
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic

from ..catalogs.fragmentation import (
    FragmentationResult,
    FragmentationScheme,
    FragmentationSpec,
    FragmenterType,
    FragmentResult,
    FragmentScreeningRule,
    FragmentSolverAssignment,
    FragmentSpec,
    ScreeningMetric,
    SolverKind,
)
from ..primitives import JobStatus

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class QFMBathType(str, enum.Enum):
    """Bath-orbital construction for the embedded wavefunction (EWF)."""
    MP2  = "mp2"     # MP2 natural-orbital bath, truncated by occupancy
    DMET = "dmet"    # DMET bath (exact for the mean-field 1-RDM)
    FULL = "full"    # no truncation — full environment


class QFMFragmentationScheme(str, enum.Enum):
    """How the orbital space is fragmented before embedding."""
    IAO    = "iao"       # intrinsic atomic orbitals
    ATOMIC = "atomic"    # atom-projected orbitals


class QFMSolverName(str, enum.Enum):
    """Solvers in the quantum and classical zoos."""
    SQD     = "sqd"        # sample-based quantum diagonalization
    EXT_SQD = "ext_sqd"    # extended SQD (planned upstream)
    FCI     = "fci"
    CCSD    = "ccsd"

    @property
    def kind(self) -> SolverKind:
        return (
            SolverKind.QUANTUM
            if self in (QFMSolverName.SQD, QFMSolverName.EXT_SQD)
            else SolverKind.CLASSICAL
        )


# ---------------------------------------------------------------------------
# Configuration blocks (config.yaml)
# ---------------------------------------------------------------------------

class QFMEWFConfig(pydantic.BaseModel):
    """The ``embedder.ewf`` block.

    ``truncation`` is the bath-occupancy cutoff — the single knob that trades
    fragment size (and therefore qubit count) against accuracy, which makes it
    the adaptive control for this method.
    """
    bath_type:     QFMBathType             = QFMBathType.MP2
    truncation:    float                   = 1e-5
    fragmentation: QFMFragmentationScheme  = QFMFragmentationScheme.IAO
    bath_options:  dict[str, Any]          = {}
    solver_options: dict[str, Any]         = {}

    def to_screening_rule(self) -> FragmentScreeningRule:
        """Express the bath truncation as a framework-general screening rule."""
        return FragmentScreeningRule(
            name="bath_truncation",
            metric=ScreeningMetric.BATH_OCCUPANCY,
            cutoff=self.truncation,
            options={"bath_type": self.bath_type.value},
        )


class QFMLUCJConfig(pydantic.BaseModel):
    """The ``sqd.lucj`` block — LUCJ ansatz shape.

    ``connect_every_n`` exists because alpha-beta interactions are expensive
    to route on heavy-hex hardware; it thins them to every Nth qubit pair.
    """
    n_reps:          int = 1
    max_connection:  int = 12    # highest orbital index allowed an alpha-beta connection
    connect_every_n: int = 4     # connect alpha-beta pairs every N qubits


class QFMTranspilationConfig(pydantic.BaseModel):
    """The ``sqd.transpilation`` block."""
    optimization_level: int        = 0
    seed_transpiler:    int | None = None


class QFMSBDConfig(pydantic.BaseModel):
    """The ``sqd.sbd`` block — the external sample-based diagonalization binary."""
    exe_path:         str | None = None
    cpus_per_batch:   int        = 8
    submission_delay: float | None = None    # HPC batch submission spacing
    monitor_delay:    float | None = None    # HPC status-poll interval


class QFMSQDConfig(pydantic.BaseModel):
    """The ``sqd`` block — sample-based quantum diagonalization parameters.

    SQD samples bitstrings from the QPU, builds a configuration subspace from
    them and diagonalizes the Hamiltonian in it, iterating self-consistently.
    ``n_batches`` × ``samples_per_batch`` sets the subspace size and
    ``iterations`` the number of self-consistent passes.
    """
    symmetrize_spin:     bool  = True     # identical alpha/beta strings (only mode supported)
    n_batches:           int   = 1
    iterations:          int   = 5
    samples_per_batch:   int   = 1000
    energy_tol:          float = 1e-8
    occupancies_tol:     float = 1e-5
    carryover_threshold: float = 1e-4     # configurations carried between iterations
    add_hf_string:       bool  = True     # seed every subspace with the HF determinant
    lucj:                QFMLUCJConfig          = pydantic.Field(default_factory=QFMLUCJConfig)
    transpilation:       QFMTranspilationConfig = pydantic.Field(
        default_factory=QFMTranspilationConfig
    )
    sbd:                 QFMSBDConfig           = pydantic.Field(default_factory=QFMSBDConfig)

    @property
    def total_samples(self) -> int:
        """Configurations drawn per self-consistent iteration."""
        return self.n_batches * self.samples_per_batch


class QFMExtSQDConfig(pydantic.BaseModel):
    """The ``ext_sqd`` block.

    ``dprime_cutoff`` selects the dominant configurations kept from the SQD
    wavefunction: lower keeps more (more accurate, more expensive).
    """
    dprime_cutoff: float = 1e-5


class QFMSamplerOptions(pydantic.BaseModel):
    """The ``qpu.sampler_options`` block — Qiskit Runtime SamplerV2 options."""
    default_shots:            int  = 20000
    dd_enable:                bool = False
    dd_sequence_type:         str | None = None    # "XY4" | "XpXm" | "XY4pm"
    twirling_enable_gates:    bool = False
    twirling_enable_measure:  bool = False


class QFMQPUConfig(pydantic.BaseModel):
    """The ``qpu`` block, minus credentials.

    ``channel`` and ``instance`` identify the service the run went through and
    are safe to store; the API token from the upstream ``credentials`` block
    is intentionally not represented here.
    """
    provider:        str = "ibm_quantum"
    backend_name:    str | None = None
    channel:         str | None = None      # "ibm_cloud" | "ibm_quantum"
    instance:        str | None = None      # CRN of the service instance
    sampler_options: QFMSamplerOptions = pydantic.Field(default_factory=QFMSamplerOptions)


class QFMWorkflowConfig(pydantic.BaseModel):
    """A complete quantum-fragment-methods ``config.yaml``."""
    basis:    str
    ewf:      QFMEWFConfig      = pydantic.Field(default_factory=QFMEWFConfig)
    qpu:      QFMQPUConfig | None    = None
    sqd:      QFMSQDConfig | None    = None
    ext_sqd:  QFMExtSQDConfig | None = None
    geometry_file: str | None   = None
    charge:   int               = 0
    multiplicity: int           = 1

    @classmethod
    def from_config_dict(cls, config: dict[str, Any]) -> QFMWorkflowConfig:
        """Parse a loaded ``config.yaml``, dropping any credentials.

        Accepts the upstream nesting (``workflow.basis``, ``embedder.ewf``,
        ``qpu.credentials``, …).  The ``token`` under ``qpu.credentials`` is
        never read, so a config file can be passed in verbatim without leaking
        a secret into the resulting record.
        """
        workflow = config.get("workflow", {}) or {}
        embedder = config.get("embedder", {}) or {}
        qpu_block = config.get("qpu", {}) or {}
        credentials = qpu_block.get("credentials", {}) or {}
        sampler = qpu_block.get("sampler_options", {}) or {}
        dd = sampler.get("dynamical_decoupling", {}) or {}
        twirling = sampler.get("twirling", {}) or {}

        qpu = None
        if qpu_block:
            qpu = QFMQPUConfig(
                provider=qpu_block.get("provider", "ibm_quantum"),
                backend_name=qpu_block.get("backend_name"),
                channel=credentials.get("channel"),
                instance=credentials.get("instance"),
                sampler_options=QFMSamplerOptions(
                    default_shots=sampler.get("default_shots", 20000),
                    dd_enable=dd.get("enable", False),
                    dd_sequence_type=dd.get("sequence_type"),
                    twirling_enable_gates=twirling.get("enable_gates", False),
                    twirling_enable_measure=twirling.get("enable_measure", False),
                ),
            )

        sqd_block = config.get("sqd")
        sqd = None
        if sqd_block:
            sqd = QFMSQDConfig(
                **{
                    k: v
                    for k, v in sqd_block.items()
                    if k not in ("lucj", "transpilation", "sbd")
                },
                lucj=QFMLUCJConfig(**(sqd_block.get("lucj") or {})),
                transpilation=QFMTranspilationConfig(**(sqd_block.get("transpilation") or {})),
                sbd=QFMSBDConfig(**(sqd_block.get("sbd") or {})),
            )

        ext_block = config.get("ext_sqd")
        return cls(
            basis=workflow.get("basis", "sto-3g"),
            ewf=QFMEWFConfig(**(embedder.get("ewf") or {})),
            qpu=qpu,
            sqd=sqd,
            ext_sqd=QFMExtSQDConfig(**ext_block) if ext_block else None,
        )

    def to_fragmentation_spec(self, name: str = "qfm") -> FragmentationSpec:
        """Convert to the framework-general spec.

        Encodes the upstream solver priority as ``FragmentSolverAssignment``
        rules: SQD first, with a classical CCSD fallback that matches
        everything.  Adjust ``max_qubits`` on the SQD rule to the QPU you are
        actually targeting — the config file does not state it.
        """
        rules = [
            FragmentSolverAssignment(
                solver_name=QFMSolverName.SQD.value,
                solver_kind=SolverKind.QUANTUM,
                priority=10,
                condition="fragment fits the target QPU",
                backend_name=self.qpu.backend_name if self.qpu else None,
                options={"shots": self.qpu.sampler_options.default_shots} if self.qpu else {},
            ),
            FragmentSolverAssignment(
                solver_name=QFMSolverName.CCSD.value,
                solver_kind=SolverKind.CLASSICAL,
                priority=0,
                condition="default fallback",
            ),
        ]
        if self.ext_sqd is not None:
            rules.insert(
                0,
                FragmentSolverAssignment(
                    solver_name=QFMSolverName.EXT_SQD.value,
                    solver_kind=SolverKind.QUANTUM,
                    priority=20,
                    condition=f"dprime_cutoff={self.ext_sqd.dprime_cutoff}",
                ),
            )
        return FragmentationSpec(
            name=name,
            scheme=FragmentationScheme.EWF,
            fragmenter=(
                FragmenterType.ORBITAL
                if self.ewf.fragmentation == QFMFragmentationScheme.IAO
                else FragmenterType.ATOMIC
            ),
            max_order=1,           # embedding, not an n-body expansion
            basis=self.basis,
            charge=self.charge,
            multiplicity=self.multiplicity,
            supersystem_label=self.geometry_file,
            screening=[self.ewf.to_screening_rule()],
            solver_rules=rules,
            metadata={
                "source": "qiskit-community/quantum-fragment-methods",
                "bath_type": self.ewf.bath_type.value,
            },
        )


# ---------------------------------------------------------------------------
# Fragments and results
# ---------------------------------------------------------------------------

class QFMFragment(pydantic.BaseModel):
    """Mirrors ``application/embedding/base.py::Fragment``.

    ``n_electrons`` is upstream either an int or an ``(alpha, beta)`` tuple;
    both are accepted here and normalised into ``n_electrons`` plus the
    optional spin split.
    """
    fragment_id:     int | str
    atom_indices:    list[int]      = []
    orbital_indices: list[int]      = []
    n_electrons:     int | None     = None
    n_alpha:         int | None     = None
    n_beta:          int | None     = None
    n_bath:          int | None     = None
    metadata:        dict[str, Any] = {}

    @property
    def n_orbitals(self) -> int:
        return len(self.orbital_indices)

    @property
    def estimated_qubits(self) -> int:
        """Jordan-Wigner qubit count: two spin orbitals per spatial orbital."""
        return 2 * self.n_orbitals

    @classmethod
    def from_fragment(cls, fragment: Any) -> QFMFragment:
        """Build from an upstream ``Fragment`` object (duck-typed, no import)."""
        raw: Any = getattr(fragment, "n_electrons", None)
        alpha: int | None = None
        beta: int | None = None
        n_elec: int | None = None
        if isinstance(raw, (tuple, list)) and len(raw) == 2:
            alpha, beta = int(raw[0]), int(raw[1])
            n_elec = alpha + beta
        elif raw is not None:
            n_elec = int(raw)
        return cls(
            fragment_id=fragment.fragment_id,
            atom_indices=list(getattr(fragment, "atom_indices", []) or []),
            orbital_indices=list(getattr(fragment, "orbital_indices", []) or []),
            n_electrons=n_elec,
            n_alpha=alpha,
            n_beta=beta,
            metadata=dict(getattr(fragment, "metadata", {}) or {}),
        )

    def to_fragment_spec(self) -> FragmentSpec:
        return FragmentSpec(
            fragment_id=str(self.fragment_id),
            atom_indices=self.atom_indices,
            orbital_indices=self.orbital_indices,
            n_orbitals=self.n_orbitals,
            n_bath=self.n_bath,
            n_electrons=self.n_electrons,
            n_alpha=self.n_alpha,
            n_beta=self.n_beta,
            num_qubits=self.estimated_qubits or None,
            metadata=self.metadata,
        )


class QFMSolverResult(pydantic.BaseModel):
    """Mirrors ``application/solvers/base.py::SolverResult``.

    The upstream object also carries ``wavefunction``, ``rdm1`` and ``rdm2``
    as NumPy arrays.  Those are not stored here — a benchmark record must stay
    JSON-serialisable, and RDMs for a protein-scale run are far too large.
    ``has_rdm1`` / ``has_rdm2`` record whether they were produced.
    """
    fragment_id:  int | str
    solver:       QFMSolverName
    energy:       float
    converged:    bool           = True
    status:       JobStatus      = JobStatus.SUCCEEDED
    n_orbitals:   int | None     = None
    n_electrons:  int | None     = None
    num_qubits:   int | None     = None
    shots:        int | None     = None
    backend_name: str | None     = None
    wall_seconds: float | None   = None
    has_rdm1:     bool           = False
    has_rdm2:     bool           = False
    record_id:    str | None     = None    # -> BenchmarkRecord.experiment_id
    metadata:     dict[str, Any] = {}

    def to_fragment_result(self, coefficient: float = 1.0) -> FragmentResult:
        return FragmentResult(
            fragment_id=str(self.fragment_id),
            solver_name=self.solver.value,
            solver_kind=self.solver.kind,
            coefficient=coefficient,
            energy=self.energy,
            converged=self.converged,
            status=self.status,
            num_qubits=self.num_qubits,
            num_shots=self.shots,
            wall_seconds=self.wall_seconds,
            backend_name=self.backend_name,
            record_id=self.record_id,
            metadata=self.metadata,
        )


class QFMWorkflowResult(pydantic.BaseModel):
    """Mirrors ``workflow.py::WorkflowResult`` — the reconstructed total."""
    total_energy:      float
    mf_energy:         float | None          = None
    reference_energy:  float | None          = None   # exact / CCSD(T) supersystem
    embedder:          str                   = "EWF"
    basis:             str | None            = None
    fragments:         list[QFMFragment]     = []
    fragment_results:  list[QFMSolverResult] = []
    wall_seconds:      float | None          = None
    status:            JobStatus             = JobStatus.SUCCEEDED

    @property
    def fragment_energies(self) -> dict[str, float]:
        return {str(r.fragment_id): r.energy for r in self.fragment_results}

    @property
    def num_quantum_fragments(self) -> int:
        return sum(1 for r in self.fragment_results if r.solver.kind == SolverKind.QUANTUM)

    def to_fragmentation_result(self) -> FragmentationResult:
        """Bridge to the framework-general result.

        Embedding reconstructs by summing per-fragment contributions with unit
        weight (there is no inclusion-exclusion coefficient), so every term
        enters with coefficient 1.0.
        """
        return FragmentationResult(
            spec_name=self.embedder,
            scheme=FragmentationScheme.EWF,
            total_energy=self.total_energy,
            mean_field_energy=self.mf_energy,
            reference_energy=self.reference_energy,
            fragment_results=[r.to_fragment_result() for r in self.fragment_results],
            n_terms_evaluated=len(self.fragment_results),
            wall_seconds=self.wall_seconds,
            status=self.status,
            metadata={
                "source": "qiskit-community/quantum-fragment-methods",
                "embedder": self.embedder,
                "basis": self.basis,
            },
        )


__all__ = [
    "QFMBathType",
    "QFMEWFConfig",
    "QFMExtSQDConfig",
    "QFMFragment",
    "QFMFragmentationScheme",
    "QFMLUCJConfig",
    "QFMQPUConfig",
    "QFMSBDConfig",
    "QFMSQDConfig",
    "QFMSamplerOptions",
    "QFMSolverName",
    "QFMSolverResult",
    "QFMTranspilationConfig",
    "QFMWorkflowConfig",
    "QFMWorkflowResult",
]
