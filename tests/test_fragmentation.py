"""Fragmentation schema tests — general module plus the two project mirrors.

Schema layer only: neither Fragme∩t nor quantum-fragment-methods is installed,
and nothing here imports them.
"""
from __future__ import annotations

import json

import pytest

from qpubench.schemas.catalogs.fragmentation import (
    FragmentationLayer,
    FragmentationResult,
    FragmentationScheme,
    FragmentationSpec,
    FragmenterType,
    FragmentExpansionTerm,
    FragmentResult,
    FragmentScreeningRule,
    FragmentSolverAssignment,
    FragmentSpec,
    ScreeningMetric,
    SolverKind,
)
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.mirrors.fragmentqc_fragment import (
    FragmentCombinator,
    FragmentJobRecord,
    FragmentModName,
    FragmentModSpec,
    FragmentPIENode,
    FragmentPIETree,
    FragmentRunRecord,
    FragmentStrategy,
)
from qpubench.schemas.mirrors.qiskitcommunity_fragment_methods import (
    QFMBathType,
    QFMFragment,
    QFMFragmentationScheme,
    QFMQPUConfig,
    QFMSolverName,
    QFMSolverResult,
    QFMWorkflowConfig,
    QFMWorkflowResult,
)
from qpubench.schemas.primitives import ComputingModel, JobStatus

# ---------------------------------------------------------------------------
# General expansion semantics
# ---------------------------------------------------------------------------

def _trimer_total_energy_spec() -> FragmentationSpec:
    """A 3-monomer 2-body MBE of the *total* energy: coefficients sum to 1."""
    return FragmentationSpec(
        name="trimer",
        scheme=FragmentationScheme.MBE,
        max_order=2,
        fragments=[
            FragmentSpec(fragment_id="m0", order=1, atom_indices=[0, 1, 2]),
            FragmentSpec(fragment_id="m1", order=1, atom_indices=[3, 4, 5]),
            FragmentSpec(fragment_id="m2", order=1, atom_indices=[6, 7, 8]),
            FragmentSpec(fragment_id="d01", order=2, primary_ids=["m0", "m1"]),
            FragmentSpec(fragment_id="d02", order=2, primary_ids=["m0", "m2"]),
            FragmentSpec(fragment_id="d12", order=2, primary_ids=["m1", "m2"]),
        ],
        expansion=[
            # E = sum(dimers) - (n-2) * sum(monomers), n = 3
            FragmentExpansionTerm(fragment_id="d01", coefficient=1.0, order=2),
            FragmentExpansionTerm(fragment_id="d02", coefficient=1.0, order=2),
            FragmentExpansionTerm(fragment_id="d12", coefficient=1.0, order=2),
            FragmentExpansionTerm(fragment_id="m0", coefficient=-2 / 3, order=1),
            FragmentExpansionTerm(fragment_id="m1", coefficient=-2 / 3, order=1),
            FragmentExpansionTerm(fragment_id="m2", coefficient=-2 / 3, order=1),
        ],
    )


def test_complete_expansion_coefficients_sum_to_one():
    spec = _trimer_total_energy_spec()
    assert spec.coefficient_sum == pytest.approx(1.0)
    assert spec.is_complete()
    assert spec.terms_by_order() == {1: 3, 2: 3}


def test_screened_terms_drop_out_of_the_expansion():
    """Screening is reported, not enforced: a screened term leaves the sum
    short of 1, which is how an adaptive run is distinguished from a bug."""
    spec = _trimer_total_energy_spec()
    spec.expansion[0].screened = True
    assert len(spec.active_terms) == 5
    assert not spec.is_complete()
    assert spec.coefficient_sum == pytest.approx(0.0)


def test_screening_rule_threshold_tightens_with_order():
    rule = FragmentScreeningRule(
        name="energy_trimming",
        metric=ScreeningMetric.ENERGY_DELTA,
        thresholds={2: 1e-4, 3: 1e-5},
        cutoff=1e-3,
        backend="xtb",
    )
    assert rule.threshold_for(2) == pytest.approx(1e-4)
    assert rule.threshold_for(3) == pytest.approx(1e-5)
    assert rule.threshold_for(9) == pytest.approx(1e-3)   # falls back to cutoff


