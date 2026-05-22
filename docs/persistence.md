# Persistence

qpubench ships two stores. Both implement the `ResultStore` protocol:

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

The query matches on the `model_dump()` representation of `BenchmarkRecord`. Nested dicts use the same `__` convention, e.g. `result__expectation_values` would require a further traversal that the query engine does not yet support — load the record and filter in Python for deep nesting.

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

```python
# Flat pandas DataFrame for analysis and plotting
df = store.to_dataframe()
print(df[["molecule", "final_eigenvalue", "circuit_depth"]].describe())

# Query (same __ syntax as NDJSONStore; column-level only)
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
| `circuit_modality`, `circuit_format` | `circuit.*` |
| `backend_name`, `backend_provider` | `backend.*` |
| `shots`, `opt_level`, `error_mitigation` | `options.*` |
| `result_status`, `qpu_time_s`, `total_time_s` | `result.*` |
| `molecule`, `basis`, `ansatz`, `final_eigenvalue`, `ground_truth` | `vqa.*` |
| `_raw_json` | Full JSON (for `load()` round-trip) |

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
