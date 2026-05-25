"""Schema unit tests.

These tests exercise the schema layer only — no quantum SDK dependencies.
Run with: pytest tests/
"""
from __future__ import annotations

import json
import math

import pytest

from qpubench.schemas.mbqc import (
    AdaptiveSpec,
    ByproductUpdateSpec,
    CommutationSpec,
    MBQCExecutionResult,
    MBQCPattern,
    MBQCProgramWord,
    MBQCQubitState,
    MBQCRound,
)
from qpubench.schemas.observable import PauliTerm, SparsePauliObservable
from qpubench.schemas.primitives import ComplexNumber, PauliLabel
from qpubench.schemas.record import BenchmarkRecord, VQAConfig
from qpubench.schemas.backend import BackendSpec, GateCharacteristics, QubitCharacteristics
from qpubench.schemas.circuit import CircuitSpec, ParameterBinding
from qpubench.schemas.execution import ExecutionOptions, TranspilerConfig, ZNEConfig
from qpubench.schemas.result import (
    ExpectationResult,
    FidelityResult,
    FidelityMetric,
    QuantumResult,
    ShotResult,
    TranspileLayout,
)
from qpubench.schemas.primitives import (
    CircuitFormat,
    ErrorMitigationStrategy,
    QPUModality,
    JobStatus,
)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def test_pauli_label_qrack_encoding():
    assert PauliLabel.I.to_qrack_int() == 0
    assert PauliLabel.X.to_qrack_int() == 1
    assert PauliLabel.Z.to_qrack_int() == 2   # non-sequential: Z before Y
    assert PauliLabel.Y.to_qrack_int() == 3


def test_pauli_label_qiskit_c_encoding():
    assert PauliLabel.X.to_qiskit_c_bit_term() == 0b0010
    assert PauliLabel.Z.to_qiskit_c_bit_term() == 0b0001
    assert PauliLabel.Y.to_qiskit_c_bit_term() == 0b0011


def test_complex_number_roundtrip():
    c = ComplexNumber(re=1.5, im=-2.3)
    assert c.value == complex(1.5, -2.3)
    restored = ComplexNumber.from_complex(c.value)
    assert math.isclose(restored.re, c.re)
    assert math.isclose(restored.im, c.im)


# ---------------------------------------------------------------------------
# Observable
# ---------------------------------------------------------------------------

def test_pauli_term_length_mismatch():
    with pytest.raises(ValueError, match="qubit_indices length"):
        PauliTerm(
            qubit_indices=(0, 1),
            pauli_ops=(PauliLabel.X,),   # mismatched
        )


def test_pauli_term_qrack_arrays():
    term = PauliTerm(
        qubit_indices=(0, 2),
        pauli_ops=(PauliLabel.X, PauliLabel.Z),
    )
    qubits, paulis = term.to_qrack_arrays()
    assert qubits == [0, 2]
    assert paulis == [1, 2]   # X=1, Z=2


def test_sparse_pauli_from_legacy_dict():
    obs = {"X1,Z3": 0.5, "Z0": -1.0}
    spo = SparsePauliObservable.from_legacy_dict(obs, num_qubits=4)
    assert spo.num_qubits == 4
    assert len(spo.terms) == 2
    coeffs = {t.coefficient.re for t in spo.terms}
    assert 0.5 in coeffs
    assert -1.0 in coeffs


def test_sparse_pauli_flat_qrack_arrays():
    spo = SparsePauliObservable(
        num_qubits=2,
        terms=[
            PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.Z,)),
            PauliTerm(qubit_indices=(1,), pauli_ops=(PauliLabel.X,)),
        ],
    )
    qubits, paulis = spo.to_qrack_flat_arrays()
    assert qubits == [0, 1]
    assert paulis == [2, 1]   # Z=2, X=1


# ---------------------------------------------------------------------------
# MBQC bit-level encoding
# ---------------------------------------------------------------------------

def test_byproduct_update_pack_unpack():
    spec = ByproductUpdateSpec(z_mask=0b101, x_mask=0b010)
    assert spec.b_prog == (0b010 << 3) | 0b101
    restored = ByproductUpdateSpec.from_b_prog(spec.b_prog)
    assert restored.z_mask == 0b101
    assert restored.x_mask == 0b010


def test_byproduct_update_logic():
    spec = ByproductUpdateSpec(z_mask=0b010, x_mask=0b100)
    # m_below=0, m_self=1, m_above=0  → z_update=1 (m[1]&z_mask[1]), x_update=0
    dz, dx = spec.update(m_below=0, m_self=1, m_above=0)
    assert dz == 1
    assert dx == 0


def test_adaptive_spec_pack_unpack():
    spec = AdaptiveSpec(sr_mask=0b110, z_byp_enable=True, x_byp_enable=False)
    assert spec.s_prog == 0b01110
    restored = AdaptiveSpec.from_s_prog(spec.s_prog)
    assert restored.sr_mask == 0b110
    assert restored.z_byp_enable is True
    assert restored.x_byp_enable is False


def test_adaptive_spec_compute_s():
    spec = AdaptiveSpec(sr_mask=0b100, z_byp_enable=False, x_byp_enable=False)
    # Only sr[2] (most recent) contributes
    assert spec.compute_s(shift_register=0b100, ops_stored_z=0, ops_stored_x=0) == 1
    assert spec.compute_s(shift_register=0b011, ops_stored_z=0, ops_stored_x=0) == 0


def test_adaptive_spec_byproduct_contribution():
    spec = AdaptiveSpec(sr_mask=0b000, z_byp_enable=True, x_byp_enable=False)
    assert spec.compute_s(shift_register=0, ops_stored_z=1, ops_stored_x=0) == 1
    assert spec.compute_s(shift_register=0, ops_stored_z=0, ops_stored_x=1) == 0


def test_commutation_spec_pack_unpack():
    spec = CommutationSpec.cnot_control_target_below()
    assert spec.cnot_enable is True
    assert spec.role == 0b01
    restored = CommutationSpec.from_c_prog(spec.c_prog)
    assert restored.cnot_enable == spec.cnot_enable
    assert restored.role == spec.role


def test_program_word_roundtrip():
    pw = MBQCProgramWord(
        byproduct_update=ByproductUpdateSpec(z_mask=0b010, x_mask=0b100),
        adaptive=AdaptiveSpec(sr_mask=0b110, z_byp_enable=True),
        commutation=CommutationSpec(store_ops=True),
    )
    word = pw.word
    assert 0 <= word <= 0xFFFF
    restored = MBQCProgramWord.from_word(word)
    assert restored.byproduct_update.z_mask == 0b010
    assert restored.byproduct_update.x_mask == 0b100
    assert restored.adaptive.sr_mask == 0b110
    assert restored.adaptive.z_byp_enable is True
    assert restored.commutation.store_ops is True


def test_program_word_bin_str_length():
    pw = MBQCProgramWord()
    s  = pw.to_bin_str()
    assert len(s) == 16
    assert set(s).issubset({"0", "1"})


# ---------------------------------------------------------------------------
# MBQC pattern and COE generation
# ---------------------------------------------------------------------------

def _simple_pattern(n: int = 1, d: int = 4) -> MBQCPattern:
    return MBQCPattern(
        num_logical_qubits=n,
        rounds=[
            [MBQCRound.non_adaptive(theta=i * 0.1) for _ in range(n)]
            for i in range(d)
        ],
    )


