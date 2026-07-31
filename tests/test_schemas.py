"""Schema unit tests.

These tests exercise the schema layer only — no quantum SDK dependencies.
Run with: pytest tests/
"""
from __future__ import annotations

import json
import math

import pydantic
import pytest

from qpubench.schemas.backend import BackendSpec, GateCharacteristics, QubitCharacteristics
from qpubench.schemas.catalogs.reactions import (
    ArrheniusRateConstant,
    KineticsReactionSpec,
    KineticsSpeciesSpec,
    ReactionCoordinateSpec,
    ReactionMechanism,
    ReactionPathResult,
    ReactionType,
)
from qpubench.schemas.circuit import CircuitSpec, ParameterBinding
from qpubench.schemas.execution import ExecutionOptions, TranspilerConfig, ZNEConfig
from qpubench.schemas.mirrors.johnrscott_mbqc_fpga import (
    AdaptiveSpec,
    ByproductUpdateSpec,
    CommutationSpec,
    MBQCExecutionResult,
    MBQCPattern,
    MBQCProgramWord,
    MBQCQubitState,
    MBQCRound,
)
from qpubench.schemas.observable import Pauli, PauliTerm, SparsePauliObservable
from qpubench.schemas.primitives import (
    CircuitFormat,
    ComplexNumber,
    ComputingModel,
    ErrorMitigationStrategy,
    JobStatus,
    PauliLabel,
    QubitModality,
)
from qpubench.schemas.record import SCHEMA_VERSION, BenchmarkRecord, VQAConfig, VQAResult
from qpubench.schemas.result import (
    ExpectationResult,
    QuantumResult,
    ShotResult,
    TranspileLayout,
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


def test_pauli_shorthand_matches_explicit_construction():
    """Pauli() is sugar — it must build exactly what the long form builds."""
    assert Pauli("Z0 Z1") == SparsePauliObservable(
        num_qubits=2,
        terms=[
            PauliTerm(
                qubit_indices=(0, 1),
                pauli_ops=(PauliLabel.Z, PauliLabel.Z),
                coefficient=ComplexNumber(re=1.0),
            )
        ],
    )
    assert Pauli("X1,Z3", 0.5) == Pauli("X1 Z3", 0.5)   # either separator parses
    assert Pauli("X0 Y1") == Pauli("y1 x0")             # order and case are irrelevant


def test_pauli_num_qubits_inference():
    assert Pauli("Z0 Z1").num_qubits == 2
    assert Pauli("X3").num_qubits == 4               # one past the highest index
    assert Pauli("X0", num_qubits=7).num_qubits == 7  # explicit wins
    assert Pauli("").num_qubits == 0                  # identity mentions no qubit
    assert Pauli("").terms[0].qubit_indices == ()


def test_pauli_rejects_malformed_input():
    with pytest.raises(ValueError, match="Malformed Pauli factor"):
        Pauli("Q0")
    with pytest.raises(ValueError, match="Malformed Pauli factor"):
        Pauli("Z")                                    # letter without an index
    with pytest.raises(ValueError, match="more than one factor"):
        Pauli("Z0 X0")                                # ambiguous product order
    with pytest.raises(ValueError, match="mapping's values"):
        Pauli({"Z0": 1.0}, 0.5)


def test_observable_arithmetic():
    h = -1.05 * Pauli("") + 0.39 * Pauli("Z0") - 0.39 * Pauli("Z1") + 0.18 * Pauli("X0 X1")
    assert h.num_qubits == 2                          # widest summand wins
    assert [t.coefficient.re for t in h.terms] == [-1.05, 0.39, -0.39, 0.18]
    assert h == Pauli({"": -1.05, "Z0": 0.39, "Z1": -0.39, "X0 X1": 0.18}, num_qubits=2)

    assert (Pauli("Z0") / 2).terms[0].coefficient.re == 0.5
    assert (-Pauli("Z0")).terms[0].coefficient.re == -1.0
    assert sum([Pauli("Z0"), Pauli("X1")]) == Pauli({"Z0": 1.0, "X1": 1.0})  # sum() starts at 0

    with pytest.raises(TypeError):
        Pauli("Z0") + 3
    with pytest.raises(TypeError):
        Pauli("Z0") * Pauli("Z1")


def test_observable_arithmetic_agrees_with_dense_matrix():
    """The operators must mean what they say on the resulting matrix."""
    h = 0.5 * Pauli("Z0") + 0.25 * Pauli("X0")
    assert h.to_dense_matrix() == [[0.5, 0.25], [0.25, -0.5]]
    assert (h - h).to_dense_matrix() == [[0.0, 0.0], [0.0, 0.0]]
    assert (2 * h).to_dense_matrix() == [[1.0, 0.5], [0.5, -1.0]]


def test_observable_simplify_merges_like_terms():
    h = Pauli("Z0") + Pauli("Z0") + Pauli("X0 Z1") + Pauli("Z1 X0")
    simplified = h.simplify()
    assert len(simplified.terms) == 2                 # factor order does not block a merge
    assert simplified.num_qubits == h.num_qubits == 2
    assert sorted(t.coefficient.re for t in simplified.terms) == [2.0, 2.0]
    assert simplified.to_dense_matrix() == h.to_dense_matrix()   # same operator either way

    assert (Pauli("Y0") - Pauli("Y0")).simplify().terms == []    # exact cancellation drops out


def test_to_dense_matrix_single_qubit_paulis():
    for label, expected in [
        (PauliLabel.X, [[0.0, 1.0], [1.0, 0.0]]),
        (PauliLabel.Z, [[1.0, 0.0], [0.0, -1.0]]),
    ]:
        spo = SparsePauliObservable(
            num_qubits=1,
            terms=[PauliTerm(qubit_indices=(0,), pauli_ops=(label,))],
        )
        assert spo.to_dense_matrix() == expected


def test_to_dense_matrix_pauli_y_is_complex():
    spo = SparsePauliObservable(
        num_qubits=1,
        terms=[PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.Y,))],
    )
    # Y = [[0, -i], [i, 0]] — real=True (default) must refuse it
    with pytest.raises(ValueError):
        spo.to_dense_matrix()
    m = spo.to_dense_matrix(real=False)
    assert m == [[0j, -1j], [1j, 0j]]


def test_to_dense_matrix_two_qubit_zz():
    spo = SparsePauliObservable(
        num_qubits=2,
        terms=[PauliTerm(qubit_indices=(0, 1), pauli_ops=(PauliLabel.Z, PauliLabel.Z),
                         coefficient=ComplexNumber(re=0.5))],
    )
    m = spo.to_dense_matrix()
    # ZZ diag = (+1, -1, -1, +1) over |q1 q0> = |00>,|01>,|10>,|11>
    assert [m[i][i] for i in range(4)] == [0.5, -0.5, -0.5, 0.5]
    assert all(m[r][c] == 0.0 for r in range(4) for c in range(4) if r != c)


def test_from_dense_matrix_decomposes_known_hamiltonian():
    # H = 0.5*X + 0.25*Z - 1.0*I on one qubit
    matrix = [[0.25 - 1.0, 0.5], [0.5, -0.25 - 1.0]]
    spo = SparsePauliObservable.from_dense_matrix(matrix)
    assert spo.num_qubits == 1
    by_ops = {t.pauli_ops: t.coefficient.re for t in spo.terms}
    assert by_ops[()] == pytest.approx(-1.0)
    assert by_ops[(PauliLabel.X,)] == pytest.approx(0.5)
    assert by_ops[(PauliLabel.Z,)] == pytest.approx(0.25)


def test_dense_matrix_roundtrip_multi_qubit():
    spo = SparsePauliObservable(
        num_qubits=3,
        terms=[
            PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.Z,),
                      coefficient=ComplexNumber(re=-1.1)),
            PauliTerm(qubit_indices=(0, 2), pauli_ops=(PauliLabel.X, PauliLabel.Y),
                      coefficient=ComplexNumber(re=0.3)),
            PauliTerm(qubit_indices=(1, 2), pauli_ops=(PauliLabel.Y, PauliLabel.Y),
                      coefficient=ComplexNumber(re=0.7)),
        ],
    )
    dense = spo.to_dense_matrix(real=False)
    back = SparsePauliObservable.from_dense_matrix(dense, 3)
    again = back.to_dense_matrix(real=False)
    for row_a, row_b in zip(again, dense):
        for a, b in zip(row_a, row_b):
            assert a == pytest.approx(b, abs=1e-12)


def test_dense_matrix_size_guards():
    spo = SparsePauliObservable(
        num_qubits=11,
        terms=[PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.Z,))],
    )
    with pytest.raises(ValueError):
        spo.to_dense_matrix()
    with pytest.raises(ValueError):
        SparsePauliObservable.from_dense_matrix([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])


def test_dense_matrix_matches_qiskit_reference():
    pytest.importorskip("qiskit")
    import numpy as np
    from qiskit.quantum_info import SparsePauliOp

    spo = SparsePauliObservable(
        num_qubits=2,
        terms=[
            PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.X,),
                      coefficient=ComplexNumber(re=0.4)),
            PauliTerm(qubit_indices=(0, 1), pauli_ops=(PauliLabel.Y, PauliLabel.Z),
                      coefficient=ComplexNumber(re=-0.9)),
        ],
    )
    ref = SparsePauliOp.from_list(spo.to_qiskit_pauli_list(2)).to_matrix()
    assert np.allclose(np.array(spo.to_dense_matrix(real=False)), ref)
    back = SparsePauliObservable.from_dense_matrix([list(row) for row in ref], 2)
    assert np.allclose(np.array(back.to_dense_matrix(real=False)), ref)


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
        line for line in coe.splitlines()
        if line.strip() and not line.strip().endswith("=") and "initialization" not in line
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
        line.split(";")[0].strip()
        for line in coe.splitlines()
        if line.strip() and not line.strip().endswith("=") and "initialization" not in line
    ]
    assert len(data_lines) == 4
    hex_width = pattern.num_logical_qubits * 4
    for line in data_lines:
        assert len(line) == hex_width


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
            computing_model=ComputingModel.GATE_BASED,
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
    assert data["qpubench_schema_version"] == SCHEMA_VERSION
    restored = BenchmarkRecord.model_validate_json(json_str)
    assert restored.experiment_id == record.experiment_id
    assert restored.result.expectation_values[0].value == -1.137


def test_vqa_result_energy_error():
    res = VQAResult(
        final_eigenvalue=-1.137,
        ground_truth=-1.138,
    )
    assert res.energy_error is not None
    assert math.isclose(res.energy_error, 0.001, rel_tol=1e-6)
    assert res.chemical_accuracy is True


def test_vqa_config_rejects_computed_fields():
    """Computed outputs belong in VQAResult — passing them here must fail loudly."""
    with pytest.raises(pydantic.ValidationError):
        VQAConfig(problem_type="chemistry", final_eigenvalue=-1.137)
    with pytest.raises(pydantic.ValidationError):
        VQAConfig(problem_type="chemistry", ground_truth=-1.1373)


def test_vqa_result_fci_fallback_reference():
    res = VQAResult(final_eigenvalue=-1.137, fci_energy=-1.138)
    assert res.reference_energy == -1.138
    assert res.chemical_accuracy is True


# ---------------------------------------------------------------------------
# reactions
# ---------------------------------------------------------------------------

def _record_with_energy(energy: float) -> BenchmarkRecord:
    circuit = CircuitSpec(num_qubits=2, serialized="OPENQASM 2.0;")
    return BenchmarkRecord(
        circuit=circuit,
        backend=BackendSpec.aer_statevector(num_qubits=2),
        options=ExecutionOptions(shots=1024),
        result=QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=[
                ExpectationResult(observable_index=0, value=energy, std_error=0.0)
            ],
        ),
        vqa=VQAConfig(problem_type="chemistry"),
        vqa_result=VQAResult(final_eigenvalue=energy),
        num_qubits=2,
    )


def _three_point_spec() -> ReactionCoordinateSpec:
    circuit = CircuitSpec(num_qubits=2, serialized="OPENQASM 2.0;")
    return ReactionCoordinateSpec(
        label="toy reaction",
        coordinate_name="bond_length_angstrom",
        coordinate_values=[0.7, 1.2, 1.8],
        problems=[circuit, circuit, circuit],
        reactant_index=0,
        transition_state_index=1,
        product_index=2,
    )


def test_reaction_coordinate_spec_length_mismatch():
    circuit = CircuitSpec(num_qubits=2, serialized="OPENQASM 2.0;")
    with pytest.raises(pydantic.ValidationError):
        ReactionCoordinateSpec(
            label="bad",
            coordinate_name="bond_length_angstrom",
            coordinate_values=[0.7, 1.2],
            problems=[circuit],
        )


def test_reaction_coordinate_spec_index_out_of_range():
    circuit = CircuitSpec(num_qubits=2, serialized="OPENQASM 2.0;")
    with pytest.raises(pydantic.ValidationError):
        ReactionCoordinateSpec(
            label="bad",
            coordinate_name="bond_length_angstrom",
            coordinate_values=[0.7, 1.2],
            problems=[circuit, circuit],
            transition_state_index=5,
        )


def test_reaction_path_result_length_mismatch():
    spec = _three_point_spec()
    with pytest.raises(pydantic.ValidationError):
        ReactionPathResult(spec=spec, records=[_record_with_energy(-1.0)])


def test_reaction_path_result_energies_and_barrier():
    spec = _three_point_spec()
    records = [
        _record_with_energy(-1.130),   # reactant
        _record_with_energy(-1.100),   # transition state (highest energy)
        _record_with_energy(-1.140),   # product
    ]
    result = ReactionPathResult(spec=spec, records=records)

    assert result.energies == [-1.130, -1.100, -1.140]
    assert math.isclose(result.barrier_height, 0.030, rel_tol=1e-9)
    assert math.isclose(result.reaction_energy, -0.010, rel_tol=1e-9)

    plot = result.to_dict_for_plot()
    assert plot["bond_length_angstrom"] == [0.7, 1.2, 1.8]
    assert plot["energy"] == [-1.130, -1.100, -1.140]


def test_arrhenius_rate_constant_formula():
    """k(T) = A * T**b * exp(-Ea / RT) — verified against real Cantera
    (ArrheniusRate) at A=1e13, b=0, Ea=50000 J/mol, T=1000 K in this repo's
    own sandbox: 24452259380.205738."""
    rate = ArrheniusRateConstant(A=1.0e13, b=0.0, Ea=50000.0)
    assert math.isclose(rate.rate_at(1000.0), 24452259380.205738, rel_tol=1e-9)


def test_reaction_path_result_rate_constant_bridge():
    spec = _three_point_spec()
    records = [
        _record_with_energy(-1.130),   # reactant
        _record_with_energy(-1.100),   # transition state
        _record_with_energy(-1.140),   # product
    ]
    result = ReactionPathResult(spec=spec, records=records)

    arrhenius = result.to_arrhenius_rate_constant(prefactor_hz=1.0e13)
    assert arrhenius is not None
    assert arrhenius.b == 0.0
    # barrier_height (0.030 Ha) converted to J/mol
    assert math.isclose(arrhenius.Ea, 0.030 * 4.359744722206e-18 * 6.02214076e23, rel_tol=1e-9)

    k = result.rate_constant(temperature_k=298.15, prefactor_hz=1.0e13)
    assert k is not None
    assert k == arrhenius.rate_at(298.15)


def test_reaction_path_result_rate_constant_none_without_barrier():
    circuit = CircuitSpec(num_qubits=2, serialized="OPENQASM 2.0;")
    spec = ReactionCoordinateSpec(
        label="no TS marked",
        coordinate_name="bond_length_angstrom",
        coordinate_values=[0.7, 1.2],
        problems=[circuit, circuit],
    )
    result = ReactionPathResult(
        spec=spec, records=[_record_with_energy(-1.0), _record_with_energy(-1.1)]
    )
    assert result.to_arrhenius_rate_constant() is None
    assert result.rate_constant(temperature_k=298.15) is None


def test_kinetics_reaction_spec_falloff_requires_low_p_rate_constant():
    with pytest.raises(pydantic.ValidationError):
        KineticsReactionSpec(
            equation="H + O2 (+M) <=> HO2 (+M)",
            type=ReactionType.FALLOFF,
            rate_constant=ArrheniusRateConstant(A=4.65e12, b=0.44, Ea=0.0),
        )


def test_reaction_mechanism_to_cantera_dict_declares_units():
    mech = ReactionMechanism(
        phase_name="gas",
        species=[
            KineticsSpeciesSpec(name="A", composition={"H": 2}),
            KineticsSpeciesSpec(name="B", composition={"H": 2}),
        ],
        reactions=[
            KineticsReactionSpec(
                equation="A <=> B",
                rate_constant=ArrheniusRateConstant(A=1.0e13, b=0.0, Ea=50000.0),
            )
        ],
    )
    d = mech.to_cantera_dict()
    assert d["units"] == {"quantity": "mol", "activation-energy": "J/mol"}
    assert d["phases"][0]["name"] == "gas"
    assert d["species"][0] == {"name": "A", "composition": {"H": 2}}
    assert d["reactions"][0]["equation"] == "A <=> B"
    assert d["reactions"][0]["rate-constant"] == {"A": 1.0e13, "b": 0.0, "Ea": 50000.0}


def test_reaction_mechanism_to_cantera_yaml_round_trips():
    pytest.importorskip("yaml")
    import yaml

    mech = ReactionMechanism(
        phase_name="gas",
        species=[
            KineticsSpeciesSpec(name="A", composition={"H": 2}),
            KineticsSpeciesSpec(name="B", composition={"H": 2}),
        ],
        reactions=[
            KineticsReactionSpec(
                equation="A <=> B",
                rate_constant=ArrheniusRateConstant(A=1.0e13, b=0.0, Ea=50000.0),
            )
        ],
    )
    text = mech.to_cantera_yaml()
    parsed = yaml.safe_load(text)
    assert parsed == mech.to_cantera_dict()


def test_reaction_mechanism_loads_in_real_cantera():
    """Verifies against the real cantera package, all three ReactionType
    values, that to_cantera_yaml() output is genuinely loadable and its
    rate constants match ArrheniusRateConstant.rate_at() exactly."""
    ct = pytest.importorskip("cantera")

    rate = ArrheniusRateConstant(A=1.0e13, b=0.0, Ea=50000.0)
    mech = ReactionMechanism(
        phase_name="gas",
        species=[
            KineticsSpeciesSpec(name="A", composition={"H": 2}),
            KineticsSpeciesSpec(name="B", composition={"H": 2}),
        ],
        reactions=[KineticsReactionSpec(equation="A <=> B", rate_constant=rate)],
    )
    gas = ct.Solution(yaml=mech.to_cantera_yaml())
    assert math.isclose(gas.reaction(0).rate(1000.0), rate.rate_at(1000.0), rel_tol=1e-9)


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
    assert b.computing_model == ComputingModel.GATE_BASED


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


