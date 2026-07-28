"""Distributed quantum execution — circuit partitioning and circuit cutting.

Cross-cutting module: the *union* of the two families of technique for running
one logical circuit across several QPUs, not a mirror of any single project.
Upstream specifics live in the project mirrors, which bridge into these types:

    felixburt_disqco     DISQCO — multilevel hypergraph partitioning of a
                         circuit over a quantum network, minimising EPR pairs
                         (arXiv:2503.19082, arXiv:2507.16036)
    bscwdc_qdislib       Qdislib (BSC) — gate and wire cutting with
                         quasiprobability reconstruction over PyCOMPSs

The two mechanisms, and why one schema
--------------------------------------
Both answer "this circuit does not fit on one QPU", but pay for it differently:

* **Partitioning** (``DistributionStrategy.PARTITION``) keeps one entangled
  computation and moves qubits between QPUs with teleportation.  The cost is
  **entanglement**: EPR pairs (ebits) consumed on the network links, plus
  classical communication for LOCC.  Cost grows with the *cut size* of the
  partition and is linear in circuit repetitions.

* **Cutting** (``GATE_CUT`` / ``WIRE_CUT`` / …) breaks the circuit into
  genuinely independent subcircuits with no quantum link at all, and pays in
  **classical sampling overhead**: each cut expands into a quasiprobability
  decomposition (6 terms for a gate cut, 8 for a wire cut), so ``k`` cuts need
  ``base ** k`` subcircuit evaluations.  Exponential in the number of cuts,
  but embarrassingly parallel and needs no quantum network.

Sharing ``QPUNetworkSpec``, ``SubcircuitSpec`` and ``DistributedRunResult``
across both is what makes them comparable: the same benchmark can ask whether
a given circuit is cheaper to teleport or to cut, and read one set of numbers.

Attaching to a record
---------------------
    from qpubench.schemas.distributed_execution import CircuitCutSpec

    circuit = CircuitSpec(..., distribution=cut_spec)         # model or dict
    options = ExecutionOptions(distributed_run_config=run_cfg)
    result  = QuantumResult(..., vendor_results={"distributed_run_result": run_res})

    cut_spec = CircuitCutSpec.model_validate(circuit.distribution)
"""
from __future__ import annotations

import enum
import math
from typing import Any

import pydantic

from .circuit import CircuitSpec
from .primitives import ComputingModel, JobStatus, QubitModality
from .result import ExpectationResult, QuantumResult

# Quasiprobability decomposition sizes.  A gate cut expands each cut into 6
# terms and a wire cut into 8, so k cuts require base**k subcircuit
# evaluations to reconstruct one expectation value.
GATE_CUT_OVERHEAD_BASE = 6
WIRE_CUT_OVERHEAD_BASE = 8


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class DistributionStrategy(str, enum.Enum):
    """How one logical circuit is spread over multiple QPUs."""
    NONE               = "none"                 # monolithic, single QPU
    PARTITION          = "partition"            # teleportation over a quantum network
    GATE_CUT           = "gate_cut"             # cut two-qubit gates (6 terms each)
    WIRE_CUT           = "wire_cut"             # cut wires (8 terms each)
    HADAMARD_GATE_CUT  = "hadamard_gate_cut"    # ancilla-based gate cut, no mid-circuit measure
    MIXED_CUT          = "mixed_cut"            # gate + wire cuts on one circuit
    CIRCUIT_KNITTING   = "circuit_knitting"     # Qiskit addon (ibm-ckt) cut finding


class PartitionerType(str, enum.Enum):
    """Algorithm that chooses the assignment of circuit nodes to QPUs."""
    FIDUCCIA_MATTHEYSES = "fm"                  # FM heuristic on the temporal hypergraph
    MULTILEVEL_FM       = "multilevel_fm"       # coarsen -> FM per level -> refine
    GENETIC             = "genetic"
    GENETIC_FM_HYBRID   = "genetic_fm_hybrid"
    FGP                 = "fgp"                 # fine-grained partitioning
    KERNIGHAN_LIN       = "kernighan_lin"
    GIRVAN_NEWMAN       = "girvan_newman"
    SPECTRAL            = "spectral"
    METIS               = "metis"
    RANDOM              = "random"
    MANUAL              = "manual"              # assignment supplied by the caller


