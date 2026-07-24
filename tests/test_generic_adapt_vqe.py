"""Tests for integrations/generic_adapt_vqe/ and the two thin adapters built
on it (ibm_qiskit_adapt_vqe, microsoft_qdk_adapt_vqe).

Requires: pip install 'qpubench[adapt_vqe]'  (scipy + numpy — not quantum
SDKs; scipy runs the classical optimizer, numpy independently verifies the
Jordan-Wigner and circuit-synthesis math via dense-matrix construction).
Skipped automatically if unavailable, consistent with test_schemas.py
staying zero-SDK.

integrations/ is not an installed package (by design — see
integrations/*/README.md, "copy into your project"); this test file adds
the repo root to sys.path so integrations.generic_adapt_vqe and friends are
importable as namespace packages, exactly like examples/qforte_vqe_benchmark.py.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from qpubench import BenchmarkRunner, ExecutionOptions, StubGateAdapter
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import AdaptVQERunConfig, AlgorithmSpec
from qpubench.schemas.observable import PauliTerm, SparsePauliObservable
from qpubench.schemas.primitives import AlgorithmFamily, CircuitFormat, ComplexNumber, PauliLabel

from integrations.generic_adapt_vqe.pool import (
    double_excitation_observable,
    generate_singles_doubles_pool,
    single_excitation_observable,
)
from integrations.generic_adapt_vqe.circuit_synthesis import pauli_exponential_qasm3_lines
from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine
from integrations.ibm_qiskit_adapt_vqe.adapter import IBMQiskitAdaptVQEAdapter
from integrations.microsoft_qdk_adapt_vqe.adapter import MicrosoftQDKAdaptVQEAdapter


# ---------------------------------------------------------------------------
# Ground-truth Jordan-Wigner matrix construction (independent of pool.py)
# ---------------------------------------------------------------------------

_I2 = np.eye(2, dtype=complex)
_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
_Z = np.array([[1, 0], [0, -1]], dtype=complex)
_SIGMA_PLUS = np.array([[0, 0], [1, 0]], dtype=complex)


def _kron_n(ops):
    out = ops[0]
    for o in ops[1:]:
        out = np.kron(out, o)
    return out


def _jw_creation(idx: int, n: int):
    ops = [(_Z if k < idx else _SIGMA_PLUS if k == idx else _I2) for k in range(n)]
    return _kron_n(ops)


def _pauli_term_matrix(term: PauliTerm, n: int):
    ops = [_I2] * n
    label_map = {"X": _X, "Y": _Y, "Z": _Z}
    for qi, label in zip(term.qubit_indices, term.pauli_ops):
        ops[qi] = label_map[label.value]
    return _kron_n(ops)


def _observable_matrix(obs: SparsePauliObservable, n: int):
    mat = np.zeros((2**n, 2**n), dtype=complex)
    for term in obs.terms:
        c = term.coefficient.re + 1j * term.coefficient.im
        mat += c * _pauli_term_matrix(term, n)
    return mat


# ---------------------------------------------------------------------------
# pool.py — Jordan-Wigner correctness (independently verified, not assumed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("p,q,n", [(1, 0, 2), (2, 0, 3), (3, 1, 4)])
def test_single_excitation_matches_dense_jw(p, q, n):
    ap, aq = _jw_creation(p, n), _jw_creation(q, n)
    ref = ap @ aq.conj().T - aq @ ap.conj().T
    mine = _observable_matrix(single_excitation_observable(p, q, n), n)
    assert np.max(np.abs(ref - mine)) < 1e-9


@pytest.mark.parametrize(
    "p,q,r,s,n",
    [
        (3, 2, 1, 0, 4),   # adjacent quadruple
        (5, 3, 2, 0, 6),   # gaps in both pairs
        (5, 2, 1, 0, 6),   # spread virtual pair, adjacent occupied pair
        (7, 6, 2, 0, 8),   # adjacent virtual pair, spread occupied pair
    ],
)
def test_double_excitation_matches_dense_jw(p, q, r, s, n):
    ap, aq, ar, as_ = (_jw_creation(i, n) for i in (p, q, r, s))
    fwd = ap @ aq @ ar.conj().T @ as_.conj().T
    ref = fwd - fwd.conj().T
    mine = _observable_matrix(double_excitation_observable(p, q, r, s, n), n)
    assert np.max(np.abs(ref - mine)) < 1e-9


def test_double_excitation_rejects_interleaved_indices():
    with pytest.raises(ValueError, match="non-interleaved|virtual pair"):
        double_excitation_observable(4, 1, 3, 0, 5)  # q=1 < r=3: interleaved


def test_generate_singles_doubles_pool_size():
    # num_qubits=6, num_electrons=2 -> occ={0,1}, virt={2,3,4,5}
    # singles: 2 occ x 4 virt = 8; doubles: C(2,2) x C(4,2) = 1 x 6 = 6
    pool = generate_singles_doubles_pool(num_qubits=6, num_electrons=2)
    singles = [p for p in pool if p.label.startswith("single_")]
    doubles = [p for p in pool if p.label.startswith("double_")]
    assert len(singles) == 8
    assert len(doubles) == 6
    for op in pool:
        assert op.observable.num_qubits == 6
        # anti-Hermitian generator -> purely imaginary Pauli coefficients
        assert all(t.coefficient.re == 0.0 for t in op.observable.terms)


# ---------------------------------------------------------------------------
# circuit_synthesis.py — exp(-i*angle*P) matches scipy.linalg.expm
# ---------------------------------------------------------------------------

def _rx(theta):
    return np.array([
        [np.cos(theta / 2), -1j * np.sin(theta / 2)],
        [-1j * np.sin(theta / 2), np.cos(theta / 2)],
    ], dtype=complex)


def _rz(theta):
    return np.array([[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]], dtype=complex)


def _h_matrix():
    return (1 / np.sqrt(2)) * np.array([[1, 1], [1, -1]], dtype=complex)


def _cnot_matrix(control, target, n):
    dim = 2**n
    mat = np.zeros((dim, dim), dtype=complex)
    for basis in range(dim):
        bits = [(basis >> (n - 1 - k)) & 1 for k in range(n)]
        if bits[control] == 1:
            bits[target] ^= 1
        new_basis = 0
        for b in bits:
            new_basis = (new_basis << 1) | b
        mat[new_basis, basis] = 1.0
    return mat


def _qasm3_lines_to_unitary(lines: list[str], n: int):
    """Minimal QASM3 line interpreter for h/rx/rz/cx — test-only, not a real parser."""
    dim = 2**n
    U = np.eye(dim, dtype=complex)
    H = _h_matrix()

    def apply_1q(gate, qubit):
        ops = [_I2] * n
        ops[qubit] = gate
        return _kron_n(ops)

    for line in lines:
        line = line.strip().rstrip(";")
        if line.startswith("h "):
            qi = int(line.split("[")[1].split("]")[0])
            U = apply_1q(H, qi) @ U
        elif line.startswith("rx("):
            angle = float(line[3:].split(")")[0])
            qi = int(line.split("[")[1].split("]")[0])
            U = apply_1q(_rx(angle), qi) @ U
        elif line.startswith("rz("):
            angle = float(line[3:].split(")")[0])
            qi = int(line.split("[")[1].split("]")[0])
            U = apply_1q(_rz(angle), qi) @ U
        elif line.startswith("cx "):
            parts = line[3:].split(",")
            a = int(parts[0].split("[")[1].split("]")[0])
            b = int(parts[1].split("[")[1].split("]")[0])
            U = _cnot_matrix(a, b, n) @ U
    return U


@pytest.mark.parametrize(
    "qubit_indices,labels,angle,n",
    [
        ((0, 1), (PauliLabel.X, PauliLabel.Y), 0.37, 2),
        ((0, 2), (PauliLabel.X, PauliLabel.Y), 0.37, 3),
        ((1, 3, 5), (PauliLabel.X, PauliLabel.Z, PauliLabel.Y), 0.21, 6),
    ],
)
def test_pauli_exponential_matches_expm(qubit_indices, labels, angle, n):
    from scipy.linalg import expm

    label_map = {"X": _X, "Y": _Y, "Z": _Z}
    ops = [_I2] * n
    for qi, lab in zip(qubit_indices, labels):
        ops[qi] = label_map[lab.value]
    P = _kron_n(ops)
    target = expm(-1j * angle * P)

    lines = pauli_exponential_qasm3_lines(qubit_indices, labels, angle)
    mine = _qasm3_lines_to_unitary(lines, n)
    assert np.max(np.abs(target - mine)) < 1e-9


# ---------------------------------------------------------------------------
# engine.py — end-to-end control flow (StubGateAdapter, no vendor SDK)
# ---------------------------------------------------------------------------

def _toy_hamiltonian() -> SparsePauliObservable:
    return SparsePauliObservable(num_qubits=4, terms=[
        PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.Z,), coefficient=ComplexNumber(re=1.0)),
        PauliTerm(qubit_indices=(1,), pauli_ops=(PauliLabel.Z,), coefficient=ComplexNumber(re=1.0)),
        PauliTerm(qubit_indices=(0, 1), pauli_ops=(PauliLabel.X, PauliLabel.X),
                  coefficient=ComplexNumber(re=0.5)),
    ])


def test_engine_runs_to_completion():
    engine = GenericAdaptVQEEngine(
        hamiltonian=_toy_hamiltonian(),
        num_qubits=4,
        num_electrons=2,
        energy_backend=StubGateAdapter(seed=42),
        config=AdaptVQERunConfig(max_macro_iterations=2, max_micro_iterations=10),
    )
    assert len(engine.pool) == 5  # 2x2 singles + 1x1 doubles
    result, vqa, vqa_result = engine.run()
    assert result.status.value == "succeeded"
    assert result.expectation_values
    assert vqa.algorithm == "ADAPTVQE"
    assert vqa_result.num_parameters == len(result.adapt_history or [])


def test_engine_circuit_starts_with_hf_reference():
    engine = GenericAdaptVQEEngine(
        hamiltonian=_toy_hamiltonian(), num_qubits=4, num_electrons=2,
        energy_backend=StubGateAdapter(seed=0),
    )
    circuit = engine.circuit_spec(selected=[], amplitudes=[])
    assert circuit.format == CircuitFormat.QASM3
    assert "x q[0];" in circuit.serialized
    assert "x q[1];" in circuit.serialized
    assert "x q[2];" not in circuit.serialized  # only occupied qubits get X


# ---------------------------------------------------------------------------
# Adapters — same AlgorithmFamily.ADAPT_VQE, same AdaptVQERunConfig, two packages
# ---------------------------------------------------------------------------

def _molecule_problem() -> CircuitSpec:
    return CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized=json.dumps({
            "num_qubits": 4, "num_electrons": 2,
            "hamiltonian": _toy_hamiltonian().model_dump(),
        }),
    )


@pytest.mark.parametrize("adapter_cls", [IBMQiskitAdaptVQEAdapter, MicrosoftQDKAdaptVQEAdapter])
def test_adapter_runs_via_benchmark_runner(adapter_cls):
    runner = BenchmarkRunner()
    runner.register(adapter_cls(energy_backend=StubGateAdapter(seed=7)), name="adapter")
    opts = ExecutionOptions(
        algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
        adapt_vqe_run_config=AdaptVQERunConfig(max_macro_iterations=1, max_micro_iterations=5),
    )
    record = runner.run(_molecule_problem(), "adapter", opts)
    assert record.result.status.value == "succeeded"
    assert record.vqa is not None
    assert record.vqa.algorithm == "ADAPTVQE"


def test_same_config_switches_implementation_between_adapters():
    """The actual deliverable: one AdaptVQERunConfig, two interchangeable adapters."""
    runner = BenchmarkRunner()
    runner.register(
        IBMQiskitAdaptVQEAdapter(energy_backend=StubGateAdapter(seed=1)),
        name="ibm_qiskit_adapt_vqe",
    )
    runner.register(
        MicrosoftQDKAdaptVQEAdapter(energy_backend=StubGateAdapter(seed=1)),
        name="microsoft_qdk_adapt_vqe",
    )
    shared_config = AdaptVQERunConfig(max_macro_iterations=1, max_micro_iterations=5)
    alg_spec = AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE)
    opts = ExecutionOptions(algorithm_spec=alg_spec, adapt_vqe_run_config=shared_config)

    problem = _molecule_problem()
    rec_a = runner.run(problem, "ibm_qiskit_adapt_vqe", opts)
    rec_b = runner.run(problem, "microsoft_qdk_adapt_vqe", opts)

    assert rec_a.result.status.value == "succeeded"
    assert rec_b.result.status.value == "succeeded"
    # Same seeded stub backend + same config + same starting point -> identical trace.
    assert rec_a.result.expectation_values[0].value == rec_b.result.expectation_values[0].value
