"""DISQCO — distributed quantum circuit optimisation over a QPU network.

Upstream: https://github.com/felix-burt/DISQCO.  Implements:

* Burt et al., *A Multilevel Framework for Partitioning Quantum Circuits*
  (arXiv:2503.19082) — the temporal-hypergraph model and the multilevel
  Fiduccia-Mattheyses partitioner.
* *Entanglement-Efficient Distribution of Quantum Circuits over Large-Scale
  Quantum Networks* (arXiv:2507.16036) — general (non-complete) network
  topologies and network coarsening.

The model
---------
A circuit becomes a **temporally extended hypergraph**: a vertex per
``(qubit, time)`` and a hyperedge per group of gates that can share one
distributed control.  Partitioning that hypergraph assigns every vertex to a
QPU; because vertices are time-resolved, a qubit may sit on different QPUs at
different depths — the partitioner is choosing *when to teleport*.  The
objective is the number of auxiliary EPR pairs (ebits) consumed, counted along
real network routes, so a partition that looks cheap on a complete graph can
be expensive on a linear one.

Multilevel means two different things here, both recorded:

* **hypergraph coarsening** — contract the circuit's time axis into a
  hierarchy, partition the coarsest level, project down and refine
  (``DisqcoCoarsener``);
* **network coarsening** — contract the *network* into sub-regions and
  partition hierarchically across them (``DisqcoCoarsener.NETWORK``).

Bridges into ``distributed_execution``: ``DisqcoNetworkSpec.to_network_spec()``
and ``DisqcoPartitionResult.to_partition_spec()`` /
``.to_distributed_run_result()``.

Assignment array convention
---------------------------
Upstream, an assignment is a NumPy array indexed ``[qubit][time]`` holding a
QPU *index*.  ``DisqcoPartitionResult.assignment`` keeps that layout as nested
lists, and the conversion helpers map indices to ``QPUNodeSpec.node_id``
strings via the network's node ordering — so the index order in
``DisqcoNetworkSpec.qpu_sizes`` is significant.
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic

from .circuit import CircuitSpec
from .distributed_execution import (
    CircuitPartitionSpec,
    CoarseningStrategy,
    DistributedRunResult,
    DistributionStrategy,
    EntanglementCost,
    NetworkTopology,
    PartitionerType,
    QPULinkSpec,
    QPUNetworkSpec,
    QPUNodeSpec,
    QubitAssignment,
    ReconstructionMethod,
    ReconstructionResult,
)
from .primitives import CircuitFormat, ComputingModel, JobStatus


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class DisqcoPartitionerType(str, enum.Enum):
    """Partitioners reachable through ``QuantumCircuitPartitioner.create``."""
    FM      = "fm"        # Fiduccia-Mattheyses on the temporal hypergraph
    GENETIC = "genetic"   # genetic search over assignments
    FGP     = "fgp"       # fine-grained partitioning

    def to_partitioner_type(self, multilevel: bool = False) -> PartitionerType:
        if self is DisqcoPartitionerType.FM:
            return (
                PartitionerType.MULTILEVEL_FM if multilevel
                else PartitionerType.FIDUCCIA_MATTHEYSES
            )
        return {
            DisqcoPartitionerType.GENETIC: PartitionerType.GENETIC,
            DisqcoPartitionerType.FGP: PartitionerType.FGP,
        }[self]


class DisqcoCoarsener(str, enum.Enum):
    """Temporal coarseners in ``graphs/coarsening/coarsener.py``.

    They differ in how aggressively they contract the time axis, trading
    partition quality against runtime — which one was used is part of
    reproducing a benchmark number.
    """
    NONE               = "none"
    FULL               = "coarsen_full"
    STATIC             = "coarsen_static"
    BLOCKS             = "coarsen_blocks"
    RECURSIVE          = "coarsen_recursive"
    RECURSIVE_BATCHES  = "coarsen_recursive_batches"
    RECURSIVE_MAPPED   = "coarsen_recursive_mapped"
    SUBGRAPH           = "coarsen_recursive_subgraph"
    NETWORK            = "network_coarsener"

    def to_strategy(self) -> CoarseningStrategy:
        return {
            DisqcoCoarsener.NONE: CoarseningStrategy.NONE,
            DisqcoCoarsener.FULL: CoarseningStrategy.FULL,
            DisqcoCoarsener.STATIC: CoarseningStrategy.STATIC,
            DisqcoCoarsener.BLOCKS: CoarseningStrategy.BLOCKS,
            DisqcoCoarsener.RECURSIVE: CoarseningStrategy.RECURSIVE,
            DisqcoCoarsener.RECURSIVE_BATCHES: CoarseningStrategy.RECURSIVE_BATCHES,
            DisqcoCoarsener.RECURSIVE_MAPPED: CoarseningStrategy.RECURSIVE,
            DisqcoCoarsener.SUBGRAPH: CoarseningStrategy.SUBGRAPH,
            DisqcoCoarsener.NETWORK: CoarseningStrategy.NETWORK,
        }[self]


class DisqcoNetworkCoupling(str, enum.Enum):
    """``QuantumNetwork.create`` coupling types."""
    ALL_TO_ALL       = "all_to_all"
    LINEAR           = "linear"
    GRID             = "grid"
    RANDOM           = "random"
    TREE             = "tree"
    NETWORK_OF_GRIDS = "network_of_grids"

    def to_topology(self) -> NetworkTopology:
        return {
            DisqcoNetworkCoupling.ALL_TO_ALL: NetworkTopology.ALL_TO_ALL,
            DisqcoNetworkCoupling.LINEAR: NetworkTopology.LINEAR,
            DisqcoNetworkCoupling.GRID: NetworkTopology.GRID,
            DisqcoNetworkCoupling.RANDOM: NetworkTopology.RANDOM,
            DisqcoNetworkCoupling.TREE: NetworkTopology.TREE,
            DisqcoNetworkCoupling.NETWORK_OF_GRIDS: NetworkTopology.NETWORK_OF_GRIDS,
        }[self]


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

class DisqcoNetworkSpec(pydantic.BaseModel):
    """Mirrors ``graphs/quantum_network.py::QuantumNetwork``.

    ``qpu_sizes`` maps a QPU index to its data-qubit count and ``comm_sizes``
    to its communication-qubit count (default 1 each).  ``hetero`` is upstream's
    flag for "explicit connectivity was supplied", i.e. the network is not
    complete — it changes the cost model, because entanglement between
    unconnected QPUs must be routed and pays per hop.
    """
    qpu_sizes:        dict[int, int]
    comm_sizes:       dict[int, int]           = {}
    connectivity:     list[list[int]]          = []      # [i, j] index pairs
    coupling_type:    DisqcoNetworkCoupling    = DisqcoNetworkCoupling.ALL_TO_ALL
    hetero:           bool                     = False
    name:             str                      = "disqco_network"

    @property
    def num_qpus(self) -> int:
        return len(self.qpu_sizes)

    @property
    def total_qubits(self) -> int:
        return sum(self.qpu_sizes.values())

    def node_id(self, index: int) -> str:
        """Stable node name for a QPU index (``0 -> "q0"``)."""
        return f"q{index}"

    def to_network_spec(self) -> QPUNetworkSpec:
        """Convert to the framework-general network.

        A complete network with no explicit ``connectivity`` gets its
        all-to-all links generated, matching upstream's default.
        """
        indices = sorted(self.qpu_sizes)
        nodes = [
            QPUNodeSpec(
                node_id=self.node_id(i),
                num_data_qubits=self.qpu_sizes[i],
                num_comm_qubits=self.comm_sizes.get(i, 1),
            )
            for i in indices
        ]
        pairs = self.connectivity
        if not pairs:
            pairs = [
                [indices[a], indices[b]]
                for a in range(len(indices))
                for b in range(a + 1, len(indices))
            ]
        links = [
            QPULinkSpec(source=self.node_id(i), target=self.node_id(j)) for i, j in pairs
        ]
        return QPUNetworkSpec(
            name=self.name,
            topology=self.coupling_type.to_topology(),
            nodes=nodes,
            links=links,
            metadata={"source": "felix-burt/DISQCO", "hetero": self.hetero},
        )


class DisqcoHypergraphStats(pydantic.BaseModel):
    """Shape of the temporal hypergraph built from a circuit.

    ``group_gates`` and ``anti_diag`` control how aggressively gates are
    packed into shared hyperedges before partitioning; they materially change
    the achievable ebit count, so they belong in the record.
    """
    num_qubits:     int
    depth:          int                # time steps after layering
    num_nodes:      int | None = None  # (qubit, time) vertices
    num_hyperedges: int | None = None
    basis_gates:    list[str]  = []
    group_gates:    bool       = True  # merge distributable gate packets
    anti_diag:      bool       = True  # also group anti-diagonal gates


class DisqcoFMConfig(pydantic.BaseModel):
    """Hyperparameters of a Fiduccia-Mattheyses / multilevel FM run."""
    partitioner:  DisqcoPartitionerType = DisqcoPartitionerType.FM
    num_passes:   int                   = 1
    limit_fraction: float               = 0.125   # nodes moved per pass, as a fraction
    coarsener:    DisqcoCoarsener       = DisqcoCoarsener.NONE
    num_levels:   int | None            = None
    num_blocks:   int | None            = None
    block_size:   int | None            = None
    level_limit:  int                   = 100
    sparse:       bool                  = False
    seed:         int | None            = None
    options:      dict[str, Any]        = {}

    @property
    def is_multilevel(self) -> bool:
        return self.coarsener is not DisqcoCoarsener.NONE


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class DisqcoPartitionResult(pydantic.BaseModel):
    """Output of ``run_FM`` / ``multilevel_partition``.

    ``final_cost`` is the objective the partitioner minimised: the number of
    auxiliary EPR pairs the assignment requires.  ``cost_list`` is the cost
    after each pass, which is what convergence plots are drawn from, and
    ``time_list`` its per-pass timing when the benchmarking variant was used.
    """
    final_cost:       float
    assignment:       list[list[int]]        = []   # [qubit][time] -> QPU index
    cost_list:        list[float]            = []   # cost after each pass
    time_list:        list[float]            = []   # cumulative seconds per pass
    num_partitions:   int | None             = None
    network:          DisqcoNetworkSpec | None    = None
    hypergraph:       DisqcoHypergraphStats | None = None
    config:           DisqcoFMConfig | None   = None
    wall_seconds:     float | None            = None
    status:           JobStatus               = JobStatus.SUCCEEDED

    @property
    def ebits(self) -> int:
        """The final objective value as an integer EPR-pair count."""
        return int(round(self.final_cost))

    @property
    def initial_cost(self) -> float | None:
        return self.cost_list[0] if self.cost_list else None

    @property
    def improvement(self) -> float | None:
        """Ebits saved relative to the initial assignment."""
        return None if not self.cost_list else self.cost_list[0] - self.final_cost

    @property
    def is_time_varying(self) -> bool:
        """True if any qubit's QPU changes during the circuit — i.e. it teleports."""
        return any(len(set(row)) > 1 for row in self.assignment)

    def to_entanglement_cost(self) -> EntanglementCost:
        return EntanglementCost(ebits=self.ebits)

    def to_partition_spec(self) -> CircuitPartitionSpec:
        """Convert to the framework-general partition spec.

        Requires ``network`` — the QPU indices in ``assignment`` are
        meaningless without the network that names them.
        """
        if self.network is None:
            raise ValueError("to_partition_spec() needs `network` to name the QPU indices")
        assignments = [
            QubitAssignment(qubit=q, node_id=self.network.node_id(node), time_step=t)
            for q, row in enumerate(self.assignment)
            for t, node in enumerate(row)
        ]
        cfg = self.config
        return CircuitPartitionSpec(
            network=self.network.to_network_spec(),
            partitioner=(
                cfg.partitioner.to_partitioner_type(cfg.is_multilevel)
                if cfg
                else PartitionerType.FIDUCCIA_MATTHEYSES
            ),
            coarsening=cfg.coarsener.to_strategy() if cfg else CoarseningStrategy.NONE,
            num_levels=cfg.num_levels if cfg else None,
            num_qubits=self.hypergraph.num_qubits if self.hypergraph else None,
            depth=self.hypergraph.depth if self.hypergraph else None,
            assignments=assignments,
            metadata={"source": "felix-burt/DISQCO", "final_cost": self.final_cost},
        )

    def to_distributed_run_result(self) -> DistributedRunResult:
        """Bridge to the framework-general distributed-run record."""
        return DistributedRunResult(
            strategy=DistributionStrategy.PARTITION,
            network=self.network.to_network_spec() if self.network else None,
            partition=self.to_partition_spec() if self.network else None,
            entanglement_cost=self.to_entanglement_cost(),
            reconstruction=ReconstructionResult(
                value=self.final_cost, method=ReconstructionMethod.LOCC
            ),
            cost_history=self.cost_list,
            partition_seconds=self.wall_seconds,
            total_wall_seconds=self.wall_seconds,
            status=self.status,
            metadata={"source": "felix-burt/DISQCO"},
        )


