"""Tests for the real backend adapter implementations.

Aer/Braket: fully executed for real (Aer via qiskit-aer's own simulator,
Braket via BraketLocalBackend which wraps braket.devices.LocalSimulator —
neither needs credentials).

IBM/IQM: real transpile()/run() logic is exercised against a bundled fake
backend (qiskit_ibm_runtime.fake_provider.FakeManilaV2 /
iqm.qiskit_iqm.fake_backends.fake_adonis.IQMFakeAdonis) with only the
credential-fetching `_get_backend()` call mocked out — everything else
(ISA transpilation, observable layout remapping, PUB construction, result
parsing) runs for real, same as it would against a live device.

Each SDK stack is optional; every test module is skipped cleanly if its
package isn't installed (pip install 'qpubench[qiskit,braket,iqm]').
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.observable import SparsePauliObservable
from qpubench.schemas.primitives import CircuitFormat, JobStatus

_BELL_QASM3 = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
h q[0];
cx q[0], q[1];
"""


def _bell_circuit(with_observable: bool = False) -> CircuitSpec:
    circ = CircuitSpec(num_qubits=2, format=CircuitFormat.QASM3, serialized=_BELL_QASM3)
    if with_observable:
        obs = SparsePauliObservable.from_legacy_dict({"Z0,Z1": 1.0}, num_qubits=2)
        circ = circ.model_copy(update={"observables": [obs]})
    return circ


def _assert_bell_counts(counts: dict[str, int]) -> None:
    """Bell state: only '00'/'11' should appear with non-trivial probability."""
    total = sum(counts.values())
    correlated = counts.get("00", 0) + counts.get("11", 0)
    assert correlated / total > 0.9


# ---------------------------------------------------------------------------
# Aer — fully real, no credentials needed
# ---------------------------------------------------------------------------

qiskit_aer = pytest.importorskip("qiskit_aer")


class TestAerAdapter:
    def test_sampler(self) -> None:
        from qpubench.backends.aer_adapter import AerAdapter

        adapter = AerAdapter()
        result = adapter.run(_bell_circuit(), ExecutionOptions(shots=1000, seed=7))
        assert result.status == JobStatus.SUCCEEDED
        assert result.shots is not None
        _assert_bell_counts(result.shots.counts)

    def test_estimator(self) -> None:
        from qpubench.backends.aer_adapter import AerAdapter

        adapter = AerAdapter()
        result = adapter.run(_bell_circuit(with_observable=True), ExecutionOptions())
        assert result.status == JobStatus.SUCCEEDED
        assert result.expectation_values[0].value == pytest.approx(1.0, abs=1e-9)

    def test_transpile(self) -> None:
        from qpubench.backends.aer_adapter import AerAdapter

        adapter = AerAdapter()
        tqc, _layout = adapter.transpile(_bell_circuit(), ExecutionOptions())
        assert tqc.format == CircuitFormat.QASM3
        assert tqc.gate_counts


# ---------------------------------------------------------------------------
# PennyLane lightning.qubit — fully real, no credentials needed
# ---------------------------------------------------------------------------

pennylane = pytest.importorskip("pennylane")
pennylane_qiskit = pytest.importorskip("pennylane_qiskit")


class TestPennyLaneLightningAdapter:
    def test_sampler(self) -> None:
        from qpubench.backends.pennylane_lightning_adapter import PennyLaneLightningAdapter

        adapter = PennyLaneLightningAdapter()
        result = adapter.run(_bell_circuit(), ExecutionOptions(shots=1000))
        assert result.status == JobStatus.SUCCEEDED
        assert result.shots is not None
        _assert_bell_counts(result.shots.counts)

    def test_estimator_exact(self) -> None:
        from qpubench.backends.pennylane_lightning_adapter import PennyLaneLightningAdapter

        adapter = PennyLaneLightningAdapter()
        result = adapter.run(_bell_circuit(with_observable=True), ExecutionOptions())
        assert result.status == JobStatus.SUCCEEDED
        assert result.expectation_values[0].value == pytest.approx(1.0, abs=1e-9)
        assert result.expectation_values[0].std_error == 0.0

    def test_estimator_with_shots_reports_std_error(self) -> None:
        from qpubench.backends.pennylane_lightning_adapter import PennyLaneLightningAdapter

        adapter = PennyLaneLightningAdapter()
        result = adapter.run(_bell_circuit(with_observable=True), ExecutionOptions(shots=2048))
        assert result.expectation_values[0].num_shots == 2048
        # Bell state ZZ is an eigenstate (variance 0) so std_error is exactly 0,
        # unlike a generic observable — this only checks the field is populated.
        assert result.expectation_values[0].std_error == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# MitiqZNEAdapter — fully real, wraps a noisy Aer simulator
