"""Qdislib — distributed circuit cutting over PyCOMPSs.

Upstream: https://github.com/bsc-wdc/qdislib (Barcelona Supercomputing Centre,
Workflows and Distributed Computing group).  Cite:

* Tejedor, Casas, Conejero, Cervera-Lierta & Badia, *Orchestrating Quantum-HPC
  Workflows with Distributed Quantum Circuit Cutting*, SC '25 Workshops, ACM
  2025, pp. 1898-1906, doi:10.1145/3731599.3767547.
* Tejedor, Conejero & Badia, *A Semantic Quantum Circuit Cache for Scalable and
  Distributed Quantum-Classical Workflows*, arXiv:2604.26788, 2026.
* SparseCut, hardware-aware cut selection: arXiv:2511.05492.

The mechanism
-------------
Cutting replaces a two-qubit gate (**gate cut**) or a wire (**wire cut**) with
a quasiprobability decomposition, splitting the circuit into subcircuits with
no quantum link between them.  Each gate cut expands into 6 terms and each
wire cut into 8, so ``k`` cuts require ``base ** k`` subcircuit evaluations —
exponential in cuts, but every evaluation is independent, which is exactly the
shape PyCOMPSs distributes across CPUs, GPUs and QPUs.

Contrast with DISQCO (``felixburt_disqco``): partitioning pays in EPR pairs and
needs a quantum network; cutting pays in classical sampling overhead and needs
none.  Both bridge to ``distributed_execution.DistributedRunResult``, which is
what lets a benchmark compare them on the same circuit.

Cut identifiers
---------------
Upstream names cuts by gate label: a gate cut is ``["CZ_2"]`` and a wire cut is
a pair of endpoint gates ``[("H_1", "CZ_2")]``.  ``find_cut`` returns one shape
or the other and callers dispatch on it; ``QdislibCutRecord`` stores the kind
explicitly so a stored record never has to re-infer it.
"""
from __future__ import annotations

import enum
import math
from typing import Any

import pydantic

from .distributed_execution import (
    GATE_CUT_OVERHEAD_BASE,
    WIRE_CUT_OVERHEAD_BASE,
    CircuitCutSpec,
    CutSpec,
    DistributedRunResult,
    DistributionStrategy,
    ReconstructionMethod,
    ReconstructionResult,
    SubcircuitResult,
    SubcircuitSpec,
)
from .primitives import ComputingModel, JobStatus
from .result import ExpectationResult, QuantumResult


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class QdislibSoftware(str, enum.Enum):
    """Backend a subcircuit is emitted for.

    Must match the backend it is evaluated on — Qdislib emits subcircuits in
    the target SDK's own circuit type, it does not convert at execution time.
    """
    QIBO      = "qibo"
    QISKIT    = "qiskit"
    CUDAQ     = "cudaq"
    PENNYLANE = "pennylane"


class QdislibCutKind(str, enum.Enum):
    """Cutting technique used."""
    GATE     = "gate"       # cut two-qubit gates; 6 quasiprobability terms each
    WIRE     = "wire"       # cut wires; 8 terms each
    HADAMARD = "hadamard"   # ancilla-based Hadamard-test gate cut, no mid-circuit measure
    MIXED    = "mixed"      # gate + wire cuts on one circuit

    def to_strategy(self) -> DistributionStrategy:
        return {
            QdislibCutKind.GATE: DistributionStrategy.GATE_CUT,
            QdislibCutKind.WIRE: DistributionStrategy.WIRE_CUT,
            QdislibCutKind.HADAMARD: DistributionStrategy.HADAMARD_GATE_CUT,
            QdislibCutKind.MIXED: DistributionStrategy.MIXED_CUT,
        }[self]


class QdislibFindCutImplementation(str, enum.Enum):
    """Cut-search backend used by ``find_cut``."""
    QDISLIB = "qdislib"    # Kernighan-Lin / Girvan-Newman / spectral / METIS, scored
    IBM_CKT = "ibm-ckt"    # Qiskit circuit-knitting optimizer, hardware-aware


class QdislibCacheMode(str, enum.Enum):
    """Granularity of the semantic circuit cache (arXiv:2604.26788)."""
    EXPECTATION = "expectation"    # cache reconstructed expectation values
    COUNTS      = "counts"         # cache raw measurement counts
    NONE        = "none"


# ---------------------------------------------------------------------------
# Cut discovery and cost
# ---------------------------------------------------------------------------