def test_pattern_shape_validation():
    with pytest.raises(ValueError, match="Round 0"):
        MBQCPattern(
            num_logical_qubits=2,
            rounds=[[MBQCRound.non_adaptive(theta=0.0)]],  # only 1 entry for N=2
        )


def test_single_qubit_coe_line_count():
    pattern = _simple_pattern(n=1, d=6)
    coe = pattern.to_single_qubit_coe(qubit_idx=0)
    data_lines = [
        l for l in coe.splitlines()
        if l.strip() and not l.strip().endswith("=") and "initialization" not in l
    ]
    assert len(data_lines) == 6


def test_single_qubit_coe_binary_words():
    pattern = _simple_pattern(n=1, d=3)
    coe = pattern.to_single_qubit_coe(qubit_idx=0)
    for line in coe.splitlines():
        word_part = line.split(";")[0].strip()
        # Skip header lines and blank lines; data lines start with 0 or 1
        if not word_part or word_part[0] not in "01":
            continue
        assert len(word_part) == 16
        assert set(word_part).issubset({"0", "1"})


def test_multi_qubit_coe_roundtrip():
    pattern = _simple_pattern(n=2, d=4)
    coe = pattern.to_multi_qubit_coe()
    assert "memory_initialization_radix=16" in coe
    data_lines = [
        l.split(";")[0].strip()
        for l in coe.splitlines()
        if l.strip() and not l.strip().endswith("=") and "initialization" not in l
    ]
    assert len(data_lines) == 4
    hex_width = pattern.num_logical_qubits * 4
    for l in data_lines:
        assert len(l) == hex_width


# ---------------------------------------------------------------------------
# MBQC execution result CSV round-trip
# ---------------------------------------------------------------------------

def _make_history(n: int, d: int) -> list[list[MBQCQubitState]]:
    return [
        [
            MBQCQubitState(
                round_index=r,
                qubit_index=q,
                theta=0.0,
                measurement=(r + q) % 2,
                setting_used=0,
                ops_z=q % 2,
                ops_x=(r * q) % 2,
                ops_stored_z=0,
                ops_stored_x=0,
                shift_register=0,
            )
            for q in range(n)
        ]
        for r in range(d)
    ]


def test_mbqc_execution_result_csv_roundtrip():
    n = 3
    d = 5
    result = MBQCExecutionResult(
        num_logical_qubits=n,
        num_rounds=d,
        history=_make_history(n, d),
    )
    csv_text = result.to_multi_qubit_csv()
    restored = MBQCExecutionResult.from_multi_qubit_csv(csv_text, num_logical_qubits=n)
    assert restored.num_rounds == d
    for r in range(d):
        for q in range(n):
            assert restored.history[r][q].measurement == result.history[r][q].measurement
            assert restored.history[r][q].ops_z       == result.history[r][q].ops_z
            assert restored.history[r][q].ops_x       == result.history[r][q].ops_x


def test_corrected_outcomes_xor():
    n = 2
    result = MBQCExecutionResult(
        num_logical_qubits=n,
        num_rounds=1,
        history=[[
            MBQCQubitState(
                round_index=0, qubit_index=0, theta=0.0,
                measurement=1, setting_used=0,
                ops_z=0, ops_x=1,   # X byproduct → flips outcome
                ops_stored_z=0, ops_stored_x=0, shift_register=0,
            ),
            MBQCQubitState(
                round_index=0, qubit_index=1, theta=0.0,
                measurement=0, setting_used=0,
                ops_z=1, ops_x=0,   # Z byproduct → does NOT flip outcome
                ops_stored_z=0, ops_stored_x=0, shift_register=0,
            ),
        ]],
    )
    corrected = result.corrected_outcomes()
    assert corrected[0] == 0   # 1 XOR 1 = 0
    assert corrected[1] == 0   # 0 XOR 0 = 0 (Z doesn't flip)


# ---------------------------------------------------------------------------
# BenchmarkRecord JSON round-trip
# ---------------------------------------------------------------------------

def _minimal_record() -> BenchmarkRecord:
    return BenchmarkRecord(
        circuit=CircuitSpec(num_qubits=2, serialized="OPENQASM 2.0;"),
        backend=BackendSpec.aer_statevector(num_qubits=2),
        options=ExecutionOptions(shots=1024),
        result=QuantumResult(
            modality=QPUModality.GATE_BASED,
            expectation_values=[
                ExpectationResult(observable_index=0, value=-1.137, std_error=0.001)
            ],
        ),
        num_qubits=2,
    )


def test_benchmark_record_json_roundtrip():
    record  = _minimal_record()
    json_str = record.model_dump_json()
    data     = json.loads(json_str)
    assert data["schema_version"] == "1.7.0"
    restored = BenchmarkRecord.model_validate_json(json_str)
    assert restored.experiment_id == record.experiment_id
    assert restored.result.expectation_values[0].value == -1.137


def test_vqa_config_energy_error():
    vqa = VQAConfig(
        problem_type="chemistry",
        final_eigenvalue=-1.137,
        ground_truth=-1.138,
    )
    assert vqa.energy_error is not None
    assert math.isclose(vqa.energy_error, 0.001, rel_tol=1e-6)
    assert vqa.chemical_accuracy is True


def test_shot_result_probabilities():
    shots = ShotResult(num_qubits=2, num_shots=1000, counts={"00": 500, "11": 500})
    probs = shots.probabilities()
    assert math.isclose(probs["00"], 0.5)
    assert math.isclose(probs["11"], 0.5)
    assert shots.most_probable() in {"00", "11"}


# ---------------------------------------------------------------------------
# Gate-based modality: BackendSpec
# ---------------------------------------------------------------------------

def test_backend_spec_aer_statevector():
    b = BackendSpec.aer_statevector(num_qubits=5)
    assert b.simulator is True
    assert b.provider == "aer"
    assert b.num_qubits == 5
    assert b.qpu_modality == QPUModality.GATE_BASED


def test_backend_spec_ibm_auth():
    b = BackendSpec.ibm("ibm_brisbane", instance="ibm-q/open/main", token_ref="t123")
    assert b.auth["token_ref"] == "t123"
    assert b.auth["instance"] == "ibm-q/open/main"
    assert b.simulator is False


def test_backend_spec_qrack():
    b = BackendSpec.qrack(num_qubits=10, gpu=False)
    assert b.provider == "qrack"
    assert b.simulator is True
    assert b.auth["gpu"] == "False"


def test_backend_spec_gate_error_lookup():
    b = BackendSpec(
        name="test", provider="aer",
        gate_characteristics=[
            GateCharacteristics(gate_name="cx", qubit_indices=(0, 1), error_rate=0.005),
            GateCharacteristics(gate_name="cx", qubit_indices=(1, 2), error_rate=0.007),
        ],
    )
    assert b.gate_error("cx", (0, 1)) == 0.005
    assert b.gate_error("cx", (1, 2)) == 0.007
    assert b.gate_error("cx", (2, 3)) is None


def test_qubit_characteristics_fields():
    q = QubitCharacteristics(
        qubit_index=0, t1_s=150e-6, t2_s=80e-6, readout_error=0.02
    )
    assert q.t1_s == pytest.approx(150e-6)
    assert q.readout_error == pytest.approx(0.02)

    b = BackendSpec(
        name="hw", provider="ibm",
        qubit_characteristics=[q],
    )
    assert b.qubit_t1(0) == pytest.approx(150e-6)
    assert b.qubit_t1(1) is None


