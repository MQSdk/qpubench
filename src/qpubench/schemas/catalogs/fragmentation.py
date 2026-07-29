"""Molecular fragmentation and fragment-based embedding — the general schema.

Cross-cutting module: it is the *union* of the fragmentation vocabularies used
by several external projects, not a mirror of any single one.  The upstream
specifics live in the project mirrors, each of which bridges into the types
defined here:

    fragmentqc_fragment              Fragme∩t (Herbert group, GitLab
                                     fragment-qc/fragment) — MBE / GMBE via
                                     principle-of-inclusion-exclusion trees,
                                     multilevel layers, adaptive screening mods
    qiskitcommunity_fragment_methods quantum-fragment-methods (IBM Quantum +
                                     Cleveland Clinic) — EWF / DMET / MBE
                                     embedding with per-fragment quantum
                                     (SQD, ext-SQD) or classical (FCI, CCSD)
                                     solvers

The abstraction they share
--------------------------
*Every* fragmentation method — MBE, GMBE, DMET, EWF, ONIOM — reduces one
intractable supersystem to:

1. a set of **fragments** (subsystems in real space or orbital space),
2. an **expansion**: a list of ``(fragment, signed coefficient)`` terms whose
   weighted sum reconstructs a supersystem property,
3. a **solver assignment** per fragment (classical or quantum), and
4. optionally **screening rules** that drop terms below a threshold — the
   *adaptive* part — and **layers** that solve different orders at different
   levels of theory — the *multilevel* part.

``FragmentExpansionTerm`` is deliberately the most general form: an arbitrary
real coefficient on an arbitrary fragment.  A plain 2-body MBE, a generalized
MBE over overlapping fragments, and an ONIOM-style subtractive scheme are all
expressible without a method-specific schema.  For a complete expansion the
coefficients sum to 1 (see ``FragmentationSpec.is_complete``).

Distributed execution
---------------------
Fragmentation decomposes the *problem*; ``distributed_execution`` decomposes
the *circuit* that solves each fragment.  They compose: a ``FragmentResult``
carries ``record_id``, linking it to the ``BenchmarkRecord`` of the run that
produced it — which may itself have been partitioned or cut across QPUs.

Attaching to a record
---------------------
    from qpubench.schemas.fragmentation import FragmentationSpec

    spec   = CircuitSpec(..., fragmentation=frag_spec)   # model or dict
    result = QuantumResult(..., vendor_results={"fragmentation_result": frag_res})

    frag_spec = FragmentationSpec.model_validate(spec.fragmentation)
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic

from ..primitives import ComputingModel, JobStatus
from ..result import ExpectationResult, QuantumResult

CHEMICAL_ACCURACY_HARTREE = 1.6e-3


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class FragmentationScheme(str, enum.Enum):
    """How fragment energies are combined into a supersystem property.

    MBE / GMBE / BOTTOM_UP / TOP_DOWN come from Fragme∩t's combinators;
    DMET / EWF / IAO / ATOMIC from the embedding literature (Vayesta,
    quantum-fragment-methods); ONIOM is the classic subtractive multilevel
    scheme.  CUSTOM covers anything expressible as a signed expansion.
    """
    MBE            = "mbe"             # many-body expansion over disjoint fragments
    GMBE           = "gmbe"            # generalized MBE (overlapping fragments, PIE)
    BOTTOM_UP      = "bottom_up"       # build n-mers upward from primaries
    TOP_DOWN       = "top_down"        # remove from the supersystem downward
    MBCP           = "mbcp"            # many-body counterpoise
    BSSE_BALANCED  = "bsse_balanced"   # BSSE-balanced fragmentation
    DMET           = "dmet"            # density matrix embedding theory
    EWF            = "ewf"             # embedded wavefunction (bath-orbital)
    IAO            = "iao"             # intrinsic atomic orbital fragmentation
    ATOMIC         = "atomic"          # atom-wise orbital fragmentation
    ONIOM          = "oniom"           # subtractive multilevel embedding
    CUSTOM         = "custom"


class FragmenterType(str, enum.Enum):
    """How the primary fragments are carved out of the supersystem.

    Orthogonal to FragmentationScheme: the fragmenter decides *what* the
    fragments are, the scheme decides *how they are combined*.
    """
    PDB                 = "pdb"                  # residues / chains from a PDB file
    WATER               = "water"                # one molecule per water
    COVALENT_COMPONENTS = "covalent_components"  # connected components of the bond graph
    GROUPS              = "groups"               # user-declared atom groups
    SUPERSYSTEM         = "supersystem"          # single fragment = whole system
    RAW                 = "raw"                  # fragments given verbatim
    COMPOUND            = "compound"             # per-species fragmenter dispatch
    ATOMIC              = "atomic"               # one fragment per atom
    ORBITAL             = "orbital"              # orbital-space (IAO / Löwdin), not spatial
    CUSTOM              = "custom"


class SolverKind(str, enum.Enum):
    """Whether a fragment is solved classically, on a QPU, or by both."""
    CLASSICAL = "classical"
    QUANTUM   = "quantum"
    HYBRID    = "hybrid"


class ScreeningMetric(str, enum.Enum):
    """Quantity an adaptive screening rule thresholds on.

    Screening is what makes a high-order expansion tractable: terms whose
    metric falls outside the threshold are never submitted at all.
    """
    CENTRE_OF_MASS_DISTANCE = "com_distance"
    CLOSEST_ATOM_DISTANCE   = "closest_distance"
    ENERGY_DELTA            = "energy_delta"        # cheap-method n-body energy
    ENERGY_PRODUCT          = "energy_product"      # product of child energies
    BATH_OCCUPANCY          = "bath_occupancy"      # DMET/EWF bath truncation
    AMPLITUDE               = "amplitude"           # CI / CC amplitude cutoff
    CUSTOM                  = "custom"


# ---------------------------------------------------------------------------
# Fragments and expansions
# ---------------------------------------------------------------------------

class FragmentSpec(pydantic.BaseModel):
    """One fragment — a subsystem of the supersystem, in real or orbital space.

    A *primary* fragment has ``order == 1`` and no ``primary_ids``.  An n-mer
    produced by a bottom-up combinator lists the primaries it unions in
    ``primary_ids`` and sets ``order = len(primary_ids)``.

    Real-space vs orbital-space
    ---------------------------
    Spatial fragmenters (PDB, water, covalent components) populate
    ``atom_indices``.  Orbital fragmenters (IAO, atomic, DMET/EWF) populate
    ``orbital_indices``.  Embedding methods populate both plus ``n_bath``.

    num_qubits is the *estimated* qubit count for the quantum solver assigned
    to this fragment — typically ``2 * n_orbitals`` under Jordan-Wigner.  It is
    the number that decides whether a fragment fits on a given QPU, so it is a
    first-class field rather than metadata.
    """
    fragment_id:     str
    label:           str | None       = None    # human-readable ("ALA-12", "frag_3")
    order:           int              = 1       # n-body order; 1 = primary
    primary_ids:     list[str]        = []      # primaries this n-mer unions
    atom_indices:    list[int]        = []      # real-space fragmenters
    orbital_indices: list[int]        = []      # orbital-space fragmenters
    n_orbitals:      int | None       = None
    n_bath:          int | None       = None    # bath orbitals (DMET / EWF)
    n_electrons:     int | None       = None
    n_alpha:         int | None       = None
    n_beta:          int | None       = None
    charge:          int              = 0
    multiplicity:    int              = 1
    basis:           str | None       = None    # per-fragment basis override
    capping:         str | None       = None    # "hydrogen", "rcaps", None
    num_qubits:      int | None       = None    # estimated qubit cost
    metadata:        dict[str, Any]   = {}

    @property
    def num_atoms(self) -> int:
        return len(self.atom_indices)

    @property
    def is_primary(self) -> bool:
        return self.order == 1 and not self.primary_ids


class FragmentExpansionTerm(pydantic.BaseModel):
    """One signed term of a fragmentation expansion.

    This is the general form every scheme reduces to.  A 2-body MBE is
    ``+1`` on each dimer and ``-(n-1)`` on each monomer; a GMBE over
    overlapping fragments has the inclusion-exclusion coefficients of the
    PIE tree; an ONIOM correction layer carries ``-1`` on the low-level terms.

    ``method`` overrides the layer's level of theory for this single term,
    which is how mixed-resolution ("adaptive multilevel") expansions are
    expressed without a separate schema.
    """
    fragment_id: str
    coefficient: float                    # PIE / MBE coefficient; may be fractional
    order:       int | None    = None     # convenience copy of the fragment order
    layer:       int | None    = None     # index into FragmentationSpec.layers
    method:      str | None    = None     # per-term level-of-theory override
    screened:    bool          = False    # dropped by a screening rule, never run


class FragmentScreeningRule(pydantic.BaseModel):
    """An adaptive rule that drops expansion terms before they are submitted.

    ``thresholds`` is keyed by n-body order because screening almost always
    tightens with order (a 3-body term must clear a stricter bar than a
    2-body one).  Mirrors the ``thresholds: {order: value}`` shape used by
    Fragme∩t's energy-screening mods.

    ``backend`` names the *cheap* method used to evaluate the metric (xTB,
    HF/STO-3G, …) — screening is only worthwhile when the estimator is far
    cheaper than the solver it protects.
    """
    name:         str                                # "distance", "energy_trimming", …
    metric:       ScreeningMetric
    thresholds:   dict[int, float]   = {}            # n-body order -> threshold
    cutoff:       float | None       = None          # single global threshold
    min_value:    float | None       = None          # e.g. minimum separation
    max_value:    float | None       = None          # e.g. maximum separation
    backend:      str | None         = None          # cheap estimator ("xtb", "hf")
    applies_to_orders: list[int]     = []            # empty = all orders
    options:      dict[str, Any]     = {}

    def threshold_for(self, order: int) -> float | None:
        """Threshold at this n-body order, falling back to ``cutoff``."""
        if order in self.thresholds:
            return self.thresholds[order]
        return self.cutoff


class FragmentationLayer(pydantic.BaseModel):
    """One level of a multilevel (ONIOM-like) fragmented calculation.

    A multilevel calculation stacks layers: a high-accuracy method on a small
    active fragment set, a cheaper method on a larger one, combined with signs
    so the cheap contribution inside the accurate region cancels.  ``sign``
    carries that cancellation (``-1.0`` for a subtractive layer).

    ``max_order`` truncates the expansion *within this layer*, so a 4-body
    expansion at MP2 can sit under a 2-body expansion at CCSD(T).
    """
    level:        int                                # 0 = outermost / cheapest
    name:         str | None          = None
    scheme:       FragmentationScheme = FragmentationScheme.MBE
    fragmenter:   FragmenterType      = FragmenterType.CUSTOM
    max_order:    int                 = 2
    method:       str                 = "hf"         # "ccsd(t)", "mp2", "b3lyp", "sqd"
    basis:        str | None          = None
    solver_kind:  SolverKind          = SolverKind.CLASSICAL
    sign:         float               = 1.0          # -1.0 for subtractive layers
    screening:    list[FragmentScreeningRule] = []
    options:      dict[str, Any]      = {}


class FragmentSolverAssignment(pydantic.BaseModel):
    """A rule assigning a solver to fragments that match its conditions.

    Mirrors the priority-ordered rule dispatch in quantum-fragment-methods:
    rules are tried highest ``priority`` first and the first match wins, so a
    quantum solver can claim the fragments that fit on the QPU while a
    classical fallback catches the rest.

    ``condition`` is free-text documentation of the predicate; the
    ``max_*`` fields are its machine-checkable form and are what
    ``matches()`` actually evaluates.  A rule with no ``max_*`` set matches
    every fragment (i.e. it is a default solver).
    """
    solver_name:  str                              # "sqd", "ext_sqd", "fci", "ccsd", "vqe"
    solver_kind:  SolverKind = SolverKind.CLASSICAL
    priority:     int        = 0
    condition:    str | None = None                # human-readable predicate
    max_orbitals: int | None = None
    max_electrons: int | None = None
    max_qubits:   int | None = None
    max_order:    int | None = None
    backend_name: str | None = None                # BackendSpec.name to run on
    options:      dict[str, Any] = {}

    def matches(self, fragment: FragmentSpec) -> bool:
        """True if this rule's machine-checkable limits admit ``fragment``.

        Limits compared against an unset fragment field do not reject: a
        fragment with no ``num_qubits`` estimate is not excluded by
        ``max_qubits``.  ``condition`` is never evaluated.
        """
        checks = (
            (self.max_orbitals, fragment.n_orbitals),
            (self.max_electrons, fragment.n_electrons),
            (self.max_qubits, fragment.num_qubits),
            (self.max_order, fragment.order),
        )
        return all(limit is None or value is None or value <= limit for limit, value in checks)


class FragmentationSpec(pydantic.BaseModel):
    """The complete decomposition plan for one supersystem.

    Everything needed to reproduce a fragmented calculation: the fragments,
    the signed expansion over them, the layers, the screening rules and the
    solver-assignment rules.

    Completeness
    ------------
    A valid expansion of the whole supersystem has coefficients summing to 1
    (each atom counted exactly once).  ``coefficient_sum`` and ``is_complete``
    expose that check — a sum below 1 usually means screening dropped terms,
    which is expected for an adaptive run and is why it is reported rather
    than enforced.
    """
    name:              str
    scheme:            FragmentationScheme = FragmentationScheme.MBE
    fragmenter:        FragmenterType      = FragmenterType.CUSTOM
    max_order:         int                 = 2
    basis:             str | None          = None
    charge:            int                 = 0
    multiplicity:      int                 = 1
    supersystem_atoms: int | None          = None
    supersystem_label: str | None          = None   # molecule / PDB identifier
    periodic:          bool                = False
    lattice_vectors:   list[list[float]]   = []     # 3x3 for periodic systems
    fragments:         list[FragmentSpec]  = []
    expansion:         list[FragmentExpansionTerm] = []
    layers:            list[FragmentationLayer]    = []
    screening:         list[FragmentScreeningRule] = []
    solver_rules:      list[FragmentSolverAssignment] = []
    metadata:          dict[str, Any]      = {}

    @property
    def num_fragments(self) -> int:
        return len(self.fragments)

    @property
    def is_multilevel(self) -> bool:
        return len(self.layers) > 1

    @property
    def is_adaptive(self) -> bool:
        """True if any screening rule is attached, at spec or layer level."""
        return bool(self.screening) or any(layer.screening for layer in self.layers)

    @property
    def active_terms(self) -> list[FragmentExpansionTerm]:
        """Expansion terms that survived screening."""
        return [t for t in self.expansion if not t.screened]

    @property
    def coefficient_sum(self) -> float:
        """Sum of surviving coefficients — 1.0 for a complete expansion."""
        return sum(t.coefficient for t in self.active_terms)

    def is_complete(self, tol: float = 1e-9) -> bool:
        """True if the surviving expansion covers the supersystem exactly."""
        return abs(self.coefficient_sum - 1.0) <= tol

    def fragment(self, fragment_id: str) -> FragmentSpec | None:
        for f in self.fragments:
            if f.fragment_id == fragment_id:
                return f
        return None

    def terms_by_order(self) -> dict[int, int]:
        """Count of surviving expansion terms per n-body order."""
        counts: dict[int, int] = {}
        for t in self.active_terms:
            order = t.order
            if order is None:
                frag = self.fragment(t.fragment_id)
                order = frag.order if frag is not None else 0
            counts[order] = counts.get(order, 0) + 1
        return counts

    def assign_solver(self, fragment: FragmentSpec) -> FragmentSolverAssignment | None:
        """First matching solver rule by descending priority, or None."""
        for rule in sorted(self.solver_rules, key=lambda r: -r.priority):
            if rule.matches(fragment):
                return rule
        return None

    def quantum_fragments(self) -> list[FragmentSpec]:
        """Fragments whose assigned solver runs on a QPU."""
        out = []
        for f in self.fragments:
            rule = self.assign_solver(f)
            if rule is not None and rule.solver_kind in (SolverKind.QUANTUM, SolverKind.HYBRID):
                out.append(f)
        return out

    @property
    def max_fragment_qubits(self) -> int | None:
        """Largest per-fragment qubit estimate — the QPU width this plan needs."""
        widths = [f.num_qubits for f in self.fragments if f.num_qubits is not None]
        return max(widths) if widths else None


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class FragmentResult(pydantic.BaseModel):
    """The solver output for a single fragment.

    ``record_id`` links to the ``BenchmarkRecord.experiment_id`` of the run
    that produced this energy.  That is the join between the fragmentation
    layer and the rest of qpubench: a fragment solved by SQD on hardware has
    a full record of its own — backend, shots, mitigation, timings — and this
    result only carries the energy and the coefficient it enters with.
    """
    fragment_id:        str
    solver_name:        str
    solver_kind:        SolverKind    = SolverKind.CLASSICAL
    coefficient:        float         = 1.0     # expansion coefficient for this term
    energy:             float
    hf_energy:          float | None  = None
    correlation_energy: float | None  = None
    converged:          bool          = True
    status:             JobStatus     = JobStatus.SUCCEEDED
    num_qubits:         int | None    = None
    num_shots:          int | None    = None
    wall_seconds:       float | None  = None
    backend_name:       str | None    = None
    record_id:          str | None    = None    # -> BenchmarkRecord.experiment_id
    layer:              int | None    = None
    error_message:      str | None    = None
    metadata:           dict[str, Any] = {}

    @property
    def weighted_energy(self) -> float:
        """The fragment's contribution to the reconstructed total."""
        return self.coefficient * self.energy


