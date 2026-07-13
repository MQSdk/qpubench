"""Result persistence.

NDJSONStore  — zero-dependency append-only store (default).
               Each line is a complete JSON-encoded BenchmarkRecord.
               Suitable for streaming writes and simple grep-based queries.

ParquetStore — optional columnar store requiring pyarrow + pandas.
               Enables fast analytical queries over large sweep results.

S3Store      — optional object store requiring boto3.
               One JSON object per record, so concurrent writers never race
               on a shared file the way NDJSONStore's append target can.
               Works against real AWS S3 and any S3-compatible endpoint
               (MinIO, Hugging Face Storage Buckets, ...); see
               S3Store.huggingface() for a ready-made HF configuration.
"""
from __future__ import annotations

import pathlib
from collections.abc import Iterator
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
        return [r for r in self._iter() if _matches(r, filters)]

    def all(self) -> list[BenchmarkRecord]:
        return list(self._iter())

    def _iter(self) -> Iterator[BenchmarkRecord]:
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

    Performance: save() rewrites the whole file per record (Parquet files are
    immutable), so saving n records one at a time is O(n²) I/O.  Treat this
    as an export/analysis format — collect records during a sweep with
    NDJSONStore, then bulk-load them here via save_many().
    """

    def __init__(self, path: pathlib.Path | str) -> None:
        self._path = pathlib.Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, record: BenchmarkRecord) -> None:
        self.save_many([record])

    def save_many(self, records: list[BenchmarkRecord]) -> None:
        """Append records in one read-concat-write cycle (one rewrite total)."""
        if not records:
            return
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as e:
            raise ImportError(
                "ParquetStore requires pyarrow and pandas. "
                "Install with: pip install 'qpubench[storage]'"
            ) from e

        rows = [_flatten_record(r) for r in records]
        new_table = pa.Table.from_pydict(
            {k: [row[k] for row in rows] for k in rows[0]}
        )

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

        df = pq.read_table(self._path).to_pandas()
        for col, val in filters.items():
            if col in df.columns:
                df = df[df[col] == val]
        return [
            BenchmarkRecord.model_validate_json(row["_raw_json"])
            for _, row in df.iterrows()
        ]

    def to_dataframe(self) -> Any:
        """Return a pandas DataFrame of flattened records (no pyarrow dependency)."""
        import pyarrow.parquet as pq

        return pq.read_table(self._path).to_pandas()


# ---------------------------------------------------------------------------
# S3 (optional) — AWS S3 and S3-compatible endpoints (MinIO, HF buckets, ...)
# ---------------------------------------------------------------------------

class S3Store:
    """Object store backed by S3 or any S3-compatible endpoint.

    Requires: pip install 'qpubench[s3]'

    One JSON object per record, written to
    f"{prefix}/{experiment_id}.json" (or f"{experiment_id}.json" with no
    prefix). Unlike NDJSONStore's shared append-only file, there is no
    read-modify-write of shared state, so concurrent writers — separate
    processes, machines, or a distributed sweep — do not race.

    Only put_object, get_object, and the list_objects_v2 paginator are
    used, so this works unmodified against real AWS S3 and against
    S3-compatible gateways such as MinIO or Hugging Face Storage Buckets
    (see S3Store.huggingface()).

    Pass an already-constructed boto3 client via `client=` (e.g. one built
    from an AWS CLI profile) or pass boto3.client("s3", ...) kwargs
    directly — endpoint_url, region_name, aws_access_key_id,
    aws_secret_access_key, config=botocore.config.Config(...), etc.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        *,
        client: Any | None = None,
        **client_kwargs: Any,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = client if client is not None else _s3_client(**client_kwargs)

    @classmethod
    def huggingface(
        cls,
        bucket: str,
        namespace: str,
        *,
        access_key_id: str,
        secret_access_key: str,
        prefix: str = "",
    ) -> S3Store:
        """Construct an S3Store backed by a Hugging Face Storage Bucket.

        namespace   your HF username or organization — scopes the gateway
                    endpoint (https://s3.hf.co/<namespace>).
        access_key_id / secret_access_key
                    S3 credentials generated from a HF User Access Token:
                    Settings -> Access Tokens -> (token) -> Generate S3
                    credentials. access_key_id is prefixed "HFAK...".

        The HF S3 gateway is single-region and path-style addressed, and
        only supports ListObjectsV2; the botocore Config below matches
        https://huggingface.co/docs/hub/en/storage-buckets-s3
        """
        try:
            from botocore.config import Config
        except ImportError as e:
            raise ImportError(
                "S3Store.huggingface() requires boto3. "
                "Install with: pip install 'qpubench[s3]'"
            ) from e
        return cls(
            bucket=bucket,
            prefix=prefix,
            endpoint_url=f"https://s3.hf.co/{namespace}",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(
                region_name="us-east-1",
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def _key(self, experiment_id: str) -> str:
        return f"{self._prefix}/{experiment_id}.json" if self._prefix else f"{experiment_id}.json"

    def save(self, record: BenchmarkRecord) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._key(record.experiment_id),
            Body=record.model_dump_json().encode("utf-8"),
            ContentType="application/json",
        )

    def load(self, experiment_id: str) -> BenchmarkRecord:
        key = self._key(experiment_id)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except self._client.exceptions.NoSuchKey as e:
            raise KeyError(
                f"experiment_id {experiment_id!r} not found in "
                f"s3://{self._bucket}/{key}"
            ) from e
        return BenchmarkRecord.model_validate_json(_read_body(response))

    def query(self, **filters: Any) -> list[BenchmarkRecord]:
        """Filter records by dot-separated field path (see NDJSONStore.query)."""
        return [r for r in self._iter() if _matches(r, filters)]

    def all(self) -> list[BenchmarkRecord]:
        return list(self._iter())

    def _iter(self) -> Iterator[BenchmarkRecord]:
        list_prefix = f"{self._prefix}/" if self._prefix else ""
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=list_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".json"):
                    continue
                response = self._client.get_object(Bucket=self._bucket, Key=key)
                yield BenchmarkRecord.model_validate_json(_read_body(response))


def _s3_client(**kwargs: Any) -> Any:
    try:
        import boto3
    except ImportError as e:
        raise ImportError(
            "S3Store requires boto3. Install with: pip install 'qpubench[s3]'"
        ) from e
    return boto3.client("s3", **kwargs)


def _read_body(get_object_response: dict[str, Any]) -> str:
    body = get_object_response["Body"].read()
    return body.decode("utf-8") if isinstance(body, bytes) else body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _matches(record: BenchmarkRecord, filters: dict[str, Any]) -> bool:
    """Shared query() semantics: double-underscore keys are dot-paths."""
    flat = record.model_dump()
    return all(
        _nested_get(flat, k.replace("__", ".")) == v
        for k, v in filters.items()
    )


def _nested_get(d: dict[str, Any], key: str) -> Any:
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
        "circuit_computing_model": record.circuit.computing_model.value,
        "circuit_qubit_modality":  record.circuit.qubit_modality.value if record.circuit.qubit_modality else None,
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
        # VQA inputs (optional)
        "molecule":          record.vqa.molecule        if record.vqa else None,
        "basis":             record.vqa.basis           if record.vqa else None,
        "ansatz":            record.vqa.ansatz          if record.vqa else None,
        # VQA computed outputs (optional)
        "final_eigenvalue":  record.vqa_result.final_eigenvalue if record.vqa_result else None,
        "ground_truth":      record.vqa_result.ground_truth     if record.vqa_result else None,
        # full record for lossless round-trip
        "_raw_json":         record.model_dump_json(),
    }
    return flat