# ---------------------------------------------------------------------------

mitiq = pytest.importorskip("mitiq")
pytest.importorskip("ply")  # cirq-core's QASM import needs this; see module docstring


def _noisy_aer_adapter():
    import json

    from qiskit_aer.noise import NoiseModel, depolarizing_error

    from qpubench.backends.aer_adapter import AerAdapter

    noise_model = NoiseModel()
    noise_model.add_all_qubit_quantum_error(depolarizing_error(0.02, 1), ["h"])
    noise_model.add_all_qubit_quantum_error(depolarizing_error(0.05, 2), ["cx"])
    return AerAdapter(noise_model_json=json.dumps(noise_model.to_dict()))


class TestMitiqZNEAdapter:
    def test_zne_reduces_bias_vs_raw_noisy_estimate(self) -> None:
        from qpubench.backends.unitaryfund_mitiq_adapter import MitiqZNEAdapter

        circuit = _bell_circuit(with_observable=True)
        noisy_inner = _noisy_aer_adapter()
        raw = noisy_inner.run(circuit, ExecutionOptions())
        assert raw.expectation_values is not None
        raw_value = raw.expectation_values[0].value

        adapter = MitiqZNEAdapter(noisy_inner)
        mitigated = adapter.run(circuit, ExecutionOptions())
        assert mitigated.status == JobStatus.SUCCEEDED
        mitigated_value = mitigated.expectation_values[0].value

        # Exact (noiseless) value is 1.0 — ZNE should land closer to it.
        assert abs(mitigated_value - 1.0) < abs(raw_value - 1.0)
        assert mitigated.expectation_values[0].raw_values

    def test_linear_factory_reports_extrapolation_error(self) -> None:
        from qpubench.backends.unitaryfund_mitiq_adapter import MitiqZNEAdapter
        from qpubench.schemas.mirrors.unitaryfund_mitiq import MitiqZNEConfig, MitiqZNEFactory

        adapter = MitiqZNEAdapter(
            _noisy_aer_adapter(), MitiqZNEConfig(factory=MitiqZNEFactory.LINEAR)
        )
        result = adapter.run(_bell_circuit(with_observable=True), ExecutionOptions())
        # Unlike RichardsonFactory (exact interpolation, 0 residual DOF),
        # LinearFactory under-fits 3 points and has a real covariance-based error.
        assert result.expectation_values[0].std_error > 0.0

    def test_sampler_path_passes_through_unmitigated(self) -> None:
        from qpubench.backends.unitaryfund_mitiq_adapter import MitiqZNEAdapter

        adapter = MitiqZNEAdapter(_noisy_aer_adapter())
        result = adapter.run(_bell_circuit(), ExecutionOptions(shots=1000))
        assert result.status == JobStatus.SUCCEEDED
        assert result.shots is not None

    def test_spec_and_inner_delegate(self) -> None:
        from qpubench.backends.unitaryfund_mitiq_adapter import MitiqZNEAdapter

        inner = _noisy_aer_adapter()
        adapter = MitiqZNEAdapter(inner)
        assert adapter.spec == inner.spec
        assert adapter.inner is inner
        assert adapter.validate(_bell_circuit()) == inner.validate(_bell_circuit())


# ---------------------------------------------------------------------------
# Braket — fully real via BraketLocalBackend, no AWS account needed
# ---------------------------------------------------------------------------

qiskit_braket_provider = pytest.importorskip("qiskit_braket_provider")


class TestBraketAdapter:
    def test_sampler(self) -> None:
        from qpubench.backends.braket_adapter import BraketAdapter

        adapter = BraketAdapter(device_arn="local")
        result = adapter.run(_bell_circuit(), ExecutionOptions(shots=1000))
        assert result.status == JobStatus.SUCCEEDED
        _assert_bell_counts(result.shots.counts)

    def test_estimator(self) -> None:
        from qpubench.backends.braket_adapter import BraketAdapter

        adapter = BraketAdapter(device_arn="local")
        result = adapter.run(_bell_circuit(with_observable=True), ExecutionOptions())
        assert result.status == JobStatus.SUCCEEDED
        assert result.expectation_values[0].value == pytest.approx(1.0, abs=1e-9)

    def test_transpile(self) -> None:
        from qpubench.backends.braket_adapter import BraketAdapter

        adapter = BraketAdapter(device_arn="local")
        tqc, layout = adapter.transpile(_bell_circuit(), ExecutionOptions())
        assert tqc.format == CircuitFormat.QASM3
        assert layout is not None


