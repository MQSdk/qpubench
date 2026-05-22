"""Result persistence.

NDJSONStore  — zero-dependency append-only store (default).
               Each line is a complete JSON-encoded BenchmarkRecord.
               Suitable for streaming writes and simple grep-based queries.

ParquetStore — optional columnar store requiring pyarrow + pandas.
               Enables fast analytical queries over large sweep results.
"""
from __future__ import annotations

import pathlib
from typing import Any, Protocol, runtime_checkable

from .schemas.record import BenchmarkRecord


@runtime_checkable
class ResultStore(Protocol):
    def save(self, record: BenchmarkRecord) -> None: ...
    def load(self, experiment_id: str) -> BenchmarkRecord: ...
    def query(self, **filters: Any) -> list[BenchmarkRecord]: ...


# ---------------------------------------------------------------------------
# NDJSON (newline-delimited JSON)
# ---------------------------------------------------------------------------

class NDJSONStore:
    """Append-only NDJSON store.

    Thread-safety: individual write() calls on CPython are atomic for lines
    shorter than PIPE_BUF (~4 KB on Linux).  For large records or concurrent
    writers use an explicit file lock or separate per-worker files.
    """

    def __init__(self, path: pathlib.Path | str) -> None:
        self._path = pathlib.Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, record: BenchmarkRecord) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")

    def load(self, experiment_id: str) -> BenchmarkRecord:
        for record in self._iter():
            if record.experiment_id == experiment_id:
                return record
        raise KeyError(f"experiment_id {experiment_id!r} not found in {self._path}")

    def query(self, **filters: Any) -> list[BenchmarkRecord]:
        """Filter records by dot-separated field path.

        Examples:
            store.query(backend__name="aer_statevector")
            store.query(result__status="succeeded", vqa__molecule="H2")

        Keys use double-underscore as separator to avoid clash with Python's
        reserved keyword `filter`.
        """
        results: list[BenchmarkRecord] = []
        for record in self._iter():
            flat = record.model_dump()
            if all(
                _nested_get(flat, k.replace("__", ".")) == v
                for k, v in filters.items()
            ):
                results.append(record)
        return results

    def all(self) -> list[BenchmarkRecord]:
        return list(self._iter())

    def _iter(self):
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield BenchmarkRecord.model_validate_json(line)


# ---------------------------------------------------------------------------
# Parquet (optional)
# ---------------------------------------------------------------------------

class ParquetStore:
    """Columnar store backed by a single Parquet file.

    Requires: pip install 'qpubench[storage]'

    Records are flattened one level deep (nested dicts become JSON strings)
    so they fit into a tabular schema.  Use NDJSONStore if you need to round-
    trip complete nested records.
    """

    def __init__(self, path: pathlib.Path | str) -> None:
        self._path = pathlib.Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, record: BenchmarkRecord) -> None:
        try:
            import pandas as pd
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as e:
            raise ImportError(
                "ParquetStore requires pyarrow and pandas. "
                "Install with: pip install 'qpubench[storage]'"
            ) from e

        row = _flatten_record(record)
        new_table = pa.Table.from_pydict({k: [v] for k, v in row.items()})

        if self._path.exists():
            existing = pq.read_table(self._path)
            combined = pa.concat_tables([existing, new_table], promote_options="default")
        else:
            combined = new_table

        pq.write_table(combined, self._path)

    def load(self, experiment_id: str) -> BenchmarkRecord:
        import pyarrow.parquet as pq

        table = pq.read_table(self._path)
        df    = table.to_pandas()
        rows  = df[df["experiment_id"] == experiment_id]
        if rows.empty:
            raise KeyError(experiment_id)
        return BenchmarkRecord.model_validate_json(rows.iloc[0]["_raw_json"])

    def query(self, **filters: Any) -> list[BenchmarkRecord]:
        import pyarrow.parquet as pq

        table = pq.read_table(self._path)
        df    = table.to_pandas()
        mask  = pd.Series([True] * len(df), index=df.index)
        for col, val in filters.items():
            if col in df.columns:
                mask &= df[col] == val
        return [
            BenchmarkRecord.model_validate_json(row["_raw_json"])
            for _, row in df[mask].iterrows()
        ]

    def to_dataframe(self):
        """Return a pandas DataFrame of flattened records (no pyarrow dependency)."""
        import pandas as pd
        import pyarrow.parquet as pq

        return pq.read_table(self._path).to_pandas()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nested_get(d: dict, key: str) -> Any:
    for part in key.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)  # type: ignore[assignment]
    return d


def _flatten_record(record: BenchmarkRecord) -> dict[str, Any]:
    """Flatten one level of nesting for Parquet column layout."""
    import json

    flat: dict[str, Any] = {
        "schema_version":  record.schema_version,
        "experiment_id":   record.experiment_id,
        "run_id":          record.run_id,
        "timestamp":       record.timestamp.isoformat(),
        "num_qubits":      record.num_qubits,
        "circuit_depth":   record.circuit_depth,
        "tags":            json.dumps(record.tags),
        "notes":           record.notes,
        # circuit
        "circuit_modality":  record.circuit.modality.value,
        "circuit_format":    record.circuit.format.value,
        # backend
        "backend_name":      record.backend.name,
        "backend_provider":  record.backend.provider,
        # options
        "shots":             record.options.shots,
        "opt_level":         record.options.optimization_level,
        "error_mitigation":  record.options.error_mitigation.value,
        # result
        "result_status":     record.result.status.value,
        "qpu_time_s":        record.result.qpu_time_s,
        "total_time_s":      record.result.total_time_s,
        # VQA (optional)
        "molecule":          record.vqa.molecule        if record.vqa else None,
        "basis":             record.vqa.basis           if record.vqa else None,
        "ansatz":            record.vqa.ansatz          if record.vqa else None,
        "final_eigenvalue":  record.vqa.final_eigenvalue if record.vqa else None,
        "ground_truth":      record.vqa.ground_truth    if record.vqa else None,
        # full record for lossless round-trip
        "_raw_json":         record.model_dump_json(),
    }
    return flat