# ---------------------------------------------------------------------------
# Gate-based modality: ExecutionOptions
# ---------------------------------------------------------------------------

def test_execution_options_defaults():
    opts = ExecutionOptions()
    assert opts.shots is None
    assert opts.memory is False
    assert opts.init_qubits is True
    assert opts.optimization_level == 1
    assert opts.error_mitigation == ErrorMitigationStrategy.NONE


def test_zne_auto_config():
    opts = ExecutionOptions(error_mitigation=ErrorMitigationStrategy.ZNE)
    assert opts.zne_config is not None
    assert opts.zne_config.noise_factors == (1.0, 3.0, 5.0)


def test_execution_options_explicit_zne():
    opts = ExecutionOptions(
        error_mitigation=ErrorMitigationStrategy.ZNE,
        zne_config=ZNEConfig(noise_factors=(1.0, 2.0, 4.0), extrapolator="richardson"),
    )
    assert opts.zne_config.extrapolator == "richardson"


def test_transpiler_config_defaults():
    tc = TranspilerConfig()
    assert tc.layout_method is None
    assert tc.routing_method is None
    assert tc.approximation_degree == pytest.approx(1.0)
    assert tc.basis_gates == []


def test_transpiler_config_in_options():
    opts = ExecutionOptions(
        transpiler=TranspilerConfig(
            layout_method="sabre",
            routing_method="sabre",
            approximation_degree=0.99,
        )
    )
    assert opts.transpiler.layout_method == "sabre"
    assert opts.transpiler.approximation_degree == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# Gate-based modality: CircuitSpec
# ---------------------------------------------------------------------------

BELL_QASM = """\
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q -> c;
"""


def test_circuit_spec_classical_bits():
    c = CircuitSpec(num_qubits=2, num_classical_bits=2, serialized=BELL_QASM)
    assert c.num_classical_bits == 2


def test_circuit_spec_parametric():
    c = CircuitSpec(
        num_qubits=1,
        parameters=["theta", "phi"],
        serialized="OPENQASM 2.0;",
    )
    assert c.is_parametric() is True
    assert c.is_bound() is False


def test_circuit_spec_bind():
    c = CircuitSpec(
        num_qubits=1,
        parameters=["theta"],
        serialized="OPENQASM 2.0;",
    )
    bound = c.bind({"theta": 1.57})
    assert bound.is_bound() is True
    assert bound.parameter_bindings[0].value == pytest.approx(1.57)


def test_circuit_spec_invalid_binding():
    with pytest.raises(ValueError, match="not declared in parameters"):
        CircuitSpec(
            num_qubits=1,
            parameters=["theta"],
            parameter_bindings=[ParameterBinding(name="phi", value=0.5)],
            serialized="OPENQASM 2.0;",
        )


def test_circuit_spec_gate_counts():
    c = CircuitSpec(
        num_qubits=2,
        serialized=BELL_QASM,
        gate_counts={"h": 1, "cx": 1, "measure": 2},
    )
    assert c.circuit_depth == 4   # sum of all gate counts


def test_circuit_spec_gate_counts_empty():
    c = CircuitSpec(num_qubits=2, serialized=BELL_QASM)
    assert c.circuit_depth is None


# ---------------------------------------------------------------------------
# Gate-based modality: QuantumResult / TranspileLayout
# ---------------------------------------------------------------------------

def test_transpile_layout_valid():
    tl = TranspileLayout(
        num_virtual=2, num_physical=5,
        initial_layout=[0, 1],
        final_layout=[0, 3],
    )
    assert tl.final_layout[1] == 3


def test_transpile_layout_length_mismatch():
    with pytest.raises(ValueError, match="initial_layout length"):
        TranspileLayout(
            num_virtual=3, num_physical=5,
            initial_layout=[0, 1],    # too short
            final_layout=[0, 1, 2],
        )


def test_quantum_result_with_layout():
    result = QuantumResult(
        modality=QPUModality.GATE_BASED,
        shots=ShotResult(num_qubits=2, num_shots=1024, counts={"00": 512, "11": 512}),
        transpile_layout=TranspileLayout(
            num_virtual=2, num_physical=127,
            initial_layout=[0, 1],
            final_layout=[0, 5],
        ),
        transpiled_circuit="OPENQASM 2.0; ...",
    )
    assert result.transpile_layout.final_layout == [0, 5]
    assert result.transpiled_circuit is not None


def test_quantum_result_quasi_probabilities():
    result = QuantumResult(
        modality=QPUModality.GATE_BASED,
        quasi_probabilities={"00": 0.48, "11": 0.52},
        status=JobStatus.SUCCEEDED,
    )
    assert result.quasi_probabilities["11"] == pytest.approx(0.52)


def test_shot_result_marginal():
    shots = ShotResult(
        num_qubits=3,
        num_shots=100,
        counts={"000": 25, "001": 25, "110": 25, "111": 25},
    )
    marginal = shots.marginal([0])   # qubit 0 only (rightmost in MSB-first)
    assert marginal["0"] == 50      # 000 + 110
    assert marginal["1"] == 50      # 001 + 111


def test_shot_result_memory():
    shots = ShotResult(
        num_qubits=2,
        num_shots=3,
        counts={"00": 2, "11": 1},
        memory=["00", "00", "11"],
    )
    assert len(shots.memory) == 3


# ---------------------------------------------------------------------------
# Runner + StubGateAdapter integration
# ---------------------------------------------------------------------------

def test_runner_gate_based_stub():
    from qpubench import BenchmarkRunner, StubGateAdapter
    from qpubench.schemas.observable import SparsePauliObservable, PauliTerm

    circuit = CircuitSpec(
        num_qubits=2,
        serialized=BELL_QASM,
        observables=[
            SparsePauliObservable(
                num_qubits=2,
                terms=[PauliTerm(
                    qubit_indices=(0,),
                    pauli_ops=(PauliLabel.Z,),
                )],
            )
        ],
    )
    runner = BenchmarkRunner()
    runner.register(StubGateAdapter(seed=0), name="stub")
    record = runner.run(circuit, "stub", ExecutionOptions(shots=1024))

    assert record.result.status == JobStatus.SUCCEEDED
    assert record.result.total_time_s is not None
    assert record.result.expectation_values is not None
    assert record.result.expectation_values[0].observable_index == 0


def test_runner_sweep_produces_correct_count():
    from qpubench import BenchmarkRunner, StubGateAdapter

    circuit = CircuitSpec(num_qubits=1, serialized="OPENQASM 2.0;")
    runner  = BenchmarkRunner()
    runner.register(StubGateAdapter(seed=1), name="s")

    records = runner.sweep(
        circuits=[circuit],
        backend_names=["s"],
        options_list=[ExecutionOptions(shots=s) for s in [256, 1024]],
    )
    assert len(records) == 2   # 1 circuit × 1 backend × 2 option sets


# ---------------------------------------------------------------------------
# AlgorithmSpec and algorithm-driven schemas
# ---------------------------------------------------------------------------

from qpubench.schemas.execution import AlgorithmSpec
from qpubench.schemas.result import AdaptIteration
from qpubench.schemas.primitives import CircuitFormat