def test_solver_rules_dispatch_by_priority_and_first_match_wins():
    spec = FragmentationSpec(
        name="s",
        fragments=[
            FragmentSpec(fragment_id="small", n_orbitals=8, num_qubits=16),
            FragmentSpec(fragment_id="big", n_orbitals=60, num_qubits=120),
        ],
        solver_rules=[
            FragmentSolverAssignment(solver_name="ccsd", priority=0),
            FragmentSolverAssignment(
                solver_name="sqd", solver_kind=SolverKind.QUANTUM,
                priority=10, max_qubits=48,
            ),
        ],
    )
    assert spec.assign_solver(spec.fragments[0]).solver_name == "sqd"
    assert spec.assign_solver(spec.fragments[1]).solver_name == "ccsd"
    assert [f.fragment_id for f in spec.quantum_fragments()] == ["small"]
    assert spec.max_fragment_qubits == 120


def test_solver_rule_does_not_reject_on_unset_fragment_fields():
    """A limit compared against a fragment that never reported that quantity
    must not exclude it — otherwise every under-specified fragment silently
    falls through to the classical fallback."""
    rule = FragmentSolverAssignment(solver_name="sqd", max_qubits=10)
    assert rule.matches(FragmentSpec(fragment_id="unknown"))
    assert rule.matches(FragmentSpec(fragment_id="fits", num_qubits=4))
    assert not rule.matches(FragmentSpec(fragment_id="wide", num_qubits=40))


def test_multilevel_and_adaptive_flags():
    spec = FragmentationSpec(name="s")
    assert not spec.is_multilevel and not spec.is_adaptive

    spec.layers = [
        FragmentationLayer(level=0, max_order=4, method="mp2"),
        FragmentationLayer(
            level=1, max_order=2, method="ccsd(t)", sign=-1.0,
            screening=[
                FragmentScreeningRule(name="d", metric=ScreeningMetric.CENTRE_OF_MASS_DISTANCE)
            ],
        ),
    ]
    assert spec.is_multilevel and spec.is_adaptive


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def test_reconstructed_energy_recomputes_from_stored_terms():
    """total_energy is what upstream said; reconstructed_energy is derived —
    a mismatch means the record is missing a contributing fragment."""
    res = FragmentationResult(
        spec_name="trimer",
        total_energy=-3.0,
        reference_energy=-3.0005,
        fragment_results=[
            FragmentResult(fragment_id="d01", solver_name="ccsd", coefficient=1.0, energy=-1.5),
            FragmentResult(fragment_id="m0", solver_name="ccsd", coefficient=-1.0, energy=-0.5),
            FragmentResult(fragment_id="m1", solver_name="ccsd", coefficient=1.0, energy=-2.0),
        ],
    )
    assert res.reconstructed_energy == pytest.approx(-3.0)
    assert res.energy_error == pytest.approx(5e-4)
    assert res.chemical_accuracy is True


def test_energy_error_and_accuracy_are_none_without_a_reference():
    res = FragmentationResult(spec_name="s", total_energy=-1.0)
    assert res.energy_error is None
    assert res.chemical_accuracy is None
    assert res.quantum_fragment_fraction is None


def test_quantum_fragment_fraction_and_failures():
    res = FragmentationResult(
        spec_name="s",
        total_energy=-1.0,
        fragment_results=[
            FragmentResult(
                fragment_id="a", solver_name="sqd", solver_kind=SolverKind.QUANTUM,
                energy=-0.5, num_qubits=20,
            ),
            FragmentResult(
                fragment_id="b", solver_name="ccsd", energy=-0.5,
                status=JobStatus.FAILED,
            ),
        ],
    )
    assert res.num_quantum_fragments == 1
    assert res.quantum_fragment_fraction == pytest.approx(0.5)
    assert res.max_fragment_qubits == 20
    assert [f.fragment_id for f in res.failed_fragments()] == ["b"]


