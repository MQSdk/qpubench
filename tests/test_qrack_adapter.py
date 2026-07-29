"""Tests for QrackAdapter — real execution against the PyQrack simulator.

Its own module rather than a section of test_backend_adapters.py: that file
calls pytest.importorskip at module level for each SDK stack in turn, so a
missing qiskit-aer skips everything defined after it. Qrack needs only pyqrack
and qiskit, and should be exercised whenever those two are present.

Everything here runs for real on the CPU simulator — no credentials, no GPU,
no mocking.
"""

from __future__ import annotations

import pytest

from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.observable import SparsePauliObservable
from qpubench.schemas.primitives import CircuitFormat, JobStatus

pytest.importorskip("qiskit")  # PyQrack has no QASM parser; see the adapter docstring

try:
    import pyqrack  # noqa: F401
except (ImportError, OSError) as exc:
    # Not importorskip: pyqrack ships a prebuilt shared library, so a machine
    # without it — or with a libstdc++ older than the wheel was built against —
    # fails with OSError, which importorskip does not catch.
    pytest.skip(f"pyqrack unavailable: {exc}", allow_module_level=True)

_BELL_QASM3 = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
h q[0];
cx q[0], q[1];
"""


def _bell_circuit() -> CircuitSpec:
    return CircuitSpec(num_qubits=2, format=CircuitFormat.QASM3, serialized=_BELL_QASM3)


def _assert_bell_counts(counts: dict[str, int]) -> None:
    """Bell state: only '00'/'11' should appear with non-trivial probability."""
    total = sum(counts.values())
    assert (counts.get("00", 0) + counts.get("11", 0)) / total > 0.9


class TestQrackAdapter:
    """Real PyQrack execution — no credentials, no GPU required.

    gpu=False throughout: CI hosts have no OpenCL platform, and Qrack falls
    back noisily rather than failing when asked for a GPU it cannot find.
    """

    def _adapter(self):
        from qpubench.backends.qrack_adapter import QrackAdapter

        return QrackAdapter(2, gpu=False)

    def test_validate_accepts_a_matching_gate_circuit(self) -> None:
        assert self._adapter().validate(_bell_circuit()) == []

    def test_validate_flags_a_qubit_count_mismatch(self) -> None:
        from qpubench.backends.qrack_adapter import QrackAdapter

        warnings = QrackAdapter(3, gpu=False).validate(_bell_circuit())
        assert any("3 qubits" in w for w in warnings)

    def test_estimator_path_is_exact_on_a_bell_state(self) -> None:
        """<ZZ> = <XX> = +1 and <YY> = -1 for (|00> + |11>)/sqrt(2)."""
        circuit = _bell_circuit().model_copy(update={"observables": [
            SparsePauliObservable.from_legacy_dict({"Z0,Z1": 1.0}, num_qubits=2),
            SparsePauliObservable.from_legacy_dict({"X0,X1": 1.0}, num_qubits=2),
            SparsePauliObservable.from_legacy_dict({"Y0,Y1": 1.0}, num_qubits=2),
        ]})
        result = self._adapter().run(circuit, ExecutionOptions())

        assert result.status == JobStatus.SUCCEEDED
        zz, xx, yy = (ev.value for ev in result.expectation_values)
        assert zz == pytest.approx(1.0, abs=1e-6)
        assert xx == pytest.approx(1.0, abs=1e-6)
        assert yy == pytest.approx(-1.0, abs=1e-6)
        assert result.fidelity.fidelity == pytest.approx(1.0, abs=1e-6)

    def test_multi_term_observable_is_a_weighted_sum(self) -> None:
        """0.5*ZZ + 0.5*XX evaluates to 1.0, not to <ZZXX>.

        Guards the module docstring's gotcha 2: Qrack's pauli_expectation
        returns one Pauli product, so the terms must be summed here.
        """
        observable = SparsePauliObservable.from_legacy_dict(
            {"Z0,Z1": 0.5, "X0,X1": 0.5}, num_qubits=2
        )
        circuit = _bell_circuit().model_copy(update={"observables": [observable]})
        result = self._adapter().run(circuit, ExecutionOptions())

        assert result.status == JobStatus.SUCCEEDED
        assert result.expectation_values[0].value == pytest.approx(1.0, abs=1e-6)

    def test_sampler_path_produces_correlated_counts(self) -> None:
        result = self._adapter().run(_bell_circuit(), ExecutionOptions(shots=2000))

        assert result.status == JobStatus.SUCCEEDED
        assert result.shots.num_shots == 2000
        assert sum(result.shots.counts.values()) == 2000
        _assert_bell_counts(result.shots.counts)

    def test_memory_records_one_bitstring_per_shot(self) -> None:
        result = self._adapter().run(
            _bell_circuit(), ExecutionOptions(shots=64, memory=True)
        )
        assert len(result.shots.memory) == 64
        assert all(len(b) == 2 for b in result.shots.memory)

    def test_bit_order_matches_the_qiskit_counts_convention(self) -> None:
        """x q[0] must read back as "01" — last character is qubit 0."""
        from qpubench.backends.qrack_adapter import QrackAdapter

        qasm = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nx q[0];\n'
        circuit = CircuitSpec(num_qubits=2, format=CircuitFormat.QASM3, serialized=qasm)
        result = QrackAdapter(2, gpu=False).run(circuit, ExecutionOptions(shots=16))

        assert result.shots.counts == {"01": 16}

    def test_sampling_without_shots_raises_rather_than_guessing(self) -> None:
        with pytest.raises(ValueError, match="explicit shot count"):
            self._adapter().run(_bell_circuit(), ExecutionOptions())

    def test_unparseable_circuit_raises(self) -> None:
        """Adapters let failures propagate; BenchmarkRunner records them FAILED."""
        from openqasm3.parser import QASM3ParsingError

        circuit = CircuitSpec(
            num_qubits=2, format=CircuitFormat.QASM3, serialized="this is not qasm"
        )
        with pytest.raises(QASM3ParsingError):
            self._adapter().run(circuit, ExecutionOptions(shots=8))

    def test_qgc_spec_without_a_path_raises(self) -> None:
        circuit = CircuitSpec(num_qubits=2, format=CircuitFormat.QGC, serialized="")
        with pytest.raises(ValueError, match="no file path"):
            self._adapter().run(circuit, ExecutionOptions(shots=8))

    def test_runner_converts_an_adapter_failure_into_a_failed_record(self) -> None:
        """The FAILED path lives in the runner, not in each adapter."""
        from qpubench.runner import BenchmarkRunner

        runner = BenchmarkRunner()
        runner.register(self._adapter(), name="qrack")
        record = runner.run(_bell_circuit(), "qrack", ExecutionOptions())

        assert record.result.status == JobStatus.FAILED
        assert "explicit shot count" in record.result.error_message
