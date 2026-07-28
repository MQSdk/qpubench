"""Fragme∩t — the Herbert group's fragmentation framework.

Upstream: https://gitlab.com/fragment-qc/fragment (Apache-2.0).  Docs at
https://fragment-qc.gitlab.io.  Fragme∩t is a framework for *prototyping and
benchmarking* fragmentation methods rather than one method: fragmenters,
combinators, screening mods and per-layer backends are composed in a
declarative ``strategy.yaml`` file.

Publications the schema follows
-------------------------------
* Broderick & Herbert, *Scalable generalized screening for high-order terms in
  the many-body expansion*, J. Chem. Phys. **159**, 174801 (2023) —
  the generalized screening this module's mods represent.
* Bowling, Broderick & Herbert, J. Phys. Chem. Lett. **14**, 3826 (2023).

The one idea worth importing wholesale
--------------------------------------
Fragme∩t represents *any* expansion as a **PIE tree** (principle of inclusion
and exclusion): nodes keyed by a set of primary-fragment indices, each with an
integer coefficient.  A 2-body MBE, a generalized MBE over overlapping
fragments and a screened high-order expansion are all the same object — only
the coefficients differ.  ``FragmentPIETree.to_expansion()`` converts it to
the framework-general ``fragmentation.FragmentExpansionTerm`` list, which is
what makes Fragme∩t results comparable with the embedding-based methods in
``qiskitcommunity_fragment_methods``.

Note on the upstream Pydantic version: Fragme∩t's own ``fragment/schemas/``
models are Pydantic v1 (``pydantic.validator``, ``orm_mode``).  These are
independent Pydantic v2 mirrors, not imports — qpubench never depends on the
upstream package.
"""
from __future__ import annotations

import datetime
import enum
from typing import Any

import pydantic

from .fragmentation import (
    FragmentationLayer,
    FragmentationResult,
    FragmentationScheme,
    FragmentationSpec,
    FragmenterType,
    FragmentExpansionTerm,
    FragmentResult,
    FragmentScreeningRule,
    FragmentSpec,
    ScreeningMetric,
    SolverKind,
)
from .primitives import JobStatus


# ---------------------------------------------------------------------------
# Enumerations — mirror the Literal discriminators in fragment/schemas/strategy.py
# ---------------------------------------------------------------------------

class FragmentCombinator(str, enum.Enum):
    """How a fragmenter's primaries are combined into the expansion."""
    BOTTOM_UP = "bottom_up"    # build n-mers upward, PIE coefficients from overlaps
    TOP_DOWN  = "top_down"     # subtract from the supersystem downward
    MBE       = "mbe"          # textbook many-body expansion


class FragmentFragmenterName(str, enum.Enum):
    """Fragmenters shipped with Fragme∩t (``FragmenterTypes`` union)."""
    PDB            = "pdb"
    WATER          = "water"
    SUPERSYSTEM    = "supersystem"
    RAW            = "raw"
    COMPOUND       = "compound"
    MBCP           = "mbcp"            # many-body counterpoise
    BSSE_BALANCED  = "bssebalanced"


class FragmentModName(str, enum.Enum):
    """Mods — the composable filters and transformations on a view.

    Screening mods (``distance``, ``xtbenergy``, ``energy_trimming``, …) are
    the adaptive part of an adaptive fragmentation run: they decide which
    n-body terms are ever submitted.  Basis mods change the basis a term is
    computed in (counterpoise-style corrections), and the MIC mods handle
    periodic minimum-image conventions.
    """
    RCAPS                       = "rcaps"
    DISTANCE                    = "distance"
    XTB_ENERGY                  = "xtbenergy"
    XTB_CHILDREN_ENERGY         = "xtbchildrenenergy"
    XTB_CHILDREN_ENERGY_PRODUCT = "xtbchildrenenergyproduct"
    ENERGY_TRIMMING             = "energy_trimming"
    USE_SUPERSYSTEM_BASIS       = "usesupersystembasis"
    CLUSTER_BASIS               = "clusterbasis"
    USE_CLOUD_BASIS             = "usecloudbasis"
    MIC_FILTER                  = "micfilter"
    MIC_WRAP_SYSTEM             = "micwrapsystem"