def test_to_quantum_result_takes_an_explicit_computing_model():
    """A fragmented calculation may be entirely classical, so the model is
    never inferred."""
    res = FragmentationResult(spec_name="s", total_energy=-1.5, wall_seconds=3.0)
    qr = res.to_quantum_result(computing_model=ComputingModel.GATE_BASED)
    assert qr.expectation_values[0].value == pytest.approx(-1.5)
    assert qr.wall_seconds == 3.0
    assert qr.vendor_results["fragmentation_result"]["total_energy"] == -1.5


def test_fragmentation_spec_round_trips_through_json():
    spec = _trimer_total_energy_spec()
    assert FragmentationSpec.model_validate(json.loads(spec.model_dump_json())) == spec


def test_circuit_spec_accepts_a_fragmentation_model_and_dumps_it():
    spec = _trimer_total_energy_spec()
    circuit = CircuitSpec(num_qubits=8, fragmentation=spec)
    assert isinstance(circuit.fragmentation, dict)
    assert FragmentationSpec.model_validate(circuit.fragmentation) == spec


# ---------------------------------------------------------------------------
# Fragme∩t mirror
# ---------------------------------------------------------------------------

_STRATEGY_YAML = {
    "mods": [
        {
            "name": "close",
            "mod_name": "distance",
            "method": "com",
            "max_distance": 8.0,
        },
        {
            "name": "trim",
            "mod_name": "energy_trimming",
            "backend": "xtb_cheap",
            "thresholds": {2: 1e-4, 3: 1e-6},
        },
        {"name": "cp", "mod_name": "clusterbasis"},
    ],
    "systems": [{"name": "water20", "source": "water20.xyz"}],
    "backends": [
        {
            "name": "mp2",
            "program": "pyscf",
            "method": "mp2",
            "basis": "cc-pVDZ",
            "conv_tol": 1e-9,
        },
        {"name": "cheap", "program": "xtb"},
    ],
    "fragmenters": [
        {"name": "waters", "fragmenter": "water", "combinator": "mbe", "mods": ["close"]},
    ],
    "calculations": [
        {
            "name": "mbe3",
            "system": "water20",
            "layers": [
                {
                    "backend": "cheap",
                    "view": {"order": 3, "fragmenter": "waters"},
                    "mods": ["trim"],
                },
                {"backend": "mp2", "view": {"order": 2, "fragmenter": "waters"}},
            ],
        }
    ],
}


def test_strategy_yaml_round_trips_and_converts():
    strategy = FragmentStrategy.model_validate(_STRATEGY_YAML)
    assert strategy.fragmenter("waters").combinator is FragmentCombinator.MBE
    assert strategy.backend("mp2").basis == "cc-pVDZ"

    spec = strategy.to_fragmentation_spec("mbe3")
    assert spec.scheme is FragmentationScheme.MBE
    assert spec.fragmenter is FragmenterType.WATER
    assert spec.is_multilevel and spec.is_adaptive
    assert [layer.method for layer in spec.layers] == ["xtb", "mp2"]
    assert spec.layers[0].max_order == 3
    # the layer-level `trim` mod became a screening rule on that layer
    assert spec.layers[0].screening[0].thresholds == {2: 1e-4, 3: 1e-6}


def test_unknown_calculation_name_raises():
    strategy = FragmentStrategy.model_validate(_STRATEGY_YAML)
    with pytest.raises(ValueError, match="no calculation named"):
        strategy.to_fragmentation_spec("nope")


def test_only_screening_mods_become_screening_rules():
    """Basis and MIC mods change how a term is computed, not whether it is."""
    strategy = FragmentStrategy.model_validate(_STRATEGY_YAML)
    assert strategy.mod("close").to_screening_rule().metric is (
        ScreeningMetric.CENTRE_OF_MASS_DISTANCE
    )
    assert strategy.mod("trim").to_screening_rule().backend == "xtb_cheap"
    assert strategy.mod("cp").to_screening_rule() is None


def test_distance_mod_method_selects_the_metric():
    closest = FragmentModSpec(
        name="c", mod_name=FragmentModName.DISTANCE, method="closest", max_distance=5.0
    )
    assert closest.to_screening_rule().metric is ScreeningMetric.CLOSEST_ATOM_DISTANCE