def test_algorithm_spec_defaults():
    alg = AlgorithmSpec(name="UCCNVQE")
    assert alg.pool_type == "SD"
    assert alg.optimizer == "BFGS"
    assert alg.use_analytic_grad is True
    assert alg.opt_thresh == pytest.approx(1.0e-5)
    assert alg.avqe_thresh == pytest.approx(1.0e-2)
    assert alg.adapt_maxiter == 20


def test_algorithm_spec_adapt_vqe():
    alg = AlgorithmSpec(
        name="ADAPTVQE",
        pool_type="SDTQ",
        optimizer="jacobi",
        avqe_thresh=1.0e-4,
        adapt_maxiter=30,
    )
    assert alg.name == "ADAPTVQE"
    assert alg.pool_type == "SDTQ"
    assert alg.adapt_maxiter == 30


def test_algorithm_spec_in_execution_options():
    opts = ExecutionOptions(
        algorithm_spec=AlgorithmSpec(name="ADAPTVQE", pool_type="GSD")
    )
    assert opts.algorithm_spec is not None
    assert opts.algorithm_spec.name == "ADAPTVQE"
    assert opts.algorithm_spec.pool_type == "GSD"


def test_algorithm_spec_json_roundtrip():
    alg = AlgorithmSpec(
        name="SPQE",
        pool_type="GSD",
        extra_params={"spqe_thresh": 1.0e-4, "max_excit": 2},
    )
    restored = AlgorithmSpec.model_validate_json(alg.model_dump_json())
    assert restored.name == "SPQE"
    assert restored.extra_params["spqe_thresh"] == pytest.approx(1.0e-4)


def test_adapt_iteration_schema():
    it = AdaptIteration(
        iteration=3,
        energy=-2.1628,
        grad_norm=8.3e-5,
        n_operators=4,
        n_cnot=12,
        n_classical_params=4,
        n_pauli_measures=1440,
    )
    assert it.n_cnot == 12
    assert it.grad_norm == pytest.approx(8.3e-5)


def test_quantum_result_with_adapt_history():
    history = [
        AdaptIteration(iteration=i, energy=-2.0 - i * 0.05,
                       grad_norm=0.1 / (i + 1), n_operators=i + 1,
                       n_cnot=i * 3, n_classical_params=i + 1)
        for i in range(4)
    ]
    result = QuantumResult(
        modality=QPUModality.GATE_BASED,
        expectation_values=[
            ExpectationResult(observable_index=0, value=-2.1628, std_error=0.0)
        ],
        adapt_history=history,
        status=JobStatus.SUCCEEDED,
    )
    assert len(result.adapt_history) == 4
    assert result.adapt_history[-1].energy == pytest.approx(-2.15)
    assert result.adapt_history[-1].n_operators == 4


def test_molecule_json_circuit_format():
    circuit = CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized='{"build_type": "external", "filename": "He-ccpvdz.json", "basis": "cc-pvdz"}',
    )
    assert circuit.format == CircuitFormat.MOLECULE_JSON
    assert "build_type" in circuit.serialized


def test_vqa_config_chemistry_fields():
    vqa = VQAConfig(
        problem_type="chemistry",
        molecule="He",
        basis="cc-pvdz",
        num_electrons=2,
        num_alpha=1,
        num_beta=1,
        hf_energy=-2.8551,
        algorithm="UCCNVQE",
        pool_type="SD",
        n_cnot=4,
        n_pauli_trm_measures=240,
        final_eigenvalue=-2.9003,
        ground_truth=-2.9003,
    )
    assert vqa.num_electrons == 2
    assert vqa.algorithm == "UCCNVQE"
    assert vqa.pool_type == "SD"
    assert vqa.n_cnot == 4
    assert vqa.chemical_accuracy is True


def test_vqa_config_adapt_maxiter_flag():
    vqa = VQAConfig(
        problem_type="chemistry",
        algorithm="ADAPTVQE",
        adapt_maxiter_reached=True,
        final_eigenvalue=-2.10,
        ground_truth=-2.16,
    )
    assert vqa.adapt_maxiter_reached is True
    assert vqa.chemical_accuracy is False   # error > 1 mHartree


# ---------------------------------------------------------------------------
# AlgorithmAdapter + runner integration (mock, no QForte required)
# ---------------------------------------------------------------------------

class _MockQForteAdapter:
    """Minimal AlgorithmAdapter that mimics QForteAdapter without QForte."""

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(name="mock_qforte", provider="qforte", simulator=True)

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        if circuit.format != CircuitFormat.MOLECULE_JSON:
            return [f"Expected MOLECULE_JSON, got {circuit.format}"]
        return []

    def run_algorithm(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[QuantumResult, VQAConfig]:
        alg_name = (options.algorithm_spec.name
                    if options.algorithm_spec else "UCCNVQE")
        result = QuantumResult(
            modality=QPUModality.GATE_BASED,
            expectation_values=[
                ExpectationResult(
                    observable_index=0,
                    value=-2.9003,
                    std_error=0.0,
                )
            ],
            adapt_history=(
                [AdaptIteration(iteration=0, energy=-2.90, grad_norm=1e-5,
                                n_operators=1, n_cnot=2, n_classical_params=1)]
                if alg_name == "ADAPTVQE" else None
            ),
            status=JobStatus.SUCCEEDED,
        )
        vqa = VQAConfig(
            problem_type="chemistry",
            molecule="He",
            basis="cc-pvdz",
            algorithm=alg_name,
            final_eigenvalue=-2.9003,
            ground_truth=-2.9003,
        )
        return result, vqa


def test_algorithm_adapter_via_runner():
    from qpubench import BenchmarkRunner

    mol_spec = CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized='{"build_type": "external", "filename": "He.json"}',
    )
    runner = BenchmarkRunner()
    runner.register(_MockQForteAdapter(), name="mock_qforte")

    record = runner.run(
        mol_spec,
        "mock_qforte",
        ExecutionOptions(algorithm_spec=AlgorithmSpec(name="UCCNVQE")),
        tags=["qforte", "test"],
    )
    assert record.result.status == JobStatus.SUCCEEDED
    assert record.vqa is not None
    assert record.vqa.algorithm == "UCCNVQE"
    assert record.vqa.chemical_accuracy is True
    assert record.result.expectation_values[0].value == pytest.approx(-2.9003)


def test_adapt_vqe_via_algorithm_adapter():
    from qpubench import BenchmarkRunner

    mol_spec = CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized='{"build_type": "external", "filename": "He.json"}',
    )
    runner = BenchmarkRunner()
    runner.register(_MockQForteAdapter(), name="mock_qforte")

    record = runner.run(
        mol_spec,
        "mock_qforte",
        ExecutionOptions(algorithm_spec=AlgorithmSpec(name="ADAPTVQE", avqe_thresh=1.0e-4)),
    )
    assert record.result.adapt_history is not None
    assert len(record.result.adapt_history) == 1
    assert record.result.adapt_history[0].n_cnot == 2


def test_algorithm_adapter_sweep():
    from qpubench import BenchmarkRunner

    mol_spec = CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized='{"build_type": "external", "filename": "He.json"}',
    )
    runner = BenchmarkRunner()
    runner.register(_MockQForteAdapter(), name="mock_qforte")

    records = runner.sweep(
        circuits=[mol_spec],
        backend_names=["mock_qforte"],
        options_list=[
            ExecutionOptions(algorithm_spec=AlgorithmSpec(name=name))
            for name in ["UCCNVQE", "ADAPTVQE"]
        ],
        run_id="he_sweep",
        tags=["sweep"],
    )
    assert len(records) == 2
    algorithms = {r.vqa.algorithm for r in records}
    assert algorithms == {"UCCNVQE", "ADAPTVQE"}