class FragmentBackendProgram(str, enum.Enum):
    """Electronic-structure programs Fragme∩t can drive per layer."""
    QCHEM  = "qchem"
    CP2K   = "cp2k"
    ORCA   = "orca"
    NWCHEM = "nwchem"
    XTB    = "xtb"
    LIBXTB = "libxtb"
    PYSCF  = "pyscf"
    MOPAC  = "mopac"
    XYZ    = "xyz"       # writes geometries only; no energy


class FragmentViewType(str, enum.Enum):
    """View kinds from ``fragment/views.py`` (``ViewType``)."""
    PRIMARY   = "primary"      # the base fragmentation, order 0
    AUXILIARY = "auxiliary"    # an n-body expansion built on a primary view
    PRIMITIVE = "primitive"    # the atom-level decomposition


# ---------------------------------------------------------------------------
# Strategy file (strategy.yaml)
# ---------------------------------------------------------------------------

class FragmentModSpec(pydantic.BaseModel):
    """One entry of the strategy file's ``mods:`` list.

    The upstream models are a discriminated union keyed on ``mod_name``; this
    is the flattened superset, so a round-trip keeps every field any mod uses
    without a per-mod class.  ``thresholds`` is keyed by n-body order, as in
    the xTB-energy and energy-trimming mods.
    """
    name:           str
    mod_name:       FragmentModName
    note:           str                     = ""
    thresholds:     dict[int, float]        = {}       # n-body order -> threshold
    tolerance:      float | None            = None     # RCaps
    cutoff:         float | None            = None     # RCaps / UseCloudBasis
    k:              int | None              = None     # RCaps
    ignore_charged: bool | None             = None     # RCaps
    method:         str | None              = None     # Distance: "com" | "closest"
    min_distance:   float | None            = None
    max_distance:   float | None            = None
    backend:        str | None              = None     # cheap estimator backend name
    lattice_a:      float | None            = None     # MIC mods
    lattice_b:      float | None            = None
    lattice_c:      float | None            = None

    def to_screening_rule(self) -> FragmentScreeningRule | None:
        """Convert to a framework-general screening rule.

        Returns None for mods that are not screening rules (basis and MIC
        mods change *how* a term is computed, not *whether* it is), so
        callers can map over every mod and filter the Nones.
        """
        metric_map = {
            FragmentModName.DISTANCE: (
                ScreeningMetric.CENTRE_OF_MASS_DISTANCE
                if (self.method or "com").lower() == "com"
                else ScreeningMetric.CLOSEST_ATOM_DISTANCE
            ),
            FragmentModName.XTB_ENERGY: ScreeningMetric.ENERGY_DELTA,
            FragmentModName.XTB_CHILDREN_ENERGY: ScreeningMetric.ENERGY_DELTA,
            FragmentModName.XTB_CHILDREN_ENERGY_PRODUCT: ScreeningMetric.ENERGY_PRODUCT,
            FragmentModName.ENERGY_TRIMMING: ScreeningMetric.ENERGY_DELTA,
        }
        metric = metric_map.get(self.mod_name)
        if metric is None:
            return None
        return FragmentScreeningRule(
            name=self.name,
            metric=metric,
            thresholds=self.thresholds,
            cutoff=self.cutoff,
            min_value=self.min_distance,
            max_value=self.max_distance,
            backend=self.backend,
            options={"mod_name": self.mod_name.value},
        )


class FragmentBackendSpec(pydantic.BaseModel):
    """One entry of the strategy file's ``backends:`` list.

    Flattens the per-program models plus the nested PySCF ``procedure`` block,
    so ``method``/``basis``/``xc`` are readable without knowing which program
    produced them.
    """
    name:            str
    program:         FragmentBackendProgram
    note:            str          = ""
    template:        str | None   = None
    input_template:  str | None   = None      # CP2K
    potential_file:  str | None   = None      # CP2K
    memory:          float | None = None      # xTB
    accuracy:        float | None = None      # libxTB
    # PySCF procedure block
    method:          str | None   = None      # "hf" | "ks" | "mp2" | "dfmp2" | "ccsd" | "ccsd(t)"
    basis:           str | None   = None
    xc:              str | None   = None      # KS/DFT functional
    auxbasis:        str | None   = None      # DF-MP2 / RI-MP2
    conv_tol:        float | None = None
    direct_scf_tol:  float | None = None
    driver:          str | None   = None
    mp2_driver:      str | None   = None
    use_newton:      bool         = False