class FragmentationResult(pydantic.BaseModel):
    """Reconstructed supersystem property from all fragment results.

    ``total_energy`` is what the upstream code reported.  ``reconstructed_energy``
    recomputes it from the stored per-fragment results, so the two disagreeing
    is a signal that the record is incomplete (screened terms, a failed
    fragment) rather than a silent error.
    """
    spec_name:           str
    scheme:              FragmentationScheme = FragmentationScheme.MBE
    total_energy:        float
    mean_field_energy:   float | None        = None
    reference_energy:    float | None        = None   # supersystem exact / CCSD(T)
    fragment_results:    list[FragmentResult] = []
    n_terms_evaluated:   int | None          = None
    n_terms_screened:    int                 = 0
    wall_seconds:        float | None        = None
    status:              JobStatus           = JobStatus.SUCCEEDED
    metadata:            dict[str, Any]      = {}

    @property
    def reconstructed_energy(self) -> float:
        """Coefficient-weighted sum over the stored fragment results."""
        return sum(r.weighted_energy for r in self.fragment_results)

    @property
    def correlation_energy(self) -> float | None:
        if self.mean_field_energy is None:
            return None
        return self.total_energy - self.mean_field_energy

    @property
    def energy_error(self) -> float | None:
        """|total - reference|, or None without a reference."""
        if self.reference_energy is None:
            return None
        return abs(self.total_energy - self.reference_energy)

    @property
    def chemical_accuracy(self) -> bool | None:
        err = self.energy_error
        return None if err is None else err < CHEMICAL_ACCURACY_HARTREE

    @property
    def num_quantum_fragments(self) -> int:
        return sum(
            1 for r in self.fragment_results
            if r.solver_kind in (SolverKind.QUANTUM, SolverKind.HYBRID)
        )

    @property
    def quantum_fragment_fraction(self) -> float | None:
        """Share of fragments solved on a QPU — None if there are no results."""
        if not self.fragment_results:
            return None
        return self.num_quantum_fragments / len(self.fragment_results)

    @property
    def max_fragment_qubits(self) -> int | None:
        widths = [r.num_qubits for r in self.fragment_results if r.num_qubits is not None]
        return max(widths) if widths else None

    def energies_by_fragment(self) -> dict[str, float]:
        return {r.fragment_id: r.energy for r in self.fragment_results}

    def failed_fragments(self) -> list[FragmentResult]:
        return [r for r in self.fragment_results if r.status != JobStatus.SUCCEEDED]

    def to_quantum_result(
        self,
        computing_model: ComputingModel = ComputingModel.GATE_BASED,
    ) -> QuantumResult:
        """Bridge to QuantumResult with the reconstructed energy as the expectation.

        ``computing_model`` is explicit because a fragmented calculation may be
        entirely classical, or mix classical and quantum fragments.
        """
        return QuantumResult(
            computing_model=computing_model,
            expectation_values=[
                ExpectationResult(observable_index=0, value=self.total_energy, std_error=0.0)
            ],
            status=self.status,
            wall_seconds=self.wall_seconds,
            metadata={
                "scheme": self.scheme.value,
                "n_fragments": len(self.fragment_results),
                "n_quantum_fragments": self.num_quantum_fragments,
                "n_terms_screened": self.n_terms_screened,
                "max_fragment_qubits": self.max_fragment_qubits,
            },
            vendor_results={"fragmentation_result": self.model_dump()},
        )


__all__ = [
    "CHEMICAL_ACCURACY_HARTREE",
    "FragmentExpansionTerm",
    "FragmentResult",
    "FragmentScreeningRule",
    "FragmentSolverAssignment",
    "FragmentSpec",
    "FragmentationLayer",
    "FragmentationResult",
    "FragmentationScheme",
    "FragmentationSpec",
    "FragmenterType",
    "ScreeningMetric",
    "SolverKind",
]