def test_benchmark_record_algorithm_json_roundtrip():
    from qpubench import BenchmarkRunner
    import json as _json

    mol_spec = CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized="mock.json",
    )
    runner = BenchmarkRunner()
    runner.register(_MockQForteAdapter(), name="mock_qforte")
    record = runner.run(
        mol_spec, "mock_qforte",
        ExecutionOptions(algorithm_spec=AlgorithmSpec(name="UCCNVQE")),
    )
    json_str = record.model_dump_json()
    data = _json.loads(json_str)
    assert data["options"]["algorithm_spec"]["name"] == "UCCNVQE"
    restored = BenchmarkRecord.model_validate_json(json_str)
    assert restored.vqa.algorithm == "UCCNVQE"


# ---------------------------------------------------------------------------
# QDK chemistry pipeline schemas
# ---------------------------------------------------------------------------

def test_molecule_structure_spec():
    from qpubench.schemas.qdk_chemistry import AtomSpec, CoordinateUnit, MoleculeStructureSpec
    mol = MoleculeStructureSpec(
        atoms=[
            AtomSpec(symbol="N", x=0.0, y=0.0, z=-0.55),
            AtomSpec(symbol="N", x=0.0, y=0.0, z=0.55),
        ],
        charge=0,
        spin_multiplicity=1,
        units=CoordinateUnit.ANGSTROM,
        name="stretched_N2",
    )
    assert mol.num_atoms == 2
    assert mol.formula == "N2"
    data = mol.model_dump()
    assert data["charge"] == 0


def test_scf_run_config_and_result():
    from qpubench.schemas.qdk_chemistry import SCFMethod, SCFRunConfig, SCFResult
    cfg = SCFRunConfig(method=SCFMethod.HF, basis_or_guess="cc-pvdz")
    res = SCFResult(
        hf_energy=-108.954_000,
        num_alpha=7,
        num_beta=7,
        num_basis_functions=28,
        stable=True,
    )
    assert res.hf_energy < 0
    assert cfg.convergence == 1.0e-9


def test_active_space_selection_config():
    from qpubench.schemas.qdk_chemistry import (
        ActiveSpaceSelectorType,
        ActiveSpaceSelectionConfig,
        ActiveSpaceSelectionResult,
    )
    cfg = ActiveSpaceSelectionConfig(
        selector_type=ActiveSpaceSelectorType.QDK_AUTOCAS_EOS,
        entropy_threshold=0.1,
    )
    result = ActiveSpaceSelectionResult(
        selector_type=ActiveSpaceSelectorType.QDK_AUTOCAS_EOS,
        alpha_indices=[0, 1, 2, 3],
        beta_indices=[0, 1, 2, 3],
        num_active_electrons=10,
        num_active_orbitals=4,
        num_qubits=8,
    )
    assert result.num_qubits == 8
    assert cfg.selector_type == ActiveSpaceSelectorType.QDK_AUTOCAS_EOS


def test_qubit_hamiltonian_spec():
    from qpubench.schemas.qdk_chemistry import (
        PauliStringTerm,
        QubitEncodingType,
        QubitHamiltonianSpec,
    )
    import math
    schatten = 4.7231
    qham = QubitHamiltonianSpec(
        num_qubits=8,
        num_pauli_terms=161,
        schatten_norm=schatten,
        encoding=QubitEncodingType.JORDAN_WIGNER,
        evolution_time_max=math.pi / schatten,
        pauli_terms=[PauliStringTerm(pauli_string="IIIIZZZZ", coefficient=-0.3215)],
    )
    assert qham.num_pauli_terms == 161
    assert math.isclose(qham.evolution_time_max, math.pi / schatten, rel_tol=1e-9)


def test_model_hamiltonian_ising():
    from qpubench.schemas.qdk_chemistry import (
        BoundaryCondition,
        IsingParams,
        LatticeGraphSpec,
        LatticeTopology,
        ModelHamiltonianSpec,
        ModelHamiltonianType,
    )
    spec = ModelHamiltonianSpec(
        hamiltonian_type=ModelHamiltonianType.ISING,
        lattice=LatticeGraphSpec(
            topology=LatticeTopology.CHAIN,
            num_sites=6,
            boundary_condition=BoundaryCondition.OPEN,
        ),
        ising=IsingParams(J=1.0, h=0.5),
    )
    assert spec.lattice.num_sites == 6
    assert spec.ising.h == 0.5


def test_model_hamiltonian_only_one_param_block():
    from qpubench.schemas.qdk_chemistry import (
        HeisenbergParams,
        IsingParams,
        LatticeGraphSpec,
        LatticeTopology,
        ModelHamiltonianSpec,
        ModelHamiltonianType,
    )
    import pytest
    with pytest.raises(Exception):
        ModelHamiltonianSpec(
            hamiltonian_type=ModelHamiltonianType.ISING,
            lattice=LatticeGraphSpec(topology=LatticeTopology.RING, num_sites=4),
            ising=IsingParams(J=1.0, h=0.5),
            heisenberg=HeisenbergParams(J=1.0),
        )


def test_qpe_config_and_result():
    from qpubench.schemas.qdk_chemistry import (
        QPEConfig,
        QPEMethod,
        QPEResult,
        TimeEvolutionBuilderType,
        TimeEvolutionConfig,
        TrotterConfig,
    )
    cfg = QPEConfig(
        method=QPEMethod.ITERATIVE,
        evolution_time=0.6647,
        num_bits=8,
        shots_per_bit=10,
        time_evolution=TimeEvolutionConfig(
            builder_type=TimeEvolutionBuilderType.TROTTER,
            evolution_time=0.6647,
            trotter_config=TrotterConfig(order=1, num_step_terms=161),
        ),
    )
    result = QPEResult(
        raw_energy=-108.954_123,
        bitstring_msb_first="10110100",
        alias_branches=[-108.954_123, -102.341],
        error_mha=0.5,
        quantization_limit_mha=1.7,
        num_bits_used=8,
        evolution_time=0.6647,
        exact_reference_energy=-108.954_623,
    )
    assert result.raw_energy < 0
    assert len(result.bitstring_msb_first) == 8
    assert cfg.time_evolution.trotter_config.num_step_terms == 161


def test_resource_estimator_config():
    from qpubench.schemas.qdk_chemistry import (
        ErrorBudgetPartition,
        QECScheme,
        QubitParamsType,
        ResourceEstimatorConfig,
        ResourceEstimationResult,
    )
    cfg = ResourceEstimatorConfig(
        qubit_params=QubitParamsType.GATE_NS_E3,
        qec_scheme=QECScheme.SURFACE_CODE,
        error_budget=ErrorBudgetPartition(
            logical_error_rate=1e-3,
            distillation_failure_rate=1e-4,
            rotation_synthesis_error=1e-4,
        ),
    )
    res = ResourceEstimationResult(
        num_physical_qubits=1_000_000,
        runtime_seconds=3600.0,
        num_logical_qubits=100,
        code_distance=21,
        t_factory_count=12,
        t_states_required=5_000_000,
    )
    assert res.code_distance == 21
    assert cfg.qec_scheme == QECScheme.SURFACE_CODE