class FragmentFragmenterSpec(pydantic.BaseModel):
    """One entry of the strategy file's ``fragmenters:`` list."""
    name:        str
    fragmenter:  FragmentFragmenterName
    note:        str                    = ""
    mods:        list[str]              = []       # names of mods to apply
    combinator:  FragmentCombinator | None = None
    bu_missing:  int                    = 0        # bottom-up: tolerated missing children
    fragments:   dict[str, str]         = {}       # Compound: species -> fragmenter name
    default:     str | None             = None     # Compound: fallback fragmenter


class FragmentSubsystemSpec(pydantic.BaseModel):
    """An include/exclude selection carving a subsystem out of a supersystem."""
    name:    str
    note:    str        = ""
    include: str | None = None
    exclude: str | None = None


class FragmentSupersystemSpec(pydantic.BaseModel):
    """One entry of the strategy file's ``systems:`` list."""
    name:       str
    source:     str                       # geometry file path (xyz, PDB, …)
    note:       str                       = ""
    charges:    dict[int, int]            = {}     # atom index -> formal charge
    subsystems: list[FragmentSubsystemSpec] = []


class FragmentViewSpec(pydantic.BaseModel):
    """A view: an n-body expansion of one system under one fragmenter."""
    order:      int
    fragmenter: str                              # fragmenter name
    system:     str | None    = None             # supersystem name; None = partial view
    view_type:  FragmentViewType = FragmentViewType.AUXILIARY


class FragmentLayerSpec(pydantic.BaseModel):
    """One layer of a calculation: a backend applied to a view.

    Stacking layers is how Fragme∩t expresses a multilevel calculation — a
    high-order cheap expansion plus a low-order accurate one.
    """
    backend: str                       # backend name
    view:    FragmentViewSpec
    mods:    list[str] = []            # extra mods applied at this layer


class FragmentCalculationSpec(pydantic.BaseModel):
    """One entry of the strategy file's ``calculations:`` list."""
    name:   str
    note:   str                     = ""
    system: str | list[str]         = "ALL"      # "ALL", one name, or a list
    layers: list[FragmentLayerSpec] = []


class FragmentStrategy(pydantic.BaseModel):
    """A complete Fragme∩t ``strategy.yaml``.

    Load with ``FragmentStrategy.model_validate(yaml.safe_load(text))`` — the
    field names match the upstream file verbatim, so a strategy file
    round-trips through this model unchanged.
    """
    mods:         list[FragmentModSpec]         = []
    systems:      list[FragmentSupersystemSpec] = []
    backends:     list[FragmentBackendSpec]     = []
    fragmenters:  list[FragmentFragmenterSpec]  = []
    calculations: list[FragmentCalculationSpec] = []

    def backend(self, name: str) -> FragmentBackendSpec | None:
        return next((b for b in self.backends if b.name == name), None)

    def fragmenter(self, name: str) -> FragmentFragmenterSpec | None:
        return next((f for f in self.fragmenters if f.name == name), None)

    def mod(self, name: str) -> FragmentModSpec | None:
        return next((m for m in self.mods if m.name == name), None)

    def to_fragmentation_spec(self, calculation: str | None = None) -> FragmentationSpec:
        """Convert one calculation into the framework-general spec.

        Each Fragme∩t layer becomes a ``FragmentationLayer`` carrying the
        backend's method/basis and the layer's own mods as screening rules.
        ``calculation`` selects which of the strategy's calculations to
        convert; the first one is used when omitted.

        The expansion itself is *not* populated — Fragme∩t generates it by
        running the fragmenter over a real geometry.  Attach the terms from
        ``FragmentPIETree.to_expansion()`` once the tree is built.
        """
        calcs = self.calculations
        if calculation is not None:
            calcs = [c for c in calcs if c.name == calculation]
        if not calcs:
            raise ValueError(f"no calculation named {calculation!r} in this strategy")
        calc = calcs[0]

        layers: list[FragmentationLayer] = []
        for level, layer in enumerate(calc.layers):
            backend = self.backend(layer.backend)
            frag = self.fragmenter(layer.view.fragmenter)
            rules = [
                rule
                for name in layer.mods
                if (mod := self.mod(name)) is not None
                and (rule := mod.to_screening_rule()) is not None
            ]
            layers.append(
                FragmentationLayer(
                    level=level,
                    name=layer.backend,
                    scheme=_scheme_for(frag),
                    fragmenter=_fragmenter_type(frag),
                    max_order=layer.view.order,
                    method=(backend.method or backend.program.value) if backend else "unknown",
                    basis=backend.basis if backend else None,
                    solver_kind=SolverKind.CLASSICAL,
                    screening=rules,
                )
            )

        top = calc.layers[-1] if calc.layers else None
        top_frag = self.fragmenter(top.view.fragmenter) if top else None
        return FragmentationSpec(
            name=calc.name,
            scheme=_scheme_for(top_frag),
            fragmenter=_fragmenter_type(top_frag),
            max_order=top.view.order if top else 1,
            supersystem_label=calc.system if isinstance(calc.system, str) else None,
            layers=layers,
            screening=[
                rule for mod in self.mods if (rule := mod.to_screening_rule()) is not None
            ],
            metadata={"source": "fragment-qc/fragment", "note": calc.note},
        )


