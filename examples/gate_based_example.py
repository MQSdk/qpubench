"""Gate-based benchmark example using the stub backend.

Demonstrates:
  - Building a CircuitSpec with a SparsePauliObservable
  - Registering a StubGateAdapter
  - Running a single experiment
  - Running a parameter sweep
  - Persisting and querying results

Run with:
    python examples/gate_based_example.py
"""
from __future__ import annotations

import pathlib

from qpubench import (
    BackendSpec,
    BenchmarkRecord,
    BenchmarkRunner,
    CircuitSpec,
    ComplexNumber,
    ExecutionOptions,
    NDJSONStore,
    PauliLabel,
    PauliTerm,
    SparsePauliObservable,
    StubGateAdapter,
    VQAConfig,
    ZNEConfig,
)
from qpubench.schemas.primitives import ErrorMitigationStrategy

BELL_QASM = """\
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0],q[1];
"""

ZZ_OBSERVABLE = SparsePauliObservable(
    num_qubits=2,
    terms=[
        PauliTerm(
            qubit_indices=(0, 1),
            pauli_ops=(PauliLabel.Z, PauliLabel.Z),
            coefficient=ComplexNumber(re=1.0),
        )
    ],
)


def main() -> None:
    store  = NDJSONStore(pathlib.Path("results/gate_example.ndjson"))
    runner = BenchmarkRunner(store=store)
    runner.register(StubGateAdapter(seed=42), name="stub")

    # -- Single run ----------------------------------------------------------
    circuit = CircuitSpec(num_qubits=2, serialized=BELL_QASM, observables=[ZZ_OBSERVABLE])
    options = ExecutionOptions(shots=1024)

    record = runner.run(
        circuit,
        "stub",
        options,
        vqa=VQAConfig(problem_type="circuit_test"),
        tags=["bell_state", "example"],
    )
    ev = record.result.expectation_values[0]
    print(f"[single run] ⟨ZZ⟩ = {ev.value:.4f} ± {ev.std_error:.4f}")

    # -- Parameter sweep (shots × error mitigation) --------------------------
    shots_options = [
        ExecutionOptions(shots=s) for s in [256, 1024, 4096]
    ]
    zne_options = ExecutionOptions(
        shots=1024,
        error_mitigation=ErrorMitigationStrategy.ZNE,
        zne_config=ZNEConfig(noise_factors=(1.0, 3.0, 5.0)),
    )
    all_options = shots_options + [zne_options]

    records = runner.sweep(
        circuits=[circuit],
        backend_names=["stub"],
        options_list=all_options,
        run_id="bell_sweep_01",
        tags=["sweep"],
    )
    print(f"\n[sweep] {len(records)} records saved to {store._path}")

    # -- Query ----------------------------------------------------------------
    succeeded = store.query(result__status="succeeded")
    print(f"[query] {len(succeeded)} succeeded records in store")


if __name__ == "__main__":
    main()