# ---------------------------------------------------------------------------
# IBM — real transpile/run logic against a bundled fake backend
# ---------------------------------------------------------------------------

qiskit_ibm_runtime = pytest.importorskip("qiskit_ibm_runtime")


class TestIBMAdapter:
    def _fake_backend(self) -> object:
        from qiskit_ibm_runtime.fake_provider import FakeManilaV2

        return FakeManilaV2()

    def test_sampler(self) -> None:
        from qpubench.backends.ibm_adapter import IBMAdapter

        adapter = IBMAdapter("ibm_test", instance="test/test/test")
        with patch.object(IBMAdapter, "_get_backend", return_value=self._fake_backend()):
            result = adapter.run(_bell_circuit(), ExecutionOptions(shots=1000))
        assert result.status == JobStatus.SUCCEEDED
        assert result.vendor_results.get("ibm_runtime_record") is not None
        _assert_bell_counts(result.shots.counts)

    def test_estimator(self) -> None:
        from qpubench.backends.ibm_adapter import IBMAdapter

        adapter = IBMAdapter("ibm_test", instance="test/test/test")
        with patch.object(IBMAdapter, "_get_backend", return_value=self._fake_backend()):
            result = adapter.run(_bell_circuit(with_observable=True), ExecutionOptions(shots=4000))
        assert result.status == JobStatus.SUCCEEDED
        # Noisy fake backend: correlated but not exact.
        assert result.expectation_values[0].value > 0.5

    def test_transpile(self) -> None:
        from qpubench.backends.ibm_adapter import IBMAdapter

        adapter = IBMAdapter("ibm_test", instance="test/test/test")
        with patch.object(IBMAdapter, "_get_backend", return_value=self._fake_backend()):
            tqc, layout = adapter.transpile(_bell_circuit(), ExecutionOptions())
        assert tqc.format == CircuitFormat.QASM3
        assert layout.num_physical == 5


# ---------------------------------------------------------------------------
# IQM — real transpile/run logic against a bundled fake backend
# ---------------------------------------------------------------------------

iqm_client = pytest.importorskip("iqm.qiskit_iqm")


class TestIQMAdapter:
    def _fake_backend(self) -> object:
        from iqm.qiskit_iqm.fake_backends.fake_adonis import IQMFakeAdonis

        return IQMFakeAdonis()

    def test_sampler(self) -> None:
        from qpubench.backends.iqm_adapter import IQMAdapter

        adapter = IQMAdapter("adonis")
        with patch.object(IQMAdapter, "_get_backend", return_value=self._fake_backend()):
            result = adapter.run(_bell_circuit(), ExecutionOptions(shots=1000))
        assert result.status == JobStatus.SUCCEEDED
        assert result.shots.num_qubits == 2

    def test_estimator_not_implemented(self) -> None:
        """Real, documented upstream limitation — not a stub."""
        from qpubench.backends.iqm_adapter import IQMAdapter

        adapter = IQMAdapter("adonis")
        with patch.object(IQMAdapter, "_get_backend", return_value=self._fake_backend()):
            with pytest.raises(NotImplementedError):
                adapter.run(_bell_circuit(with_observable=True), ExecutionOptions())

    def test_transpile(self) -> None:
        from qpubench.backends.iqm_adapter import IQMAdapter

        adapter = IQMAdapter("adonis")
        with patch.object(IQMAdapter, "_get_backend", return_value=self._fake_backend()):
            tqc, layout = adapter.transpile(_bell_circuit(), ExecutionOptions())
        assert tqc.format == CircuitFormat.QASM3
        assert layout.num_physical == 5


# ---------------------------------------------------------------------------
# Quantinuum — real compile/run logic without a live account
# ---------------------------------------------------------------------------
#
# transpile(): exercised offline via QuantinuumBackend(machine_debug=True),
# which performs real Quantinuum compilation to the Rz/PhasedX/ZZPhase native
# gate set. run(): the full sampler plumbing (qiskit->tket conversion,
# process_circuit, get_result, counts parsing) is exercised against a local
# pytket simulator (pytket.extensions.qiskit.AerBackend), which returns real
# Bell-correlated counts — machine_debug returns only trivial all-zero shots,
# so it cannot validate the counts path. Only the credential-fetching
# `_get_backend()` call needs a real Quantinuum account.

pytket_quantinuum = pytest.importorskip("pytket.extensions.quantinuum")
pytket_qiskit = pytest.importorskip("pytket.extensions.qiskit")

