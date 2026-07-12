"""Guide: choose a data persister / result store.

Mechanism: NDJSONStore / ParquetStore / S3Store all implement the same
ResultStore protocol (save/load/query); S3Store also works against MinIO
and Hugging Face Storage Buckets, not just AWS S3.

Run:
    python examples/guides/data_persister_manager.py
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench import (
    BackendSpec, BenchmarkRecord, CircuitSpec, ComputingModel,
    ExecutionOptions, ExpectationResult, NDJSONStore, ParquetStore, QuantumResult,
)

BELL_QASM = """\
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0],q[1];
"""


def _sample_record() -> BenchmarkRecord:
    return BenchmarkRecord(
        circuit=CircuitSpec(num_qubits=2, serialized=BELL_QASM),
        backend=BackendSpec.aer_statevector(num_qubits=2),
        options=ExecutionOptions(shots=1024),
        result=QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=[ExpectationResult(observable_index=0, value=1.0, std_error=0.0)],
        ),
        num_qubits=2,
    )


def main() -> None:
    record = _sample_record()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)

        # NDJSONStore — zero dependencies, append-only, grep-able.
        ndjson_store = NDJSONStore(tmp_path / "results.ndjson")
        ndjson_store.save(record)
        loaded = ndjson_store.load(record.experiment_id)
        print(f"NDJSONStore : saved + loaded, energy = "
              f"{loaded.result.expectation_values[0].value}")
        print(f"              {len(ndjson_store.query(result__status='succeeded'))} "
              f"matching query(result__status='succeeded')")

        # ParquetStore — pip install 'qpubench[storage]' (pyarrow + pandas)
        try:
            parquet_store = ParquetStore(tmp_path / "results.parquet")
            parquet_store.save(record)
            print(f"ParquetStore: saved (columnar, {len(parquet_store.query())} rows)")
        except ImportError as exc:
            print(f"ParquetStore: skipped ({exc})")

        # S3Store — pip install 'qpubench[s3]' (boto3); shown constructed
        # only, not exercised against real network I/O in this example.
        try:
            from qpubench import S3Store
            s3_store = S3Store.huggingface(
                bucket="my-benchmark-results",
                namespace="my-org",
                access_key_id="HFAK_placeholder",
                secret_access_key="placeholder",
            )
            print(f"S3Store     : constructed against {s3_store.__class__.__name__} "
                  f"(HF Storage Buckets) — not exercised here, needs real credentials")
        except ImportError as exc:
            print(f"S3Store     : skipped ({exc})")


if __name__ == "__main__":
    main()