def test_qchem_pipeline_spec_roundtrip():
    from qpubench.schemas.qdk_chemistry import (
        AtomSpec,
        CoordinateUnit,
        FermionicHamiltonianSpec,
        MoleculeStructureSpec,
        QChemPipelineSpec,
        QubitEncodingType,
        QubitHamiltonianSpec,
        SCFResult,
        SCFRunConfig,
    )
    pipeline = QChemPipelineSpec(
        molecule=MoleculeStructureSpec(
            atoms=[
                AtomSpec(symbol="N", x=0.0, y=0.0, z=-0.55),
                AtomSpec(symbol="N", x=0.0, y=0.0, z=0.55),
            ],
            name="stretched_N2",
        ),
        scf_config=SCFRunConfig(basis_or_guess="cc-pvdz"),
        scf_result=SCFResult(
            hf_energy=-108.954,
            num_alpha=7,
            num_beta=7,
            num_basis_functions=28,
        ),
        fermionic_hamiltonian=FermionicHamiltonianSpec(
            num_active_orbitals=4,
            num_active_electrons_alpha=5,
            num_active_electrons_beta=5,
            core_energy=-99.12,
            num_one_body_integrals=16,
            num_two_body_integrals=256,
            schatten_norm=4.7231,
        ),
        qubit_hamiltonian=QubitHamiltonianSpec(
            num_qubits=8,
            num_pauli_terms=161,
            schatten_norm=4.7231,
            encoding=QubitEncodingType.JORDAN_WIGNER,
        ),
    )
    json_str = pipeline.model_dump_json()
    import json
    data = json.loads(json_str)
    assert data["molecule"]["name"] == "stretched_N2"
    restored = QChemPipelineSpec.model_validate_json(json_str)
    assert restored.fermionic_hamiltonian.num_active_orbitals == 4
    assert restored.qubit_hamiltonian.num_qubits == 8


def test_backend_spec_qdk_chemistry_simulator():
    b = BackendSpec.qdk_chemistry_simulator(
        executor="qdk_sparse_state_simulator",
        num_qubits=8,
    )
    assert b.provider == "qdk_chemistry"
    assert b.simulator is True
    assert b.qpu_modality == QPUModality.QPE


def test_backend_spec_azure_quantum():
    b = BackendSpec.azure_quantum(
        "microsoft.estimator",
        resource_id_ref="AZ_RESOURCE_ID",
        location_ref="AZ_LOCATION",
    )
    assert b.provider == "azure_quantum"
    assert b.simulator is True
    assert b.auth["target"] == "microsoft.estimator"


# ---------------------------------------------------------------------------
# GBS schemas (DTU-GBS / photonic_QC)
# ---------------------------------------------------------------------------

def test_gbs_program_spec_fock_path():
    from qpubench.schemas.gbs import (
        GBSMeasurementType,
        GBSProgramSpec,
        InterferometerSpec,
        SqueezingGateSpec,
    )
    import math
    r = 0.5
    # 4-mode GBS: 4 squeezed inputs + random 4×4 interferometer
    U = [1.0, 0.0, 0.0, 0.0,
         0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0,
         0.0, 0.0, 0.0, 1.0]
    prog = GBSProgramSpec(
        num_modes=4,
        squeezing_params=[SqueezingGateSpec(mode_index=i, r=r) for i in range(4)],
        interferometer=InterferometerSpec(
            mode_indices=[0, 1, 2, 3],
            unitary_real=U,
            unitary_imag=[0.0] * 16,
        ),
        measurement_type=GBSMeasurementType.FOCK,
    )
    assert prog.num_modes == 4
    assert len(prog.squeezing_params) == 4
    assert math.isclose(prog.squeezing_params[0].r, 0.5)


def test_gbs_program_spec_s2gate_path():
    from qpubench.schemas.gbs import GBSMeasurementType, GBSProgramSpec, S2GateSpec
    prog = GBSProgramSpec(
        num_modes=4,
        s2_gates=[S2GateSpec(mode_a=i, mode_b=i + 4, r=1.0) for i in range(4)],
        measurement_type=GBSMeasurementType.FOCK,
    )
    assert len(prog.s2_gates) == 4
    assert prog.s2_gates[0].mode_b == 4


def test_gbs_sample_properties():
    from qpubench.schemas.gbs import GBSSample
    s = GBSSample(photon_numbers=[0, 1, 2, 0, 1])
    assert s.total_photons == 4
    assert s.num_clicks == 0   # no click_pattern set

    t = GBSSample(click_pattern=[1, 0, 1, 1, 0])
    assert t.num_clicks == 3


def test_gbs_sampling_result_roundtrip():
    import json
    from qpubench.schemas.gbs import (
        GBSBackendType,
        GBSMeasurementType,
        GBSProgramSpec,
        GBSSample,
        GBSSamplingConfig,
        GBSSamplingResult,
        SqueezingGateSpec,
    )
    prog = GBSProgramSpec(
        num_modes=2,
        squeezing_params=[SqueezingGateSpec(mode_index=0, r=0.5),
                          SqueezingGateSpec(mode_index=1, r=0.5)],
        measurement_type=GBSMeasurementType.THRESHOLD,
    )
    cfg = GBSSamplingConfig(
        program=prog,
        backend_type=GBSBackendType.GAUSSIAN_SIMULATOR,
        num_shots=10,
        seed=42,
    )
    res = GBSSamplingResult(
        config=cfg,
        samples=[GBSSample(click_pattern=[1, 0]), GBSSample(click_pattern=[0, 1])],
        mean_photon_number=0.5,
        num_shots_completed=2,
    )
    json_str = res.model_dump_json()
    data = json.loads(json_str)
    assert data["config"]["num_shots"] == 10
    restored = GBSSamplingResult.model_validate_json(json_str)
    assert restored.samples[0].click_pattern == [1, 0]


def test_gaussian_state_spec():
    from qpubench.schemas.gbs import GaussianStateSpec, GaussianStateType, QuadratureOrdering
    # 2-mode squeezed vacuum: 4×4 covariance matrix (trivial identity for vacuum)
    V = [1.0] * 16   # placeholder 4×4 flattened
    state = GaussianStateSpec(
        num_modes=2,
        state_type=GaussianStateType.TWO_MODE_SQUEEZED,
        covariance_matrix=V,
        quadrature_ordering=QuadratureOrdering.XP_BLOCKS,
    )
    assert state.num_modes == 2
    assert len(state.covariance_matrix) == 16


def test_hafnian_matrix_spec():
    from qpubench.schemas.gbs import HafnianMatrixSpec, QuadratureOrdering
    # 4×4 A matrix for 2 modes
    spec = HafnianMatrixSpec(
        num_modes=2,
        A_real=[0.0] * 16,
        A_imag=[0.0] * 16,
        index_convention=QuadratureOrdering.INTERLEAVED,
    )
    assert spec.num_modes == 2
    assert len(spec.A_real) == 16


