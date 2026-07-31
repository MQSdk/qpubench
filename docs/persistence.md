# Stores & persistence

A **store** is where the `BenchmarkRunner` persists every `BenchmarkRecord` after execution, the third of qpubench's three layers (schemas describe, adapters execute, stores persist). qpubench ships three stores. All implement the `ResultStore` protocol:

```python
class ResultStore(Protocol):
    def save(self, record: BenchmarkRecord) -> None: ...
    def load(self, experiment_id: str) -> BenchmarkRecord: ...
    def query(self, **filters) -> list[BenchmarkRecord]: ...
```

---

## NDJSONStore

Zero-dependency, append-only, one JSON record per line.  
Suitable for streaming writes, `grep`-based ad-hoc queries, and compatibility with any NDJSON tool.

```python
import pathlib
from qpubench import BenchmarkRunner, NDJSONStore

store  = NDJSONStore(pathlib.Path("results/sweep.ndjson"))
runner = BenchmarkRunner(store=store)
```

### Querying

Keys use `__` as a field-path separator:

```python
# Filter by backend name
records = store.query(backend__name="aer_statevector")

# Multiple filters (AND)
records = store.query(result__status="succeeded", vqa__molecule="H2")

# Algorithm-driven runs
records = store.query(options__algorithm_spec__name="ADAPTVQE")

# Load a single record by UUID
record = store.load("3f2a1b4c-...")

# All records
all_records = store.all()
```

The query matches on the `model_dump()` representation of `BenchmarkRecord`. Nested dicts use the same `__` convention, e.g. `result__expectation_values` would require a further traversal that the query engine does not yet support; load the record and filter in Python for deep nesting.

### Thread safety

Individual `write()` calls on CPython are atomic for lines shorter than `PIPE_BUF` (~4 KB on Linux). For large records or concurrent writers, use an explicit file lock or separate per-worker files.

---

## ParquetStore

Columnar store backed by a single Parquet file. Requires `pip install 'qpubench[storage]'`.

```python
from qpubench.store import ParquetStore
import pathlib

store = ParquetStore(pathlib.Path("results/sweep.parquet"))
```

Records are flattened one level deep before writing. A `_raw_json` column stores the full JSON for lossless round-trips.

`save()` rewrites the whole file per record (Parquet files are immutable), so treat this as an **export/analysis format**: collect records during a sweep with `NDJSONStore`, then bulk-load them with `store.save_many(records)` (one rewrite total).

```python
# Flat pandas DataFrame for analysis and plotting
df = store.to_dataframe()
print(df[["molecule", "final_eigenvalue", "circuit_depth"]].describe())

# Query, column-level only: filters use flat single-underscore column
# names (not NDJSONStore's dotted __ paths); unknown columns are ignored
records = store.query(backend_name="aer_statevector")
records = store.query(result_status="succeeded")

# Load by UUID (uses _raw_json → BenchmarkRecord round-trip)
record = store.load("3f2a1b4c-...")
```

Flat column names produced from a `BenchmarkRecord`:

| Column | Source |
|---|---|
| `schema_version`, `experiment_id`, `run_id`, `timestamp` | Top-level |
| `num_qubits`, `circuit_depth`, `tags`, `notes` | Top-level |
| `circuit_computing_model`, `circuit_qubit_modality`, `circuit_format` | `circuit.*` |
| `backend_name`, `backend_provider` | `backend.*` |
| `shots`, `opt_level`, `error_mitigation` | `options.*` |
| `result_status`, `qpu_time_s`, `total_time_s` | `result.*` |
| `molecule`, `basis`, `ansatz` | `vqa.*` (inputs) |
| `final_eigenvalue`, `ground_truth` | `vqa_result.*` (computed outputs) |
| `_raw_json` | Full JSON (for `load()` round-trip) |

---

## S3Store

Object store backed by S3 or any S3-compatible endpoint. Requires `pip install 'qpubench[s3]'`.

One JSON object per record, `f"{prefix}/{experiment_id}.json"`, instead of NDJSONStore's shared append-only file. There is no read-modify-write of shared state, so concurrent writers (separate processes, machines, or a distributed sweep) do not race. Only `put_object`, `get_object`, and the `list_objects_v2` paginator are used, so it works unmodified against real AWS S3 and against S3-compatible gateways.

