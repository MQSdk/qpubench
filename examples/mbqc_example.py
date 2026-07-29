"""MBQC benchmark example using the stub MBQC backend.

Demonstrates:
  - Building an MBQCPattern for a single-qubit X rotation
    (4-round measurement sequence from mbqc.cpp::addUnitary())
  - Generating FPGA COE file content
  - Running via StubMBQCAdapter
  - Inspecting corrected outcomes and byproduct operators

Run with:
    python examples/mbqc_example.py
"""
from __future__ import annotations

import math
import pathlib

from qpubench import (
    BenchmarkRunner,
    CircuitSpec,
    ExecutionOptions,
    MBQCPattern,
    MBQCProgramWord,
    MBQCRound,
    NDJSONStore,
    StubMBQCAdapter,
)
from qpubench.schemas.mirrors.johnrscott_mbqc_fpga import (
    AdaptiveSpec,
    ByproductUpdateSpec,
    CommutationSpec,
)
from qpubench.schemas.primitives import ComputingModel, CircuitFormat


def rx_pattern(xi: float, eta: float, zeta: float) -> MBQCPattern:
    """Single-qubit unitary U = Rx(zeta)·Rz(eta)·Rx(xi) as a 4-round MBQC pattern.

    Program table from mbqc.cpp::addUnitary() (1 logical qubit, 4 rounds):

      Round 0  phi=0       s_prog=0b01100  b_prog=0b000010  c_prog=0b00001
      Round 1  phi=-xi     s_prog=0b10100  b_prog=0b010000  c_prog=0
      Round 2  phi=-eta    s_prog=0b01101  b_prog=0b000010  c_prog=0
      Round 3  phi=-zeta   s_prog=0b00000  b_prog=0b010000  c_prog=0
    """
    rounds_data = [
        (0.0,   0b01100, 0b000010, 0b00001),
        (-xi,   0b10100, 0b010000, 0b00000),
        (-eta,  0b01101, 0b000010, 0b00000),
        (-zeta, 0b00000, 0b010000, 0b00000),
    ]
    rounds = []
    for theta, s_raw, b_raw, c_raw in rounds_data:
        pw = MBQCProgramWord(
            byproduct_update=ByproductUpdateSpec.from_b_prog(b_raw),
            adaptive=AdaptiveSpec.from_s_prog(s_raw),
            commutation=CommutationSpec.from_c_prog(c_raw),
        )
        rounds.append([MBQCRound(theta=theta, program_word=pw)])
    return MBQCPattern(num_logical_qubits=1, rounds=rounds)


def main() -> None:
    # Build pattern for a π/3 rotation around X
    xi   = math.pi / 3
    eta  = 0.0
    zeta = 0.0
    pattern = rx_pattern(xi=xi, eta=eta, zeta=zeta)

    print("=== COE file for qubit 0 ===")
    print(pattern.to_single_qubit_coe(qubit_idx=0))
    print()

    # Validate program word round-trip
    for d, row in enumerate(pattern.rounds):
        pw      = row[0].program_word
        restored = MBQCProgramWord.from_word(pw.word)
        assert restored.word == pw.word, f"Round {d}: word mismatch"
    print("All program word round-trips OK\n")

    # Run via stub backend
    circuit = CircuitSpec(
        computing_model=ComputingModel.MBQC,
        num_qubits=pattern.num_logical_qubits,
        format=CircuitFormat.MEASUREMENT_PATTERN,
        measurement_pattern=pattern,
    )
    store  = NDJSONStore(pathlib.Path("results/mbqc_example.ndjson"))
    runner = BenchmarkRunner(store=store)
    runner.register(StubMBQCAdapter(seed=7, fidelity=0.97), name="mbqc_stub")

    record = runner.run(
        circuit,
        "mbqc_stub",
        ExecutionOptions(shots=100, cluster_depth=pattern.num_rounds),
        tags=["mbqc", "rx_rotation"],
    )

    result = record.result
    print(f"Status:   {result.status}")
    print(f"Fidelity: {result.fidelity.fidelity:.4f} ({result.fidelity.metric})")
    if result.mbqc_rounds:
        last = result.mbqc_rounds[-1]
        print(f"Final outcomes (raw):      {last.outcomes}")
        print(f"Final byproduct Z (packed): {last.byproduct_z:0{pattern.num_logical_qubits}b}")
        print(f"Final byproduct X (packed): {last.byproduct_x:0{pattern.num_logical_qubits}b}")
    if result.shots:
        print(f"Shot counts: {result.shots.counts}")

    print(f"\nRecord saved → {store._path}")


if __name__ == "__main__":
    main()