class QdislibFindCutConfig(pydantic.BaseModel):
    """Arguments to ``find_cut``.

    ``coupling_map`` switches on hardware-aware selection (SparseCut): cuts are
    chosen to remove the gates that would route worst on that device, rather
    than purely to balance the partition.
    """
    max_qubits:       int | None                 = None   # per-subcircuit width cap
    max_cuts:         int | None                 = None
    gate_cut:         bool                       = True
    wire_cut:         bool                       = True
    mixed:            bool                       = False
    implementation:   QdislibFindCutImplementation = QdislibFindCutImplementation.QDISLIB
    weights:          dict[str, float]           = {}     # loss-function weights
    seed:             int | None                 = None
    forbidden_gates:  list[str]                  = []
    forbidden_qubits: list[int]                  = []
    top_n:            int | None                 = None   # return N best candidates
    coupling_map:     list[list[int]]            = []     # hardware-aware selection
    layout:           list[int]                  = []     # virtual -> physical mapping


class QdislibCutCost(pydantic.BaseModel):
    """The dict returned by ``cut_cost`` — sizing a run before launching it.

    ``terms`` (``base ** num_cuts``) dominates the cost of a cut run: it is the
    number of subcircuit configurations the reconstruction must evaluate, and
    it is exponential in the number of cuts regardless of how small the
    subcircuits are.
    """
    num_cuts: int
    kind:     QdislibCutKind
    base:     int          # 6 for gate cuts, 8 for wire cuts
    terms:    int          # base ** num_cuts

    @classmethod
    def from_cut_cost(cls, cost: dict[str, Any]) -> QdislibCutCost:
        """Build from the raw ``qd.cut_cost(cut)`` return value."""
        return cls(
            num_cuts=int(cost["num_cuts"]),
            kind=QdislibCutKind(cost["kind"]),
            base=int(cost["base"]),
            terms=int(cost["terms"]),
        )


class QdislibCutRecord(pydantic.BaseModel):
    """The cut ``find_cut`` chose, in a form that does not need re-inferring.

    ``gate_ids`` holds gate-cut identifiers (``"CZ_2"``) and ``wire_endpoints``
    holds wire-cut endpoint pairs (``["H_1", "CZ_2"]``).  A mixed cut populates
    both.
    """
    kind:            QdislibCutKind
    gate_ids:        list[str]        = []
    wire_endpoints:  list[list[str]]  = []
    num_subcircuits: int | None       = None
    max_qubits:      int | None       = None    # width cap the cut was found under
    observables:     list[str]        = []

    @property
    def num_cuts(self) -> int:
        return len(self.gate_ids) + len(self.wire_endpoints)

    @property
    def terms(self) -> int:
        """Quasiprobability terms — ``6**gate_cuts * 8**wire_cuts``."""
        return sampling_overhead(len(self.gate_ids), len(self.wire_endpoints))

    @classmethod
    def from_find_cut(
        cls,
        cut: list[Any],
        *,
        kind: QdislibCutKind | None = None,
        **kwargs: Any,
    ) -> QdislibCutRecord:
        """Build from a raw ``find_cut`` return value.

        Uses upstream's own shape test when ``kind`` is not given: wire cuts
        are ``(source, target)`` pairs, gate cuts are plain identifiers.
        """
        gate_ids: list[str] = []
        wire_endpoints: list[list[str]] = []
        for entry in cut or []:
            if isinstance(entry, (tuple, list)):
                wire_endpoints.append([str(e) for e in entry])
            else:
                gate_ids.append(str(entry))
        if kind is None:
            if gate_ids and wire_endpoints:
                kind = QdislibCutKind.MIXED
            elif wire_endpoints:
                kind = QdislibCutKind.WIRE
            else:
                kind = QdislibCutKind.GATE
        return cls(kind=kind, gate_ids=gate_ids, wire_endpoints=wire_endpoints, **kwargs)

    def to_cut_spec(self, num_qubits: int | None = None) -> CircuitCutSpec:
        """Convert to the framework-general cut spec."""
        cuts = [
            CutSpec(kind="gate", gate_id=g, overhead_base=GATE_CUT_OVERHEAD_BASE)
            for g in self.gate_ids
        ] + [
            CutSpec(kind="wire", endpoints=e, overhead_base=WIRE_CUT_OVERHEAD_BASE)
            for e in self.wire_endpoints
        ]
        return CircuitCutSpec(
            strategy=self.kind.to_strategy(),
            cuts=cuts,
            num_subcircuits=self.num_subcircuits,
            max_qubits_per_subcircuit=self.max_qubits,
            num_qubits=num_qubits,
            observables=self.observables,
            reconstruction=ReconstructionMethod.QUASIPROBABILITY,
            metadata={"source": "bsc-wdc/qdislib"},
        )