class CoarseningStrategy(str, enum.Enum):
    """Multilevel coarsening applied before partitioning.

    Coarsening contracts the circuit hypergraph into a hierarchy of smaller
    graphs; the partitioner runs on the coarsest level and the solution is
    projected back down and refined.  Which coarsener is used trades solution
    quality against runtime, which is why it is a recorded field.
    """
    NONE               = "none"
    FULL               = "full"                 # contract to a fixed number of levels
    STATIC             = "static"               # single static contraction
    BLOCKS             = "blocks"               # contract fixed-size time blocks
    RECURSIVE          = "recursive"            # halve the time axis each level
    RECURSIVE_BATCHES  = "recursive_batches"    # batched recursive contraction
    SUBGRAPH           = "subgraph"             # contract on subgraphs
    NETWORK            = "network"              # coarsen the network, not the circuit


class NetworkTopology(str, enum.Enum):
    """Connectivity pattern of the quantum network linking the QPUs."""
    ALL_TO_ALL       = "all_to_all"
    LINEAR           = "linear"
    GRID             = "grid"
    TREE             = "tree"
    RANDOM           = "random"
    NETWORK_OF_GRIDS = "network_of_grids"
    CUSTOM           = "custom"


class ReconstructionMethod(str, enum.Enum):
    """How subcircuit outputs are recombined into the original observable."""
    QUASIPROBABILITY = "quasiprobability"   # signed weighted sum over cut terms
    SAMPLING         = "sampling"           # sampled reconstruction of a distribution
    LOCC             = "locc"               # partitioned run; no classical recombination
    NONE             = "none"


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

class QPUNodeSpec(pydantic.BaseModel):
    """One QPU in a quantum network.

    ``num_comm_qubits`` is the count reserved for holding halves of EPR pairs;
    it is what caps how many teleportations can be in flight at once, so it is
    separate from the data register rather than folded into a total width.
    """
    node_id:         str
    num_data_qubits: int
    num_comm_qubits: int                  = 1
    backend_name:    str | None           = None     # -> BackendSpec.name
    qubit_modality:  QubitModality | None = None
    coupling_map:    list[list[int]]      = []       # intra-QPU connectivity
    metadata:        dict[str, Any]       = {}

    @property
    def total_qubits(self) -> int:
        return self.num_data_qubits + self.num_comm_qubits


class QPULinkSpec(pydantic.BaseModel):
    """A directly-connected pair of QPUs able to share entanglement.

    Only directly connected nodes can generate EPR pairs; long-range
    entanglement is distributed along a path of links, consuming auxiliary
    pairs at every hop.  That is why ``ebits`` on a route is larger than one.
    """
    source:        str
    target:        str
    ebit_rate_hz:  float | None = None    # EPR pair generation rate
    fidelity:      float | None = None    # raw EPR pair fidelity
    latency_s:     float | None = None
    capacity:      int          = 1       # simultaneous EPR pairs supported

    @property
    def key(self) -> str:
        """Canonical undirected identifier, e.g. ``"q0<->q1"``."""
        a, b = sorted((self.source, self.target))
        return f"{a}<->{b}"