def test_takagi_decomposition_spec():
    from qpubench.schemas.gbs import TakagiDecompositionSpec
    import math
    spec = TakagiDecompositionSpec(
        singular_values=[0.8, 0.6, 0.4, 0.2],
        unitary_real=[1.0, 0.0, 0.0, 0.0,
                      0.0, 1.0, 0.0, 0.0,
                      0.0, 0.0, 1.0, 0.0,
                      0.0, 0.0, 0.0, 1.0],
        unitary_imag=[0.0] * 16,
        num_modes=4,
    )
    assert len(spec.singular_values) == 4
    assert math.isclose(spec.singular_values[0], 0.8)


def test_gbs_clique_finding_result():
    from qpubench.schemas.gbs import GBSCliqueFindingResult, GBSGraphConfig, GraphScalingMethod
    import json
    A = [0, 1, 1, 0,
         1, 0, 1, 1,
         1, 1, 0, 1,
         0, 1, 1, 0]
    cfg = GBSGraphConfig(
        adjacency_matrix=A,
        num_nodes=4,
        num_photons=2,
        num_samples=100,
        scaling_method=GraphScalingMethod.DIVIDE_BY_MAX,
    )
    res = GBSCliqueFindingResult(
        config=cfg,
        raw_samples=[[0, 1], [1, 2], [2, 3]],
        shrunk_cliques=[[0, 1], [1, 2], [2, 3]],
        searched_cliques=[[0, 1, 2], [1, 2, 3]],
        mean_density=0.75,
        mean_clique_size=2.5,
        max_clique_size=3,
        min_clique_size=2,
    )
    json_str = res.model_dump_json()
    restored = GBSCliqueFindingResult.model_validate_json(json_str)
    assert restored.max_clique_size == 3
    assert len(restored.raw_samples) == 3


def test_vibronic_spectrum_config_and_result():
    from qpubench.schemas.gbs import (
        DuschinskyResult,
        NormalModeData,
        VibronicGBSParams,
        VibronicSpectrumConfig,
        VibronicSpectrumResult,
    )
    import json
    cfg = VibronicSpectrumConfig(
        molecule_name="water",
        ground_state_file="Ground_Water.out.txt",
        excited_state_file="Excited_Water.txt",
        temperature_K=0.0,
        num_samples=100,
        freq_range_cm1=(-1000.0, 8000.0),
    )
    ground = NormalModeData(
        num_atoms=3,
        num_modes=3,
        equilibrium_geometry=[0.0, -0.121, 0.0, 1.425, 0.962, 0.0, -1.425, 0.962, 0.0],
        normal_mode_vectors=[1.0] * 9,
        frequencies_cm1=[1595.0, 3657.0, 3756.0],
        atomic_masses_amu=[15.995, 1.008, 1.008],
    )
    dusch = DuschinskyResult(
        num_modes=3,
        rotation_matrix_Ud=[1.0, 0.0, 0.0,
                            0.0, 1.0, 0.0,
                            0.0, 0.0, 1.0],
        displacement_delta=[0.01, 0.02, 0.0],
    )
    params = VibronicGBSParams(
        num_modes=3,
        t=[0.1, 0.05, 0.0],
        U1_real=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        U1_imag=[0.0] * 9,
        r=[0.2, 0.15, 0.05],
        U2_real=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        U2_imag=[0.0] * 9,
        alpha_real=[0.0, 0.0, 0.0],
        alpha_imag=[0.0, 0.0, 0.0],
    )
    result = VibronicSpectrumResult(
        config=cfg,
        ground_state_data=ground,
        duschinsky=dusch,
        gbs_params=params,
        sample_energies_cm1=[0.0, 1595.0, 3657.0],
        histogram_bins=[0.0, 1000.0, 2000.0, 4000.0],
        histogram_counts=[50.0, 30.0, 20.0],
        reference_peak_positions=[0.0, 1420.0, 3100.0],
        reference_peak_intensities=[100.0, 23.9, 2.6],
        num_samples_completed=100,
    )
    json_str = result.model_dump_json()
    data = json.loads(json_str)
    assert data["config"]["molecule_name"] == "water"
    restored = VibronicSpectrumResult.model_validate_json(json_str)
    assert restored.duschinsky.num_modes == 3
    assert len(restored.sample_energies_cm1) == 3


def test_tdm_gbs_config():
    from qpubench.schemas.gbs import TDMDelaySpec, TDMGBSConfig, TDMSqueezingLevel
    delays = TDMDelaySpec(delays=[1, 6, 36], effective_modes=216)
    cfg = TDMGBSConfig(
        delays=delays,
        squeezing_level=TDMSqueezingLevel.HIGH,
        num_shots=10_000,
        crop=True,
        num_modes_requested=216,
        device_arn="arn:aws:braket:us-east-1::device/qpu/xanadu/Borealis",
    )
    assert cfg.delays.effective_modes == 216
    assert cfg.squeezing_level == TDMSqueezingLevel.HIGH


def test_cluster_state_spec():
    from qpubench.schemas.gbs import ClusterStateSpec, GaussianStateType
    import math
    spec = ClusterStateSpec(
        state_type=GaussianStateType.CLUSTER_1D,
        num_nodes=5,
        squeezing_r=0.5,
        measurement_angles=[0.0, math.pi / 4, math.pi / 2, 0.0, math.pi / 4],
    )
    assert spec.num_nodes == 5
    assert len(spec.measurement_angles) == 5


def test_backend_spec_xanadu_x8():
    b = BackendSpec.xanadu_x8()
    assert b.provider == "xanadu"
    assert b.qpu_modality == QPUModality.GBS
    assert b.simulator is False


def test_backend_spec_xanadu_borealis():
    b = BackendSpec.xanadu_borealis(via_braket=True)
    assert b.provider == "aws_braket"
    assert b.qpu_modality == QPUModality.GBS
    assert "Borealis" in b.auth["device_arn"]


def test_backend_spec_strawberry_fields_gaussian():
    b = BackendSpec.strawberry_fields_gaussian(num_modes=12)
    assert b.provider == "strawberry_fields"
    assert b.qpu_modality == QPUModality.GBS
    assert b.simulator is True


# ---------------------------------------------------------------------------
# QSE / KQD schemas (v1.7.0)
# ---------------------------------------------------------------------------

def test_neel_state_spec():
    from qpubench.schemas.qse import NeelStateSpec
    s = NeelStateSpec(num_spins=8, shift=0)
    assert s.num_spins == 8
    assert s.shift == 0


def test_slater_determinant_ref():
    from qpubench.schemas.qse import SlaterDeterminantRef
    ref = SlaterDeterminantRef(ncas=4, occ_alpha=[0, 1], occ_beta=[0, 1])
    assert ref.num_qubits == 8
    assert ref.num_electrons == 4
    bits = ref.bitstring
    assert len(bits) == 8
    assert bits[0] == "1"
    assert bits[4] == "1"


def test_kqd_reference_spec_neel():
    from qpubench.schemas.qse import KQDReferenceSpec, KQDReferenceStateType, NeelStateSpec
    neel = NeelStateSpec(num_spins=6, shift=0)
    ref = KQDReferenceSpec(
        state_type=KQDReferenceStateType.NEEL,
        bitstring="101010",
        neel=neel,
        label="neel_shift0",
    )
    assert ref.state_type == KQDReferenceStateType.NEEL
    assert ref.bitstring == "101010"


