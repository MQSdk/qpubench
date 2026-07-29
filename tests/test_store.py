"""Tests for qpubench.store — NDJSONStore, S3Store.

S3Store is tested against an in-memory fake that mimics only the boto3 S3
client surface S3Store actually calls (put_object, get_object,
get_paginator("list_objects_v2").paginate, .exceptions.NoSuchKey), so these
tests run without boto3 installed.
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.primitives import ComputingModel
from qpubench.schemas.record import BenchmarkRecord
from qpubench.schemas.result import ExpectationResult, QuantumResult
from qpubench.store import NDJSONStore, S3Store


def _minimal_record(**overrides: Any) -> BenchmarkRecord:
    defaults: dict[str, Any] = dict(
        circuit=CircuitSpec(num_qubits=2, serialized="OPENQASM 2.0;"),
        backend=BackendSpec.aer_statevector(num_qubits=2),
        options=ExecutionOptions(shots=1024),
        result=QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=[
                ExpectationResult(observable_index=0, value=-1.137, std_error=0.001)
            ],
        ),
        num_qubits=2,
    )
    defaults.update(overrides)
    return BenchmarkRecord(**defaults)


# ---------------------------------------------------------------------------
# Fake boto3 S3 client — in-memory, duck-types only what S3Store calls
# ---------------------------------------------------------------------------

class _NoSuchKey(Exception):
    pass


class _FakeExceptions:
    NoSuchKey = _NoSuchKey


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakePaginator:
    def __init__(self, client: _FakeS3Client) -> None:
        self._client = client

    def paginate(self, *, Bucket: str, Prefix: str = ""):
        keys = sorted(k for k in self._client.objects if k.startswith(Prefix))
        yield {"Contents": [{"Key": k} for k in keys]}


class _FakeS3Client:
    """Minimal in-memory double for the boto3 S3 client surface S3Store uses."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.exceptions = _FakeExceptions()

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str | None = None) -> None:
        self.objects[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise self.exceptions.NoSuchKey(Key)
        return {"Body": _FakeBody(self.objects[Key])}

    def get_paginator(self, name: str) -> _FakePaginator:
        assert name == "list_objects_v2"
        return _FakePaginator(self)


# ---------------------------------------------------------------------------
# NDJSONStore — quick smoke coverage
# ---------------------------------------------------------------------------

def test_ndjson_store_save_load_query(tmp_path: pathlib.Path):
    store = NDJSONStore(tmp_path / "results.ndjson")
    record = _minimal_record()
    store.save(record)

    loaded = store.load(record.experiment_id)
    assert loaded.experiment_id == record.experiment_id

    assert store.query(backend__name="aer_statevector") == [loaded]
    assert store.all() == [loaded]

    with pytest.raises(KeyError):
        store.load("does-not-exist")


# ---------------------------------------------------------------------------
# S3Store
# ---------------------------------------------------------------------------

def test_s3store_save_and_load_roundtrip():
    client = _FakeS3Client()
    store = S3Store("my-bucket", client=client)
    record = _minimal_record()

    store.save(record)
    loaded = store.load(record.experiment_id)

    assert loaded.experiment_id == record.experiment_id
    assert loaded.result.expectation_values[0].value == -1.137
    assert f"{record.experiment_id}.json" in client.objects


def test_s3store_load_missing_key_raises_keyerror():
    store = S3Store("my-bucket", client=_FakeS3Client())
    with pytest.raises(KeyError):
        store.load("does-not-exist")


def test_s3store_prefix_is_applied_to_keys():
    client = _FakeS3Client()
    store = S3Store("my-bucket", prefix="/results/sweep1/", client=client)
    record = _minimal_record()

    store.save(record)

    assert f"results/sweep1/{record.experiment_id}.json" in client.objects


def test_s3store_no_prefix_uses_bare_key():
    client = _FakeS3Client()
    store = S3Store("my-bucket", client=client)
    record = _minimal_record()

    store.save(record)

    assert list(client.objects) == [f"{record.experiment_id}.json"]


def test_s3store_all_and_query():
    client = _FakeS3Client()
    store = S3Store("my-bucket", client=client)

    r1 = _minimal_record()
    r2 = _minimal_record(tags=["h2"])
    store.save(r1)
    store.save(r2)

    assert len(store.all()) == 2

    matches = store.query(backend__name="aer_statevector")
    assert len(matches) == 2

    tagged = store.query(tags=["h2"])
    assert len(tagged) == 1
    assert tagged[0].experiment_id == r2.experiment_id


def test_s3store_ignores_non_json_keys_when_listing():
    client = _FakeS3Client()
    store = S3Store("my-bucket", client=client)
    record = _minimal_record()
    store.save(record)
    client.objects["README.md"] = b"not a record"

    assert len(store.all()) == 1


def _boto3_available() -> bool:
    try:
        import boto3  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(_boto3_available(), reason="boto3 installed; ImportError guard not exercised")
def test_s3store_requires_boto3_without_injected_client():
    with pytest.raises(ImportError, match="boto3"):
        S3Store("my-bucket")


@pytest.mark.skipif(_boto3_available(), reason="boto3 installed; ImportError guard not exercised")
def test_s3store_huggingface_requires_boto3():
    with pytest.raises(ImportError, match="boto3"):
        S3Store.huggingface("my-bucket", "my-namespace", region="us-east-1")


# ---------------------------------------------------------------------------
# Credential and region handling (reviewer feedback round 6)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "secret_kwarg",
    ["aws_access_key_id", "aws_secret_access_key", "aws_session_token"],
)
def test_s3store_rejects_literal_credentials(secret_kwarg):
    """Literal AWS keys must never be accepted as constructor arguments."""
    with pytest.raises(TypeError, match="Refusing literal credentials"):
        S3Store("my-bucket", **{secret_kwarg: "AKIA-hardcoded-secret"})


def test_s3store_huggingface_has_no_credential_parameters():
    """The HF helper takes no credential arguments at all."""
    import inspect

    params = inspect.signature(S3Store.huggingface).parameters
    assert not [p for p in params if "key" in p or "token" in p or "secret" in p]


def test_resolve_region_requires_an_explicit_choice(monkeypatch):
    """No built-in region default: caller or environment must name one."""
    from qpubench.store import _resolve_region

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    with pytest.raises(ValueError, match="No region configured"):
        _resolve_region(None)

    monkeypatch.setenv("AWS_REGION", "eu-north-1")
    assert _resolve_region(None) == "eu-north-1"
    assert _resolve_region("us-west-2") == "us-west-2"


def test_records_written_before_the_rename_still_load(tmp_path):
    """Old NDJSON records carrying a bare `schema_version` key still validate."""
    record = _minimal_record()
    payload = record.model_dump(mode="json")
    payload["schema_version"] = payload.pop("qpubench_schema_version")

    import json

    path = tmp_path / "legacy.ndjson"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    restored = NDJSONStore(path).all()
    assert len(restored) == 1
    assert restored[0].qpubench_schema_version == record.qpubench_schema_version