def test_pie_tree_coefficients_and_conversion():
    tree = FragmentPIETree(
        primaries=[[0, 1], [2, 3], [4, 5]],
        nodes=[
            FragmentPIENode(key=[0, 1], coefficient=1),
            FragmentPIENode(key=[0, 2], coefficient=1),
            FragmentPIENode(key=[1, 2], coefficient=1),
            FragmentPIENode(key=[0], coefficient=-1),
            FragmentPIENode(key=[1], coefficient=-1),
            FragmentPIENode(key=[2], coefficient=-1),
            FragmentPIENode(key=[0, 1, 2], coefficient=0),   # structural only
        ],
        order=2,
    )
    assert tree.num_primaries == 3
    assert tree.coefficient_sum() == 0            # interaction energy, not total
    assert len(tree.nonzero_nodes) == 6           # the zero-coefficient node is dropped
    assert tree.nodes_by_order() == {1: 3, 2: 3}

    expansion = tree.to_expansion()
    assert len(expansion) == 6
    assert expansion[0].fragment_id == "n(0,1)"

    fragments = {f.fragment_id: f for f in tree.to_fragments()}
    assert fragments["n(0,1)"].atom_indices == [0, 1, 2, 3]
    assert fragments["n(0,1)"].order == 2


def test_fragment_run_record_bridges_to_the_general_result():
    run = FragmentRunRecord(
        strategy_name="s",
        calculation_name="mbe3",
        total_energy=-4.0,
        supersystem_energy=-4.0004,
        jobs=[
            FragmentJobRecord(
                job_id=1, name="n(0,1)", status=JobStatus.SUCCEEDED,
                energy=-2.5, coefficient=1,
            ),
            FragmentJobRecord(
                job_id=2, name="n(0)", status=JobStatus.SUCCEEDED,
                energy=-1.5, coefficient=-1,
            ),
        ],
    )
    res = run.to_fragmentation_result()
    assert res.total_energy == pytest.approx(-4.0)
    assert res.reconstructed_energy == pytest.approx(-1.0)   # 1*(-2.5) + (-1)*(-1.5)
    assert res.energy_error == pytest.approx(4e-4)
    assert res.metadata["strategy"] == "s"


# ---------------------------------------------------------------------------
# quantum-fragment-methods mirror
# ---------------------------------------------------------------------------

_QFM_CONFIG = {
    "workflow": {"basis": "6-31g"},
    "embedder": {"ewf": {"bath_type": "mp2", "truncation": 1e-5, "fragmentation": "iao"}},
    "qpu": {
        "provider": "ibm_quantum",
        "backend_name": "ibm_pittsburgh",
        "credentials": {
            "channel": "ibm_cloud",
            "token": "SECRET-DO-NOT-STORE",
            "instance": "crn:v1:bluemix:public:...",
        },
        "sampler_options": {
            "default_shots": 20000,
            "dynamical_decoupling": {"enable": True, "sequence_type": "XY4"},
            "twirling": {"enable_gates": False, "enable_measure": False},
        },
    },
    "sqd": {
        "symmetrize_spin": True,
        "n_batches": 10,
        "iterations": 5,
        "samples_per_batch": 3000,
        "energy_tol": 1e-8,
        "occupancies_tol": 1e-5,
        "carryover_threshold": 1e-4,
        "add_hf_string": True,
        "lucj": {"n_reps": 1, "max_connection": 12, "connect_every_n": 4},
        "transpilation": {"optimization_level": 0, "seed_transpiler": 42},
        "sbd": {"exe_path": "/workspace/executable/diag", "cpus_per_batch": 8},
    },
    "ext_sqd": {"dprime_cutoff": 1e-5},
}