class DisqcoExtractedCircuit(pydantic.BaseModel):
    """Output of ``PartitionedCircuitExtractor``.

    The extractor emits a single Qiskit circuit in which each QPU is a pair of
    registers — data qubits and communication qubits — sharing one classical
    register for LOCC.  ``epr_pairs_requested`` counts only *directly linked*
    node pairs, since that is all the hardware can generate; multi-hop
    entanglement appears as several such requests along the route.
    """
    num_data_qubits:     int
    num_comm_qubits:     int
    num_clbits:          int
    depth:               int | None      = None
    epr_pairs_requested: int | None      = None
    epr_pairs_per_link:  dict[str, int]  = {}     # "q0<->q1" -> count
    gate_counts:         dict[str, int]  = {}
    qasm:                str | None      = None
    verified:            bool | None     = None   # circuit_extraction/verification.py

    @property
    def total_qubits(self) -> int:
        return self.num_data_qubits + self.num_comm_qubits

    def to_circuit_spec(self) -> CircuitSpec:
        """Wrap the extracted circuit as a CircuitSpec.

        Falls back to ``CircuitFormat.JSON`` with no ``serialized`` payload
        when no QASM was captured, so the spec still records the shape and
        gate counts of the extracted circuit.
        """
        return CircuitSpec(
            computing_model=ComputingModel.GATE_BASED,
            num_qubits=self.total_qubits,
            num_classical_bits=self.num_clbits,
            format=CircuitFormat.QASM2 if self.qasm else CircuitFormat.JSON,
            serialized=self.qasm,
            gate_counts=self.gate_counts,
        )

    def to_entanglement_cost(self) -> EntanglementCost:
        return EntanglementCost(
            ebits=self.epr_pairs_requested or sum(self.epr_pairs_per_link.values()),
            ebits_per_link=self.epr_pairs_per_link,
            classical_bits=self.num_clbits,
        )


__all__ = [
    "DisqcoCoarsener",
    "DisqcoExtractedCircuit",
    "DisqcoFMConfig",
    "DisqcoHypergraphStats",
    "DisqcoNetworkCoupling",
    "DisqcoNetworkSpec",
    "DisqcoPartitionResult",
    "DisqcoPartitionerType",
]