class QPUNetworkSpec(pydantic.BaseModel):
    """A set of QPUs and the entanglement links between them."""
    name:     str
    topology: NetworkTopology  = NetworkTopology.ALL_TO_ALL
    nodes:    list[QPUNodeSpec] = []
    links:    list[QPULinkSpec] = []
    metadata: dict[str, Any]    = {}

    @property
    def num_nodes(self) -> int:
        return len(self.nodes)

    @property
    def total_data_qubits(self) -> int:
        return sum(n.num_data_qubits for n in self.nodes)

    @property
    def total_comm_qubits(self) -> int:
        return sum(n.num_comm_qubits for n in self.nodes)

    @property
    def is_homogeneous(self) -> bool:
        """True if every QPU has the same data-register width."""
        sizes = {n.num_data_qubits for n in self.nodes}
        return len(sizes) <= 1

    def node(self, node_id: str) -> QPUNodeSpec | None:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None

    def neighbors(self, node_id: str) -> list[str]:
        """Directly linked node ids (links are treated as undirected)."""
        out: list[str] = []
        for link in self.links:
            if link.source == node_id:
                out.append(link.target)
            elif link.target == node_id:
                out.append(link.source)
        return out

    def is_connected(self) -> bool:
        """True if every node is reachable from the first one."""
        if not self.nodes:
            return True
        seen = {self.nodes[0].node_id}
        stack = [self.nodes[0].node_id]
        while stack:
            for nb in self.neighbors(stack.pop()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        return len(seen) == len(self.nodes)

    @classmethod
    def from_sizes(
        cls,
        sizes: list[int],
        *,
        name: str = "network",
        topology: NetworkTopology = NetworkTopology.ALL_TO_ALL,
        comm_sizes: list[int] | None = None,
        connectivity: list[tuple[int, int]] | None = None,
    ) -> QPUNetworkSpec:
        """Build a network from per-QPU data-register widths.

        Nodes are named ``q0``, ``q1``, ….  ``connectivity`` gives explicit
        index pairs; without it, ALL_TO_ALL and LINEAR generate their own and
        any other topology needs the pairs supplied.
        """
        nodes = [
            QPUNodeSpec(
                node_id=f"q{i}",
                num_data_qubits=size,
                num_comm_qubits=1 if comm_sizes is None else comm_sizes[i],
            )
            for i, size in enumerate(sizes)
        ]
        if connectivity is None:
            n = len(sizes)
            if topology == NetworkTopology.LINEAR:
                connectivity = [(i, i + 1) for i in range(n - 1)]
            elif topology == NetworkTopology.ALL_TO_ALL:
                connectivity = [(i, j) for i in range(n) for j in range(i + 1, n)]
            else:
                raise ValueError(
                    f"topology {topology.value!r} needs explicit connectivity pairs"
                )
        links = [QPULinkSpec(source=f"q{i}", target=f"q{j}") for i, j in connectivity]
        return cls(name=name, topology=topology, nodes=nodes, links=links)


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------

class QubitAssignment(pydantic.BaseModel):
    """Placement of one circuit qubit on one QPU, optionally at one time step.

    A *static* assignment (``time_step is None``) pins a qubit to a QPU for
    the whole circuit.  A *temporal* assignment gives the qubit a different
    home at different depths — the qubit was teleported in between, which is
    exactly what the partitioner is choosing when it minimises ebits.
    """
    qubit:     int
    node_id:   str
    time_step: int | None = None      # None = static placement


class EntanglementCost(pydantic.BaseModel):
    """Quantum communication consumed by a partitioned execution.

    ``ebits`` is the headline number the partitioners minimise: total EPR
    pairs, counting every hop of a multi-hop route.  ``cat_entanglements``
    and ``teleportations`` split it by mechanism — a cat-entangler distributes
    one control across several QPUs for a group of gates, while a
    teleportation moves a qubit's state outright.
    """
    ebits:             int
    cat_entanglements: int | None      = None
    teleportations:    int | None      = None
    classical_bits:    int | None      = None
    ebits_per_link:    dict[str, int]  = {}     # QPULinkSpec.key -> ebits
    depth_overhead:    int | None      = None   # extra depth from comm operations

    @property
    def num_links_used(self) -> int:
        return sum(1 for v in self.ebits_per_link.values() if v > 0)


class CircuitPartitionSpec(pydantic.BaseModel):
    """A circuit assigned across a quantum network, communicating by teleportation."""
    network:        QPUNetworkSpec
    partitioner:    PartitionerType     = PartitionerType.FIDUCCIA_MATTHEYSES
    coarsening:     CoarseningStrategy  = CoarseningStrategy.NONE
    num_levels:     int | None          = None      # multilevel coarsening depth
    num_qubits:     int | None          = None      # circuit width partitioned
    depth:          int | None          = None      # circuit depth (time steps)
    assignments:    list[QubitAssignment] = []
    strategy:       DistributionStrategy = DistributionStrategy.PARTITION
    metadata:       dict[str, Any]      = {}

    @property
    def is_time_varying(self) -> bool:
        """True if any qubit changes QPU during the circuit (i.e. is teleported)."""
        return any(a.time_step is not None for a in self.assignments)

    @property
    def nodes_used(self) -> list[str]:
        return sorted({a.node_id for a in self.assignments})

    def qubits_per_node(self) -> dict[str, int]:
        """Distinct circuit qubits placed on each QPU at any time."""
        per_node: dict[str, set[int]] = {}
        for a in self.assignments:
            per_node.setdefault(a.node_id, set()).add(a.qubit)
        return {k: len(v) for k, v in per_node.items()}

    def exceeds_capacity(self) -> dict[str, int]:
        """Nodes over their data-register width, mapped to the overflow amount.

        Empty means the assignment fits.  Checked per node against
        ``QPUNodeSpec.num_data_qubits``; nodes absent from the network are
        skipped rather than reported as failures.
        """
        over: dict[str, int] = {}
        for node_id, count in self.qubits_per_node().items():
            node = self.network.node(node_id)
            if node is not None and count > node.num_data_qubits:
                over[node_id] = count - node.num_data_qubits
        return over


# ---------------------------------------------------------------------------
# Cutting
# ---------------------------------------------------------------------------

class CutSpec(pydantic.BaseModel):
    """A single cut point in a circuit.

    A **gate cut** names one two-qubit gate (``gate_id="CZ_2"``) and replaces
    it with a quasiprobability sum over single-qubit operations.  A **wire
    cut** names the pair of gates straddling the wire
    (``endpoints=("H_1", "CZ_2")``) and replaces the wire with a
    measure-and-prepare pair.

    ``overhead_base`` is the number of quasiprobability terms this one cut
    contributes; it defaults from ``kind`` and is overridable for techniques
    with a different decomposition.
    """
    kind:          str                       # "gate" | "wire" | "hadamard"
    gate_id:       str | None    = None      # gate cuts
    endpoints:     list[str]     = []        # wire cuts: [source_gate, target_gate]
    qubits:        list[int]     = []        # circuit qubits touched
    overhead_base: int | None    = None      # terms this cut expands into

    @property
    def terms(self) -> int:
        """Quasiprobability terms for this cut (6 gate / 8 wire by default)."""
        if self.overhead_base is not None:
            return self.overhead_base
        return WIRE_CUT_OVERHEAD_BASE if self.kind == "wire" else GATE_CUT_OVERHEAD_BASE


class CircuitCutSpec(pydantic.BaseModel):
    """A circuit decomposed into independent subcircuits by cutting.

    Unlike partitioning there is no quantum link between the pieces: the
    subcircuits run anywhere, in any order, and the original observable is
    recovered classically.  The price is ``sampling_overhead`` evaluations.
    """
    strategy:                  DistributionStrategy = DistributionStrategy.GATE_CUT
    cuts:                      list[CutSpec]        = []
    num_subcircuits:           int | None           = None
    max_qubits_per_subcircuit: int | None           = None
    num_qubits:                int | None           = None   # original circuit width
    observables:               list[str]            = []     # Pauli strings measured
    reconstruction:            ReconstructionMethod = ReconstructionMethod.QUASIPROBABILITY
    metadata:                  dict[str, Any]       = {}

    @property
    def num_cuts(self) -> int:
        return len(self.cuts)

    @property
    def sampling_overhead(self) -> int:
        """Subcircuit configurations the reconstruction must evaluate.

        The product of each cut's term count — ``6**k`` for k gate cuts,
        ``8**k`` for wire cuts, and the mixed product when both are used.
        This factor, not subcircuit size, is what dominates the cost of a cut
        run, so size a benchmark by this number before launching it.
        """
        return math.prod(c.terms for c in self.cuts) if self.cuts else 1

    def cuts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.cuts:
            counts[c.kind] = counts.get(c.kind, 0) + 1
        return counts


class SubcircuitSpec(pydantic.BaseModel):
    """One independently executable piece of a distributed circuit.

    Produced by cutting (a quasiprobability term) or by partitioning (the
    per-QPU register of the extracted circuit).  ``qubit_map`` records which
    original circuit qubits this piece holds, which is what makes results
    reassemblable.
    """
    subcircuit_id: str
    num_qubits:    int
    qubit_map:     list[int]         = []      # index -> original circuit qubit
    node_id:       str | None        = None    # QPU this piece is assigned to
    circuit:       CircuitSpec | None = None
    shots:         int | None        = None
    backend_name:  str | None        = None
    term_index:    int | None        = None    # index into the quasiprobability sum
    metadata:      dict[str, Any]    = {}


class SubcircuitResult(pydantic.BaseModel):
    """Outcome of evaluating one subcircuit."""
    subcircuit_id:     str
    expectation_value: float | None       = None
    counts:            dict[str, int]     = {}
    shots:             int | None         = None
    coefficient:       float              = 1.0   # quasiprobability weight (may be negative)
    wall_seconds:      float | None       = None
    node_id:           str | None         = None
    backend_name:      str | None         = None
    status:            JobStatus          = JobStatus.SUCCEEDED
    record_id:         str | None         = None  # -> BenchmarkRecord.experiment_id
    error_message:     str | None         = None


class ReconstructionResult(pydantic.BaseModel):
    """The observable recovered from the subcircuit results."""
    value:                     float
    std_error:                 float | None         = None
    method:                    ReconstructionMethod = ReconstructionMethod.QUASIPROBABILITY
    num_terms:                 int | None           = None   # terms in the sum
    num_subcircuit_evaluations: int | None          = None
    sampling_overhead:         int | None           = None
    exact_value:               float | None         = None   # noiseless reference

    @property
    def error(self) -> float | None:
        """|value - exact_value|, or None without a reference."""
        if self.exact_value is None:
            return None
        return abs(self.value - self.exact_value)


class DistributedRunConfig(pydantic.BaseModel):
    """Execution-layer hyperparameters for a distributed run.

    Package-agnostic: the same config drives a DISQCO partitioning run and a
    Qdislib cutting run, with the unused half left at its default.  Attach it
    to ``ExecutionOptions.distributed_run_config``; the resulting *choices*
    (which gates were cut, which qubit went where) are outputs and belong on
    ``CircuitSpec.distribution`` instead.
    """
    strategy:                  DistributionStrategy = DistributionStrategy.NONE
    max_qubits_per_subcircuit: int | None           = None
    max_cuts:                  int | None           = None
    allow_gate_cut:            bool                 = True
    allow_wire_cut:            bool                 = True
    partitioner:               PartitionerType | None    = None
    coarsening:                CoarseningStrategy        = CoarseningStrategy.NONE
    num_levels:                int | None           = None
    num_passes:                int                  = 1
    shots_per_subcircuit:      int | None           = None
    reconstruct:               bool                 = True
    reconstruction:            ReconstructionMethod = ReconstructionMethod.QUASIPROBABILITY
    seed:                      int | None           = None
    software:                  str | None           = None   # subcircuit emission target
    num_workers:               int | None           = None   # distributed runtime workers
    options:                   dict[str, Any]       = {}


class DistributedRunResult(pydantic.BaseModel):
    """Complete record of running one circuit across multiple QPUs.

    Whichever strategy was used, the comparable numbers are here: the
    ``entanglement_cost`` a partitioned run paid, the ``sampling_overhead`` a
    cut run paid, and the wall time and subcircuit count for both.
    """
    strategy:           DistributionStrategy
    network:            QPUNetworkSpec | None       = None
    partition:          CircuitPartitionSpec | None = None
    cut:                CircuitCutSpec | None       = None
    entanglement_cost:  EntanglementCost | None     = None
    subcircuit_results: list[SubcircuitResult]      = []
    reconstruction:     ReconstructionResult | None = None
    cost_history:       list[float]                 = []     # optimiser cost per pass
    partition_seconds:  float | None                = None
    find_cut_seconds:   float | None                = None
    execute_seconds:    float | None                = None
    total_wall_seconds: float | None                = None
    num_workers:        int | None                  = None
    status:             JobStatus                   = JobStatus.SUCCEEDED
    error_message:      str | None                  = None
    metadata:           dict[str, Any]              = {}

    @property
    def num_subcircuits(self) -> int:
        return len(self.subcircuit_results)

    @property
    def total_shots(self) -> int:
        return sum(r.shots or 0 for r in self.subcircuit_results)

    @property
    def ebits(self) -> int | None:
        """EPR pairs consumed, or None for a cutting run (which uses none)."""
        return None if self.entanglement_cost is None else self.entanglement_cost.ebits

    @property
    def sampling_overhead(self) -> int | None:
        """Quasiprobability terms, or None for a partitioning run."""
        return None if self.cut is None else self.cut.sampling_overhead

    @property
    def communication_cost(self) -> int | None:
        """The single number this strategy pays for being distributed.

        EPR pairs for a partitioned run, quasiprobability terms for a cut
        run.  They are not the same currency — this is for reporting which
        knob a run is dominated by, not for comparing the two directly.
        """
        return self.ebits if self.ebits is not None else self.sampling_overhead

    @property
    def failed_subcircuits(self) -> list[SubcircuitResult]:
        return [r for r in self.subcircuit_results if r.status != JobStatus.SUCCEEDED]

    def to_quantum_result(
        self,
        computing_model: ComputingModel = ComputingModel.GATE_BASED,
    ) -> QuantumResult:
        """Bridge to QuantumResult with the reconstructed observable."""
        expectations = None
        if self.reconstruction is not None:
            expectations = [
                ExpectationResult(
                    observable_index=0,
                    value=self.reconstruction.value,
                    std_error=self.reconstruction.std_error or 0.0,
                )
            ]
        return QuantumResult(
            computing_model=computing_model,
            expectation_values=expectations,
            status=self.status,
            error_message=self.error_message,
            wall_seconds=self.total_wall_seconds,
            metadata={
                "strategy": self.strategy.value,
                "num_subcircuits": self.num_subcircuits,
                "ebits": self.ebits,
                "sampling_overhead": self.sampling_overhead,
                "num_qpus": self.network.num_nodes if self.network else None,
            },
            vendor_results={"distributed_run_result": self.model_dump()},
        )


__all__ = [
    "GATE_CUT_OVERHEAD_BASE",
    "WIRE_CUT_OVERHEAD_BASE",
    "CircuitCutSpec",
    "CircuitPartitionSpec",
    "CoarseningStrategy",
    "CutSpec",
    "DistributedRunConfig",
    "DistributedRunResult",
    "DistributionStrategy",
    "EntanglementCost",
    "NetworkTopology",
    "PartitionerType",
    "QPULinkSpec",
    "QPUNetworkSpec",
    "QPUNodeSpec",
    "QubitAssignment",
    "ReconstructionMethod",
    "ReconstructionResult",
    "SubcircuitResult",
    "SubcircuitSpec",
]
