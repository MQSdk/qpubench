"""Distributed-execution schema tests — general module plus DISQCO / Qdislib.

Schema layer only: neither upstream package is installed or imported.
"""
from __future__ import annotations

import json

import pytest

from qpubench.schemas.catalogs.distributed_execution import (
    GATE_CUT_OVERHEAD_BASE,
    WIRE_CUT_OVERHEAD_BASE,
    CircuitCutSpec,
    CircuitPartitionSpec,
    CoarseningStrategy,
    CutSpec,
    DistributedRunConfig,
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
    SubcircuitResult,
)
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.mirrors.bscwdc_qdislib import (
    QdislibCacheStats,
    QdislibCutCost,
    QdislibCutKind,
    QdislibCutRecord,
    QdislibEstimateMetrics,
    QdislibRunRecord,
    QdislibSoftware,
    QdislibSubcircuit,
    QdislibSubcircuitResult,
    max_cuts_for_budget,
    sampling_overhead,
)
from qpubench.schemas.mirrors.felixburt_disqco import (
    DisqcoCoarsener,
    DisqcoExtractedCircuit,
    DisqcoFMConfig,
    DisqcoNetworkCoupling,
    DisqcoNetworkSpec,
    DisqcoPartitionerType,
    DisqcoPartitionResult,
)
from qpubench.schemas.primitives import JobStatus

# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------

def test_from_sizes_generates_linear_and_all_to_all_connectivity():
    line = QPUNetworkSpec.from_sizes([8, 8, 8, 8], topology=NetworkTopology.LINEAR)
    assert line.num_nodes == 4 and line.total_data_qubits == 32
    assert len(line.links) == 3
    assert line.neighbors("q1") == ["q0", "q2"]
    assert line.is_connected()

    full = QPUNetworkSpec.from_sizes([4, 4, 4])
    assert len(full.links) == 3          # complete graph on 3 nodes
    assert sorted(full.neighbors("q0")) == ["q1", "q2"]


def test_from_sizes_requires_explicit_pairs_for_other_topologies():
    with pytest.raises(ValueError, match="needs explicit connectivity"):
        QPUNetworkSpec.from_sizes([4] * 9, topology=NetworkTopology.GRID)


def test_comm_qubits_are_tracked_separately_from_data_qubits():
    net = QPUNetworkSpec.from_sizes([8, 8], comm_sizes=[2, 3])
    assert net.total_data_qubits == 16
    assert net.total_comm_qubits == 5
    assert net.node("q1").total_qubits == 11


def test_disconnected_network_is_detected():
    net = QPUNetworkSpec(
        name="split",
        nodes=[QPUNodeSpec(node_id=f"q{i}", num_data_qubits=4) for i in range(4)],
        links=[QPULinkSpec(source="q0", target="q1"), QPULinkSpec(source="q2", target="q3")],
    )
    assert not net.is_connected()
    assert net.is_homogeneous


def test_link_key_is_undirected_and_canonical():
    assert QPULinkSpec(source="q3", target="q1").key == "q1<->q3"
    assert QPULinkSpec(source="q1", target="q3").key == "q1<->q3"


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------

def test_time_varying_assignment_means_teleportation():
    net = QPUNetworkSpec.from_sizes([2, 2], topology=NetworkTopology.LINEAR)
    static = CircuitPartitionSpec(
        network=net,
        assignments=[QubitAssignment(qubit=0, node_id="q0"),
                     QubitAssignment(qubit=1, node_id="q1")],
    )
    assert not static.is_time_varying

    moving = CircuitPartitionSpec(
        network=net,
        assignments=[QubitAssignment(qubit=0, node_id="q0", time_step=0),
                     QubitAssignment(qubit=0, node_id="q1", time_step=1)],
    )
    assert moving.is_time_varying
    assert moving.nodes_used == ["q0", "q1"]


def test_exceeds_capacity_reports_the_overflow_per_node():
    net = QPUNetworkSpec.from_sizes([2, 8], topology=NetworkTopology.LINEAR)
    spec = CircuitPartitionSpec(
        network=net,
        assignments=[QubitAssignment(qubit=q, node_id="q0") for q in range(5)],
    )
    assert spec.qubits_per_node() == {"q0": 5}
    assert spec.exceeds_capacity() == {"q0": 3}


