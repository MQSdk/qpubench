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
    assert data["schema_version"] == "1.3.0"
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
    assert restored.result.expectation_values[0].value == pytest.approx(-2.9003)
