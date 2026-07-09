"""qrunch guide: "Using Quantum Computers"

Verdict: Yes for the construction/registration pattern; execution needs
real hardware credentials. Revised 2026-07-08: IBMAdapter and IQMAdapter
are now real implementations (EstimatorV2/SamplerV2 PUBs, resilience
levels, sessions/batches — see docs/backends.md; both verified end-to-end
against bundled fake backends in tests/test_backend_adapters.py). They no
longer raise NotImplementedError — the only remaining gap for this guide is
a live IBM Quantum / IQM Resonance account, which this demo doesn't have.

Mechanism: BackendSpec.ibm(...) / BackendSpec.iqm(...) construction +
registration with BenchmarkRunner; IBMAdapter.run() is invoked for real and
its actual failure mode (a credentials/auth error from
QiskitRuntimeService, not NotImplementedError) is shown, with the
swap-in point to StubGateAdapter marked clearly below for running this
demo without an account.

Run:
    python examples/guides/quantum_computers.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench import BackendSpec, BenchmarkRunner, CircuitSpec, ExecutionOptions, StubGateAdapter
from qpubench.backends.ibm_adapter import IBMAdapter

BELL_QASM = """\
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0],q[1];
"""


def main() -> None:
    ibm_spec = BackendSpec.ibm("ibm_brisbane", token_ref="IBM_QUANTUM_TOKEN")
    iqm_spec = BackendSpec.iqm("garnet_star", api_token_ref="IQM_TOKEN")

    print(f"IBM backend spec: name={ibm_spec.name!r} provider={ibm_spec.provider!r} "
          f"modality={ibm_spec.qubit_modality}")
    print(f"IQM backend spec: name={iqm_spec.name!r} provider={iqm_spec.provider!r} "
          f"modality={iqm_spec.qubit_modality}")

    runner = BenchmarkRunner()
    runner.register(IBMAdapter(backend_name="ibm_brisbane"), name="ibm")

    circuit = CircuitSpec(num_qubits=2, serialized=BELL_QASM)
    record = runner.run(circuit, "ibm", ExecutionOptions(shots=1024))
    if record.result.status.value == "failed":
        # IBMAdapter.run() is real (see docs/backends.md) — this demo has
        # no live IBM Quantum credentials, so QiskitRuntimeService itself
        # fails to authenticate. BenchmarkRunner.run() converts that
        # exception into a FAILED QuantumResult rather than raising, so
        # record.result.status is how to detect it. Set IBM_QUANTUM_TOKEN
        # (or pass token=...) to run this against a real backend instead.
        print(f"No live IBM Quantum credentials: {record.result.error_message}")
        print("Running the same circuit through StubGateAdapter instead:")
        runner.register(StubGateAdapter(seed=2), name="stub")
        record = runner.run(circuit, "stub", ExecutionOptions(shots=1024))
    print(f"  status = {record.result.status}")


if __name__ == "__main__":
    main()