def test_backend_spec_braket_qpu():
    b = BackendSpec.braket(
        "arn:aws:braket:us-east-1::device/qpu/rigetti/Ankaa-3",
        s3_bucket_ref="MY_BRAKET_BUCKET",
    )
    assert b.provider == "aws_braket"
    assert b.name == "Ankaa-3"
    assert b.simulator is False
    assert b.auth["s3_bucket_ref"] == "MY_BRAKET_BUCKET"


def test_backend_spec_braket_simulator():
    b = BackendSpec.braket("arn:aws:braket:::device/quantum-simulator/amazon/sv1")
    assert b.simulator is True
    assert b.name == "sv1"


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
    assert c.total_gates == 4   # sum of all gate counts


def test_circuit_spec_gate_counts_empty():
    c = CircuitSpec(num_qubits=2, serialized=BELL_QASM)
    assert c.total_gates is None


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
        computing_model=ComputingModel.GATE_BASED,
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
        computing_model=ComputingModel.GATE_BASED,
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
    from qpubench.schemas.observable import PauliTerm, SparsePauliObservable

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


def test_runner_register_auto_stub_and_run_shots_shorthand():
    from qpubench import BenchmarkRunner
    from qpubench.backends.stub import StubGateAdapter
    from qpubench.schemas.observable import PauliTerm, SparsePauliObservable

    circuit = CircuitSpec(
        num_qubits=2,
        serialized=BELL_QASM,
        observables=[
            SparsePauliObservable(
                num_qubits=2,
                terms=[PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.Z,))],
            )
        ],
    )
    runner = BenchmarkRunner()
    runner.register(name="stub", seed=42)          # no adapter object needed
    assert isinstance(runner._backends["stub"], StubGateAdapter)

    record = runner.run(circuit, "stub", shots=4096)   # no ExecutionOptions needed
    assert record.result.status == JobStatus.SUCCEEDED
    assert record.options.shots == 4096

    # Shorthand reproducibility matches the explicit form
    runner.register(StubGateAdapter(seed=42), name="explicit")
    explicit = runner.run(circuit, "explicit", ExecutionOptions(shots=4096))
    assert (
        record.result.expectation_values[0].value
        == explicit.result.expectation_values[0].value
    )


def test_runner_register_and_run_shorthand_misuse():
    import pytest

    from qpubench import BenchmarkRunner, StubGateAdapter

    runner = BenchmarkRunner()
    with pytest.raises(TypeError):
        runner.register(seed=1)                    # auto-stub needs a name
    with pytest.raises(TypeError):
        runner.register(StubGateAdapter(), name="s", seed=1)   # seed is stub-only

    runner.register(name="stub")
    circuit = CircuitSpec(num_qubits=1, serialized="OPENQASM 2.0;")
    with pytest.raises(TypeError):
        runner.run(circuit, "stub", ExecutionOptions(shots=8), shots=16)


# ---------------------------------------------------------------------------
# AlgorithmSpec and algorithm-driven schemas
# ---------------------------------------------------------------------------

from qpubench.schemas.execution import (
    AdaptVQERunConfig,
    AlgorithmSpec,
    QAOARunConfig,
    VQERunConfig,
)
from qpubench.schemas.primitives import AlgorithmFamily
from qpubench.schemas.result import AdaptIteration


def test_algorithm_spec_defaults():
    alg = AlgorithmSpec(name="UCCNVQE")
    assert alg.family is None
    assert alg.extra_params == {}


def test_adapt_vqe_config_defaults():
    cfg = AdaptVQERunConfig()
    assert cfg.pool_type == "SD"
    assert cfg.optimizer == "BFGS"
    assert cfg.use_analytic_gradient is True
    assert cfg.energy_threshold == pytest.approx(1.0e-5)
    assert cfg.gradient_threshold == pytest.approx(1.0e-2)
    assert cfg.max_macro_iterations == 20


def test_algorithm_spec_adapt_vqe():
    alg = AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE)
    cfg = AdaptVQERunConfig(pool_type="SDTQ", optimizer="jacobi", max_macro_iterations=30)
    assert alg.name == "ADAPTVQE"
    assert alg.family == AlgorithmFamily.ADAPT_VQE
    assert cfg.pool_type == "SDTQ"
    assert cfg.max_macro_iterations == 30


def test_algorithm_spec_in_execution_options():
    opts = ExecutionOptions(
        algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
        adapt_vqe_run_config=AdaptVQERunConfig(pool_type="GSD"),
    )
    assert opts.algorithm_spec is not None
    assert opts.algorithm_spec.name == "ADAPTVQE"
    assert opts.adapt_vqe_run_config is not None
    assert opts.adapt_vqe_run_config.pool_type == "GSD"


def test_algorithm_family_qpe_tag():
    """QPE has no AlgorithmAdapter implementation yet (schema/metadata only,
    see microsoft_qdk.QPEConfig) but the family tag exists so a future
    implementation has a name to converge on."""
    alg = AlgorithmSpec(name="QPE", family=AlgorithmFamily.QPE)
    assert alg.family == AlgorithmFamily.QPE


def test_qaoa_run_config_defaults():
    cfg = QAOARunConfig()
    assert cfg.reps == 1
    assert cfg.mixer == "x"
    assert cfg.optimizer == "COBYLA"
    assert cfg.max_iterations == 100
    assert cfg.initialization == "ramp"
    assert cfg.alpha_cvar == pytest.approx(1.0)


def test_qaoa_run_config_in_execution_options():
    """QAOA runs as a plain optimization loop (no AlgorithmAdapter), but its
    package-agnostic knobs travel on ExecutionOptions.qaoa_run_config next to
    adapt_vqe_run_config — labelled by VQAConfig(algorithm="QAOA")."""
    opts = ExecutionOptions(
        algorithm_spec=AlgorithmSpec(name="QAOA", family=AlgorithmFamily.QAOA),
        qaoa_run_config=QAOARunConfig(reps=3, mixer="xy", alpha_cvar=0.25),
    )
    assert opts.qaoa_run_config is not None
    assert opts.qaoa_run_config.reps == 3
    assert opts.qaoa_run_config.mixer == "xy"
    assert opts.qaoa_run_config.alpha_cvar == pytest.approx(0.25)
    assert opts.algorithm_spec.family == AlgorithmFamily.QAOA
    # round-trips as part of the options
    restored = ExecutionOptions.model_validate_json(opts.model_dump_json())
    assert restored.qaoa_run_config.reps == 3


def test_vqa_config_names_qaoa_run():
    """A QAOA run is named by VQAConfig; its knobs live in QAOARunConfig, not
    as VQAConfig fields (same layering as ADAPT-VQE)."""
    vqa = VQAConfig(problem_type="optimization", algorithm="QAOA",
                    optimizer="COBYLA")
    assert vqa.algorithm == "QAOA"
    assert vqa.problem_type == "optimization"


def test_vqe_run_config_in_execution_options():
    """Fixed-ansatz VQE has a package-agnostic contract of its own, on
    ExecutionOptions.vqe_run_config next to the ADAPT and QAOA ones."""
    opts = ExecutionOptions(
        algorithm_spec=AlgorithmSpec(name="UCCNVQE", family=AlgorithmFamily.VQE),
        vqe_run_config=VQERunConfig(
            ansatz="EfficientSU2", layers=3, optimizer="COBYLA",
            initialization="random", init_scale=0.05,
        ),
    )
    assert opts.vqe_run_config is not None
    assert opts.vqe_run_config.ansatz == "EfficientSU2"
    assert opts.vqe_run_config.layers == 3
    assert opts.algorithm_spec.family == AlgorithmFamily.VQE
    restored = ExecutionOptions.model_validate_json(opts.model_dump_json())
    assert restored.vqe_run_config.initialization == "random"
    assert restored.vqe_run_config.init_scale == pytest.approx(0.05)


def test_vqe_run_config_defaults():
    cfg = VQERunConfig()
    assert cfg.ansatz == "UCCSD"
    assert cfg.layers == 1
    assert cfg.optimizer == "BFGS"
    assert cfg.initial_parameters == []
    # no seed of its own — ExecutionOptions.seed governs the random draw
    assert "seed" not in VQERunConfig.model_fields


def test_run_configs_are_independent_fields():
    """The three family contracts coexist on ExecutionOptions; setting one
    leaves the others None rather than displacing them."""
    opts = ExecutionOptions(vqe_run_config=VQERunConfig(ansatz="TwoLocal"))
    assert opts.vqe_run_config is not None
    assert opts.adapt_vqe_run_config is None
    assert opts.qaoa_run_config is None


def test_algorithm_spec_json_roundtrip():
    alg = AlgorithmSpec(
        name="SPQE",
        extra_params={"spqe_thresh": 1.0e-4, "max_excit": 2, "pool_type": "GSD"},
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
        computing_model=ComputingModel.GATE_BASED,
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
        algorithm="UCCNVQE",
        pool_type="SD",
    )
    res = VQAResult(
        hf_energy=-2.8551,
        n_cnot=4,
        n_pauli_trm_measures=240,
        final_eigenvalue=-2.9003,
        ground_truth=-2.9003,
    )
    assert vqa.num_electrons == 2
    assert vqa.algorithm == "UCCNVQE"
    assert vqa.pool_type == "SD"
    assert res.n_cnot == 4
    assert res.chemical_accuracy is True