# Native gate types pytket may leave after Quantinuum compilation.
_QTM_NATIVE_OPS = {"PhasedX", "Rz", "ZZPhase", "ZZMax", "TK2", "Measure", "Barrier"}


class TestQuantinuumAdapter:
    def _debug_backend(self) -> object:
        from pytket.extensions.quantinuum import QuantinuumBackend

        return QuantinuumBackend(device_name="H2-1E", machine_debug=True)

    def _sim_backend(self) -> object:
        from pytket.extensions.qiskit import AerBackend

        return AerBackend()

    def test_transpile(self) -> None:
        from qpubench.backends.quantinuum_adapter import QuantinuumAdapter

        adapter = QuantinuumAdapter("H2-1E")
        with patch.object(QuantinuumAdapter, "_get_backend", return_value=self._debug_backend()):
            tqc, layout = adapter.transpile(_bell_circuit(), ExecutionOptions())
        assert tqc.format == CircuitFormat.QASM3
        assert tqc.gate_counts
        # Compiled to Quantinuum native gates only.
        assert set(tqc.gate_counts) <= _QTM_NATIVE_OPS
        assert layout.num_virtual == 2

    def test_sampler(self) -> None:
        from qpubench.backends.quantinuum_adapter import QuantinuumAdapter

        adapter = QuantinuumAdapter("H2-1E")
        with patch.object(QuantinuumAdapter, "_get_backend", return_value=self._sim_backend()):
            result = adapter.run(_bell_circuit(), ExecutionOptions(shots=1000, seed=7))
        assert result.status == JobStatus.SUCCEEDED
        assert result.shots is not None
        assert result.shots.num_qubits == 2
        _assert_bell_counts(result.shots.counts)

    def test_estimator_not_implemented(self) -> None:
        """Real, documented upstream limitation — Quantinuum has no Estimator."""
        from qpubench.backends.quantinuum_adapter import QuantinuumAdapter

        adapter = QuantinuumAdapter("H2-1E")
        with patch.object(QuantinuumAdapter, "_get_backend", return_value=self._debug_backend()):
            with pytest.raises(NotImplementedError):
                adapter.run(_bell_circuit(with_observable=True), ExecutionOptions())


# ---------------------------------------------------------------------------
# Qibo — local numpy simulator: fully real, no credentials needed
# ---------------------------------------------------------------------------
#
# The Qibolab (self-hosted hardware) and Qibo cloud paths need a real lab /
# account, but the local-simulator path (execution="local", default "numpy"
# backend) runs the full adapter end-to-end with no credentials — QASM load,
# measurement injection, frequency/sample parsing, and the big-endian ->
# little-endian bitstring fix.

qibo = pytest.importorskip("qibo")


class TestQiboAdapter:
    def test_sampler(self) -> None:
        from qpubench.backends.qibo_adapter import QiboAdapter

        adapter = QiboAdapter()  # local numpy simulator
        result = adapter.run(_bell_circuit(), ExecutionOptions(shots=1000))
        assert result.status == JobStatus.SUCCEEDED
        assert result.shots is not None
        assert result.shots.num_qubits == 2
        _assert_bell_counts(result.shots.counts)

    def test_bit_ordering_matches_qiskit_convention(self) -> None:
        """X on qubit 0 must read as '01' (q0 rightmost), not qibo's '10'."""
        from qpubench.backends.qibo_adapter import QiboAdapter

        x_on_q0 = CircuitSpec(
            num_qubits=2,
            format=CircuitFormat.QASM3,
            serialized='OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nx q[0];\n',
        )
        adapter = QiboAdapter()
        result = adapter.run(x_on_q0, ExecutionOptions(shots=100))
        assert result.shots.counts == {"01": 100}

    def test_estimator_not_implemented(self) -> None:
        """Real, documented limitation — Qibo hardware returns samples."""
        from qpubench.backends.qibo_adapter import QiboAdapter

        adapter = QiboAdapter()
        with pytest.raises(NotImplementedError):
            adapter.run(_bell_circuit(with_observable=True), ExecutionOptions())

    def test_spec_execution_modes(self) -> None:
        from qpubench.backends.qibo_adapter import QiboAdapter

        assert QiboAdapter().spec.simulator is True
        assert QiboAdapter("sim", execution="cloud").spec.provider == "qibo"
        assert QiboAdapter("my_lab", execution="qibolab").spec.simulator is False
        with pytest.raises(ValueError):
            QiboAdapter(execution="bogus")