def _scheme_for(frag: FragmentFragmenterSpec | None) -> FragmentationScheme:
    """Map a fragmenter's combinator (and special fragmenters) to a scheme."""
    if frag is None:
        return FragmentationScheme.CUSTOM
    if frag.fragmenter == FragmentFragmenterName.MBCP:
        return FragmentationScheme.MBCP
    if frag.fragmenter == FragmentFragmenterName.BSSE_BALANCED:
        return FragmentationScheme.BSSE_BALANCED
    return {
        FragmentCombinator.MBE: FragmentationScheme.MBE,
        FragmentCombinator.BOTTOM_UP: FragmentationScheme.BOTTOM_UP,
        FragmentCombinator.TOP_DOWN: FragmentationScheme.TOP_DOWN,
        None: FragmentationScheme.GMBE,
    }[frag.combinator]


def _fragmenter_type(frag: FragmentFragmenterSpec | None) -> FragmenterType:
    if frag is None:
        return FragmenterType.CUSTOM
    return {
        FragmentFragmenterName.PDB: FragmenterType.PDB,
        FragmentFragmenterName.WATER: FragmenterType.WATER,
        FragmentFragmenterName.SUPERSYSTEM: FragmenterType.SUPERSYSTEM,
        FragmentFragmenterName.RAW: FragmenterType.RAW,
        FragmentFragmenterName.COMPOUND: FragmenterType.COMPOUND,
        FragmentFragmenterName.MBCP: FragmenterType.CUSTOM,
        FragmentFragmenterName.BSSE_BALANCED: FragmenterType.CUSTOM,
    }[frag.fragmenter]


# ---------------------------------------------------------------------------
# PIE tree — the expansion itself
# ---------------------------------------------------------------------------

class FragmentPIENode(pydantic.BaseModel):
    """One node of a principle-of-inclusion-exclusion tree.

    ``key`` is the set of primary-fragment indices this node covers (stored
    sorted so the JSON form is canonical; upstream it is a ``frozenset``).
    ``coefficient`` is its signed weight in the expansion — the whole point of
    the tree is computing these correctly when primaries overlap.

    A node with ``coefficient == 0`` is a structural node that contributes
    nothing: it exists so its children's overlaps resolve, and it is never
    submitted as a job.
    """
    key:         list[int]
    coefficient: int
    method:      str | None = None       # per-node level-of-theory override

    @property
    def order(self) -> int:
        """n-body order — the number of primaries this node unions."""
        return len(self.key)

    @property
    def fragment_id(self) -> str:
        """Canonical identifier, e.g. ``"n(0,3,7)"``."""
        return "n(" + ",".join(str(i) for i in self.key) + ")"