def test_vqa_result_adapt_maxiter_flag():
    res = VQAResult(
        adapt_maxiter_reached=True,
        final_eigenvalue=-2.10,
        ground_truth=-2.16,
    )
    assert res.adapt_maxiter_reached is True
    assert res.chemical_accuracy is False   # error > 1 mHartree


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
    ) -> tuple[QuantumResult, VQAConfig, VQAResult]:
        alg_name = (options.algorithm_spec.name
                    if options.algorithm_spec else "UCCNVQE")
        result = QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
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
        )
        vqa_result = VQAResult(
            final_eigenvalue=-2.9003,
            ground_truth=-2.9003,
        )
        return result, vqa, vqa_result


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
    assert record.vqa_result is not None
    assert record.vqa_result.chemical_accuracy is True
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
        ExecutionOptions(
            algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
            adapt_vqe_run_config=AdaptVQERunConfig(gradient_threshold=1.0e-4),
        ),
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
    import json as _json

    from qpubench import BenchmarkRunner

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
    from qpubench.schemas.mirrors.microsoft_qdk import (
        AtomSpec,
        CoordinateUnit,
        MoleculeStructureSpec,
    )
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
    from qpubench.schemas.mirrors.microsoft_qdk import SCFMethod, SCFResult, SCFRunConfig
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
    from qpubench.schemas.mirrors.microsoft_qdk import (
        ActiveSpaceSelectionConfig,
        ActiveSpaceSelectionResult,
        ActiveSpaceSelectorType,
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
    import math

    from qpubench.schemas.mirrors.microsoft_qdk import (
        PauliStringTerm,
        QubitEncodingType,
        QubitHamiltonianSpec,
    )
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
    from qpubench.schemas.mirrors.microsoft_qdk import (
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
    import pytest

    from qpubench.schemas.mirrors.microsoft_qdk import (
        HeisenbergParams,
        IsingParams,
        LatticeGraphSpec,
        LatticeTopology,
        ModelHamiltonianSpec,
        ModelHamiltonianType,
    )
    with pytest.raises(Exception):
        ModelHamiltonianSpec(
            hamiltonian_type=ModelHamiltonianType.ISING,
            lattice=LatticeGraphSpec(topology=LatticeTopology.RING, num_sites=4),
            ising=IsingParams(J=1.0, h=0.5),
            heisenberg=HeisenbergParams(J=1.0),
        )


def test_qpe_config_and_result():
    from qpubench.schemas.mirrors.microsoft_qdk import (
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
    from qpubench.schemas.mirrors.microsoft_qdk import (
        ErrorBudgetPartition,
        QECScheme,
        QubitParamsType,
        ResourceEstimationResult,
        ResourceEstimatorConfig,
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
    from qpubench.schemas.mirrors.microsoft_qdk import (
        AtomSpec,
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
    assert b.computing_model == ComputingModel.GATE_BASED


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
    import math

    from qpubench.schemas.mirrors.mqsdk_photoq import (
        GBSMeasurementType,
        GBSProgramSpec,
        InterferometerSpec,
        SqueezingGateSpec,
    )
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
    from qpubench.schemas.mirrors.mqsdk_photoq import GBSMeasurementType, GBSProgramSpec, S2GateSpec
    prog = GBSProgramSpec(
        num_modes=4,
        s2_gates=[S2GateSpec(mode_a=i, mode_b=i + 4, r=1.0) for i in range(4)],
        measurement_type=GBSMeasurementType.FOCK,
    )
    assert len(prog.s2_gates) == 4
    assert prog.s2_gates[0].mode_b == 4


def test_gbs_sample_properties():
    from qpubench.schemas.mirrors.mqsdk_photoq import GBSSample
    s = GBSSample(photon_numbers=[0, 1, 2, 0, 1])
    assert s.total_photons == 4
    assert s.num_clicks == 0   # no click_pattern set

    t = GBSSample(click_pattern=[1, 0, 1, 1, 0])
    assert t.num_clicks == 3


def test_gbs_sampling_result_roundtrip():
    import json

    from qpubench.schemas.mirrors.mqsdk_photoq import (
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
    from qpubench.schemas.mirrors.mqsdk_photoq import (
        GaussianStateSpec,
        GaussianStateType,
        QuadratureOrdering,
    )
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
    from qpubench.schemas.mirrors.mqsdk_photoq import HafnianMatrixSpec, QuadratureOrdering
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
    import math

    from qpubench.schemas.mirrors.mqsdk_photoq import TakagiDecompositionSpec
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
    from qpubench.schemas.mirrors.mqsdk_photoq import (
        GBSCliqueFindingResult,
        GBSGraphConfig,
        GraphScalingMethod,
    )
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


def test_tdm_gbs_config():
    from qpubench.schemas.mirrors.mqsdk_photoq import TDMDelaySpec, TDMGBSConfig, TDMSqueezingLevel
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
    import math

    from qpubench.schemas.mirrors.mqsdk_photoq import ClusterStateSpec, GaussianStateType
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
    assert b.computing_model == ComputingModel.GBS
    assert b.qubit_modality == QubitModality.PHOTONIC
    assert b.simulator is False


def test_backend_spec_xanadu_borealis():
    b = BackendSpec.xanadu_borealis(via_braket=True)
    assert b.provider == "aws_braket"
    assert b.computing_model == ComputingModel.GBS
    assert b.qubit_modality == QubitModality.PHOTONIC
    assert "Borealis" in b.auth["device_arn"]


def test_backend_spec_strawberry_fields_gaussian():
    b = BackendSpec.strawberry_fields_gaussian(num_modes=12)
    assert b.provider == "strawberry_fields"
    assert b.computing_model == ComputingModel.GBS
    assert b.qubit_modality == QubitModality.PHOTONIC
    assert b.simulator is True


# ---------------------------------------------------------------------------
# photoq additions: pseudo-PNRD click-counting, simulation methods, new
# backends (ORCA PT Series, DTU QCloud, Xanadu Aurora), dominating-set / BBS
# ---------------------------------------------------------------------------

def test_pseudo_pnrd_collision_error():
    from qpubench.schemas.mirrors.mqsdk_photoq import PseudoPNRDSpec
    det = PseudoPNRDSpec(num_branches=4, multiplexing="spatial")
    # 1 photon into 4 branches can never collide.
    assert det.collision_error(1) == 0.0
    # 2 photons into 4 branches: ways_total=C(5,2)=10, allowed=C(4,2)=6 -> 0.4.
    assert abs(det.collision_error(2) - 0.4) < 1e-12
    # More photons than branches always collide.
    assert det.collision_error(5) == 1.0
    with pytest.raises(ValueError):
        PseudoPNRDSpec(num_branches=0)


def test_click_pattern_probability_result():
    from qpubench.schemas.mirrors.mqsdk_photoq import (
        ClickPatternProbabilityResult,
        SimulationMethod,
    )
    res = ClickPatternProbabilityResult(
        num_modes=2, num_branches=2,
        method=SimulationMethod.KENSINGTONIAN_FORMULA,
        click_patterns=[[0, 0], [1, 0], [0, 1], [1, 1]],
        probabilities=[0.5, 0.2, 0.2, 0.1],
        total_probability=1.0, fock_cutoff=8,
    )
    assert len(res.click_patterns) == len(res.probabilities) == 4
    assert res.method == SimulationMethod.KENSINGTONIAN_FORMULA
    # length mismatch is rejected
    with pytest.raises(ValueError):
        ClickPatternProbabilityResult(
            num_modes=2, num_branches=2,
            method=SimulationMethod.BRUTE_FORCE_POVM,
            click_patterns=[[0, 0]], probabilities=[0.5, 0.5],
        )


def test_method_comparison_roundtrip():
    from qpubench.schemas.mirrors.mqsdk_photoq import MethodComparison, SimulationMethod
    mc = MethodComparison(
        num_modes=4, num_branches=4,
        reference_method=SimulationMethod.BRUTE_FORCE_POVM,
        methods=[SimulationMethod.KENSINGTONIAN_FORMULA, SimulationMethod.TENSOR_NETWORK_MPS],
        computation_time_s={"kensingtonian_formula": 0.01, "tensor_network_mps": 1.2},
        total_variation_distance={"tensor_network_mps": 3e-4},
        mps_truncation_fidelity=0.999, mps_bond_dimension=100,
    )
    dumped = mc.model_dump()
    assert MethodComparison.model_validate(dumped).mps_bond_dimension == 100


def test_time_bin_interferometer_and_pt_series():
    from qpubench.schemas.mirrors.mqsdk_photoq import (
        PTSeriesInputType,
        PTSeriesSamplingConfig,
        PTSeriesSamplingResult,
        TimeBinInterferometerSpec,
    )
    tbi = TimeBinInterferometerSpec(
        num_modes=4, num_loops=2, input_type=PTSeriesInputType.GBS,
        squeezing=[0.5, 0.5, 0.5, 0.5],
    )
    # 2 loops on 4 modes -> 2 * (4-1) = 6 angles expected.
    assert tbi.num_angles_expected == 6
    cfg = PTSeriesSamplingConfig(interferometer=tbi, num_samples=100, device="PT-2")
    res = PTSeriesSamplingResult(
        config=cfg, samples=[[0, 1, 0, 2], [1, 0, 1, 0]], mean_photon_number=1.25,
    )
    assert res.config.interferometer.num_modes == 4
    assert len(res.samples) == 2


def test_qcloud_job_spec_and_params():
    from qpubench.schemas.mirrors.mqsdk_photoq import (
        QCloudJobResult,
        QCloudJobSpec,
        QCloudJobType,
        TNCovarianceParams,
        TNSamplingParams,
    )
    cov = TNCovarianceParams(nmodes=8, r_db=8.0, loss=0.5, basis="pi4")
    assert cov.nmodes == 8
    tn = TNSamplingParams(cov_matrix=[1.0, 0.0, 0.0, 1.0], d=8, chi=100, dd=1, N=1000, n=1)
    job = QCloudJobSpec(job_type=QCloudJobType.TN_SAMPLING, params=tn.model_dump(), worker="tn-sampling")
    assert job.job_type.value == "tn-sampling"
    assert job.base_url == "https://qcloud.dtu.dk"
    result = QCloudJobResult(spec=job, status="succeeded", samples=[[0, 1, 2]])
    assert result.status == "succeeded"


def test_aurora_dataset_spec():
    from qpubench.schemas.mirrors.mqsdk_photoq import AuroraDatasetSpec, AuroraExperiment
    spec = AuroraDatasetSpec(
        experiment=AuroraExperiment.DECODER_DEMO, condition="signal",
        batch_index=3, s3_key="decoder_demo/signal/batch_3/quadratures.npy",
    )
    assert spec.num_qubit_modes == 12
    assert spec.experiment == AuroraExperiment.DECODER_DEMO


def test_backend_spec_orca_pt_series():
    b = BackendSpec.orca_pt_series(num_modes=8, num_loops=2, device="PT-2")
    assert b.provider == "orca"
    assert b.computing_model == ComputingModel.GBS
    assert b.qubit_modality == QubitModality.PHOTONIC
    assert b.auth["num_loops"] == "2"


def test_backend_spec_dtu_qcloud():
    b = BackendSpec.dtu_qcloud(job_type="tn-sampling")
    assert b.provider == "dtu_qcloud"
    assert b.computing_model == ComputingModel.GBS
    assert b.auth["job_type"] == "tn-sampling"


def test_backend_spec_xanadu_aurora():
    b = BackendSpec.xanadu_aurora(experiment="decoder_demo")
    assert b.provider == "xanadu"
    assert b.num_qubits == 12
    assert b.auth["experiment"] == "decoder_demo"


# ---------------------------------------------------------------------------
# QSE / KQD schemas (v1.7.0)
# ---------------------------------------------------------------------------

def test_neel_state_spec():
    from qpubench.schemas.mirrors.mqsdk_qse import NeelStateSpec
    s = NeelStateSpec(num_spins=8, shift=0)
    assert s.num_spins == 8
    assert s.shift == 0


def test_slater_determinant_ref():
    from qpubench.schemas.mirrors.mqsdk_qse import SlaterDeterminantRef
    ref = SlaterDeterminantRef(ncas=4, occ_alpha=[0, 1], occ_beta=[0, 1])
    assert ref.num_qubits == 8
    assert ref.num_electrons == 4
    bits = ref.bitstring
    assert len(bits) == 8
    assert bits[0] == "1"
    assert bits[4] == "1"


def test_kqd_reference_spec_neel():
    from qpubench.schemas.mirrors.mqsdk_qse import (
        KQDReferenceSpec,
        KQDReferenceStateType,
        NeelStateSpec,
    )
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
    import math

    from qpubench.schemas.mirrors.mqsdk_qse import KQDTimeEvolutionSpec, KrylovTimeEvolutionVariant
    dt = math.pi / 3.0
    spec = KQDTimeEvolutionSpec(dt=dt, num_trotter_steps=6)
    assert spec.dt_circ == pytest.approx(dt / 6)
    assert spec.variant == KrylovTimeEvolutionVariant.EFFICIENT_ALTERNATING


def test_krylov_circuit_family_spec():
    from qpubench.schemas.mirrors.mqsdk_qse import KQDMethod, KrylovCircuitFamilySpec
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
    from qpubench.schemas.mirrors.mqsdk_qse import KrylovMatrixSpec, KrylovSubspaceMatrices
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
    from qpubench.schemas.mirrors.mqsdk_qse import KrylovEigenResult
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
    from qpubench.schemas.mirrors.mqsdk_qse import SQDConvergenceResult, SQDStep
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
    from qpubench.schemas.mirrors.mqsdk_qse import CumulativeKrylovCounts, SQDPostselectionConfig
    postsel = SQDPostselectionConfig(num_ones=2, min_unique=1)
    counts_obj = CumulativeKrylovCounts(
        cumulative_counts=[{"01": 10, "10": 8}, {"01": 15, "10": 12, "11": 0}],
        postselection=postsel,
        num_references_pooled=1,
    )
    assert counts_obj.postselection.num_ones == 2
    assert len(counts_obj.cumulative_counts) == 2


def test_cholesky_decomposition_spec():
    from qpubench.schemas.mirrors.mqsdk_qse import CholeskyDecompositionSpec
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

    from qpubench.schemas.mirrors.mqsdk_qse import (
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

    from qpubench.schemas.mirrors.mqsdk_qse import KQDConfig, KQDMethod, KQDPipelineSpec
    pipeline = KQDPipelineSpec(
        num_qubits=6,
        hamiltonian_label="ising_chain_6",
        kqd_config=KQDConfig(method=KQDMethod.SAMPLE_BASED_SQD, krylov_dim=4),
    )
    result = QuantumResult(
        computing_model=ComputingModel.GATE_BASED,
        vendor_results={"kqd_pipeline": pipeline},
    )
    json_str = result.model_dump_json()
    data = json.loads(json_str)
    assert data["computing_model"] == "gate_based"
    assert data["vendor_results"]["kqd_pipeline"]["hamiltonian_label"] == "ising_chain_6"
    restored = QuantumResult.model_validate_json(json_str)
    assert restored.vendor_results["kqd_pipeline"]["num_qubits"] == 6


def test_backend_spec_qiskit_aer():
    b = BackendSpec.qiskit_aer(method="statevector", num_qubits=12)
    assert b.provider == "aer"
    assert b.computing_model == ComputingModel.GATE_BASED
    assert b.simulator is True
    assert b.num_qubits == 12


# ---------------------------------------------------------------------------
# QESEM (Qedma) schemas (v1.8.0)
# ---------------------------------------------------------------------------

def test_qesem_observable_spec():
    from qpubench.schemas.mirrors.qedma_qesem import QESEMObservableSpec
    obs = QESEMObservableSpec(
        pauli_terms={"Z1": 1.0, "Z0,Z3": 0.3},
        description="ZZ correlation",
    )
    assert obs.pauli_terms["Z1"] == pytest.approx(1.0)
    assert obs.description == "ZZ correlation"


def test_qesem_circuit_options():
    from qpubench.schemas.mirrors.qedma_qesem import QESEMCircuitOptions, QESEMTranspilationLevel
    opts = QESEMCircuitOptions(
        error_suppression_only=False,
        twirl=True,
        transpilation_level=QESEMTranspilationLevel.STANDARD,
        parallel_execution=True,
    )
    assert opts.parallel_execution is True
    assert opts.transpilation_level == QESEMTranspilationLevel.STANDARD


def test_qesem_precision_per_factor():
    from qpubench.schemas.mirrors.qedma_qesem import QESEMPrecisionPerFactor
    pf = QESEMPrecisionPerFactor(
        scale_precision_map={"0.0": 0.1, "1.0": 0.15, "2.0": 0.2}
    )
    assert pf.scale_precision_map["0.0"] == pytest.approx(0.1)


def test_qesem_job_spec():
    from qpubench.schemas.mirrors.qedma_qesem import (
        QESEMCircuitOptions,
        QESEMJobSpec,
        QESEMObservableSpec,
        QESEMPrecisionMode,
        QESEMTranspilationLevel,
    )
    obs = QESEMObservableSpec(pauli_terms={"Z0": 0.2, "Z1": 0.2, "Z2": 0.2})
    spec = QESEMJobSpec(
        circuit_qasm='OPENQASM 2.0;\nqreg q[3];\nh q[0];\ncx q[0],q[1];',
        num_qubits=3,
        observables=[obs],
        precision=0.05,
        precision_mode=QESEMPrecisionMode.CIRCUIT,
        backend_name="ibm_fez",
        circuit_options=QESEMCircuitOptions(
            transpilation_level=QESEMTranspilationLevel.STANDARD,
        ),
        description="avg magnetization",
    )
    assert spec.backend_name == "ibm_fez"
    assert len(spec.observables) == 1
    assert spec.precision_mode == QESEMPrecisionMode.CIRCUIT


def test_qesem_expectation_values():
    from qpubench.schemas.mirrors.qedma_qesem import (
        QESEMExpectationValue,
        QESEMHeuristicResult,
        QESEMNoiseScalingResult,
        QESEMScaleExpectationValue,
    )
    raw = QESEMExpectationValue(value=-0.42, error_bar=0.08)
    assert raw.value == pytest.approx(-0.42)

    scale_zero = QESEMScaleExpectationValue(value=-0.81, error_bar=0.05, scale=0.0)
    scale_one  = QESEMScaleExpectationValue(value=-0.56, error_bar=0.04, scale=1.0)
    scale_two  = QESEMScaleExpectationValue(value=-0.32, error_bar=0.04, scale=2.0)

    ns = QESEMNoiseScalingResult(
        scaling_method="QESEM",
        results_per_scale=[scale_zero, scale_one, scale_two],
    )
    assert ns.scale_factors == pytest.approx([0.0, 1.0, 2.0])
    assert ns.zero_noise_result.value == pytest.approx(-0.81)

    heuristic = QESEMHeuristicResult(
        value=-0.80, error_bar=0.06,
        extrapolation="linear", scale_factors=[0.0, 1.0, 2.0],
    )
    assert heuristic.extrapolation == "linear"


def test_qesem_observable_result_mitigated_property():
    from qpubench.schemas.mirrors.qedma_qesem import (
        QESEMExpectationValue,
        QESEMHeuristicResult,
        QESEMNoiseScalingResult,
        QESEMObservableResult,
        QESEMScaleExpectationValue,
    )
    raw = QESEMExpectationValue(value=-0.42, error_bar=0.08)
    scale_zero = QESEMScaleExpectationValue(value=-0.81, error_bar=0.05, scale=0.0)
    ns = QESEMNoiseScalingResult(results_per_scale=[scale_zero])

    # Without heuristic: mitigated = zero_noise_result
    obs_result_no_heuristic = QESEMObservableResult(unmitigated=raw, noise_scaling=ns)
    assert obs_result_no_heuristic.mitigated.value == pytest.approx(-0.81)

    # With heuristic: mitigated = first heuristic result
    h = QESEMHeuristicResult(value=-0.80, error_bar=0.05, extrapolation="linear", scale_factors=[0.0, 1.0])
    obs_result_with_heuristic = QESEMObservableResult(unmitigated=raw, noise_scaling=ns, qesem_heuristic=[h])
    assert obs_result_with_heuristic.mitigated.value == pytest.approx(-0.80)


def test_qesem_circuit_result_properties():
    from qpubench.schemas.mirrors.qedma_qesem import (
        QESEMCircuitObservableResult,
        QESEMCircuitResult,
        QESEMExpectationValue,
        QESEMNoiseScalingResult,
        QESEMObservableResult,
        QESEMObservableSpec,
        QESEMScaleExpectationValue,
    )
    obs1 = QESEMObservableSpec(pauli_terms={"Z0": 0.5})
    obs2 = QESEMObservableSpec(pauli_terms={"Z1": 0.5})

    def make_result(mitigated_val: float) -> QESEMObservableResult:
        ns = QESEMNoiseScalingResult(
            results_per_scale=[
                QESEMScaleExpectationValue(value=mitigated_val, error_bar=0.04, scale=0.0)
            ]
        )
        return QESEMObservableResult(
            unmitigated=QESEMExpectationValue(value=mitigated_val * 0.6, error_bar=0.1),
            noise_scaling=ns,
        )

    cr = QESEMCircuitResult(
        parameter_index=0,
        observable_results=[
            QESEMCircuitObservableResult(observable=obs1, result=make_result(-0.81)),
            QESEMCircuitObservableResult(observable=obs2, result=make_result(-0.76)),
        ],
    )
    assert cr.mitigated_evs == pytest.approx([-0.81, -0.76])
    assert len(cr.noisy_evs) == 2


def test_qesem_execution_details():
    from qpubench.schemas.mirrors.qedma_qesem import QESEMExecutionDetails, QESEMTranspiledCircuit
    tc = QESEMTranspiledCircuit(
        circuit_qasm="OPENQASM 2.0; ...",
        qubit_maps=[{"0": 12, "1": 13, "2": 14}],
        num_measurement_bases=4,
    )
    details = QESEMExecutionDetails(
        total_shots=48_000,
        mitigation_shots=12_000,
        gate_fidelities={"CNOT": 0.9901, "ID1Q": 0.9989},
        transpiled_circuits=[tc],
    )
    assert details.gate_fidelities["CNOT"] == pytest.approx(0.9901)
    assert details.transpiled_circuits[0].num_measurement_bases == 4


def test_qesem_characterization_result():
    from qpubench.schemas.mirrors.qedma_qesem import (
        QESEMCharacterizationResult,
        QESEMGateInfidelity,
    )
    char = QESEMCharacterizationResult(
        qpu_name="ibm_fez",
        measurement_errors={0: 0.012, 1: 0.009, 2: 0.015},
        gate_infidelities=[
            QESEMGateInfidelity(gate_name="CNOT", qubits=(0, 1), infidelity=0.0099),
            QESEMGateInfidelity(gate_name="CNOT", qubits=(1, 2), infidelity=0.0087),
        ],
        qubit_map={0: 12, 1: 13, 2: 14},
    )
    assert char.measurement_errors[0] == pytest.approx(0.012)
    assert char.gate_infidelities[0].infidelity == pytest.approx(0.0099)


def test_qesem_job_record_roundtrip():
    import json

    from qpubench.schemas.mirrors.qedma_qesem import (
        QESEMCharacterizationResult,
        QESEMCircuitObservableResult,
        QESEMCircuitResult,
        QESEMExecutionDetails,
        QESEMExecutionMode,
        QESEMExpectationValue,
        QESEMGateInfidelity,
        QESEMJobRecord,
        QESEMJobSpec,
        QESEMJobStatus,
        QESEMNoiseScalingResult,
        QESEMObservableResult,
        QESEMObservableSpec,
        QESEMPrecisionMode,
        QESEMScaleExpectationValue,
    )
    obs = QESEMObservableSpec(pauli_terms={"Z0": 0.2, "Z1": 0.2})
    ns = QESEMNoiseScalingResult(
        results_per_scale=[
            QESEMScaleExpectationValue(value=-0.76, error_bar=0.04, scale=0.0)
        ]
    )
    obs_result = QESEMObservableResult(
        unmitigated=QESEMExpectationValue(value=-0.52, error_bar=0.09),
        noise_scaling=ns,
    )
    record = QESEMJobRecord(
        job_id="qesem-abc123",
        status=QESEMJobStatus.SUCCEEDED,
        qpu_name="ibm_fez",
        spec=QESEMJobSpec(
            backend_name="ibm_fez",
            observables=[obs],
            precision=0.05,
        ),
        precision_mode=QESEMPrecisionMode.JOB,
        execution_mode=QESEMExecutionMode.BATCH,
        analytical_qpu_time_s=240.0,
        total_execution_time_s=310.5,
        circuit_results=[
            QESEMCircuitResult(
                parameter_index=0,
                observable_results=[
                    QESEMCircuitObservableResult(observable=obs, result=obs_result)
                ],
            )
        ],
        execution_details=QESEMExecutionDetails(
            total_shots=40_000,
            mitigation_shots=10_000,
            gate_fidelities={"CNOT": 0.990},
        ),
        characterization=QESEMCharacterizationResult(
            qpu_name="ibm_fez",
            gate_infidelities=[
                QESEMGateInfidelity(gate_name="CNOT", qubits=(0, 1), infidelity=0.01)
            ],
        ),
    )
    json_str = record.model_dump_json()
    data = json.loads(json_str)
    assert data["job_id"] == "qesem-abc123"
    assert data["execution_details"]["total_shots"] == 40_000
    restored = QESEMJobRecord.model_validate_json(json_str)
    assert restored.circuit_results[0].mitigated_evs[0] == pytest.approx(-0.76)


def test_quantum_result_qesem_field():
    import json

    from qpubench.schemas.mirrors.qedma_qesem import QESEMJobRecord, QESEMJobSpec, QESEMJobStatus
    qesem_record = QESEMJobRecord(
        job_id="qesem-xyz",
        status=QESEMJobStatus.SUCCEEDED,
        spec=QESEMJobSpec(backend_name="ibm_torino", precision=0.05),
    )
    result = QuantumResult(
        computing_model=ComputingModel.GATE_BASED,
        vendor_results={"qesem_result": qesem_record},
    )
    data = json.loads(result.model_dump_json())
    assert data["vendor_results"]["qesem_result"]["job_id"] == "qesem-xyz"


def test_backend_spec_qesem():
    b = BackendSpec.qesem("ibm_fez", api_token_ref="QEDMA_TOKEN")
    assert b.provider == "qedma"
    assert b.computing_model == ComputingModel.GATE_BASED
    assert b.simulator is False
    assert b.auth["backend_name"] == "ibm_fez"
    assert b.auth["api_token_ref"] == "QEDMA_TOKEN"


def test_execution_options_qesem_mitigation_options():
    from qpubench.schemas.execution import ExecutionOptions
    from qpubench.schemas.mirrors.qedma_qesem import (
        QESEMCircuitOptions,
        QESEMExecutionMode,
        QESEMJobOptions,
        qesem_mitigation_options,
    )
    from qpubench.schemas.primitives import ErrorMitigationStrategy
    opts = ExecutionOptions(
        shots=10_000,
        error_mitigation=ErrorMitigationStrategy.QESEM,
        mitigation_options=qesem_mitigation_options(
            circuit_options=QESEMCircuitOptions(parallel_execution=True),
            job_options=QESEMJobOptions(execution_mode=QESEMExecutionMode.SESSION),
        ),
    )
    # Core stores vendor-neutral dicts; rehydrate the typed vendor schemas.
    co = QESEMCircuitOptions.model_validate(opts.mitigation_options["qesem_circuit_options"])
    jo = QESEMJobOptions.model_validate(opts.mitigation_options["qesem_job_options"])
    assert co.parallel_execution is True
    assert jo.execution_mode == QESEMExecutionMode.SESSION

    # Vendor models passed directly as values are dumped automatically.
    opts2 = ExecutionOptions(
        mitigation_options={"qesem_circuit_options": QESEMCircuitOptions()},
    )
    assert isinstance(opts2.mitigation_options["qesem_circuit_options"], dict)


# ---------------------------------------------------------------------------
# QCSchema / QCElemental / PennyLane tests
# ---------------------------------------------------------------------------

def test_qcmolecule_h2():
    from qpubench.schemas.mirrors.molssi_qcschema import QCMolecule
    # H2 at equilibrium bond length 0.742 Å = 1.4011 Bohr
    mol = QCMolecule(
        symbols=["H", "H"],
        geometry=[0.0, 0.0, -0.7005, 0.0, 0.0, 0.7005],
        molecular_charge=0.0,
        molecular_multiplicity=1,
        name="H2",
    )
    assert mol.num_atoms == 2
    assert mol.formula == "H2"
    assert len(mol.geometry) == 6


def test_qcmolecule_geometry_validation():
    import pytest

    from qpubench.schemas.mirrors.molssi_qcschema import QCMolecule
    with pytest.raises(Exception):
        QCMolecule(symbols=["H", "H"], geometry=[0.0, 0.0])  # wrong length


def test_qcmolecule_water_fragments():
    from qpubench.schemas.mirrors.molssi_qcschema import QCMolecule
    mol = QCMolecule(
        symbols=["O", "H", "H"],
        geometry=[0.0, 0.0, 0.0, 0.0, 1.43, -1.11, 0.0, 1.43, 1.11],
        name="H2O",
        fragments=[[0, 1, 2]],
        fragment_charges=[0.0],
        fragment_multiplicities=[1],
        connectivity=[(0, 1, 1.0), (0, 2, 1.0)],
    )
    assert mol.formula == "H2O"
    assert mol.num_atoms == 3
    assert len(mol.connectivity) == 2


def test_qc_model_and_driver():
    from qpubench.schemas.mirrors.molssi_qcschema import QCDriver, QCModel
    m = QCModel(method="ccsd(t)", basis="cc-pVDZ")
    assert m.method == "ccsd(t)"
    assert m.basis == "cc-pVDZ"
    assert QCDriver.ENERGY.value == "energy"
    assert QCDriver.GRADIENT.value == "gradient"
    assert QCDriver.HESSIAN.value == "hessian"
    assert QCDriver.PROPERTIES.value == "properties"


def test_qc_energy_components():
    from qpubench.schemas.mirrors.molssi_qcschema import QCEnergyComponents
    ec = QCEnergyComponents(
        nuclear_repulsion_energy=0.7137,
        scf_one_electron_energy=-3.5692,
        scf_two_electron_energy=1.8223,
        mp2_correlation_energy=-0.0351,
        mp2_total_energy=-1.1318,
        ccsd_total_energy=-1.1373,
        fci_total_energy=-1.1516,
    )
    assert ec.fci_total_energy == pytest.approx(-1.1516)
    assert ec.mp2_correlation_energy == pytest.approx(-0.0351)
    assert ec.scf_xc_energy is None


def test_qc_atomic_result_properties():
    from qpubench.schemas.mirrors.molssi_qcschema import (
        QCAtomicResultProperties,
        QCCalcInfo,
        QCEnergyComponents,
    )
    props = QCAtomicResultProperties(
        calcinfo=QCCalcInfo(nbasis=4, nmo=4, nalpha=1, nbeta=1, natom=2),
        return_energy=-1.1173,
        energy_components=QCEnergyComponents(
            nuclear_repulsion_energy=0.7137,
            ccsd_total_energy=-1.1373,
        ),
        scf_dipole_moment=[0.0, 0.0, 0.0],
    )
    assert props.return_energy == pytest.approx(-1.1173)
    assert props.calcinfo.nbasis == 4
    assert props.energy_components.ccsd_total_energy == pytest.approx(-1.1373)
    assert props.scf_dipole_moment == [0.0, 0.0, 0.0]


def test_qc_wavefunction_data():
    from qpubench.schemas.mirrors.molssi_qcschema import QCWavefunctionData
    wfn = QCWavefunctionData(
        basis_name="sto-3g",
        nao=2,
        nmo=2,
        scf_orbitals_a=[0.5489, 0.5489, 0.5489, -0.5489],  # 2×2 column-major
        scf_eigenvalues_a=[-0.5783, 0.6695],
        scf_occupations_a=[2.0, 0.0],
        overlap_matrix=[1.0, 0.6593, 0.6593, 1.0],
    )
    assert wfn.nao == 2
    assert wfn.nmo == 2
    assert len(wfn.scf_orbitals_a) == 4
    assert wfn.scf_eigenvalues_a[0] == pytest.approx(-0.5783)


def test_qc_atomic_input():
    from qpubench.schemas.mirrors.molssi_qcschema import (
        QCAtomicInput,
        QCDriver,
        QCModel,
        QCMolecule,
    )
    mol = QCMolecule(symbols=["H", "H"], geometry=[0.0, 0.0, -0.7, 0.0, 0.0, 0.7])
    inp = QCAtomicInput(
        molecule=mol,
        driver=QCDriver.ENERGY,
        model=QCModel(method="hf", basis="sto-3g"),
        keywords={"scf_type": "df"},
        id="job-001",
    )
    assert inp.schema_name == "qcschema_input"
    assert inp.schema_version == 1
    assert inp.model.method == "hf"
    assert inp.keywords["scf_type"] == "df"


def test_qc_atomic_result_roundtrip():
    from qpubench.schemas.mirrors.molssi_qcschema import (
        QCAtomicResult,
        QCAtomicResultProperties,
        QCDriver,
        QCEnergyComponents,
        QCModel,
        QCMolecule,
        QCProvenance,
        QCWavefunctionData,
    )
    mol = QCMolecule(symbols=["H", "H"], geometry=[0.0, 0.0, -0.7, 0.0, 0.0, 0.7])
    result = QCAtomicResult(
        molecule=mol,
        driver=QCDriver.ENERGY,
        model=QCModel(method="ccsd", basis="cc-pvdz"),
        return_result=-1.1373,
        properties=QCAtomicResultProperties(
            return_energy=-1.1373,
            energy_components=QCEnergyComponents(
                nuclear_repulsion_energy=0.7137,
                ccsd_total_energy=-1.1373,
            ),
        ),
        wavefunction=QCWavefunctionData(basis_name="cc-pvdz", nao=10, nmo=10),
        success=True,
        provenance=QCProvenance(creator="psi4", version="1.7"),
    )
    data = json.loads(result.model_dump_json())
    assert data["schema_name"] == "qcschema_output"
    assert data["return_result"] == pytest.approx(-1.1373)
    assert data["properties"]["return_energy"] == pytest.approx(-1.1373)
    assert data["wavefunction"]["basis_name"] == "cc-pvdz"
    restored = QCAtomicResult.model_validate(data)
    assert restored.success is True
    assert restored.provenance.creator == "psi4"


def test_qc_optimization_result():
    from qpubench.schemas.mirrors.molssi_qcschema import (
        QCAtomicInput,
        QCDriver,
        QCModel,
        QCMolecule,
        QCOptimizationResult,
    )
    mol_start = QCMolecule(symbols=["H", "H"], geometry=[0.0, 0.0, -0.8, 0.0, 0.0, 0.8])
    mol_final = QCMolecule(symbols=["H", "H"], geometry=[0.0, 0.0, -0.7, 0.0, 0.0, 0.7])
    inp_spec = QCAtomicInput(
        molecule=mol_start,
        driver=QCDriver.GRADIENT,
        model=QCModel(method="hf", basis="sto-3g"),
    )
    opt = QCOptimizationResult(
        input_specification=inp_spec,
        initial_molecule=mol_start,
        final_molecule=mol_final,
        energies=[-1.1100, -1.1160, -1.1170, -1.1173],
        success=True,
    )
    assert opt.num_steps == 4
    assert opt.converged_energy == pytest.approx(-1.1173)
    assert opt.final_molecule.num_atoms == 2


def test_pennylane_mol_dataset():
    from qpubench.schemas.mirrors.molssi_qcschema import PennyLaneMolDataset
    ds = PennyLaneMolDataset(
        molname="H2",
        basis="STO-3G",
        bondlength=0.742,
        hf_energy=-1.1175,
        fci_energy=-1.1516,
        num_electrons=2,
        num_qubits=4,
        pauli_terms=15,
        dataset_tag="H2_STO-3G_0.742",
    )
    assert ds.molname == "H2"
    assert ds.num_qubits == 4
    assert ds.correlation_energy == pytest.approx(-1.1516 - (-1.1175))


def test_pennylane_mol_dataset_correlation_energy_none():
    from qpubench.schemas.mirrors.molssi_qcschema import PennyLaneMolDataset
    ds = PennyLaneMolDataset(molname="LiH", basis="cc-pVDZ")
    assert ds.correlation_energy is None


def test_qcschema_record_reference_energy():
    from qpubench.schemas.mirrors.molssi_qcschema import (
        PennyLaneMolDataset,
        QCAtomicResult,
        QCAtomicResultProperties,
        QCDriver,
        QCModel,
        QCMolecule,
        QCSchemaRecord,
    )
    mol = QCMolecule(symbols=["H", "H"], geometry=[0.0, 0.0, -0.7, 0.0, 0.0, 0.7])
    atomic = QCAtomicResult(
        molecule=mol,
        driver=QCDriver.ENERGY,
        model=QCModel(method="fci", basis="sto-3g"),
        return_result=-1.1516,
        properties=QCAtomicResultProperties(return_energy=-1.1516),
    )
    rec = QCSchemaRecord(atomic_result=atomic)
    assert rec.reference_energy == pytest.approx(-1.1516)

    # PennyLane fallback
    rec2 = QCSchemaRecord(
        pennylane_dataset=PennyLaneMolDataset(
            molname="H2", basis="STO-3G", bondlength=0.742, fci_energy=-1.1516
        )
    )
    assert rec2.reference_energy == pytest.approx(-1.1516)

    # Empty record
    rec3 = QCSchemaRecord()
    assert rec3.reference_energy is None


def test_quantum_result_qcschema_field():
    from qpubench.schemas.mirrors.molssi_qcschema import (
        QCAtomicResult,
        QCAtomicResultProperties,
        QCDriver,
        QCModel,
        QCMolecule,
        QCSchemaRecord,
    )
    from qpubench.schemas.result import QuantumResult
    mol = QCMolecule(symbols=["H", "H"], geometry=[0.0, 0.0, -0.7, 0.0, 0.0, 0.7])
    atomic = QCAtomicResult(
        molecule=mol,
        driver=QCDriver.ENERGY,
        model=QCModel(method="ccsd(t)", basis="cc-pvdz"),
        return_result=-1.1644,
        properties=QCAtomicResultProperties(return_energy=-1.1644),
    )
    result = QuantumResult(
        computing_model=ComputingModel.GATE_BASED,
        vendor_results={"qcschema_record": QCSchemaRecord(atomic_result=atomic)},
    )
    data = json.loads(result.model_dump_json())
    assert data["vendor_results"]["qcschema_record"]["atomic_result"]["return_result"] == pytest.approx(-1.1644)


# ---------------------------------------------------------------------------
# Neutral atom / AHS (Bloqade / Aquila) tests
# ---------------------------------------------------------------------------

def test_atom_arrangement_square_lattice():
    from qpubench.schemas.mirrors.quera_bloqade import (
        AtomArrangement,
        AtomicSite,
        LatticeGeometryType,
    )
    # 3×3 square lattice at 6 µm spacing, all filled
    sites = [AtomicSite(x=i * 6.0, y=j * 6.0) for i in range(3) for j in range(3)]
    arr = AtomArrangement(
        sites=sites,
        lattice_type=LatticeGeometryType.SQUARE,
        lattice_spacing_um=6.0,
    )
    assert arr.num_sites == 9
    assert arr.num_filled_sites == 9
    assert arr.fill_fraction == pytest.approx(1.0)


def test_atom_arrangement_chain_with_defect():
    from qpubench.schemas.mirrors.quera_bloqade import (
        AtomArrangement,
        AtomicSite,
        LatticeGeometryType,
    )
    sites = [AtomicSite(x=i * 5.0, y=0.0) for i in range(5)]
    arr = AtomArrangement(
        sites=sites,
        filling=[1, 1, 0, 1, 1],   # site 2 empty
        lattice_type=LatticeGeometryType.CHAIN,
        lattice_spacing_um=5.0,
    )
    assert arr.num_sites == 5
    assert arr.num_filled_sites == 4
    assert arr.fill_fraction == pytest.approx(0.8)


def test_atom_arrangement_default_filling():
    from qpubench.schemas.mirrors.quera_bloqade import AtomArrangement, AtomicSite
    sites = [AtomicSite(x=float(i), y=0.0) for i in range(4)]
    arr = AtomArrangement(sites=sites)
    assert arr.filling == [1, 1, 1, 1]   # defaults to all-filled
    assert arr.fill_fraction == pytest.approx(1.0)


def test_ahs_time_series():
    from qpubench.schemas.mirrors.quera_bloqade import AHSTimeSeries
    # π-pulse: ramp up to Ω_max, hold, ramp down
    ts = AHSTimeSeries(
        times_us=[0.0, 0.1, 0.9, 1.0],
        values=[0.0, 15.7, 15.7, 0.0],
    )
    assert ts.num_points == 4
    assert ts.duration_us == pytest.approx(1.0)


def test_ahs_waveform_piecewise_linear():
    from qpubench.schemas.mirrors.quera_bloqade import AHSWaveform, AHSWaveformType
    wf = AHSWaveform(
        waveform_type=AHSWaveformType.PIECEWISE_LINEAR,
        durations_us=[0.3, 0.4, 0.3],
        values=[0.0, 15.7, 15.7, 0.0],
    )
    assert wf.total_duration_us == pytest.approx(1.0)
    assert wf.waveform_type == AHSWaveformType.PIECEWISE_LINEAR


def test_ahs_waveform_constant():
    from qpubench.schemas.mirrors.quera_bloqade import AHSWaveform, AHSWaveformType
    wf = AHSWaveform(
        waveform_type=AHSWaveformType.CONSTANT,
        duration_us=2.0,
        values=[15.7],
    )
    assert wf.total_duration_us == pytest.approx(2.0)


def test_ahs_driving_field():
    from qpubench.schemas.mirrors.quera_bloqade import (
        AHSDrivingField,
        AHSTimeSeries,
        NeutralAtomCoupling,
        SpatialModulationType,
    )
    times = [0.0, 0.5, 1.0, 1.5, 2.0]
    rabi = AHSTimeSeries(times_us=times, values=[0.0, 15.7, 15.7, 15.7, 0.0])
    det  = AHSTimeSeries(times_us=times, values=[-30.0, -30.0, 0.0, 30.0, 30.0])
    phase = AHSTimeSeries(times_us=[0.0, 2.0], values=[0.0, 0.0])
    field = AHSDrivingField(
        coupling=NeutralAtomCoupling.RYDBERG,
        rabi_amplitude=rabi,
        rabi_phase=phase,
        detuning=det,
        spatial_modulation=SpatialModulationType.UNIFORM,
    )
    assert field.coupling == NeutralAtomCoupling.RYDBERG
    assert field.rabi_amplitude.duration_us == pytest.approx(2.0)
    assert field.detuning.values[0] == pytest.approx(-30.0)


def test_ahs_local_detuning():
    from qpubench.schemas.mirrors.quera_bloqade import AHSLocalDetuning, AHSTimeSeries
    ts = AHSTimeSeries(times_us=[0.0, 1.0, 2.0], values=[0.0, 50.0, 0.0])
    ld = AHSLocalDetuning(
        time_series=ts,
        site_coefficients=[0.0, 1.0, 0.5, 0.0, 1.0],
    )
    assert len(ld.site_coefficients) == 5
    assert ld.time_series.duration_us == pytest.approx(2.0)


def test_ahs_program_spec():
    from qpubench.schemas.mirrors.quera_bloqade import (
        AHSDrivingField,
        AHSProgramSpec,
        AHSTimeSeries,
        AtomArrangement,
        AtomicSite,
        LatticeGeometryType,
        NeutralAtomCoupling,
    )
    sites = [AtomicSite(x=i * 6.0, y=0.0) for i in range(5)]
    arr = AtomArrangement(
        sites=sites, lattice_type=LatticeGeometryType.CHAIN, lattice_spacing_um=6.0,
    )
    rabi = AHSTimeSeries(times_us=[0.0, 0.5, 1.0], values=[0.0, 15.7, 0.0])
    det  = AHSTimeSeries(times_us=[0.0, 0.5, 1.0], values=[-30.0, 0.0, 30.0])
    field = AHSDrivingField(rabi_amplitude=rabi, detuning=det)
    prog = AHSProgramSpec(
        atom_arrangement=arr,
        driving_fields=[field],
        total_duration_us=1.0,
        description="Z2 order preparation",
    )
    assert prog.num_qubits == 5
    assert prog.coupling == NeutralAtomCoupling.RYDBERG
    assert prog.total_duration_us == pytest.approx(1.0)


def test_ahs_batch_spec():
    from qpubench.schemas.mirrors.quera_bloqade import AHSBatchSpec
    batch = AHSBatchSpec(
        variable_names=["detuning_end", "rabi_max"],
        parameter_values=[
            [-30.0, -20.0, -10.0, 0.0],   # detuning_end sweep
            [10.0,  12.0,  14.0, 15.7],   # rabi_max sweep
        ],
        num_shots_per_batch=100,
    )
    assert batch.batch_size == 4
    assert len(batch.variable_names) == 2


def test_aquila_device_spec_defaults():
    from qpubench.schemas.mirrors.quera_bloqade import AquilaDeviceSpec
    hw = AquilaDeviceSpec()
    assert hw.max_qubits == 256
    assert hw.area_width_um == pytest.approx(75.0)
    assert hw.min_atom_spacing_um == pytest.approx(4.0)
    assert hw.rabi_max_rad_us == pytest.approx(15.8)
    assert hw.max_pulse_duration_us == pytest.approx(4.0)
    assert hw.c6_rad_us_um6 == pytest.approx(5.42e6)
    assert hw.max_shots == 1000


def test_ahs_shot_result_properties():
    from qpubench.schemas.mirrors.quera_bloqade import AHSShotResult, AHSShotStatus
    good = AHSShotResult(
        status=AHSShotStatus.SUCCESS,
        pre_sequence=[1, 1, 1, 1],
        post_sequence=[1, 0, 0, 1],
    )
    assert good.is_perfect_fill is True

    defect = AHSShotResult(
        status=AHSShotStatus.SUCCESS,
        pre_sequence=[1, 0, 1, 1],   # site 1 missing
        post_sequence=[1, 0, 0, 1],
    )
    assert defect.is_perfect_fill is False

    failed = AHSShotResult(status=AHSShotStatus.FAILURE)
    assert failed.is_perfect_fill is False


def test_ahs_task_result_analysis():
    from qpubench.schemas.mirrors.quera_bloqade import AHSShotResult, AHSShotStatus, AHSTaskResult
    shots = [
        AHSShotResult(status=AHSShotStatus.SUCCESS,
                      pre_sequence=[1, 1, 1], post_sequence=[1, 0, 1]),
        AHSShotResult(status=AHSShotStatus.SUCCESS,
                      pre_sequence=[1, 1, 1], post_sequence=[0, 1, 0]),
        AHSShotResult(status=AHSShotStatus.SUCCESS,
                      pre_sequence=[1, 0, 1], post_sequence=[1, 0, 1]),  # imperfect fill
        AHSShotResult(status=AHSShotStatus.FAILURE,
                      pre_sequence=[1, 1, 1], post_sequence=[1, 0, 1]),
    ]
    task = AHSTaskResult(num_shots_requested=4, shot_results=shots)
    assert task.num_shots_completed == 4
    assert len(task.successful_shots) == 3
    assert len(task.perfect_fill_shots) == 2   # only first two
    # bitstrings for perfect-fill shots
    assert task.bitstrings == [[1, 0, 1], [0, 1, 0]]
    # counts
    assert task.counts == {"101": 1, "010": 1}
    # rydberg_densities: P(post==0) per site over 2 good shots
    # site 0: (1-1 + 1-0)/2 = 0.5
    # site 1: (1-0 + 1-1)/2 = 0.5
    # site 2: (1-1 + 1-0)/2 = 0.5
    dens = task.rydberg_densities
    assert len(dens) == 3
    assert dens[0] == pytest.approx(0.5)
    assert dens[1] == pytest.approx(0.5)


def test_ahs_task_result_roundtrip():
    from qpubench.schemas.mirrors.quera_bloqade import (
        AHSExecutionMetadata,
        AHSShotResult,
        AHSShotStatus,
        AHSTaskResult,
    )
    task = AHSTaskResult(
        metadata=AHSExecutionMetadata(
            task_id="arn:aws:braket:us-east-1::task/abc123",
            device_id="arn:aws:braket:us-east-1::device/qpu/quera/Aquila",
            status="COMPLETED",
            cost_usd=0.07,
        ),
        num_shots_requested=7,
        shot_results=[
            AHSShotResult(status=AHSShotStatus.SUCCESS,
                          pre_sequence=[1, 1], post_sequence=[1, 0]),
        ] * 7,
    )
    data = json.loads(task.model_dump_json())
    assert data["metadata"]["task_id"] == "arn:aws:braket:us-east-1::task/abc123"
    assert data["num_shots_requested"] == 7
    restored = AHSTaskResult.model_validate(data)
    assert len(restored.shot_results) == 7
    assert restored.rydberg_densities == [pytest.approx(0.0), pytest.approx(1.0)]


def test_quantum_result_ahs_field():
    from qpubench.schemas.mirrors.quera_bloqade import (
        AHSShotResult,
        AHSShotStatus,
        AHSTaskResult,
    )
    from qpubench.schemas.result import QuantumResult
    task = AHSTaskResult(
        num_shots_requested=2,
        shot_results=[
            AHSShotResult(status=AHSShotStatus.SUCCESS,
                          pre_sequence=[1, 1, 1], post_sequence=[1, 0, 1]),
            AHSShotResult(status=AHSShotStatus.SUCCESS,
                          pre_sequence=[1, 1, 1], post_sequence=[0, 1, 0]),
        ],
    )
    result = QuantumResult(
        computing_model=ComputingModel.ADIABATIC,
        qubit_modality=QubitModality.NEUTRAL_ATOM,
        vendor_results={"ahs_result": task},
    )
    data = json.loads(result.model_dump_json())
    assert data["computing_model"] == "adiabatic"
    assert data["qubit_modality"] == "neutral_atom"
    assert data["vendor_results"]["ahs_result"]["num_shots_requested"] == 2


def test_backend_spec_aquila():
    b = BackendSpec.aquila()
    assert b.provider == "quera"
    assert b.computing_model == ComputingModel.ADIABATIC
    assert b.qubit_modality == QubitModality.NEUTRAL_ATOM
    assert b.simulator is False
    assert "Aquila" in b.auth["device_arn"]


def test_backend_spec_bloqade_emulator():
    b = BackendSpec.bloqade_emulator(num_qubits=12)
    assert b.provider == "bloqade"
    assert b.computing_model == ComputingModel.ADIABATIC
    assert b.qubit_modality == QubitModality.NEUTRAL_ATOM
    assert b.simulator is True
    assert b.num_qubits == 12


# ---------------------------------------------------------------------------
# SlowQuant UCC / VQE schema tests
# ---------------------------------------------------------------------------

def test_ucc_active_space_config():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import UCCActiveSpaceConfig
    cas = UCCActiveSpaceConfig(
        num_active_electrons=2,
        num_active_orbitals=2,
        num_total_electrons=2,
        num_total_orbitals=4,
        include_orbital_optimization=False,
    )
    assert cas.num_qubits == 4   # 2 × num_active_orbitals
    assert cas.frozen_core_orbitals == 0


def test_ucc_wavefunction_config():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import (
        UCCActiveSpaceConfig,
        UCCAnsatzType,
        UCCExcitationLevel,
        UCCWavefunctionConfig,
    )
    cas = UCCActiveSpaceConfig(num_active_electrons=2, num_active_orbitals=2)
    cfg = UCCWavefunctionConfig(
        ansatz=UCCAnsatzType.UCC,
        excitations=UCCExcitationLevel.SD,
        active_space=cas,
        spin_adapted=True,
    )
    assert cfg.num_qubits == 4
    assert cfg.excitations == UCCExcitationLevel.SD
    assert cfg.spin_adapted is True


def test_ucc_scf_result_homo_lumo_gap():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import UCCSCFResult
    scf = UCCSCFResult(
        hf_energy=-1.1175,
        nuclear_repulsion=0.7137,
        num_iterations=12,
        converged=True,
        mo_energies=[-0.5783, 0.6695, 1.2345, 2.0000],
        orbital_occupations=[2.0, 0.0, 0.0, 0.0],
        homo_index=0,
    )
    assert scf.hf_energy == pytest.approx(-1.1175)
    assert scf.homo_lumo_gap == pytest.approx(0.6695 - (-0.5783))
    assert scf.converged is True


def test_ucc_scf_result_no_gap():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import UCCSCFResult
    scf = UCCSCFResult(hf_energy=-1.1175)
    assert scf.homo_lumo_gap is None


def test_ucc_integral_data():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import UCCIntegralData
    # Minimal H2/STO-3G: 2 AOs → 4-entry h_ao, 16-entry g_ao
    nao = 2
    data = UCCIntegralData(
        basis_set="STO-3G",
        num_basis_functions=nao,
        h_ao=[-1.12, -0.96, -0.96, -0.50],   # nao² = 4
        overlap_ao=[1.0, 0.66, 0.66, 1.0],
    )
    assert data.num_basis_functions == 2
    assert len(data.h_ao) == 4
    assert data.g_ao == []   # omitted


def test_ucc_optimization_result():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import (
        UCCIterationRecord,
        UCCOptimizationMethod,
        UCCOptimizationResult,
    )
    history = [
        UCCIterationRecord(iteration=0, energy=-1.1000, gradient_norm=0.12),
        UCCIterationRecord(iteration=1, energy=-1.1320, gradient_norm=0.04),
        UCCIterationRecord(iteration=2, energy=-1.1373, gradient_norm=0.001),
    ]
    opt = UCCOptimizationResult(
        method=UCCOptimizationMethod.ONE_STEP,
        num_iterations=3,
        converged=True,
        final_energy=-1.1373,
        theta=[0.0512, -0.0318],
        kappa=[],
        iteration_history=history,
        gradient_norm_final=0.001,
    )
    assert opt.final_energy == pytest.approx(-1.1373)
    assert opt.num_theta_params == 2
    assert opt.num_kappa_params == 0
    assert opt.iteration_history[2].gradient_norm == pytest.approx(0.001)


def test_ucc_rdm_data():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import UCCRDMData
    # 2 active orbitals: rdm1 is 2×2=4 entries
    rdm = UCCRDMData(
        num_active_orbitals=2,
        rdm1=[1.9823, 0.0023, 0.0023, 0.0154],
        rdm2=[],
        has_rdm3=False,
        has_rdm4=False,
    )
    assert len(rdm.rdm1) == 4
    assert rdm.has_rdm3 is False


def test_ucc_excited_state_ev_auto():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import UCCExcitedStateResult
    # eV should be auto-filled from au value
    state = UCCExcitedStateResult(
        state_index=1,
        excitation_energy_au=0.3084,
        transition_dipole=[0.0, 0.0, 1.042],
        oscillator_strength=0.3215,
    )
    assert state.excitation_energy_ev == pytest.approx(0.3084 * 27.211_386_245_988)
    assert state.oscillator_strength == pytest.approx(0.3215)


def test_ucc_linear_response_result():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import (
        UCCExcitationLevel,
        UCCExcitedStateResult,
        UCCLinearResponseResult,
        UCCLinearResponseType,
    )
    states = [
        UCCExcitedStateResult(state_index=1, excitation_energy_au=0.308,
                              transition_dipole=[0.0, 0.0, 1.04], oscillator_strength=0.32),
        UCCExcitedStateResult(state_index=2, excitation_energy_au=0.421,
                              transition_dipole=[0.0, 1.12, 0.0], oscillator_strength=0.11),
    ]
    lr = UCCLinearResponseResult(
        response_type=UCCLinearResponseType.SELF_CONSISTENT,
        excitation_level=UCCExcitationLevel.SD,
        num_states_computed=2,
        excited_states=states,
    )
    assert len(lr.excitation_energies_au) == 2
    assert lr.excitation_energies_au[0] == pytest.approx(0.308)
    assert lr.oscillator_strengths[1] == pytest.approx(0.11)


def test_ucc_circuit_spec():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import (
        UCCAnsatzType,
        UCCCircuitSpec,
        UCCExcitationLevel,
    )
    circ = UCCCircuitSpec(
        ansatz_type=UCCAnsatzType.FUCC,
        excitation_level=UCCExcitationLevel.SD,
        num_qubits=4,
        num_parameters=3,
        gate_depth=24,
        cx_count=12,
        spin_adapted=True,
    )
    assert circ.num_qubits == 4
    assert circ.cx_count == 12
    assert circ.qubit_encoding == "jordan_wigner"


def test_slowquant_record_correlation_energy():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import (
        SlowQuantRecord,
        UCCActiveSpaceConfig,
        UCCAnsatzType,
        UCCExcitationLevel,
        UCCOptimizationMethod,
        UCCOptimizationResult,
        UCCSCFResult,
        UCCWavefunctionConfig,
    )
    scf = UCCSCFResult(hf_energy=-1.1175, converged=True)
    opt = UCCOptimizationResult(
        method=UCCOptimizationMethod.ONE_STEP,
        num_iterations=5,
        converged=True,
        final_energy=-1.1373,
        theta=[0.051, -0.032],
    )
    cas = UCCActiveSpaceConfig(num_active_electrons=2, num_active_orbitals=2)
    cfg = UCCWavefunctionConfig(
        ansatz=UCCAnsatzType.UCC,
        excitations=UCCExcitationLevel.SD,
        active_space=cas,
    )
    rec = SlowQuantRecord(
        molecule_name="H2",
        basis_set="STO-3G",
        scf_result=scf,
        wavefunction_config=cfg,
        optimization_result=opt,
    )
    assert rec.correlation_energy == pytest.approx(-1.1373 - (-1.1175))
    assert rec.num_qubits == 4   # from wavefunction_config


def test_slowquant_record_roundtrip():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import (
        SlowQuantRecord,
        UCCActiveSpaceConfig,
        UCCAnsatzType,
        UCCCircuitSpec,
        UCCExcitationLevel,
        UCCExcitedStateResult,
        UCCLinearResponseResult,
        UCCLinearResponseType,
        UCCOptimizationMethod,
        UCCOptimizationResult,
        UCCSCFResult,
        UCCWavefunctionConfig,
    )
    scf = UCCSCFResult(hf_energy=-1.1175, converged=True,
                       mo_energies=[-0.578, 0.670], homo_index=0)
    opt = UCCOptimizationResult(
        method=UCCOptimizationMethod.TWO_STEP,
        num_iterations=8,
        converged=True,
        final_energy=-1.1516,
        theta=[0.04, -0.03, 0.01],
        kappa=[0.002, -0.001],
    )
    cas = UCCActiveSpaceConfig(num_active_electrons=2, num_active_orbitals=2,
                               include_orbital_optimization=True)
    cfg = UCCWavefunctionConfig(ansatz=UCCAnsatzType.TUPS,
                                excitations=UCCExcitationLevel.SD, active_space=cas)
    lr = UCCLinearResponseResult(
        response_type=UCCLinearResponseType.PROJECTED,
        excitation_level=UCCExcitationLevel.SD,
        num_states_computed=1,
        excited_states=[
            UCCExcitedStateResult(state_index=1, excitation_energy_au=0.5716,
                                  oscillator_strength=0.0)
        ],
    )
    circ = UCCCircuitSpec(ansatz_type=UCCAnsatzType.TUPS,
                          excitation_level=UCCExcitationLevel.SD,
                          num_qubits=4, num_parameters=5, gate_depth=18, cx_count=8)
    rec = SlowQuantRecord(
        molecule_name="H2",
        basis_set="STO-3G",
        scf_result=scf,
        wavefunction_config=cfg,
        optimization_result=opt,
        linear_response=lr,
        circuit_spec=circ,
    )
    data = json.loads(rec.model_dump_json())
    assert data["molecule_name"] == "H2"
    assert data["optimization_result"]["final_energy"] == pytest.approx(-1.1516)
    assert data["linear_response"]["excited_states"][0]["state_index"] == 1
    restored = SlowQuantRecord.model_validate(data)
    assert restored.num_qubits == 4
    assert restored.correlation_energy == pytest.approx(-1.1516 - (-1.1175))


def test_quantum_result_slowquant_field():
    from qpubench.schemas.mirrors.erikkjellgren_slowquant import (
        SlowQuantRecord,
        UCCOptimizationMethod,
        UCCOptimizationResult,
        UCCSCFResult,
    )
    from qpubench.schemas.result import QuantumResult
    opt = UCCOptimizationResult(
        method=UCCOptimizationMethod.ONE_STEP,
        num_iterations=4,
        converged=True,
        final_energy=-1.1373,
        theta=[0.05],
    )
    rec = SlowQuantRecord(
        molecule_name="H2",
        scf_result=UCCSCFResult(hf_energy=-1.1175, converged=True),
        optimization_result=opt,
        ucc_energy=-1.1373,
    )
    result = QuantumResult(
        computing_model=ComputingModel.GATE_BASED,
        vendor_results={"slowquant_record": rec},
    )
    data = json.loads(result.model_dump_json())
    assert data["vendor_results"]["slowquant_record"]["ucc_energy"] == pytest.approx(-1.1373)
    assert data["vendor_results"]["slowquant_record"]["molecule_name"] == "H2"


# ---------------------------------------------------------------------------
# Classiq schemas + Xenakis harmonization
# ---------------------------------------------------------------------------

from qpubench.schemas.mirrors.classiq_classiq import (
    CircuitOptimizationComparison,
    ClassiqAnsatzType,
    ClassiqChemistryModel,
    ClassiqCombinatorialOptimizationSpec,
    ClassiqConstraints,
    ClassiqFermionMapping,
    ClassiqMoleculeSpec,
    ClassiqOptimizationParameter,
    ClassiqSynthesisResult,
    ClassiqVQEResult,
)
from qpubench.schemas.mirrors.mqsdk_xenakis import (
    GAGenerationRecord,
    GARunResult,
    GateSpec,
    GenomeLayer,
    LayerGenome,
    XenakisMolecule,
)


def test_classiq_constraints_defaults():
    c = ClassiqConstraints()
    assert c.max_width is None
    assert c.optimization_parameter == ClassiqOptimizationParameter.NONE


def test_classiq_molecule_from_xenakis_roundtrip():
    mol = XenakisMolecule(
        name="H2",
        symbols=["H", "H"],
        coordinates_angstrom=[(0.0, 0.0, 0.0), (0.0, 0.0, 0.7414)],
        multiplicity=1,
    )
    cmol = ClassiqMoleculeSpec.from_xenakis_molecule(mol)
    assert cmol.spin == 0
    assert cmol.atoms[1] == ("H", (0.0, 0.0, 0.7414))

    back = cmol.to_xenakis_molecule(name="H2", basis="sto-3g")
    assert back.symbols == mol.symbols
    assert back.coordinates_angstrom == mol.coordinates_angstrom
    assert back.multiplicity == mol.multiplicity


def test_classiq_synthesis_result_to_circuit_spec():
    synth = ClassiqSynthesisResult(
        program_id="prog-1",
        qasm3="OPENQASM 3;\nqubit[2] q;\nh q[0];\ncx q[0], q[1];\n",
        width=2,
        depth=2,
        gate_count={"h": 1, "cx": 1},
        cx_count=1,
    )
    spec = synth.to_circuit_spec()
    assert spec.num_qubits == 2
    assert spec.gate_counts == {"h": 1, "cx": 1}


def test_classiq_synthesis_result_requires_width():
    synth = ClassiqSynthesisResult(qasm3="OPENQASM 3;\n")
    with pytest.raises(ValueError):
        synth.to_circuit_spec()


def test_classiq_vqe_result_to_vqa_config():
    mol = XenakisMolecule(
        name="H2", symbols=["H", "H"],
        coordinates_angstrom=[(0.0, 0.0, 0.0), (0.0, 0.0, 0.7414)],
    )
    cmol = ClassiqMoleculeSpec.from_xenakis_molecule(mol)
    model = ClassiqChemistryModel(
        molecule=cmol,
        mapping=ClassiqFermionMapping.JORDAN_WIGNER,
        ansatz=ClassiqAnsatzType.UCC,
    )
    synth = ClassiqSynthesisResult(program_id="prog-2", qasm3="OPENQASM 3;\n", width=4, cx_count=8)
    vqe = ClassiqVQEResult(final_energy=-1.137, optimized_parameters=[0.1, 0.2], synthesis=synth)

    vqa = vqe.to_vqa_config(molecule="H2", model=model)
    assert vqa.mapper == "JordanWigner"
    assert vqa.ansatz == "ucc"
    assert vqa.classiq_synthesis_id == "prog-2"

    res = vqe.to_vqa_result()
    assert res.n_cnot == 8
    assert res.num_parameters == 2
    assert res.final_eigenvalue == pytest.approx(-1.137)


def test_classiq_combinatorial_optimization_matches_xenakis_objective():
    spec = ClassiqCombinatorialOptimizationSpec(
        problem_type="maxcut",
        graph_edges=[(0, 1), (1, 2), (2, 0)],
    )
    assert spec.problem_type == "maxcut"   # same vocabulary as XenakisRunConfig.objective


def test_circuit_optimization_comparison_depth_delta():
    ga = GARunResult(
        run_id="run-1",
        history=[GAGenerationRecord(generation=0, best_fitness=1.0)],
        best_fitness=1.0,
        best_genome=LayerGenome(
            n_qubits=2,
            layers=[
                GenomeLayer(gates=[GateSpec(name="h", wires=[0])]),
                GenomeLayer(gates=[GateSpec(name="cx", wires=[0, 1])]),
                GenomeLayer(gates=[GateSpec(name="rz", wires=[1], param=0.3)]),
            ],
        ),
    )
    synth = ClassiqSynthesisResult(program_id="prog-3", qasm3="OPENQASM 3;\n", width=2, depth=2)
    cmp = CircuitOptimizationComparison(problem_label="H2 ansatz", ga_result=ga, classiq_result=synth)

    assert cmp.depth_delta == 1   # GA genome has 3 layers vs Classiq's depth=2
    assert "GA: 1 generations" in cmp.search_cost_label


def test_circuit_optimization_comparison_missing_side():
    cmp = CircuitOptimizationComparison(problem_label="H2 ansatz")
    assert cmp.depth_delta is None
    assert cmp.search_cost_label == "no data"


# ---------------------------------------------------------------------------
# mqsdk_cebule — task types confirmed against mqsdk/core/cebule.py's
# TaskType enum (gitlab.com/mqsdk/python-sdk), revised 2026-07-08
# ---------------------------------------------------------------------------

from qpubench.schemas.mirrors.mqsdk_cebule import (
    AbInitioMDInput,
    AbInitioMDMethod,
    ActivityCoefficientInput,
    AtomOrderInput,
    CebuleTaskEnvelope,
    CebuleTaskType,
    CosmoInput,
    CosmoMethod,
    CRNReaction,
    CRNSpecies,
    ForceFieldMDInput,
    GANTOFInput,
    GasSpeciesEnergyInput,
    GeneratedCatalyst,
    GeometryOptForceField,
    GeometryOptInput,
    GeometryOptMethod,
    GNNDatasetCreateInput,
    GNNDatasetExtendInput,
    GNNDatasetGetInput,
    GNNMoleculeChunk,
    GNNPredictInput,
    GNNTrainInput,
    GroupContributionInput,
    MakeSurfInput,
    PeriodicGeometryOptInput,
    RXNOptInput,
    RXNOptResult,
    SigmaInput,
    SolubilityInput,
    SurfaceReactionEnergiesInput,
    WulffConstructionInput,
    WulffFacet,
)


def test_cebule_task_type_confirmed_members_present():
    # Every member confirmed directly against mqsdk/core/cebule.py's
    # TaskType enum (re-checked 2026-07-10) — see CebuleTaskType docstring.
    confirmed = {
        "cosmo", "sigma", "solubility", "car_parrinello_md",
        "born_oppenheimer_md", "force_field_md", "geometry_opt",
        "periodic_geometry_opt", "group_contribution", "atom_order",
        "activity_coefficient", "gnn:dataset:create", "gnn:dataset:delete",
        "gnn:dataset:extend", "gnn:dataset:get", "gnn:train", "gnn:predict",
        "tn_qc_opt", "covo", "mol_map", "qasm_gen", "map_to_qasm",
    }
    actual = {member.value for member in CebuleTaskType}
    assert confirmed <= actual


def test_cebule_task_type_rxn_catalyst_members_present_but_unconfirmed():
    # Real per docs.mqs.dk's "RN Catalyst Design" section, but absent from
    # the public python-sdk repo (checked 2026-07-10) — see CebuleTaskType
    # docstring. Kept, flagged unconfirmed, not removed — same treatment
    # MOL_MAP/QASM_GEN got before the SDK confirmed them for real.
    unconfirmed = {
        "rxn_opt", "gas_species_energy", "surface_reaction_energies",
        "gan_tof", "make_surf", "wulff_construction",
    }
    actual = {member.value for member in CebuleTaskType}
    assert unconfirmed <= actual


def test_rxn_opt_input_and_result():
    rxn_input = RXNOptInput(
        reaction_list=[
            CRNReaction(name="r1", fixed_cost=10.0, unit_cost=2.0, low=0.0, high=100.0),
            CRNReaction(name="r2", fixed_cost=5.0, unit_cost=1.5, low=0.0, high=50.0),
        ],
        species_list=[
            CRNSpecies(name="A", stoich={"r1": -1.0}),
            CRNSpecies(name="B", stoich={"r1": 1.0, "r2": -1.0}),
            CRNSpecies(name="C", stoich={"r2": 1.0}),
        ],
        time_limit=60,
    )
    assert rxn_input.task_type == CebuleTaskType.RXN_OPT
    assert len(rxn_input.reaction_list) == 2
    assert rxn_input.species_list[1].stoich == {"r1": 1.0, "r2": -1.0}

    result = RXNOptResult(
        reaction_quantities={"r1": 10.0, "r2": 10.0},
        total_cost=115.0,
        solve_time=0.5,
        optimal=True,
    )
    assert result.optimal is True
    assert result.reaction_quantities["r1"] == 10.0


def test_gas_species_energy_input():
    gse = GasSpeciesEnergyInput(
        energy_calculator="dft",
        optimizer_type="bfgs",
        unitcell_length=20.0,
        temperature=298.15,
        pressure=101325.0,
        dataset_tag="test-dataset",
    )
    assert gse.task_type == CebuleTaskType.GAS_SPECIES_ENERGY


def test_surface_reaction_energies_input():
    sre = SurfaceReactionEnergiesInput(
        reaction_type="oxidation",
        temperature=500.0,
        pressure=1.0,
        dataset_tag="test-dataset",
        uncertainty=True,
    )
    assert sre.task_type == CebuleTaskType.SURFACE_REACTION_ENERGIES
    assert sre.uncertainty is True


def test_gan_tof_input_and_generated_catalyst():
    gan_input = GANTOFInput(
        reaction_type="CO2_reduction",
        dataset_tag="test-dataset",
        epochs=100,
        nclass=5,
        score_max=1.0,
        score_min=0.0,
    )
    assert gan_input.task_type == CebuleTaskType.GAN_TOF

    catalyst = GeneratedCatalyst(chemical_formula="CuZn", atomic_numbers=[29, 30], run=1)
    assert catalyst.atomic_numbers == [29, 30]


def test_make_surf_input():
    make_surf = MakeSurfInput(
        element1="Cu",
        element2="Zn",
        surface_type="fcc111",
        n_surfaces=10,
        lattice_const=3.6,
        vacuum=10.0,
        supercell=(2, 2, 4),
    )
    assert make_surf.task_type == CebuleTaskType.MAKE_SURF
    assert make_surf.supercell == (2, 2, 4)


def test_wulff_construction_input_and_facet():
    wulff_input = WulffConstructionInput(dataset_tag="test-dataset")
    assert wulff_input.task_type == CebuleTaskType.WULFF_CONSTRUCTION

    facet = WulffFacet(
        miller_indices=(1, 1, 1),
        surface_energy_ev_per_a2=0.05,
        area_fraction=0.4,
        tof=1.2,
        activation_barrier_ev=0.8,
    )
    assert facet.miller_indices == (1, 1, 1)


def test_cebule_task_envelope_defaults():
    env = CebuleTaskEnvelope()
    assert env.max_processors is None
    assert env.connected_task_id is None


def test_cosmo_input_requires_dielec_and_basis():
    cosmo = CosmoInput(basis="6-31g**", dielec=78.0, optimize=True)
    assert cosmo.task_type == CebuleTaskType.COSMO
    assert cosmo.method == "dft"
    assert cosmo.driver_convergence == "loose"


def test_sigma_input_chains_from_cosmo_task():
    sigma = SigmaInput(connected_task_id="cosmo-task-1", cosmo_method=CosmoMethod.COSMO_SAC)
    assert sigma.connected_task_id == "cosmo-task-1"
    assert sigma.cosmo_method == CosmoMethod.COSMO_SAC


def test_solubility_input_chains_from_multiple_sigma_tasks():
    sol = SolubilityInput(
        connected_task_id=["sigma-solute", "sigma-solvent"],
        temperature=298.15,
        melting_point=350.0,
        enthalpy_melting=20.0,
        sol_init=0.1,
        solv_composition=[1.0],
        change_heat_capacity_melting=5.0,
    )
    assert sol.connected_task_id == ["sigma-solute", "sigma-solvent"]
    assert sol.solv_composition == [1.0]


def test_geometry_opt_input_force_field_and_method_enums():
    geo = GeometryOptInput(
        smiles_list=["O"],
        force_field=GeometryOptForceField.MMFF94,
        optimization_method=GeometryOptMethod.GFN2_XTB,
    )
    assert geo.force_field == "mmff94"
    assert geo.optimization_method == "gfn2_xtb"


def test_periodic_geometry_opt_input_optional_cell_params():
    periodic = PeriodicGeometryOptInput(
        smiles_list=["O"],
        cell_lengths=(10.0, 10.0, 10.0),
        cell_angles=(90.0, 90.0, 90.0),
    )
    assert periodic.cell_lengths == (10.0, 10.0, 10.0)


def test_force_field_md_input_polymer_primary():
    md = ForceFieldMDInput(
        smiles_primary=["CC", "CC"],
        copies_primary=1,
        smiles_list_secondary=["O"],
        copies_list_secondary=[100],
        temperature=298.15,
        box_length_nm=3.0,
        time_fs=1000.0,
    )
    assert md.smiles_primary == ["CC", "CC"]


def test_ab_initio_md_input_uses_raw_qe_text_not_kwargs():
    bomd = AbInitioMDInput(
        method=AbInitioMDMethod.BORN_OPPENHEIMER,
        qe_input="&control\n calculation='cp'\n/\n",
    )
    assert bomd.method == AbInitioMDMethod.BORN_OPPENHEIMER
    assert "&control" in bomd.qe_input


def test_group_contribution_input_batch_of_mixtures():
    gc = GroupContributionInput(
        smiles_list=[["CCO", "O"], ["CCC", "O"]],
        gc_type="unifac",
    )
    assert len(gc.smiles_list) == 2
    assert gc.batch is True


def test_atom_order_input_smiles_or_polymer_list():
    single = AtomOrderInput(smiles="CCO")
    polymer = AtomOrderInput(smiles=["CC", "CC"], geometry=[0.0] * 6)
    assert single.geometry is None
    assert len(polymer.geometry) == 6


def test_activity_coefficient_input_envelope_only():
    # No task-specific fields confirmed yet — see class docstring.
    ac = ActivityCoefficientInput(max_processors=4)
    assert ac.task_type == CebuleTaskType.ACTIVITY_COEFFICIENT


def test_gnn_dataset_lifecycle_inputs():
    create = GNNDatasetCreateInput(
        dataset_name="ds1", includes_target_val=True, target_property="homo_lumo_gap",
    )
    extend = GNNDatasetExtendInput(
        connected_dataset_id="ds1",
        molecule_chunk=GNNMoleculeChunk(smiles=["O"], coords=[[0.0, 0.0, 0.0]], target_val=[1.2]),
    )
    get = GNNDatasetGetInput(connected_dataset_id="ds1", start=0, end=10)
    assert create.target_property == "homo_lumo_gap"
    assert extend.molecule_chunk.target_val == [1.2]
    assert get.end == 10


def test_gnn_train_and_predict_inputs():
    train = GNNTrainInput(
        connected_dataset_id="ds1", model_name="model1",
        hyperparameters={"epochs": 75},
    )
    predict = GNNPredictInput(connected_dataset_id="ds1", connected_model_id="model1")
    assert train.hyperparameters["epochs"] == 75
    assert predict.connected_model_id == "model1"


# ---------------------------------------------------------------------------
# pyscf — added while checking whether InQuanto is necessary for embedding
# and periodic-boundary quantum chemistry (it isn't; PySCF is free and
# covers the same ground). Molecule/cell/solvation fields verified against
# the real pyscf API where installed; embedding types are schema-only
# (PsiEmbed/libDMET aren't on PyPI).
# ---------------------------------------------------------------------------

from qpubench.schemas.mirrors.pyscf_pyscf import (
    DMETConfig,
    EmbeddedHamiltonianResult,
    ERIBuilderConfig,
    ERIBuilderMethod,
    ERIBuilderResult,
    OrbitalOptimizerBasinHoppingConfig,
    OrbitalOptimizerConfig,
    OrbitalOptimizerMethod,
    OrbitalOptimizerResult,
    ProjectionEmbeddingConfig,
    PySCFAtomSpec,
    PySCFCellSpec,
    PySCFMeanFieldConfig,
    PySCFMeanFieldMethod,
    PySCFMoleculeSpec,
    PySCFSolvationConfig,
)


def _h2_molecule_spec() -> PySCFMoleculeSpec:
    return PySCFMoleculeSpec(atoms=[
        PySCFAtomSpec(symbol="H", x=0.0, y=0.0, z=0.0),
        PySCFAtomSpec(symbol="H", x=0.0, y=0.0, z=0.7414),
    ])


def test_pyscf_molecule_spec_atom_string_format():
    spec = _h2_molecule_spec()
    assert spec.to_pyscf_atom_string() == "H 0.0 0.0 0.0; H 0.0 0.0 0.7414"


def test_pyscf_molecule_spec_matches_real_pyscf_energy():
    pyscf = pytest.importorskip("pyscf")
    from pyscf import scf

    spec = _h2_molecule_spec()
    mol = pyscf.gto.M(
        atom=spec.to_pyscf_atom_string(), basis=spec.basis,
        charge=spec.charge, spin=spec.spin, unit=spec.unit,
    )
    energy = scf.RHF(mol).kernel()
    assert math.isclose(energy, -1.1166843870853405, rel_tol=1e-8)


def test_pyscf_cell_spec_periodic_dimension_default():
    cell = PySCFCellSpec(
        atoms=[PySCFAtomSpec(symbol="H", x=0, y=0, z=0),
               PySCFAtomSpec(symbol="H", x=0.75, y=0.75, z=0.75)],
        lattice_vectors=((3.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 3.0)),
    )
    assert cell.dimension == 3


def test_pyscf_cell_spec_builds_real_periodic_cell():
    pytest.importorskip("pyscf")
    from pyscf.pbc import gto as pbcgto

    cell_spec = PySCFCellSpec(
        atoms=[PySCFAtomSpec(symbol="H", x=0, y=0, z=0),
               PySCFAtomSpec(symbol="H", x=0.75, y=0.75, z=0.75)],
        lattice_vectors=((3.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 3.0)),
    )
    cell = pbcgto.Cell()
    cell.atom = cell_spec.to_pyscf_atom_string()
    cell.a = [list(v) for v in cell_spec.lattice_vectors]
    cell.basis = cell_spec.basis
    cell.build()
    assert cell.natm == 2


def test_pyscf_mean_field_config_defaults():
    cfg = PySCFMeanFieldConfig()
    assert cfg.method == PySCFMeanFieldMethod.RHF
    assert cfg.xc is None


def test_pyscf_solvation_config_matches_real_pcm_defaults():
    pytest.importorskip("pyscf")
    from pyscf import gto
    from pyscf.solvent import pcm

    mol = gto.M(atom="O 0 0 0; H 0 0.757 0.587; H 0 -0.757 0.587", basis="sto-3g")
    real_pcm = pcm.PCM(mol)
    cfg = PySCFSolvationConfig()
    assert cfg.method.value == real_pcm.method
    assert math.isclose(cfg.eps, real_pcm.eps, rel_tol=1e-6)


def test_projection_embedding_config_manby_miller_fields():
    cfg = ProjectionEmbeddingConfig(
        active_atom_indices=[0, 1], environment_method="b3lyp", active_method="ccsd",
    )
    assert cfg.level_shift_mu == 1.0e6


def test_dmet_config_defaults():
    cfg = DMETConfig(impurity_atom_indices=[0])
    assert cfg.localization == "iao"
    assert cfg.max_scf_cycles == 20


def test_embedded_hamiltonian_result_feeds_active_space_size():
    result = EmbeddedHamiltonianResult(
        one_electron_integrals=[[0.0]],
        two_electron_integrals=[[[[0.0]]]],
        core_energy=-1.0,
        num_active_orbitals=2,
        num_active_electrons=2,
    )
    # Matches integrations/generic_adapt_vqe's num_qubits convention directly.
    num_qubits = 2 * result.num_active_orbitals
    assert num_qubits == 4


def test_eri_builder_config_defaults_to_standard():
    cfg = ERIBuilderConfig()
    assert cfg.method == ERIBuilderMethod.STANDARD
    assert cfg.auxbasis is None


def test_eri_builder_standard_vs_ri_matches_real_pyscf():
    pytest.importorskip("pyscf")
    from pyscf import gto, scf

    mol = gto.M(atom="O 0 0 0; H 0 0.757 0.587; H 0 -0.757 0.587", basis="cc-pvdz")
    mf_std = scf.RHF(mol).run(verbose=0)
    mf_ri = scf.RHF(mol).density_fit().run(verbose=0)

    standard = ERIBuilderResult(
        energy=mf_std.e_tot, converged=mf_std.converged, method_used=ERIBuilderMethod.STANDARD,
    )
    ri = ERIBuilderResult(
        energy=mf_ri.e_tot, converged=mf_ri.converged,
        method_used=ERIBuilderMethod.RESOLUTION_OF_IDENTITY,
        auxbasis_used=mf_ri.with_df.auxbasis,
    )
    # RI is a real, small, controlled approximation of the standard ERIs.
    assert abs(ri.energy - standard.energy) < 1.0e-3
    assert ri.auxbasis_used is not None


def test_orbital_optimizer_basin_hopping_config_defaults():
    cfg = OrbitalOptimizerBasinHoppingConfig()
    assert cfg.active is False
    assert cfg.n_macro_iterations == 20


def test_orbital_optimizer_config_defaults_to_newton():
    cfg = OrbitalOptimizerConfig(active_electrons=2, active_orbitals=2)
    assert cfg.method == OrbitalOptimizerMethod.NEWTON
    assert cfg.basin_hopping.active is False


def test_orbital_optimizer_newton_matches_real_casscf():
    pytest.importorskip("pyscf")
    from pyscf import gto, mcscf, scf

    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="6-31g", verbose=0)
    mf = scf.RHF(mol).run(verbose=0)
    mc = mcscf.CASSCF(mf, ncas=2, nelecas=2)
    mc.verbose = 0
    e_casscf = mc.kernel()[0]

    result = OrbitalOptimizerResult(
        final_energy=e_casscf, converged=mc.converged, num_iterations=1,
    )
    assert result.converged
    assert math.isclose(result.final_energy, -1.1462344220, rel_tol=1e-6)
    assert result.kappa is None


def test_orbital_optimizer_simple_kappa_rotation_matches_newton():
    pytest.importorskip("pyscf")
    import numpy as np
    from pyscf import gto, mcscf, scf
    from scipy.linalg import expm
    from scipy.optimize import minimize

    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="6-31g", verbose=0)
    mf = scf.RHF(mol).run(verbose=0)
    ncas, nelecas = 2, 2
    nmo = mf.mo_coeff.shape[1]

    mc = mcscf.CASSCF(mf, ncas=ncas, nelecas=nelecas)
    mc.verbose = 0
    e_newton = mc.kernel()[0]

    # Real non-redundant kappa parametrization — PySCF's own CASSCF mask.
    mask = mc.uniq_var_indices(nmo, mc.ncore, mc.ncas, mc.frozen)
    idx = np.where(mask)
    n_params = int(mask.sum())

    def energy_fn(x: object) -> float:
        kappa = np.zeros((nmo, nmo))
        kappa[idx] = x
        kappa = kappa - kappa.T
        rotated_mo = mf.mo_coeff @ expm(kappa)
        mc_ci = mcscf.CASCI(mf, ncas=ncas, nelecas=nelecas)
        mc_ci.verbose = 0
        return float(mc_ci.kernel(mo_coeff=rotated_mo)[0])

    res = minimize(energy_fn, np.zeros(n_params), method="Powell", options={"maxiter": 100})
    result = OrbitalOptimizerResult(
        final_energy=float(res.fun), converged=bool(res.success),
        num_iterations=int(res.nit), kappa=[float(v) for v in res.x],
    )
    # A real, independently-derived mechanism landing near the CASSCF reference.
    assert abs(result.final_energy - e_newton) < 1.0e-3
    assert result.kappa is not None
    assert len(result.kappa) == n_params


# ---------------------------------------------------------------------------
# GSOpt per-lane run configurations
# ---------------------------------------------------------------------------

from qpubench.schemas.mirrors.bestquark_gsopt import (  # noqa: E402
    GSOptAFQMCRunConfig,
    GSOptBenchmarkResult,
    GSOptGibbsRunConfig,
    GSOptRunConfig,
    GSOptTNRunConfig,
    GSOptVQERunConfig,
)

_GSOPT_VQE_CONFIG = dict(
    name="uccsd_2_BH", ansatz="uccsd", layers=2, optimizer="cobyla",
    max_steps=100, init_scale=0.01, seed=42,
)
_GSOPT_TN_CONFIG = dict(
    name="simple_tn", method="dmrg2", init_state="random",
    bond_schedule=[8, 12, 16, 24, 32, 48], cutoff=1.0e-6, solver_tol=1.0e-4,
    max_sweeps=12, tau=0.1, chi=32, init_bond_dim=4, init_seed=42,
    local_eig_ncv=4,
)
_GSOPT_DMRG_CONFIG = dict(
    name="simple_dmrg", bond_schedule=[32, 64, 96, 128, 160, 192, 256],
    cutoff=1.0e-10, solver_tol=1.0e-6, max_sweeps=64, init_bond_dim=13,
    init_seed=42,
)
_GSOPT_AFQMC_CONFIG = dict(
    name="afqmc_n2", trial="rhf", scf_conv_tol=1.0e-10, scf_max_cycle=64,
    diis_space=8, level_shift=0.0, damping=0.0, init_guess="minao",
    chol_cut=1.0e-6, num_walkers_per_rank=64, num_steps_per_block=25,
    num_blocks=100, timestep=0.005, stabilize_freq=5, pop_control_freq=5,
)
_GSOPT_GIBBS_CONFIG = dict(
    name="simple_gibbs", length=8, beta=0.8, coupling=1.0, field=0.3,
    num_chains=64, burn_in_sweeps=50, sample_sweeps=200, thinning=2, seed=42,
)


def _gsopt_result(config: dict) -> dict:
    """Minimal molecular-lane GSOptBenchmarkResult payload around a config."""
    return dict(
        task="vqe", molecule="BH",
        cas=dict(active_electrons=4, active_orbitals=4),
        score=-24.77, config=config, hf_energy=-24.75, iterations=50,
        nfev=120, final_energy=-24.77, wall_seconds=12.0,
        wall_budget_seconds=20.0,
    )


@pytest.mark.parametrize(
    "payload,expected",
    [
        (_GSOPT_VQE_CONFIG,   GSOptVQERunConfig),
        (_GSOPT_TN_CONFIG,    GSOptTNRunConfig),
        (_GSOPT_DMRG_CONFIG,  GSOptTNRunConfig),   # DMRG config ⊂ TN config
        (_GSOPT_AFQMC_CONFIG, GSOptAFQMCRunConfig),
        (_GSOPT_GIBBS_CONFIG, GSOptGibbsRunConfig),
        ({"name": "unknown_lane"}, GSOptRunConfig),
    ],
)
def test_gsopt_lane_config_union_resolves(payload, expected):
    """GSOpt is method-agnostic: each lane's `config` sub-object parses to its
    own model, and an unrecognised one falls back to the bare base rather than
    being coerced into some other lane's shape."""
    result = GSOptBenchmarkResult(**_gsopt_result(payload))
    assert type(result.config) is expected
    # survives a JSON round-trip without silently dropping lane-specific fields
    restored = GSOptBenchmarkResult.model_validate_json(result.model_dump_json())
    assert type(restored.config) is expected
    assert restored.config.model_dump() == result.config.model_dump()


def test_gsopt_dmrg_config_leaves_tn_only_fields_none():
    cfg = GSOptTNRunConfig(**_GSOPT_DMRG_CONFIG)
    assert cfg.max_sweeps == 64
    assert cfg.method is None and cfg.tau is None and cfg.chi is None


def test_gsopt_lane_configs_share_only_name():
    """The lane configs are siblings, not variations on a VQE shape: `name` is
    the one field GSOpt's five RunConfig dataclasses agree on."""
    shared = set.intersection(*(
        set(m.model_fields) for m in (
            GSOptVQERunConfig, GSOptTNRunConfig,
            GSOptAFQMCRunConfig, GSOptGibbsRunConfig,
        )
    ))
    assert shared == {"name"}


def test_gsopt_to_vqa_config_rejects_non_vqe_lanes():
    """A DMRG/AFQMC/Gibbs run is not a variational run, so VQAConfig does not
    describe it — better to raise than emit a half-populated config."""
    vqe = GSOptBenchmarkResult(**_gsopt_result(_GSOPT_VQE_CONFIG))
    assert vqe.to_vqa_config()["algorithm"] == "uccsd"

    afqmc = GSOptBenchmarkResult(**_gsopt_result(_GSOPT_AFQMC_CONFIG))
    with pytest.raises(TypeError, match="GSOptVQERunConfig"):
        afqmc.to_vqa_config()
    # the lane-agnostic conversion still works
    assert afqmc.to_quantum_result().total_time_s == pytest.approx(12.0)


def test_gsopt_config_is_not_the_shared_vqe_contract():
    """bestquark_gsopt records how one GSOpt run was parameterised; the
    execution-layer VQERunConfig is a cross-implementation contract. Same
    domain, different jobs — and no longer the same name."""
    assert VQERunConfig.__module__.endswith("execution")
    assert GSOptVQERunConfig.__module__.endswith("bestquark_gsopt")
    assert not issubclass(GSOptVQERunConfig, VQERunConfig)
    assert "vqe_run_config" in ExecutionOptions.model_fields


from qpubench.schemas.mirrors.hqs_active_space_finder import (  # noqa: E402
    DEFAULT_ENTROPY_THRESHOLD,
    ASFActiveSpace,
    ASFCandidateSpace,
    ASFOrbitalEntropy,
    ASFSelectionConfig,
    ASFSelectionMode,
    ASFSelectionResult,
)
from qpubench.schemas.mirrors.hqs_qoqo import (  # noqa: E402
    QoqoCircuitSpec,
    QoqoDeviceSpec,
    QoqoDeviceTopology,
    QoqoExpectationRule,
    QoqoImperfectReadout,
    QoqoMeasurementSpec,
    QoqoMeasurementType,
    QoqoNoiseModelSpec,
    QoqoNoiseModelType,
    QoqoOperation,
    QoqoOperationCategory,
    QoqoParameter,
    QoqoPauliProductMask,
    QoqoPauliZProductInput,
    QoqoPragma,
    QoqoQuantumProgramSpec,
)
from qpubench.schemas.mirrors.hqs_qoqo_qasm import (  # noqa: E402
    DEFAULT_QUBIT_REGISTER_NAME,
    QasmDialect,
    QoqoQasmConfig,
    QoqoQasmTranslationResult,
)
from qpubench.schemas.mirrors.hqs_struqture import (  # noqa: E402
    STRUQTURE_1_TO_2_NAMES,
    DecoherenceProductSpec,
    ModeProductSpec,
    PauliProductSpec,
    SingleDecoherenceOperator,
    SingleSpinOperator,
    StruqtureAlgebra,
    StruqtureMappedHamiltonian,
    StruqtureMapping,
    StruqtureNoiseOperator,
    StruqtureNoiseTerm,
    StruqtureOpenSystem,
    StruqtureOperator,
    StruqtureSerialisationMeta,
    StruqtureTerm,
    StruqtureType,
    StruqtureValue,
)
from qpubench.schemas.mirrors.questkit_quest import (  # noqa: E402
    QuESTCalculation,
    QuESTCalculationResult,
    QuESTChannelType,
    QuESTDeployment,
    QuESTNoiseChannel,
    QuESTPauliStr,
    QuESTPauliStrSum,
    QuESTPrecision,
    QuESTQuregSpec,
    QuESTRunRecord,
)

# ---------------------------------------------------------------------------
# hqs_struqture
# ---------------------------------------------------------------------------

def test_struqture_pauli_product_round_trips_with_core_pauli_term():
    """struqture's index type and the core PauliTerm are the same thing minus
    the coefficient, so the conversion must be lossless in both directions."""
    term = PauliTerm(
        qubit_indices=(0, 2),
        pauli_ops=(PauliLabel.X, PauliLabel.Z),
        coefficient=ComplexNumber(re=0.5, im=-0.25),
    )
    product = PauliProductSpec.from_pauli_term(term)
    assert product.to_struqture_string() == "0X2Z"
    assert product.to_pauli_term(term.coefficient) == term


def test_struqture_pauli_product_drops_identity_factors():
    """struqture has no I in its single-spin basis: an unlisted qubit *is* the
    identity, so an explicit I must be dropped rather than encoded."""
    term = PauliTerm(
        qubit_indices=(0, 1, 2),
        pauli_ops=(PauliLabel.X, PauliLabel.I, PauliLabel.Z),
    )
    product = PauliProductSpec.from_pauli_term(term)
    assert product.qubit_indices == (0, 2)
    assert product.operators == (SingleSpinOperator.X, SingleSpinOperator.Z)


def test_struqture_value_rejects_both_and_neither():
    with pytest.raises(pydantic.ValidationError):
        StruqtureValue()
    with pytest.raises(pydantic.ValidationError):
        StruqtureValue(numeric=ComplexNumber(re=1.0), symbolic_re="theta")
    assert StruqtureValue.from_float(2.0).is_symbolic is False
    assert StruqtureValue(symbolic_re="theta").is_symbolic is True


def test_struqture_operator_observable_round_trip():
    obs = SparsePauliObservable(
        num_qubits=3,
        terms=[
            PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.Z,),
                      coefficient=ComplexNumber(re=-1.0)),
            PauliTerm(qubit_indices=(0, 1), pauli_ops=(PauliLabel.X, PauliLabel.X),
                      coefficient=ComplexNumber(re=0.5)),
        ],
    )
    operator = StruqtureOperator.from_sparse_pauli_observable(obs)
    assert operator.meta.type_name == StruqtureType.PAULI_HAMILTONIAN.value
    assert operator.current_number_spins == 2
    assert operator.to_sparse_pauli_observable(num_qubits=3).terms == obs.terms


def test_struqture_symbolic_operator_refuses_numeric_conversion():
    """An unbound parameter has no numeric value; converting anyway would
    silently invent one."""
    operator = StruqtureOperator(
        meta=StruqtureSerialisationMeta(type_name=StruqtureType.PAULI_HAMILTONIAN.value),
        algebra=StruqtureAlgebra.SPINS,
        terms=[
            StruqtureTerm(
                pauli_product=PauliProductSpec(
                    qubit_indices=(0,), operators=(SingleSpinOperator.Z,)
                ),
                coefficient=StruqtureValue(symbolic_re="theta"),
            )
        ],
    )
    assert operator.is_symbolic
    with pytest.raises(ValueError, match="Symbolic coefficients"):
        operator.to_sparse_pauli_observable()


def test_struqture_fermion_operator_refuses_observable_conversion():
    operator = StruqtureOperator(
        meta=StruqtureSerialisationMeta(type_name=StruqtureType.FERMION_HAMILTONIAN.value),
        algebra=StruqtureAlgebra.FERMIONS,
        terms=[
            StruqtureTerm(
                mode_product=ModeProductSpec(creators=(0,), annihilators=(0,)),
                coefficient=StruqtureValue.from_float(1.0),
            )
        ],
    )
    with pytest.raises(ValueError, match="jordan_wigner"):
        operator.to_sparse_pauli_observable()


def test_struqture_hermitian_mode_product_requires_canonical_ordering():
    """Each h.c. pair needs exactly one representative, or the conjugate term
    is counted twice."""
    ModeProductSpec(creators=(0,), annihilators=(2,), hermitian=True)
    with pytest.raises(pydantic.ValidationError):
        ModeProductSpec(creators=(2,), annihilators=(0,), hermitian=True)
    # non-Hermitian products carry no such constraint
    ModeProductSpec(creators=(2,), annihilators=(0,))


def test_struqture_noise_term_needs_both_sides_of_the_pair():
    """A Lindblad index is (L_i, L_j); a missing side is not the identity."""
    left = DecoherenceProductSpec(
        qubit_indices=(0,), operators=(SingleDecoherenceOperator.Z,)
    )
    with pytest.raises(pydantic.ValidationError):
        StruqtureNoiseTerm(left_decoherence=left, rate=StruqtureValue.from_float(1.0))
    term = StruqtureNoiseTerm(
        left_decoherence=left,
        right_decoherence=left,
        rate=StruqtureValue.from_float(1.0),
    )
    assert term.is_diagonal


def test_struqture_noise_operator_flags_off_diagonal_rates():
    """Off-diagonal M_ij has no representation in a flat channel list, so a
    consumer needs to be able to see it is there before dropping it."""
    z = DecoherenceProductSpec(
        qubit_indices=(0,), operators=(SingleDecoherenceOperator.Z,)
    )
    x = DecoherenceProductSpec(
        qubit_indices=(0,), operators=(SingleDecoherenceOperator.X,)
    )
    meta = StruqtureSerialisationMeta(
        type_name=StruqtureType.PAULI_LINDBLAD_NOISE_OPERATOR.value
    )
    diagonal_only = StruqtureNoiseOperator(
        meta=meta,
        algebra=StruqtureAlgebra.SPINS,
        terms=[
            StruqtureNoiseTerm(
                left_decoherence=z, right_decoherence=z,
                rate=StruqtureValue.from_float(0.1),
            )
        ],
    )
    assert not diagonal_only.has_off_diagonal_rates
    mixed = diagonal_only.model_copy(
        update={
            "terms": [
                *diagonal_only.terms,
                StruqtureNoiseTerm(
                    left_decoherence=z, right_decoherence=x,
                    rate=StruqtureValue.from_float(0.01),
                ),
            ]
        }
    )
    assert mixed.has_off_diagonal_rates


def test_struqture_serialisation_meta_version_rule():
    """struqture accepts a payload when the reader's major matches the
    declared minimum and its minor is at least as new."""
    meta = StruqtureSerialisationMeta(
        type_name=StruqtureType.PAULI_HAMILTONIAN.value,
        min_version=(2, 1, 0),
        version="2.3.0",
    )
    assert meta.can_be_read_by((2, 1, 0))
    assert meta.can_be_read_by((2, 5, 0))
    assert not meta.can_be_read_by((2, 0, 9))
    assert not meta.can_be_read_by((1, 9, 0))


def test_struqture_mapped_hamiltonian_records_mapping_provenance():
    """The point of the type: a qubit Hamiltonian with the fermionic operator
    and mapping that produced it, so VQAConfig.mapper is checkable."""
    source = StruqtureOperator(
        meta=StruqtureSerialisationMeta(type_name=StruqtureType.FERMION_HAMILTONIAN.value),
        algebra=StruqtureAlgebra.FERMIONS,
        terms=[
            StruqtureTerm(
                mode_product=ModeProductSpec(creators=(0,), annihilators=(0,)),
                coefficient=StruqtureValue.from_float(1.0),
            )
        ],
    )
    mapped = StruqtureOperator.from_sparse_pauli_observable(
        SparsePauliObservable(
            num_qubits=1,
            terms=[PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.Z,))],
        )
    )
    record = StruqtureMappedHamiltonian(source=source, mapped=mapped)
    assert record.mapping is StruqtureMapping.JORDAN_WIGNER

    with pytest.raises(pydantic.ValidationError):
        StruqtureMappedHamiltonian(source=mapped, mapped=mapped)   # spin → spin
    with pytest.raises(pydantic.ValidationError):
        StruqtureMappedHamiltonian(source=source, mapped=source)   # target not spin


def test_struqture_open_system_halves_must_share_an_algebra():
    spin_meta = StruqtureSerialisationMeta(
        type_name=StruqtureType.PAULI_HAMILTONIAN.value
    )
    system = StruqtureOperator(meta=spin_meta, algebra=StruqtureAlgebra.SPINS)
    noise = StruqtureNoiseOperator(
        meta=StruqtureSerialisationMeta(
            type_name=StruqtureType.BOSON_LINDBLAD_NOISE_OPERATOR.value
        ),
        algebra=StruqtureAlgebra.BOSONS,
    )
    with pytest.raises(pydantic.ValidationError):
        StruqtureOpenSystem(meta=spin_meta, system=system, noise=noise)


def test_struqture_1_to_2_rename_map_is_complete_and_targets_real_types():
    """The 1.x names must all map onto values StruqtureType actually has."""
    known = {t.value for t in StruqtureType}
    assert set(STRUQTURE_1_TO_2_NAMES.values()) <= known
    assert STRUQTURE_1_TO_2_NAMES["SpinSystem"] == "PauliOperator"


# ---------------------------------------------------------------------------
# hqs_qoqo
# ---------------------------------------------------------------------------

def _qoqo_rotate(angle: str | float, qubit: int = 0) -> QoqoOperation:
    param = (
        QoqoParameter(expression=angle) if isinstance(angle, str)
        else QoqoParameter(value=angle)
    )
    return QoqoOperation(name="RotateX", qubits=[qubit], parameters={"theta": param})


def test_qoqo_circuit_derives_width_from_operations():
    """qoqo circuits declare no width — a Circuit is just a list of
    operations, and its size is whatever they imply."""
    circuit = QoqoCircuitSpec(
        operations=[
            _qoqo_rotate(0.5, qubit=0),
            QoqoOperation(name="CNOT", qubits=[0, 3]),
        ],
        definitions={"ro": 4},
    )
    assert circuit.num_qubits == 4
    assert circuit.gate_counts() == {"RotateX": 1, "CNOT": 1}
    spec = circuit.to_circuit_spec()
    assert spec.num_qubits == 4
    assert spec.num_classical_bits == 4
    assert spec.serialized is None   # translation is qoqo_qasm's job, and lossy


def test_qoqo_parameter_is_bound_or_free_never_both():
    with pytest.raises(pydantic.ValidationError):
        QoqoParameter()
    with pytest.raises(pydantic.ValidationError):
        QoqoParameter(value=1.0, expression="theta")


def test_qoqo_circuit_reports_free_parameters_and_pragmas():
    circuit = QoqoCircuitSpec(
        operations=[
            _qoqo_rotate("theta"),
            _qoqo_rotate("2 * theta", qubit=1),
            QoqoOperation(
                name=QoqoPragma.DAMPING.value,
                category=QoqoOperationCategory.PRAGMA,
                qubits=[0],
            ),
        ]
    )
    assert circuit.is_parametric
    assert circuit.free_parameters == ["theta", "2 * theta"]
    assert circuit.pragmas == ["PragmaDamping"]
    assert circuit.gate_counts() == {"RotateX": 2}   # PRAGMAs are not gates


def test_qoqo_expectation_rule_is_linear_or_symbolic():
    with pytest.raises(pydantic.ValidationError):
        QoqoExpectationRule(name="energy")
    with pytest.raises(pydantic.ValidationError):
        QoqoExpectationRule(name="energy", linear={0: 1.0}, symbolic="pauli_product_0")


def test_qoqo_pauli_z_product_input_checks_rule_indices():
    """A combination rule referencing a product that was never measured is a
    silently wrong energy, not a missing one."""
    mask = QoqoPauliProductMask(readout="ro", index=0, qubit_mask=[0, 1])
    QoqoPauliZProductInput(
        number_qubits=2,
        pauli_products=[mask],
        expectation_rules=[QoqoExpectationRule(name="energy", linear={0: -1.0})],
    )
    with pytest.raises(pydantic.ValidationError):
        QoqoPauliZProductInput(
            number_qubits=2,
            pauli_products=[mask],
            expectation_rules=[QoqoExpectationRule(name="energy", linear={0: -1.0, 7: 1.0})],
        )


def test_qoqo_flipped_measurement_doubles_the_circuit_count():
    """Flipped measurement cancels readout asymmetry by running each basis
    twice — a real cost that belongs in the comparison."""
    products = [
        QoqoPauliProductMask(readout="ro_z", index=0, qubit_mask=[0]),
        QoqoPauliProductMask(readout="ro_x", index=1, qubit_mask=[0]),
    ]
    plain = QoqoPauliZProductInput(number_qubits=1, pauli_products=products)
    flipped = QoqoPauliZProductInput(
        number_qubits=1, pauli_products=products, use_flipped_measurement=True
    )
    assert plain.num_circuits_per_evaluation == 2
    assert flipped.num_circuits_per_evaluation == 4


def test_qoqo_measurement_spec_requires_the_matching_input():
    with pytest.raises(pydantic.ValidationError):
        QoqoMeasurementSpec(measurement_type=QoqoMeasurementType.PAULI_Z_PRODUCT)
    with pytest.raises(pydantic.ValidationError):
        QoqoMeasurementSpec(measurement_type=QoqoMeasurementType.CHEATED)
    # ClassicalRegister returns raw registers and takes no input at all
    QoqoMeasurementSpec(measurement_type=QoqoMeasurementType.CLASSICAL_REGISTER)
    with pytest.raises(pydantic.ValidationError):
        QoqoMeasurementSpec(
            measurement_type=QoqoMeasurementType.CLASSICAL_REGISTER,
            pauli_input=QoqoPauliZProductInput(number_qubits=1),
        )


def test_qoqo_device_projects_lindblad_rates_onto_backend_spec():
    """T1 = 1/M00 and T2 = 1/M22; the off-diagonal entries have no
    BackendSpec representation and are dropped."""
    device = QoqoDeviceSpec(
        name="lattice",
        topology=QoqoDeviceTopology.SQUARE_LATTICE,
        number_qubits=4,
        rows=2,
        columns=2,
        single_qubit_gates=["RotateX"],
        two_qubit_gates=["CNOT"],
        two_qubit_edges=[(0, 1), (1, 3)],
        single_qubit_gate_times={"RotateX": {0: 2.0e-8}},
        two_qubit_gate_times={"CNOT": {"0-1": 3.0e-7}},
        decoherence_rates={
            0: [[1.0e4, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 5.0e3]],
        },
    )
    assert device.damping_rate(0) == 1.0e4
    assert device.dephasing_rate(0) == 5.0e3
    backend = device.to_backend_spec()
    assert backend.num_qubits == 4
    assert backend.coupling_map == [(0, 1), (1, 3)]
    assert backend.qubit_t1(0) == pytest.approx(1.0e-4)
    assert backend.gate_error("CNOT", (0, 1)) is None   # qoqo has no error rates
    cnot = next(g for g in backend.gate_characteristics if g.gate_name == "CNOT")
    assert cnot.duration_s == pytest.approx(3.0e-7)


def test_qoqo_square_lattice_dimensions_must_match_qubit_count():
    with pytest.raises(pydantic.ValidationError):
        QoqoDeviceSpec(
            name="bad", topology=QoqoDeviceTopology.SQUARE_LATTICE,
            number_qubits=5, rows=2, columns=2,
        )
    with pytest.raises(pydantic.ValidationError):
        QoqoDeviceSpec(
            name="bad", topology=QoqoDeviceTopology.SQUARE_LATTICE, number_qubits=4,
        )


def test_qoqo_decoherence_matrix_must_be_three_by_three():
    """The rate matrix is indexed over (sigma+, sigma-, sigma^z)."""
    with pytest.raises(pydantic.ValidationError):
        QoqoDeviceSpec(
            name="d", topology=QoqoDeviceTopology.ALL_TO_ALL, number_qubits=1,
            decoherence_rates={0: [[1.0, 0.0], [0.0, 1.0]]},
        )


def test_qoqo_noise_model_requires_its_own_payload():
    with pytest.raises(pydantic.ValidationError):
        QoqoNoiseModelSpec(model_type=QoqoNoiseModelType.IMPERFECT_READOUT)
    with pytest.raises(pydantic.ValidationError):
        QoqoNoiseModelSpec(model_type=QoqoNoiseModelType.SINGLE_QUBIT_OVERROTATION)
    model = QoqoNoiseModelSpec(
        model_type=QoqoNoiseModelType.IMPERFECT_READOUT,
        readout=QoqoImperfectReadout.uniform(3, 0.02, 0.05),
    )
    assert model.readout is not None
    assert model.readout.prob_detect_1_as_0 == {0: 0.05, 1: 0.05, 2: 0.05}


def test_qoqo_noise_model_dumps_a_struqture_noise_operator():
    """The mirror stores the Lindblad operator as a plain dict so it does not
    import another mirror; it must still round-trip through that mirror."""
    z = DecoherenceProductSpec(
        qubit_indices=(0,), operators=(SingleDecoherenceOperator.Z,)
    )
    noise = StruqtureNoiseOperator(
        meta=StruqtureSerialisationMeta(
            type_name=StruqtureType.PLUS_MINUS_LINDBLAD_NOISE_OPERATOR.value
        ),
        algebra=StruqtureAlgebra.SPINS,
        terms=[
            StruqtureNoiseTerm(
                left_decoherence=z, right_decoherence=z,
                rate=StruqtureValue.from_float(0.1),
            )
        ],
    )
    model = QoqoNoiseModelSpec(
        model_type=QoqoNoiseModelType.CONTINUOUS_DECOHERENCE,
        lindblad_noise=noise,
    )
    assert isinstance(model.lindblad_noise, dict)
    assert StruqtureNoiseOperator.model_validate(model.lindblad_noise) == noise


def test_qoqo_quantum_program_parameter_order_is_the_contract():
    program = QoqoQuantumProgramSpec(
        measurement=QoqoMeasurementSpec(
            measurement_type=QoqoMeasurementType.PAULI_Z_PRODUCT,
            pauli_input=QoqoPauliZProductInput(number_qubits=2),
        ),
        input_parameter_names=["theta", "phi"],
    )
    assert program.num_free_parameters == 2
    assert program.input_parameter_names[0] == "theta"


# ---------------------------------------------------------------------------
# hqs_qoqo_qasm
# ---------------------------------------------------------------------------

def test_qasm_dialect_maps_onto_core_circuit_format():
    """Two records can both say format=QASM3 while only one is portable."""
    assert QasmDialect.V3_BRAKET.circuit_format is CircuitFormat.QASM3
    assert QasmDialect.V2_QULACS.circuit_format is CircuitFormat.QASM2
    assert QasmDialect.V3_VANILLA.is_portable
    assert not QasmDialect.V3_BRAKET.is_portable
    assert not QasmDialect.V2_QULACS.is_portable   # omits gate definitions


def test_qasm_dialect_values_are_the_strings_upstream_parses():
    """Stored configs are handed back to qoqo_qasm verbatim."""
    assert QoqoQasmConfig(dialect=QasmDialect.V3_ROQOQO).version_string == "3.0Roqoqo"
    assert QoqoQasmConfig().qubit_register_name == DEFAULT_QUBIT_REGISTER_NAME


def test_qasm_translation_success_and_faithfulness_are_different():
    """A translation that dropped noise pragmas succeeded, and describes a
    different experiment."""
    vanilla = QoqoQasmConfig(dialect=QasmDialect.V3_VANILLA)
    dropped = QoqoQasmTranslationResult(
        config=vanilla, qasm="OPENQASM 3.0;", dropped_pragmas=["PragmaDamping"],
    )
    assert dropped.succeeded
    assert not dropped.is_faithful

    refused = QoqoQasmTranslationResult(config=vanilla, untranslated_ops=["PragmaLoop"])
    assert not refused.succeeded


def test_qasm_pragma_carrying_dialect_cannot_report_dropped_pragmas():
    with pytest.raises(pydantic.ValidationError):
        QoqoQasmTranslationResult(
            config=QoqoQasmConfig(dialect=QasmDialect.V3_BRAKET),
            qasm="OPENQASM 3.0;",
            dropped_pragmas=["PragmaDamping"],
        )


# ---------------------------------------------------------------------------
# hqs_active_space_finder
# ---------------------------------------------------------------------------

def test_asf_active_space_derives_size_and_qubit_count():
    space = ASFActiveSpace(nel=6, mo_list=[3, 4, 5, 6, 7, 8], mo_coeff_ref="chk:mp2no")
    assert space.norb == 6
    assert space.cas_label == "CAS(6,6)"
    assert space.num_qubits_jordan_wigner == 12


def test_asf_active_space_validates_against_its_mo_basis():
    """Indices are meaningless without the orbitals they index."""
    with pytest.raises(pydantic.ValidationError):
        ASFActiveSpace(nel=2, mo_list=[0, 5], mo_coeff_shape=(10, 4))
    with pytest.raises(pydantic.ValidationError):
        ASFActiveSpace(nel=2, mo_list=[0, 0])          # duplicate index
    with pytest.raises(pydantic.ValidationError):
        ASFActiveSpace(nel=5, mo_list=[0, 1])          # 5 electrons, 4 spin-orbitals
    with pytest.raises(pydantic.ValidationError):
        ASFActiveSpace(nel=2, mo_list=[0], mo_coeff_shape=(4, 10))   # more MOs than AOs


def test_asf_active_space_index_remapping_round_trips():
    space = ASFActiveSpace(nel=4, mo_list=[2, 5, 9])
    assert space.to_active_indices([5, 9]) == [1, 2]
    assert space.from_active_indices([1, 2]) == [5, 9]


def test_asf_to_gsopt_active_space_drops_the_orbital_link():
    """The conversion is lossy in the one way that matters, and says so."""
    space = ASFActiveSpace(nel=4, mo_list=[4, 5], mo_coeff_ref="chk:mp2no")
    converted = space.to_gsopt_active_space(occupied_indices=[0, 1, 2, 3])
    assert converted.active_electrons == 4
    assert converted.active_orbitals == 2
    assert converted.active_indices == [4, 5]
    assert not hasattr(converted, "mo_coeff_ref")


def test_asf_sized_selection_requires_a_requested_size():
    with pytest.raises(pydantic.ValidationError):
        ASFSelectionConfig(mode=ASFSelectionMode.SIZED)
    ASFSelectionConfig(mode=ASFSelectionMode.SIZED, requested_size=4)
    ASFSelectionConfig(mode=ASFSelectionMode.SIZED, requested_size=(6, 6))


def test_asf_selection_result_must_match_its_mode():
    space = ASFActiveSpace(nel=2, mo_list=[0, 1])
    with pytest.raises(pydantic.ValidationError):
        ASFSelectionResult(config=ASFSelectionConfig())          # entropy, no space
    with pytest.raises(pydantic.ValidationError):
        ASFSelectionResult(                                       # many, no candidates
            config=ASFSelectionConfig(mode=ASFSelectionMode.MANY),
            active_space=space,
        )
    result = ASFSelectionResult(
        config=ASFSelectionConfig(mode=ASFSelectionMode.MANY),
        candidates=[ASFCandidateSpace(active_space=space, rank=0)],
    )
    assert result.selected_orbitals == []


def test_asf_default_entropy_threshold_matches_upstream():
    """-0.1 * ln(0.25); a natural-log entropy scale, not a tuned constant."""
    assert DEFAULT_ENTROPY_THRESHOLD == pytest.approx(-0.1 * math.log(0.25))
    assert ASFSelectionConfig().entropy_threshold == DEFAULT_ENTROPY_THRESHOLD


def test_asf_result_reports_the_entropy_spectrum():
    result = ASFSelectionResult(
        config=ASFSelectionConfig(),
        active_space=ASFActiveSpace(nel=2, mo_list=[4]),
        entropies=[
            ASFOrbitalEntropy(mo_index=3, entropy=0.01),
            ASFOrbitalEntropy(mo_index=4, entropy=0.62, selected=True),
        ],
    )
    assert result.max_entropy == pytest.approx(0.62)
    assert result.selected_orbitals == [4]


# ---------------------------------------------------------------------------
# questkit_quest
# ---------------------------------------------------------------------------

def test_quest_density_matrix_costs_the_square_of_a_statevector():
    statevec = QuESTQuregSpec(num_qubits=10)
    density = QuESTQuregSpec(num_qubits=10, is_density_matrix=True)
    assert statevec.num_amplitudes == 2 ** 10
    assert density.num_amplitudes == 4 ** 10
    assert statevec.bytes_per_amplitude == 16          # double precision qcomp
    assert density.state_bytes == statevec.state_bytes ** 2 // 16


def test_quest_single_precision_halves_the_amplitude_width():
    single = QuESTQuregSpec(num_qubits=8, precision=QuESTPrecision.SINGLE)
    assert single.bytes_per_amplitude == 8
    assert single.precision.epsilon > QuESTPrecision.DOUBLE.epsilon


def test_quest_rejects_quad_precision_on_gpu():
    """QuEST refuses to build FLOAT_PRECISION=4 against CUDA."""
    with pytest.raises(pydantic.ValidationError):
        QuESTQuregSpec(
            num_qubits=4,
            precision=QuESTPrecision.QUAD,
            deployment=QuESTDeployment(gpu_accelerated=True),
        )


def test_quest_deployment_flags_and_node_count_must_agree():
    with pytest.raises(pydantic.ValidationError):
        QuESTDeployment(distributed=True)                    # num_nodes still 1
    with pytest.raises(pydantic.ValidationError):
        QuESTDeployment(num_nodes=4)                         # not marked distributed
    with pytest.raises(pydantic.ValidationError):
        QuESTDeployment(distributed=True, num_nodes=4, rank=4)
    dep = QuESTDeployment(
        multithreaded=True, gpu_accelerated=True, distributed=True, num_nodes=4
    )
    assert dep.summary == "omp+gpu+mpi(4)"


def test_quest_distributed_state_splits_across_nodes():
    spec = QuESTQuregSpec(
        num_qubits=20,
        deployment=QuESTDeployment(distributed=True, num_nodes=4),
    )
    assert spec.bytes_per_node == spec.state_bytes // 4


def test_quest_backend_spec_carries_deployment_and_precision():
    spec = QuESTQuregSpec(
        num_qubits=12,
        is_density_matrix=True,
        precision=QuESTPrecision.SINGLE,
        deployment=QuESTDeployment(gpu_accelerated=True),
    )
    backend = spec.to_backend_spec()
    assert backend.provider == "quest"
    assert backend.simulator
    assert backend.auth["precision"] == "1"
    assert backend.auth["deployment"] == "gpu"


def test_backend_spec_quest_factory():
    backend = BackendSpec.quest(16, gpu=True, distributed_nodes=8)
    assert backend.provider == "quest"
    assert backend.name == "quest_statevec_gpu_mpi8"
    assert backend.auth["num_nodes"] == "8"


def test_quest_pauli_str_sum_round_trips_with_core_observable():
    obs = SparsePauliObservable(
        num_qubits=3,
        terms=[
            PauliTerm(qubit_indices=(0, 1), pauli_ops=(PauliLabel.X, PauliLabel.Y),
                      coefficient=ComplexNumber(re=0.75)),
            PauliTerm(qubit_indices=(2,), pauli_ops=(PauliLabel.Z,),
                      coefficient=ComplexNumber(re=-1.5)),
        ],
    )
    quest_sum = QuESTPauliStrSum.from_sparse_pauli_observable(obs)
    assert quest_sum.num_terms == 2
    assert quest_sum.to_sparse_pauli_observable(num_qubits=3).terms == obs.terms


def test_quest_pauli_base4_encoding_is_sequential_unlike_qrack():
    """QuEST packs I=0,X=1,Y=2,Z=3; Qrack/Q# uses I=0,X=1,Z=2,Y=3. Mixing the
    two silently swaps Y and Z."""
    y_on_zero = QuESTPauliStr(qubit_indices=(0,), pauli_ops=(PauliLabel.Y,))
    z_on_zero = QuESTPauliStr(qubit_indices=(0,), pauli_ops=(PauliLabel.Z,))
    assert y_on_zero.to_base4_masks() == (2, 0)
    assert z_on_zero.to_base4_masks() == (3, 0)
    assert PauliLabel.Y.to_qrack_int() == 3
    assert PauliLabel.Z.to_qrack_int() == 2


def test_quest_pauli_base4_splits_high_qubits_into_the_second_word():
    string = QuESTPauliStr(
        qubit_indices=(1, 33), pauli_ops=(PauliLabel.X, PauliLabel.Z)
    )
    low, high = string.to_base4_masks()
    assert low == 1 << 2
    assert high == 3 << 2


def test_quest_noise_requires_a_density_matrix():
    """QuEST's mix* channels are undefined on a state vector."""
    channel = QuESTNoiseChannel(
        channel=QuESTChannelType.DAMPING, targets=[0], probability=0.01, position=4
    )
    with pytest.raises(pydantic.ValidationError):
        QuESTRunRecord(qureg=QuESTQuregSpec(num_qubits=4), noise_channels=[channel])
    record = QuESTRunRecord(
        qureg=QuESTQuregSpec(num_qubits=4, is_density_matrix=True),
        noise_channels=[channel],
    )
    assert record.noise_channels[0].position == 4


def test_quest_named_channels_require_their_own_arguments():
    with pytest.raises(pydantic.ValidationError):
        QuESTNoiseChannel(channel=QuESTChannelType.DEPOLARISING, targets=[0])
    with pytest.raises(pydantic.ValidationError):
        QuESTNoiseChannel(channel=QuESTChannelType.PAULIS, targets=[0], prob_x=0.01)
    with pytest.raises(pydantic.ValidationError):
        QuESTNoiseChannel(channel=QuESTChannelType.KRAUS_MAP, targets=[0])


def test_quest_run_record_looks_up_calculations_by_call():
    """calcFidelity and calcPurity are both 'a number near 1'."""
    record = QuESTRunRecord(
        qureg=QuESTQuregSpec(num_qubits=6),
        calculations=[
            QuESTCalculationResult(
                calculation=QuESTCalculation.EXPEC_PAULI_STR_SUM,
                value=ComplexNumber(re=-1.137),
            ),
            QuESTCalculationResult(
                calculation=QuESTCalculation.PURITY, value=ComplexNumber(re=1.0),
            ),
        ],
    )
    energy = record.result_for(QuESTCalculation.EXPEC_PAULI_STR_SUM)
    assert energy is not None and energy.real_value == pytest.approx(-1.137)
    assert record.result_for(QuESTCalculation.FIDELITY) is None