def test_kqd_time_evolution_spec():
    from qpubench.schemas.qse import KQDTimeEvolutionSpec, KrylovTimeEvolutionVariant
    import math
    dt = math.pi / 3.0
    spec = KQDTimeEvolutionSpec(dt=dt, num_trotter_steps=6)
    assert spec.dt_circ == pytest.approx(dt / 6)
    assert spec.variant == KrylovTimeEvolutionVariant.EFFICIENT_ALTERNATING


def test_krylov_circuit_family_spec():
    from qpubench.schemas.qse import KrylovCircuitFamilySpec, KQDMethod
    fam = KrylovCircuitFamilySpec(
        method=KQDMethod.HADAMARD_TEST,
        num_qubits_system=10,
        krylov_dim=6,
        num_references=1,
        num_circuits=6,
        circuit_labels=[[0, i] for i in range(6)],
        shots_per_circuit=1024,
        ancilla_qubits=1,
    )
    assert fam.num_circuits == 6
    assert len(fam.circuit_labels) == 6
    assert fam.ancilla_qubits == 1


def test_krylov_subspace_matrices():
    from qpubench.schemas.qse import KrylovMatrixSpec, KrylovSubspaceMatrices
    dim = 4
    identity_flat = [1.0, 0.0, 0.0, 0.0,
                     0.0, 1.0, 0.0, 0.0,
                     0.0, 0.0, 1.0, 0.0,
                     0.0, 0.0, 0.0, 1.0]
    S = KrylovMatrixSpec(label="S", dim=dim, matrix_real=identity_flat, matrix_imag=[0.0]*16)
    H = KrylovMatrixSpec(label="H", dim=dim, matrix_real=[-1.0]*16, matrix_imag=[0.0]*16)
    mats = KrylovSubspaceMatrices(S_matrix=S, H_matrix=H, krylov_dim=4)
    assert mats.S_matrix.dim == 4
    assert mats.assembly_method == "hadamard_test"


def test_krylov_eigen_result():
    from qpubench.schemas.qse import KrylovEigenResult
    res = KrylovEigenResult(
        eigenvalues=[-2.81, -1.23, 0.45, 1.87],
        ground_state_energy=-2.81,
        S_eigenvalues=[0.98, 0.75, 0.43, 0.02],
        num_eigenvalues_discarded=0,
        krylov_dim_effective=4,
    )
    assert res.ground_state_energy == pytest.approx(-2.81)
    assert res.krylov_dim_effective == 4


def test_sqd_convergence_result():
    from qpubench.schemas.qse import SQDStep, SQDConvergenceResult
    steps = [
        SQDStep(krylov_step=0, num_bitstrings=10, subspace_dim=10, energy_hartree=-1.1),
        SQDStep(krylov_step=1, num_bitstrings=18, subspace_dim=18, energy_hartree=-1.136),
        SQDStep(krylov_step=2, num_bitstrings=23, subspace_dim=23, energy_hartree=-1.1516),
    ]
    result = SQDConvergenceResult(
        steps=steps,
        final_energy=-1.1516,
        exact_energy=-1.1517530,
    )
    assert result.error_mha == pytest.approx(abs(-1.1516 - -1.1517530) * 1000.0)
    assert len(result.steps) == 3


def test_cumulative_krylov_counts():
    from qpubench.schemas.qse import CumulativeKrylovCounts, SQDPostselectionConfig
    postsel = SQDPostselectionConfig(num_ones=2, min_unique=1)
    counts_obj = CumulativeKrylovCounts(
        cumulative_counts=[{"01": 10, "10": 8}, {"01": 15, "10": 12, "11": 0}],
        postselection=postsel,
        num_references_pooled=1,
    )
    assert counts_obj.postselection.num_ones == 2
    assert len(counts_obj.cumulative_counts) == 2


def test_cholesky_decomposition_spec():
    from qpubench.schemas.qse import CholeskyDecompositionSpec
    spec = CholeskyDecompositionSpec(
        num_orbitals=4,
        eps=1.0e-6,
        n_chol=12,
        max_cholesky=80,
        accuracy=3.2e-7,
    )
    assert spec.n_chol == 12
    assert spec.accuracy == pytest.approx(3.2e-7)


def test_kqd_pipeline_spec_roundtrip():
    import json
    import math
    from qpubench.schemas.qse import (
        CholeskyDecompositionSpec,
        KQDConfig,
        KQDMethod,
        KQDPipelineSpec,
        KQDReferenceSpec,
        KQDReferenceStateType,
        KQDTimeEvolutionSpec,
        KrylovEigenResult,
        NeelStateSpec,
        RegularizationConfig,
    )
    dt = math.pi / 3.0
    pipeline = KQDPipelineSpec(
        num_qubits=10,
        hamiltonian_label="heisenberg_chain_10",
        kqd_config=KQDConfig(
            method=KQDMethod.HADAMARD_TEST,
            krylov_dim=6,
            num_references=2,
            dt=dt,
            num_trotter_steps=6,
            regularization=RegularizationConfig(threshold=1.0e-6, num_eigenvalues_k=4),
        ),
        time_evolution=KQDTimeEvolutionSpec(dt=dt, num_trotter_steps=6),
        reference_states=[
            KQDReferenceSpec(
                state_type=KQDReferenceStateType.NEEL,
                bitstring="1010101010",
                neel=NeelStateSpec(num_spins=10, shift=0),
                label="neel_0",
            ),
            KQDReferenceSpec(
                state_type=KQDReferenceStateType.NEEL,
                bitstring="0101010101",
                neel=NeelStateSpec(num_spins=10, shift=1),
                label="neel_1",
            ),
        ],
        eigen_result=KrylovEigenResult(
            eigenvalues=[-4.258, -3.11, -1.95],
            ground_state_energy=-4.258,
            S_eigenvalues=[0.99, 0.87, 0.60],
            krylov_dim_effective=3,
        ),
        exact_energy=-4.2588,
        cholesky_spec=CholeskyDecompositionSpec(num_orbitals=4, n_chol=12),
    )
    json_str = pipeline.model_dump_json()
    data = json.loads(json_str)
    assert data["num_qubits"] == 10
    assert data["hamiltonian_label"] == "heisenberg_chain_10"
    restored = KQDPipelineSpec.model_validate_json(json_str)
    assert restored.eigen_result.ground_state_energy == pytest.approx(-4.258)
    assert len(restored.reference_states) == 2


def test_quantum_result_kqd_field():
    import json
    import math
    from qpubench.schemas.qse import KQDConfig, KQDMethod, KQDPipelineSpec
    pipeline = KQDPipelineSpec(
        num_qubits=6,
        hamiltonian_label="ising_chain_6",
        kqd_config=KQDConfig(method=KQDMethod.SAMPLE_BASED_SQD, krylov_dim=4),
    )
    result = QuantumResult(
        modality=QPUModality.KQD,
        kqd_pipeline=pipeline,
    )
    json_str = result.model_dump_json()
    data = json.loads(json_str)
    assert data["modality"] == "kqd"
    assert data["kqd_pipeline"]["hamiltonian_label"] == "ising_chain_6"
    restored = QuantumResult.model_validate_json(json_str)
    assert restored.kqd_pipeline.num_qubits == 6


def test_backend_spec_qiskit_aer():
    b = BackendSpec.qiskit_aer(method="statevector", num_qubits=12)
    assert b.provider == "aer"
    assert b.qpu_modality == QPUModality.KQD
    assert b.simulator is True
    assert b.num_qubits == 12
    assert b.num_qubits == 12