def test_capacity_check_ignores_nodes_absent_from_the_network():
    net = QPUNetworkSpec.from_sizes([2, 2], topology=NetworkTopology.LINEAR)
    spec = CircuitPartitionSpec(
        network=net,
        assignments=[QubitAssignment(qubit=q, node_id="q9") for q in range(5)],
    )
    assert spec.exceeds_capacity() == {}


# ---------------------------------------------------------------------------
# Cutting overhead
# ---------------------------------------------------------------------------

def test_cut_overhead_defaults_to_six_for_gates_and_eight_for_wires():
    assert CutSpec(kind="gate", gate_id="CZ_2").terms == GATE_CUT_OVERHEAD_BASE
    assert CutSpec(kind="wire", endpoints=["H_1", "CZ_2"]).terms == WIRE_CUT_OVERHEAD_BASE
    assert CutSpec(kind="hadamard", gate_id="CX_4", overhead_base=4).terms == 4


def test_sampling_overhead_is_the_product_over_cuts():
    spec = CircuitCutSpec(
        cuts=[
            CutSpec(kind="gate", gate_id="CZ_1"),
            CutSpec(kind="gate", gate_id="CZ_2"),
            CutSpec(kind="wire", endpoints=["H_1", "CZ_3"]),
        ],
    )
    assert spec.num_cuts == 3
    assert spec.sampling_overhead == 6 * 6 * 8
    assert spec.cuts_by_kind() == {"gate": 2, "wire": 1}


def test_uncut_circuit_has_unit_overhead():
    assert CircuitCutSpec().sampling_overhead == 1


def test_sampling_overhead_helper_matches_the_spec():
    assert sampling_overhead(2, 1) == 288
    assert sampling_overhead() == 1
    assert max_cuts_for_budget(10_000) == 5              # 6**5 = 7776 <= 10000
    assert max_cuts_for_budget(10_000, base=8) == 4      # 8**4 = 4096 <= 10000
    assert max_cuts_for_budget(3) == 0                   # even one cut is too many


# ---------------------------------------------------------------------------
# The shared run result
# ---------------------------------------------------------------------------

def test_communication_cost_reports_ebits_for_a_partitioned_run():
    run = DistributedRunResult(
        strategy=DistributionStrategy.PARTITION,
        entanglement_cost=EntanglementCost(
            ebits=12, ebits_per_link={"q0<->q1": 8, "q1<->q2": 4, "q0<->q2": 0}
        ),
    )
    assert run.ebits == 12
    assert run.sampling_overhead is None
    assert run.communication_cost == 12
    assert run.entanglement_cost.num_links_used == 2


def test_communication_cost_reports_terms_for_a_cut_run():
    run = DistributedRunResult(
        strategy=DistributionStrategy.GATE_CUT,
        cut=CircuitCutSpec(cuts=[CutSpec(kind="gate", gate_id="CZ_1")] * 2),
    )
    assert run.ebits is None
    assert run.sampling_overhead == 36
    assert run.communication_cost == 36


def test_run_result_aggregates_subcircuit_outcomes():
    run = DistributedRunResult(
        strategy=DistributionStrategy.WIRE_CUT,
        subcircuit_results=[
            SubcircuitResult(subcircuit_id="a", expectation_value=0.5, shots=1024),
            SubcircuitResult(subcircuit_id="b", expectation_value=-0.2, shots=1024,
                             coefficient=-1.0),
            SubcircuitResult(subcircuit_id="c", shots=512, status=JobStatus.FAILED),
        ],
        reconstruction=ReconstructionResult(value=0.7, exact_value=0.72, num_terms=8),
    )
    assert run.num_subcircuits == 3
    assert run.total_shots == 2560
    assert [r.subcircuit_id for r in run.failed_subcircuits] == ["c"]
    assert run.reconstruction.error == pytest.approx(0.02)


def test_reconstruction_error_is_none_without_a_reference():
    assert ReconstructionResult(value=0.5).error is None


def test_run_result_bridges_to_quantum_result():
    run = DistributedRunResult(
        strategy=DistributionStrategy.GATE_CUT,
        cut=CircuitCutSpec(cuts=[CutSpec(kind="gate", gate_id="CZ_1")]),
        reconstruction=ReconstructionResult(value=-0.717, std_error=0.004),
        total_wall_seconds=42.0,
    )
    qr = run.to_quantum_result()
    assert qr.expectation_values[0].value == pytest.approx(-0.717)
    assert qr.expectation_values[0].std_error == pytest.approx(0.004)
    assert qr.metadata["sampling_overhead"] == 6
    assert qr.vendor_results["distributed_run_result"]["strategy"] == "gate_cut"


