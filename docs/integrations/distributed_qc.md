# Distributed quantum execution — decomposing the circuit

When a circuit does not fit on one QPU there are two ways out, and they pay in
different currencies. qpubench models both with one general schema plus two
project mirrors:

| Module | Upstream | Role |
|---|---|---|
| `qpubench.schemas.catalogs.distributed_execution` | — (framework-general) | Shared vocabulary: networks, partitions, cuts, reconstruction |
| `qpubench.schemas.mirrors.felixburt_disqco` | [felix-burt/DISQCO](https://github.com/felix-burt/DISQCO) | Multilevel hypergraph partitioning over a QPU network |
| `qpubench.schemas.mirrors.bscwdc_qdislib` | [bsc-wdc/qdislib](https://github.com/bsc-wdc/qdislib) | Gate/wire cutting with quasiprobability reconstruction |

Neither upstream package is a dependency.

## Partitioning vs cutting

**Partitioning** keeps one entangled computation and teleports qubits between
QPUs.

- Cost: **EPR pairs (ebits)**, counted per hop along real network routes.
- Grows with the *cut size* of the partition; linear in circuit repetitions.
- Requires a quantum network.

**Cutting** breaks the circuit into genuinely independent subcircuits with no
quantum link at all.

- Cost: **classical sampling overhead** — 6 quasiprobability terms per gate
  cut, 8 per wire cut, so `k` cuts need `base ** k` subcircuit evaluations.
- Exponential in the number of cuts, but embarrassingly parallel.
- Requires no quantum network.

Sharing `QPUNetworkSpec`, `SubcircuitSpec` and `DistributedRunResult` across
both is what makes them comparable: the same circuit can be benchmarked either
way and read off one set of fields.

```python
run.ebits                 # partitioning: EPR pairs;   cutting: None
run.sampling_overhead     # cutting: terms;            partitioning: None
run.communication_cost    # whichever one applies
```

> `communication_cost` reports the knob a run is dominated by. Ebits and
> quasiprobability terms are **not** the same unit — do not divide one by the
> other.

## Describing the network

```python
from qpubench.schemas.catalogs.distributed_execution import NetworkTopology, QPUNetworkSpec

net = QPUNetworkSpec.from_sizes([8, 8, 8, 8], topology=NetworkTopology.LINEAR)
net.total_data_qubits     # 32
net.is_homogeneous        # True
net.neighbors("q1")       # ['q0', 'q2']
net.is_connected()        # True
```

`num_comm_qubits` is separate from the data register on purpose: it is the
count reserved for holding halves of EPR pairs, and it caps how many
teleportations can be in flight at once.

Only directly connected nodes can generate EPR pairs. Long-range entanglement
is routed along a path of links, consuming auxiliary pairs at every hop — which
is why a partition that is cheap on an all-to-all network can be expensive on a
linear one, and why topology is a recorded field rather than an assumption.

## Sizing a cut before you run it

The sampling overhead — not subcircuit size — dominates the cost of a cut run.
Check it first:

```python
from qpubench.schemas.mirrors.bscwdc_qdislib import max_cuts_for_budget, sampling_overhead

sampling_overhead(num_gate_cuts=3)                   # 216
sampling_overhead(num_gate_cuts=2, num_wire_cuts=1)  # 288
max_cuts_for_budget(10_000)                          # 5 gate cuts fit
```

`CircuitCutSpec.sampling_overhead` computes the same product from an actual
cut, including mixed gate + wire cuts.

## DISQCO (`felixburt_disqco`)

A circuit becomes a **temporally extended hypergraph** — a vertex per
`(qubit, time)`, a hyperedge per group of gates that can share one distributed
control. Partitioning assigns every vertex to a QPU; because vertices are
time-resolved, a qubit may live on different QPUs at different depths. The
partitioner is choosing *when to teleport*.

```python
from qpubench.schemas.mirrors.felixburt_disqco import (
    DisqcoCoarsener, DisqcoFMConfig, DisqcoNetworkSpec, DisqcoPartitionResult,
)

network = DisqcoNetworkSpec(qpu_sizes={0: 4, 1: 4}, comm_sizes={0: 1, 1: 1})
result = DisqcoPartitionResult(
    final_cost=6.0,
    assignment=[[0, 0, 1], [0, 1, 1], [1, 1, 1], [1, 1, 1]],   # [qubit][time]
    cost_list=[11.0, 8.0, 6.0],
    network=network,
    config=DisqcoFMConfig(coarsener=DisqcoCoarsener.RECURSIVE, num_levels=3),
)

result.ebits              # 6
result.improvement        # 5.0 saved vs the initial assignment
result.is_time_varying    # True -> qubits are teleported mid-circuit
result.to_partition_spec()
result.to_distributed_run_result()
```

### Assignment array convention

Upstream an assignment is a NumPy array indexed `[qubit][time]` holding a QPU
**index**. `DisqcoPartitionResult.assignment` keeps that layout as nested
lists, and the converters map indices to `QPUNodeSpec.node_id` strings via the
network's node ordering — so the index order in `DisqcoNetworkSpec.qpu_sizes`
is significant. `to_partition_spec()` raises without a `network`, because the
indices are meaningless unnamed.

### Two kinds of "multilevel"

Both are recorded:

- **Hypergraph coarsening** (`DisqcoCoarsener.RECURSIVE`, `BLOCKS`, …) —
  contract the circuit's time axis into a hierarchy, partition the coarsest
  level, project down and refine.
- **Network coarsening** (`DisqcoCoarsener.NETWORK`) — contract the *network*
  into sub-regions and partition hierarchically across them, for large-scale
  networks.

`group_gates` and `anti_diag` on `DisqcoHypergraphStats` control how
aggressively gates are packed into shared hyperedges before partitioning. They
materially change the achievable ebit count, so they belong in the record.

### Circuit extraction

The extractor emits one Qiskit circuit in which each QPU is a pair of registers
— data and communication qubits — sharing one classical register for LOCC.

```python
extracted.epr_pairs_per_link     # {"q0<->q1": 6}
extracted.to_circuit_spec()
extracted.to_entanglement_cost()
```

`epr_pairs_requested` counts only *directly linked* node pairs, since that is
all the hardware can generate; multi-hop entanglement appears as several
requests along the route.

## Qdislib (`bscwdc_qdislib`)

Cutting replaces a two-qubit gate or a wire with a quasiprobability
decomposition. Every subcircuit evaluation is independent, which is exactly the
shape PyCOMPSs distributes across CPUs, GPUs and QPUs.

Upstream names cuts by gate label and callers dispatch on the element shape —
a gate cut is `["CZ_2"]`, a wire cut a pair `[("H_1", "CZ_2")]`.
`from_find_cut()` applies that same shape test once and stores the kind
explicitly, so a stored record never re-infers it:

```python
from qpubench.schemas.mirrors.bscwdc_qdislib import QdislibCutCost, QdislibCutRecord

cut = QdislibCutRecord.from_find_cut(["CZ_2", "CZ_5"])
cut.kind        # QdislibCutKind.GATE
cut.terms       # 36
cut.to_cut_spec(num_qubits=10)

# ingest qd.cut_cost(...) verbatim
QdislibCutCost.from_cut_cost({"num_cuts": 2, "kind": "gate", "base": 6, "terms": 36})
```

A full run, including the accuracy check against an uncut reference:

```python
run = QdislibRunRecord(
    circuit_qubits=10,
    cut=cut,
    subcircuits=[...],
    expectation_value=-0.717,
    exact_value=-0.715,          # analytical_solution / exact_statevector
    num_workers=64,
)
run.error                # 0.002
run.qubit_reduction      # qubits saved on the widest subcircuit
run.cache_hit_rate
run.to_distributed_run_result()
```

`software` must match the backend the subcircuits are evaluated on — Qdislib
emits subcircuits in the target SDK's own circuit type and does not convert at
execution time.

The three-step workflow (`*_subcircuits` → evaluate → `reconstruct`) puts the
evaluation loop under the caller's control, so where each subcircuit ran —
simulator, GPU, remote QPU — varies within a single run. That is why
`executed_on` and `cache_hit` are per-subcircuit fields.

The **semantic cache** keys on circuit semantics, so structurally different but
equivalent subcircuits share an entry — that is where the speedup in
arXiv:2604.26788 comes from, and why the hit rate is worth recording alongside
the wall time it explains.

## Attaching to a benchmark record

Inputs go on `ExecutionOptions`, choices on `CircuitSpec`, outcomes in
`QuantumResult.vendor_results`:

```python
from qpubench import CircuitSpec, ExecutionOptions
from qpubench.schemas.catalogs.distributed_execution import (
    CircuitCutSpec, DistributedRunConfig, DistributionStrategy,
)

options = ExecutionOptions(
    distributed_run_config=DistributedRunConfig(     # model or dict
        strategy=DistributionStrategy.GATE_CUT,
        max_qubits_per_subcircuit=5,
        max_cuts=3,
        shots_per_subcircuit=8192,
    ),
)
circuit = CircuitSpec(num_qubits=10, distribution=cut.to_cut_spec(10))
result  = run.to_quantum_result()

# rehydrate
DistributedRunConfig.model_validate(options.distributed_run_config)
CircuitCutSpec.model_validate(circuit.distribution)
```

The split is deliberate: `DistributedRunConfig` holds the *budgets and
strategy* you asked for, `CircuitSpec.distribution` holds the *decision* the
tool made — which gates it cut, which qubit it put where.

## Composing with fragmentation

A [fragmented](fragmentation.md) calculation produces one quantum subproblem
per fragment. Each is an ordinary circuit, and a fragment too wide for one QPU
is cut or partitioned like any other:

```python
frag_result.record_id            # -> BenchmarkRecord.experiment_id
                                 #    whose CircuitSpec.distribution holds the cut
```

That is the full pipeline: fragment the molecule, solve each fragment on a QPU,
and distribute the fragments whose circuits still do not fit.