class FragmentPIETree(pydantic.BaseModel):
    """The expansion produced by a fragmenter over one system.

    Mirrors ``fragment.views.View`` / ``fragment.core.rPIETree.PIETree``: a set
    of primaries plus the signed nodes covering them.
    """
    primaries:  list[list[int]]         = []     # each primary as its atom indices
    nodes:      list[FragmentPIENode]   = []
    order:      int                     = 1
    view_type:  FragmentViewType        = FragmentViewType.AUXILIARY
    fragmenter: str | None              = None
    system:     str | None              = None

    @property
    def num_primaries(self) -> int:
        return len(self.primaries)

    @property
    def nonzero_nodes(self) -> list[FragmentPIENode]:
        """Nodes that are actually submitted as jobs."""
        return [n for n in self.nodes if n.coefficient != 0]

    def coefficient_sum(self) -> int:
        """Sum of all coefficients — 1 for an expansion covering the supersystem."""
        return sum(n.coefficient for n in self.nodes)

    def nodes_by_order(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for n in self.nonzero_nodes:
            counts[n.order] = counts.get(n.order, 0) + 1
        return counts

    def to_expansion(self) -> list[FragmentExpansionTerm]:
        """Convert to framework-general expansion terms (zero-coefficient nodes dropped)."""
        return [
            FragmentExpansionTerm(
                fragment_id=n.fragment_id,
                coefficient=float(n.coefficient),
                order=n.order,
                method=n.method,
            )
            for n in self.nonzero_nodes
        ]

    def to_fragments(self) -> list[FragmentSpec]:
        """One FragmentSpec per submitted node, with atoms unioned from its primaries."""
        out: list[FragmentSpec] = []
        for n in self.nonzero_nodes:
            atoms: set[int] = set()
            for idx in n.key:
                if 0 <= idx < len(self.primaries):
                    atoms.update(self.primaries[idx])
            out.append(
                FragmentSpec(
                    fragment_id=n.fragment_id,
                    order=n.order,
                    primary_ids=[f"n({i})" for i in n.key],
                    atom_indices=sorted(atoms),
                )
            )
        return out


# ---------------------------------------------------------------------------
# Job and run records
# ---------------------------------------------------------------------------

class FragmentJobRecord(pydantic.BaseModel):
    """One completed fragment job — mirrors ``fragment/schemas/calculation.py::Result``.

    ``properties`` is the upstream ``PropertySet`` flattened to a dict; the
    energy is pulled out separately because it is the one property every
    fragmentation method reconstructs.
    """
    job_id:      int | str
    name:        str
    status:      JobStatus
    energy:      float | None                = None
    start_time:  datetime.datetime | None    = None
    end_time:    datetime.datetime | None    = None
    backend_id:  int | str | None            = None
    coefficient: int                         = 1
    properties:  dict[str, Any]              = {}

    @property
    def wall_seconds(self) -> float | None:
        if self.start_time is None or self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()

    def to_fragment_result(self, solver_name: str = "fragment") -> FragmentResult:
        return FragmentResult(
            fragment_id=self.name,
            solver_name=solver_name,
            solver_kind=SolverKind.CLASSICAL,
            coefficient=float(self.coefficient),
            energy=self.energy if self.energy is not None else 0.0,
            status=self.status,
            wall_seconds=self.wall_seconds,
            metadata=self.properties,
        )


class FragmentRunRecord(pydantic.BaseModel):
    """A complete Fragme∩t calculation: the tree, the jobs, and the total.

    ``total_energy`` is what Fragme∩t reported.  Compare it against
    ``to_fragmentation_result().reconstructed_energy`` to confirm every
    contributing job made it into the record.
    """
    strategy_name:    str
    calculation_name: str
    tree:             FragmentPIETree | None    = None
    jobs:             list[FragmentJobRecord]   = []
    total_energy:     float | None              = None
    supersystem_energy: float | None            = None   # unfragmented reference
    backend_name:     str | None                = None
    wall_seconds:     float | None              = None
    status:           JobStatus                 = JobStatus.SUCCEEDED

    @property
    def num_jobs(self) -> int:
        return len(self.jobs)

    def to_fragmentation_result(self) -> FragmentationResult:
        """Bridge to the framework-general result."""
        results = [j.to_fragment_result() for j in self.jobs]
        return FragmentationResult(
            spec_name=self.calculation_name,
            scheme=FragmentationScheme.GMBE,
            total_energy=(
                self.total_energy
                if self.total_energy is not None
                else sum(r.weighted_energy for r in results)
            ),
            reference_energy=self.supersystem_energy,
            fragment_results=results,
            n_terms_evaluated=len(results),
            wall_seconds=self.wall_seconds,
            status=self.status,
            metadata={
                "source": "fragment-qc/fragment",
                "strategy": self.strategy_name,
                "backend": self.backend_name,
            },
        )


__all__ = [
    "FragmentBackendProgram",
    "FragmentBackendSpec",
    "FragmentCalculationSpec",
    "FragmentCombinator",
    "FragmentFragmenterName",
    "FragmentFragmenterSpec",
    "FragmentJobRecord",
    "FragmentLayerSpec",
    "FragmentModName",
    "FragmentModSpec",
    "FragmentPIENode",
    "FragmentPIETree",
    "FragmentRunRecord",
    "FragmentStrategy",
    "FragmentSubsystemSpec",
    "FragmentSupersystemSpec",
    "FragmentViewSpec",
    "FragmentViewType",
]