def test_run_result_without_a_reconstruction_has_no_expectation_values():
    qr = DistributedRunResult(strategy=DistributionStrategy.PARTITION).to_quantum_result()
    assert qr.expectation_values is None


# ---------------------------------------------------------------------------
# Core wiring
# ---------------------------------------------------------------------------

def test_execution_options_accepts_a_run_config_model_and_dumps_it():
    cfg = DistributedRunConfig(
        strategy=DistributionStrategy.GATE_CUT,
        max_qubits_per_subcircuit=5,
        max_cuts=3,
        shots_per_subcircuit=8192,
    )
    options = ExecutionOptions(distributed_run_config=cfg)
    assert isinstance(options.distributed_run_config, dict)
    assert DistributedRunConfig.model_validate(options.distributed_run_config) == cfg


def test_circuit_spec_carries_the_cut_the_tool_chose():
    cut = CircuitCutSpec(
        strategy=DistributionStrategy.GATE_CUT,
        cuts=[CutSpec(kind="gate", gate_id="CZ_2")],
        num_qubits=10,
    )
    circuit = CircuitSpec(num_qubits=10, distribution=cut)
    assert isinstance(circuit.distribution, dict)
    assert CircuitCutSpec.model_validate(circuit.distribution) == cut


def test_network_spec_round_trips_through_json():
    net = QPUNetworkSpec.from_sizes([8, 8, 8], topology=NetworkTopology.LINEAR)
    assert QPUNetworkSpec.model_validate(json.loads(net.model_dump_json())) == net


# ---------------------------------------------------------------------------
# DISQCO mirror
# ---------------------------------------------------------------------------

def _disqco_result() -> DisqcoPartitionResult:
    return DisqcoPartitionResult(
        final_cost=6.0,
        assignment=[[0, 0, 1], [0, 1, 1], [1, 1, 1], [1, 1, 1]],
        cost_list=[11.0, 8.0, 6.0],
        time_list=[0.1, 0.4, 0.9],
        num_partitions=2,
        network=DisqcoNetworkSpec(qpu_sizes={0: 4, 1: 4}, comm_sizes={0: 1, 1: 1}),
        config=DisqcoFMConfig(coarsener=DisqcoCoarsener.RECURSIVE, num_levels=3),
        wall_seconds=0.9,
    )


def test_disqco_network_generates_all_to_all_links_when_complete():
    net = DisqcoNetworkSpec(qpu_sizes={0: 4, 1: 4, 2: 4}).to_network_spec()
    assert net.num_nodes == 3 and len(net.links) == 3
    assert net.topology is NetworkTopology.ALL_TO_ALL
    assert net.metadata["hetero"] is False


def test_disqco_network_honours_explicit_heterogeneous_connectivity():
    spec = DisqcoNetworkSpec(
        qpu_sizes={0: 4, 1: 8, 2: 4},
        connectivity=[[0, 1], [1, 2]],
        coupling_type=DisqcoNetworkCoupling.LINEAR,
        hetero=True,
    )
    net = spec.to_network_spec()
    assert len(net.links) == 2
    assert not net.is_homogeneous
    assert net.is_connected()


def test_disqco_partition_result_exposes_the_ebit_objective():
    res = _disqco_result()
    assert res.ebits == 6
    assert res.initial_cost == 11.0
    assert res.improvement == pytest.approx(5.0)
    assert res.is_time_varying          # qubits 0 and 1 change QPU mid-circuit


def test_disqco_assignment_maps_qubit_time_indices_to_node_ids():
    spec = _disqco_result().to_partition_spec()
    assert len(spec.assignments) == 4 * 3
    first = spec.assignments[0]
    assert (first.qubit, first.time_step, first.node_id) == (0, 0, "q0")
    assert spec.assignments[2].node_id == "q1"      # qubit 0 at time 2
    assert spec.coarsening is CoarseningStrategy.RECURSIVE
    assert spec.partitioner is PartitionerType.MULTILEVEL_FM


def test_disqco_partition_spec_requires_a_network_to_name_the_indices():
    res = _disqco_result()
    res.network = None
    with pytest.raises(ValueError, match="network"):
        res.to_partition_spec()