def test_qfm_config_parses_the_upstream_nesting():
    cfg = QFMWorkflowConfig.from_config_dict(_QFM_CONFIG)
    assert cfg.basis == "6-31g"
    assert cfg.ewf.bath_type is QFMBathType.MP2
    assert cfg.ewf.fragmentation is QFMFragmentationScheme.IAO
    assert cfg.qpu.backend_name == "ibm_pittsburgh"
    assert cfg.qpu.sampler_options.dd_sequence_type == "XY4"
    assert cfg.sqd.total_samples == 30_000
    assert cfg.sqd.lucj.connect_every_n == 4
    assert cfg.sqd.sbd.cpus_per_batch == 8
    assert cfg.ext_sqd.dprime_cutoff == pytest.approx(1e-5)


def test_qfm_config_never_carries_the_api_token_into_a_record():
    """Records are stored and shared; the token must not survive parsing."""
    cfg = QFMWorkflowConfig.from_config_dict(_QFM_CONFIG)
    assert "token" not in QFMQPUConfig.model_fields
    assert "SECRET-DO-NOT-STORE" not in cfg.model_dump_json()
    # the non-secret identifiers a record *should* state are kept
    assert cfg.qpu.channel == "ibm_cloud"
    assert cfg.qpu.instance.startswith("crn:v1:")


def test_qfm_config_converts_to_a_spec_with_priority_ordered_solvers():
    spec = QFMWorkflowConfig.from_config_dict(_QFM_CONFIG).to_fragmentation_spec()
    assert spec.scheme is FragmentationScheme.EWF
    assert spec.fragmenter is FragmenterType.ORBITAL
    assert [r.solver_name for r in sorted(spec.solver_rules, key=lambda r: -r.priority)] == [
        "ext_sqd",
        "sqd",
        "ccsd",
    ]
    assert spec.screening[0].metric is ScreeningMetric.BATH_OCCUPANCY
    assert spec.screening[0].cutoff == pytest.approx(1e-5)


def test_qfm_fragment_duck_types_the_upstream_object():
    class _Upstream:
        fragment_id = 3
        atom_indices = [0, 1]
        orbital_indices = [0, 1, 2, 3, 4]
        n_electrons = (3, 2)       # upstream allows an (alpha, beta) tuple
        metadata = {"residue": "ALA"}

    frag = QFMFragment.from_fragment(_Upstream())
    assert frag.n_electrons == 5 and frag.n_alpha == 3 and frag.n_beta == 2
    assert frag.n_orbitals == 5
    assert frag.estimated_qubits == 10          # Jordan-Wigner

    spec = frag.to_fragment_spec()
    assert spec.fragment_id == "3" and spec.num_qubits == 10


def test_qfm_workflow_result_bridges_with_unit_coefficients():
    """Embedding sums per-fragment contributions with unit weight — there is
    no inclusion-exclusion coefficient to apply."""
    result = QFMWorkflowResult(
        total_energy=-110.5,
        mf_energy=-108.9,
        embedder="EWF",
        basis="6-31g",
        fragment_results=[
            QFMSolverResult(
                fragment_id=0, solver=QFMSolverName.SQD, energy=-60.0,
                num_qubits=32, shots=20000, has_rdm1=True,
            ),
            QFMSolverResult(fragment_id=1, solver=QFMSolverName.CCSD, energy=-50.5),
        ],
    )
    assert result.num_quantum_fragments == 1

    res = result.to_fragmentation_result()
    assert all(r.coefficient == 1.0 for r in res.fragment_results)
    assert res.reconstructed_energy == pytest.approx(-110.5)
    assert res.correlation_energy == pytest.approx(-1.6)
    assert res.quantum_fragment_fraction == pytest.approx(0.5)


def test_qfm_solver_kind_follows_the_solver():
    assert QFMSolverName.SQD.kind is SolverKind.QUANTUM
    assert QFMSolverName.EXT_SQD.kind is SolverKind.QUANTUM
    assert QFMSolverName.FCI.kind is SolverKind.CLASSICAL
    assert QFMSolverName.CCSD.kind is SolverKind.CLASSICAL


def test_qfm_solver_result_does_not_store_rdms():
    """Records must stay JSON-serialisable; protein-scale RDMs never fit."""
    assert "rdm1" not in QFMSolverResult.model_fields
    assert "rdm2" not in QFMSolverResult.model_fields
    assert "has_rdm1" in QFMSolverResult.model_fields