# ---------------------------------------------------------------------------
# Subcircuits and execution
# ---------------------------------------------------------------------------

class QdislibSubcircuit(pydantic.BaseModel):
    """One element of a ``CutSubcircuits`` container."""
    subcircuit_id: str
    num_qubits:    int
    qubits:        list[int]        = []     # original circuit qubit indices
    software:      QdislibSoftware  = QdislibSoftware.QIBO
    qasm:          str | None       = None
    term_index:    int | None       = None   # index into the quasiprobability sum
    metadata:      dict[str, Any]   = {}

    def to_subcircuit_spec(self, shots: int | None = None) -> SubcircuitSpec:
        return SubcircuitSpec(
            subcircuit_id=self.subcircuit_id,
            num_qubits=self.num_qubits,
            qubit_map=self.qubits,
            shots=shots,
            term_index=self.term_index,
            metadata={**self.metadata, "software": self.software.value},
        )


class QdislibSubcircuitResult(pydantic.BaseModel):
    """One evaluated subcircuit.

    The three-step workflow (``*_subcircuits`` → evaluate → ``reconstruct``)
    puts the evaluation loop under the caller's control, so where each of
    these ran — simulator, GPU, remote QPU — varies within a single run and is
    worth recording per subcircuit.
    """
    subcircuit_id:     str
    expectation_value: float | None    = None
    counts:            dict[str, int]  = {}
    shots:             int | None      = None
    coefficient:       float           = 1.0     # quasiprobability weight; may be negative
    backend_name:      str | None      = None
    executed_on:       str | None      = None    # "cpu" | "gpu" | "qpu"
    cache_hit:         bool            = False
    wall_seconds:      float | None    = None
    status:            JobStatus       = JobStatus.SUCCEEDED

    def to_subcircuit_result(self) -> SubcircuitResult:
        return SubcircuitResult(
            subcircuit_id=self.subcircuit_id,
            expectation_value=self.expectation_value,
            counts=self.counts,
            shots=self.shots,
            coefficient=self.coefficient,
            wall_seconds=self.wall_seconds,
            backend_name=self.backend_name,
            status=self.status,
        )


class QdislibCacheStats(pydantic.BaseModel):
    """Semantic circuit-cache statistics (``cache.stats()``).

    The cache keys on circuit *semantics*, so structurally different but
    equivalent subcircuits share an entry — which is where the speedup in
    arXiv:2604.26788 comes from, and why the hit rate is worth recording
    alongside the wall time it explains.
    """
    hits:    int = 0
    misses:  int = 0
    size:    int | None = None
    backend: str | None = None    # "memory" | "lmdb" | "redis"

    @property
    def hit_rate(self) -> float | None:
        total = self.hits + self.misses
        return None if total == 0 else self.hits / total


class QdislibEstimateMetrics(pydantic.BaseModel):
    """The ``metrics`` dict from ``estimate(..., return_metrics=True)``."""
    cut_type:         QdislibCutKind
    num_cuts:         int
    find_cut_seconds: float | None       = None
    run_seconds:      float | None       = None
    cache:            QdislibCacheStats | None = None