def test_disqco_non_multilevel_run_maps_to_plain_fm():
    res = _disqco_result()
    res.config = DisqcoFMConfig(partitioner=DisqcoPartitionerType.FM)
    assert not res.config.is_multilevel
    assert res.to_partition_spec().partitioner is PartitionerType.FIDUCCIA_MATTHEYSES


def test_disqco_bridges_to_the_shared_run_result():
    run = _disqco_result().to_distributed_run_result()
    assert run.strategy is DistributionStrategy.PARTITION
    assert run.ebits == 6
    assert run.sampling_overhead is None            # partitioning pays no overhead
    assert run.cost_history == [11.0, 8.0, 6.0]
    assert run.reconstruction.method is ReconstructionMethod.LOCC


def test_disqco_extracted_circuit_sums_registers_and_epr_requests():
    extracted = DisqcoExtractedCircuit(
        num_data_qubits=8,
        num_comm_qubits=2,
        num_clbits=8,
        depth=31,
        epr_pairs_per_link={"q0<->q1": 6},
        gate_counts={"cx": 40, "h": 12},
        qasm="OPENQASM 2.0;",
    )
    assert extracted.total_qubits == 10
    circuit = extracted.to_circuit_spec()
    assert circuit.num_qubits == 10 and circuit.total_gates == 52
    assert extracted.to_entanglement_cost().ebits == 6


def test_disqco_extracted_circuit_without_qasm_still_records_shape():
    extracted = DisqcoExtractedCircuit(num_data_qubits=4, num_comm_qubits=1, num_clbits=4)
    circuit = extracted.to_circuit_spec()
    assert circuit.serialized is None
    assert circuit.num_qubits == 5


# ---------------------------------------------------------------------------
# Qdislib mirror
# ---------------------------------------------------------------------------

def test_find_cut_return_value_is_classified_by_element_shape():
    """Upstream returns bare identifiers for gate cuts and pairs for wire
    cuts; the record stores the kind so nothing re-infers it later."""
    gate = QdislibCutRecord.from_find_cut(["CZ_2", "CZ_5"])
    assert gate.kind is QdislibCutKind.GATE
    assert gate.num_cuts == 2 and gate.terms == 36

    wire = QdislibCutRecord.from_find_cut([("H_1", "CZ_2")])
    assert wire.kind is QdislibCutKind.WIRE
    assert wire.wire_endpoints == [["H_1", "CZ_2"]]
    assert wire.terms == 8

    mixed = QdislibCutRecord.from_find_cut(["CZ_2", ("H_1", "CZ_3")])
    assert mixed.kind is QdislibCutKind.MIXED
    assert mixed.terms == 48


def test_empty_cut_is_a_gate_cut_with_unit_overhead():
    empty = QdislibCutRecord.from_find_cut([])
    assert empty.kind is QdislibCutKind.GATE
    assert empty.num_cuts == 0 and empty.terms == 1


def test_cut_kind_maps_onto_the_general_strategy():
    assert QdislibCutKind.GATE.to_strategy() is DistributionStrategy.GATE_CUT
    assert QdislibCutKind.WIRE.to_strategy() is DistributionStrategy.WIRE_CUT
    assert QdislibCutKind.HADAMARD.to_strategy() is DistributionStrategy.HADAMARD_GATE_CUT
    assert QdislibCutKind.MIXED.to_strategy() is DistributionStrategy.MIXED_CUT


def test_cut_cost_dict_is_ingested_verbatim():
    cost = QdislibCutCost.from_cut_cost(
        {"num_cuts": 2, "kind": "gate", "base": 6, "terms": 36}
    )
    assert cost.kind is QdislibCutKind.GATE and cost.terms == 36


def test_cut_record_converts_to_the_general_cut_spec():
    record = QdislibCutRecord.from_find_cut(
        ["CZ_2", ("H_1", "CZ_3")], num_subcircuits=2, max_qubits=5
    )
    spec = record.to_cut_spec(num_qubits=10)
    assert spec.strategy is DistributionStrategy.MIXED_CUT
    assert spec.cuts_by_kind() == {"gate": 1, "wire": 1}
    assert spec.sampling_overhead == 48
    assert spec.max_qubits_per_subcircuit == 5