### AWS S3

```python
from qpubench import BenchmarkRunner, S3Store

store = S3Store(
    "my-results-bucket",
    prefix="sweeps/2026-07-06",
    region_name="eu-west-1",
    # aws_access_key_id / aws_secret_access_key are optional; omit them to
    # use the standard boto3 credential chain (env vars, ~/.aws/credentials,
    # instance role, etc.)
)
runner = BenchmarkRunner(store=store)
```

Any keyword accepted by `boto3.client("s3", ...)` can be passed through directly (`endpoint_url`, `region_name`, `aws_access_key_id`, `aws_secret_access_key`, `config=botocore.config.Config(...)`), which also makes `S3Store` work against MinIO or any other S3-compatible service. Pass an already-constructed client instead via `client=`:

```python
import boto3

store = S3Store("my-bucket", client=boto3.client("s3", endpoint_url="http://localhost:9000"))
```

### Hugging Face Storage Buckets

[Storage Buckets](https://huggingface.co/docs/hub/en/storage-buckets) expose an [S3-compatible gateway](https://huggingface.co/docs/hub/en/storage-buckets-s3) at `https://s3.hf.co/<namespace>`. `S3Store.huggingface()` sets up the required botocore `Config` (path-style addressing, single region, `ListObjectsV2`-only) for you:

```python
from qpubench import S3Store

store = S3Store.huggingface(
    bucket="my-training-bucket",
    namespace="my-username",          # or an organization name
    access_key_id="HFAK...",          # Settings → Access Tokens →
    secret_access_key="...",          #   (token) → Generate S3 credentials
    prefix="qpubench-results",
)
runner = BenchmarkRunner(store=store)
```

Generate the S3 credentials from a Hugging Face [User Access Token](https://huggingface.co/settings/tokens) with **Write** permission (its dropdown menu has a **Generate S3 credentials** action); the bucket itself must already exist (`hf buckets create my-training-bucket`, or via [huggingface_hub.create_bucket](https://huggingface.co/docs/huggingface_hub/guides/buckets)).

### Loading and querying

Identical API to `NDJSONStore`: `save()`, `load(experiment_id)`, `query(**filters)`, `all()`:

```python
record  = store.load("3f2a1b4c-...")
records = store.query(backend__name="aer_statevector", result__status="succeeded")
all_records = store.all()   # lists every object under the prefix, then fetches each
```

`query()`/`all()` list every object under the store's prefix and fetch each in turn, fine for benchmark-scale result sets, but there is no server-side filtering, so very large buckets should be partitioned by `prefix` (e.g. one prefix per `run_id`) to keep listings small.

---

## Hooks

Hooks run after every `BenchmarkRecord` is finalised but before it is saved to the store. Use them for live monitoring, intermediate logging, or side-channel metrics.

```python
def log_energy(record):
    ev  = record.result.expectation_values
    val = f"{ev[0].value:.6f}" if ev else "n/a"
    print(f"[{record.backend.name}] {record.vqa.molecule or '?'}  E={val}  "
          f"t={record.result.total_time_s:.2f}s")

runner.add_hook(log_energy)
```

Multiple hooks are called in registration order. An exception inside a hook is logged but does not abort the run or prevent persistence.

```python
# Hooks can also save intermediate state to a separate file
import json, pathlib

log_path = pathlib.Path("live_log.jsonl")

def side_log(record):
    with log_path.open("a") as f:
        f.write(json.dumps({
            "id":     record.experiment_id,
            "E":      record.result.expectation_values[0].value
                      if record.result.expectation_values else None,
            "status": record.result.status.value,
        }) + "\n")

runner.add_hook(side_log)
```

---

## Sweep + store pattern

```python
records = runner.sweep(
    circuits=[circuit_a, circuit_b],
    backend_names=["stub_gate", "aer_statevector"],
    options_list=[ExecutionOptions(shots=s) for s in [512, 2048, 8192]],
    run_id="h2_shots_sweep",
    tags=["vqe", "h2", "shots_sweep"],
)
# All 12 records (2×2×3) are saved automatically; group by run_id:
group = store.query(run_id="h2_shots_sweep")
print(f"{len(group)} records in sweep")
```
