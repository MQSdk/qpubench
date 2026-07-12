"""Guide: using the logger.

``qpubench.observability.BenchmarkLogger`` is the structured logging
subsystem: real ``logging`` levels (status-based: SUCCEEDED -> INFO, FAILED -> ERROR),
a configurable ``logging.Handler`` (``StreamHandler`` here; swap for
``FileHandler``/``RotatingFileHandler`` for real log rotation), and
``JSONFormatter`` for structured export. Built directly on top of
``BenchmarkRunner.add_hook()`` — that hook is still the wiring point, no
runner changes were needed.

Run:
    python examples/guides/logging_hook.py
"""
from __future__ import annotations

import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench import BenchmarkLogger, BenchmarkRunner, CircuitSpec, ExecutionOptions, StubGateAdapter
from qpubench import StubMBQCAdapter
from qpubench.observability import JSONFormatter
from qpubench.schemas.primitives import ComputingModel

BELL_QASM = """\
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0],q[1];
"""


def main() -> None:
    runner = BenchmarkRunner()
    runner.register(StubGateAdapter(seed=4), name="stub")

    # handlers: default StreamHandler + a second, stricter ERROR-only
    # handler on its own stream — real handler/level configurability, not
    # a single hardcoded log line. In production this second handler would
    # typically be a FileHandler dedicated to failures.
    error_handler = logging.StreamHandler()
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())

    bench_logger = BenchmarkLogger(name="qpubench.examples.benchmark")
    bench_logger.logger.addHandler(error_handler)
    bench_logger.attach(runner)

    circuit = CircuitSpec(num_qubits=2, serialized=BELL_QASM)
    for shots in [256, 1024, 4096]:
        runner.run(circuit, "stub", ExecutionOptions(shots=shots))

    # Trigger the ERROR-level path for real: StubMBQCAdapter returns
    # status=FAILED (not an exception) when handed an MBQC circuit with no
    # measurement_pattern — a normal BenchmarkRecord still gets built and
    # passed to every hook, so BenchmarkLogger logs it at ERROR, not INFO.
    runner.register(StubMBQCAdapter(seed=1), name="stub_mbqc")
    bad_mbqc_circuit = CircuitSpec(
        num_qubits=2, computing_model=ComputingModel.MBQC, serialized="{}",
    )
    runner.run(bad_mbqc_circuit, "stub_mbqc", ExecutionOptions())


if __name__ == "__main__":
    main()