def test_cache_hit_rate_is_none_before_any_lookup():
    assert QdislibCacheStats().hit_rate is None
    assert QdislibCacheStats(hits=3, misses=1).hit_rate == pytest.approx(0.75)


def test_qdislib_run_record_derives_overhead_error_and_reduction():
    run = QdislibRunRecord(
        circuit_qubits=10,
        software=QdislibSoftware.QIBO,
        cut=QdislibCutRecord.from_find_cut(["CZ_2", "CZ_5"]),
        subcircuits=[
            QdislibSubcircuit(subcircuit_id="s0", num_qubits=6, qubits=[0, 1, 2, 3, 4, 5]),
            QdislibSubcircuit(subcircuit_id="s1", num_qubits=4, qubits=[6, 7, 8, 9]),
        ],
        subcircuit_results=[
            QdislibSubcircuitResult(subcircuit_id="s0", expectation_value=0.4, shots=8192),
            QdislibSubcircuitResult(
                subcircuit_id="s1", expectation_value=-0.3, shots=8192, cache_hit=True
            ),
        ],
        expectation_value=-0.717,
        exact_value=-0.715,
        num_workers=64,
        metrics=QdislibEstimateMetrics(
            cut_type=QdislibCutKind.GATE,
            num_cuts=2,
            find_cut_seconds=0.03,
            run_seconds=4.1,
            cache=QdislibCacheStats(hits=18, misses=18),
        ),
    )
    assert run.num_cuts == 2
    assert run.sampling_overhead == 36
    assert run.max_subcircuit_qubits == 6
    assert run.qubit_reduction == 4
    assert run.error == pytest.approx(0.002)
    assert run.cache_hit_rate == pytest.approx(0.5)


def test_qdislib_cost_field_takes_precedence_over_the_cut_for_overhead():
    """`cut_cost` is what upstream actually reported; trust it over a
    recomputation when both are present."""
    run = QdislibRunRecord(
        circuit_qubits=8,
        cut=QdislibCutRecord.from_find_cut(["CZ_1"]),
        cost=QdislibCutCost(num_cuts=3, kind=QdislibCutKind.GATE, base=6, terms=216),
    )
    assert run.sampling_overhead == 216
    assert run.num_cuts == 1     # `cut` is still the authority on what was cut


def test_qdislib_error_is_none_without_an_exact_reference():
    run = QdislibRunRecord(circuit_qubits=4, expectation_value=0.5)
    assert run.error is None
    assert run.qubit_reduction is None      # no subcircuits recorded


def test_qdislib_bridges_to_the_shared_run_result():
    run = QdislibRunRecord(
        circuit_qubits=10,
        cut=QdislibCutRecord.from_find_cut([("H_1", "CZ_2")]),
        expectation_value=0.25,
        exact_value=0.26,
        num_workers=8,
        wall_seconds=5.0,
        metrics=QdislibEstimateMetrics(
            cut_type=QdislibCutKind.WIRE, num_cuts=1,
            find_cut_seconds=0.02, run_seconds=4.8,
        ),
    )
    shared = run.to_distributed_run_result()
    assert shared.strategy is DistributionStrategy.WIRE_CUT
    assert shared.sampling_overhead == 8
    assert shared.ebits is None                     # cutting consumes no entanglement
    assert shared.find_cut_seconds == pytest.approx(0.02)
    assert shared.reconstruction.error == pytest.approx(0.01)
    assert shared.num_workers == 8

    qr = run.to_quantum_result()
    assert qr.expectation_values[0].value == pytest.approx(0.25)
    assert qr.vendor_results["qdislib_run"]["circuit_qubits"] == 10


def test_the_two_strategies_are_comparable_through_one_result_type():
    """The point of the shared schema: a partitioned run and a cut run of the
    same circuit are read off the same fields."""
    partitioned = _disqco_result().to_distributed_run_result()
    cut = QdislibRunRecord(
        circuit_qubits=4,
        cut=QdislibCutRecord.from_find_cut(["CZ_1"]),
        expectation_value=0.5,
    ).to_distributed_run_result()

    assert isinstance(partitioned, DistributedRunResult)
    assert isinstance(cut, DistributedRunResult)
    assert partitioned.communication_cost == 6      # ebits
    assert cut.communication_cost == 6              # quasiprobability terms
    # same number, different currency — the strategy field is what tells them apart
    assert partitioned.strategy is not cut.strategy