class QdislibRunRecord(pydantic.BaseModel):
    """A complete Qdislib cutting run.

    ``expectation_value`` is the reconstructed observable — the answer the
    whole cut existed to produce.  ``exact_value`` is the uncut reference when
    one was computed (``analytical_solution`` / ``exact_statevector``), which
    is what turns this from a timing record into an accuracy benchmark.
    """
    circuit_qubits:    int
    software:          QdislibSoftware        = QdislibSoftware.QIBO
    cut:               QdislibCutRecord | None = None
    find_cut_config:   QdislibFindCutConfig | None = None
    cost:              QdislibCutCost | None  = None
    subcircuits:       list[QdislibSubcircuit] = []
    subcircuit_results: list[QdislibSubcircuitResult] = []
    expectation_value: float | None           = None
    exact_value:       float | None           = None
    shots:             int | None             = None
    observables:       list[str]              = []
    metrics:           QdislibEstimateMetrics | None = None
    cache_mode:        QdislibCacheMode       = QdislibCacheMode.NONE
    num_workers:       int | None             = None    # PyCOMPSs workers
    wall_seconds:      float | None           = None
    status:            JobStatus              = JobStatus.SUCCEEDED
    error_message:     str | None             = None

    @property
    def num_cuts(self) -> int:
        if self.cut is not None:
            return self.cut.num_cuts
        return self.cost.num_cuts if self.cost else 0

    @property
    def sampling_overhead(self) -> int:
        """Subcircuit configurations the reconstruction evaluated."""
        if self.cost is not None:
            return self.cost.terms
        if self.cut is not None:
            return self.cut.terms
        return 1

    @property
    def error(self) -> float | None:
        """|reconstructed - exact|, or None without an exact reference."""
        if self.expectation_value is None or self.exact_value is None:
            return None
        return abs(self.expectation_value - self.exact_value)

    @property
    def max_subcircuit_qubits(self) -> int | None:
        return max((s.num_qubits for s in self.subcircuits), default=None)

    @property
    def qubit_reduction(self) -> int | None:
        """Qubits saved on the widest subcircuit versus the uncut circuit."""
        widest = self.max_subcircuit_qubits
        return None if widest is None else self.circuit_qubits - widest

    @property
    def cache_hit_rate(self) -> float | None:
        if self.metrics is None or self.metrics.cache is None:
            return None
        return self.metrics.cache.hit_rate

    def to_distributed_run_result(self) -> DistributedRunResult:
        """Bridge to the framework-general distributed-run record."""
        reconstruction = None
        if self.expectation_value is not None:
            reconstruction = ReconstructionResult(
                value=self.expectation_value,
                method=ReconstructionMethod.QUASIPROBABILITY,
                num_terms=self.sampling_overhead,
                num_subcircuit_evaluations=len(self.subcircuit_results) or None,
                sampling_overhead=self.sampling_overhead,
                exact_value=self.exact_value,
            )
        return DistributedRunResult(
            strategy=(
                self.cut.kind.to_strategy() if self.cut else DistributionStrategy.GATE_CUT
            ),
            cut=self.cut.to_cut_spec(self.circuit_qubits) if self.cut else None,
            subcircuit_results=[r.to_subcircuit_result() for r in self.subcircuit_results],
            reconstruction=reconstruction,
            find_cut_seconds=self.metrics.find_cut_seconds if self.metrics else None,
            execute_seconds=self.metrics.run_seconds if self.metrics else None,
            total_wall_seconds=self.wall_seconds,
            num_workers=self.num_workers,
            status=self.status,
            error_message=self.error_message,
            metadata={
                "source": "bsc-wdc/qdislib",
                "software": self.software.value,
                "cache_mode": self.cache_mode.value,
                "cache_hit_rate": self.cache_hit_rate,
            },
        )

    def to_quantum_result(self) -> QuantumResult:
        """Bridge to QuantumResult with the reconstructed expectation value."""
        expectations = None
        if self.expectation_value is not None:
            expectations = [
                ExpectationResult(
                    observable_index=0, value=self.expectation_value, std_error=0.0
                )
            ]
        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=expectations,
            status=self.status,
            error_message=self.error_message,
            wall_seconds=self.wall_seconds,
            metadata={
                "num_cuts": self.num_cuts,
                "sampling_overhead": self.sampling_overhead,
                "qubit_reduction": self.qubit_reduction,
            },
            vendor_results={"qdislib_run": self.model_dump()},
        )


def sampling_overhead(num_gate_cuts: int = 0, num_wire_cuts: int = 0) -> int:
    """Quasiprobability terms for a mix of gate and wire cuts.

    ``6 ** num_gate_cuts * 8 ** num_wire_cuts`` — the standalone form of
    ``QdislibCutRecord.terms``, for sizing a run before any cut exists.
    """
    return int(
        GATE_CUT_OVERHEAD_BASE**num_gate_cuts * WIRE_CUT_OVERHEAD_BASE**num_wire_cuts
    )


def max_cuts_for_budget(budget_terms: int, base: int = GATE_CUT_OVERHEAD_BASE) -> int:
    """Largest cut count whose reconstruction stays within ``budget_terms``.

    Inverts ``base ** k <= budget``.  Returns 0 when even a single cut exceeds
    the budget.
    """
    if budget_terms < 1 or base < 2:
        return 0
    return int(math.floor(math.log(budget_terms) / math.log(base)))


__all__ = [
    "QdislibCacheMode",
    "QdislibCacheStats",
    "QdislibCutCost",
    "QdislibCutKind",
    "QdislibCutRecord",
    "QdislibEstimateMetrics",
    "QdislibFindCutConfig",
    "QdislibFindCutImplementation",
    "QdislibRunRecord",
    "QdislibSoftware",
    "QdislibSubcircuit",
    "QdislibSubcircuitResult",
    "max_cuts_for_budget",
    "sampling_overhead",
]
