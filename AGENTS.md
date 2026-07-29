# AGENTS.md — QPUBench

Modality-agnostic quantum benchmark framework. Pydantic v2 schema layer with zero quantum SDK dependencies in the core package. The schema version lives in `src/qpubench/schemas/record.py` (`SCHEMA_VERSION`).

## Stack

- Python ≥ 3.11 · Pydantic ≥ 2.0 (only mandatory runtime dep)
- Build: hatchling (PEP 517) · Package mgmt: uv / pip / Poetry 2 / conda
- Linting: ruff (line-length 100, target py311) · Types: mypy (strict) · Tests: pytest

## Commands

```sh
# Install (dev)
uv sync                         # preferred — installs package + dev group
pip install -e "." --group dev  # fallback

# Test
pytest tests/                   # full schema test suite (no quantum SDK needed)
pytest tests/test_schemas.py -k "pauli"   # single file, filtered

# Lint / format / type-check
ruff check src/ tests/
ruff format src/ tests/
mypy src/
```

Run `ruff check` and `mypy src/` before committing. Tests must pass without any quantum SDK installed.

## Architecture

```
src/qpubench/
├── schemas/       ← core record format (7 modules) — the stable core
│   ├── catalogs/  ← cross-cutting catalogues & registries
│   └── mirrors/   ← one module per mirrored external project
├── backends/      ← BackendAdapter + AlgorithmAdapter protocols + stubs
├── runner.py      ← BenchmarkRunner (run, sweep, hooks, dual-protocol dispatch)
└── store.py       ← NDJSONStore, ParquetStore, ResultStore protocol

integrations/      ← NOT installed; copy into your project
examples/          ← Runnable demos
tests/             ← Schema-only unit tests
```

`BackendAdapter` — caller provides a `CircuitSpec`, adapter executes it, returns `QuantumResult`.
`AlgorithmAdapter` — adapter generates its own circuit from a problem spec, returns `(QuantumResult, VQAConfig, VQAResult)` — inputs in `VQAConfig`, computed outputs in `VQAResult`. Detected by the runner via `isinstance()`.

Why the code uses Protocols, deferred SDK imports, `_`-prefixed modules and
the `<maintainer>_<package>.py` schema naming: [docs/developer_guide.md](docs/developer_guide.md).

## Critical constraints — never violate these

- **No quantum SDK imports inside `src/qpubench/`**. Only adapters (in your project or `integrations/`) import external SDKs. The test suite must pass with `pip install .` alone.
- **Never change a schema field name or type without bumping `schema_version`** in `src/qpubench/schemas/record.py`. Existing stored records break silently otherwise.
- **Pauli encoding is non-standard for Qrack**: I=0, X=1, **Z=2, Y=3** (Q# convention). Always use `PauliLabel.to_qrack_int()`, never raw integers.
- **MBQC byproduct register bit order**: bit 0 = Z, bit 1 = X — reversed from gate-based convention. See `schemas/mirrors/johnrscott_mbqc_fpga.py`.
- **`AlgorithmAdapter` detection is duck-typed**: your class must have both `validate_problem` and `run_algorithm` methods, or the runner silently falls through to the `BackendAdapter` path.

## Adding a new schema module

1. Create the module in the right group: `schemas/` for a core record type,
   `schemas/catalogs/` for a catalogue over several upstreams, or
   `schemas/mirrors/<org>_<package>.py` to mirror one external project.
2. Export new public types from `src/qpubench/__init__.py`.
3. Add tests in `tests/test_schemas.py` — no mocking of quantum SDKs.
4. Update the schema version string and the table in `docs/schemas.md`.

Do **not** add `model_config = ConfigDict(arbitrary_types_allowed=True)` — all schema fields must be JSON-serialisable by default.

## Adding a new adapter

Copy `integrations/template/backend_adapter_template.py` or `algorithm_adapter_template.py`.
Move SDK imports inside the methods that use them — never at module level — so importing the adapter without the SDK installed doesn't raise `ImportError`.

```python
# Good
def run(self, circuit, options):
    import qiskit_aer  # deferred import

# Bad — breaks `pip install .` users
import qiskit_aer
```

## Testing adapters

Mock the external library at the import level; do not require the SDK in CI:

```python
with patch("my_adapter.my_library", MagicMock()) as mock_lib:
    mock_lib.solve.return_value = -2.9003
    record = runner.run(mol_spec, "mine", ExecutionOptions())
assert record.result.status == JobStatus.SUCCEEDED
```

See `docs/backends.md` (writing adapters, mocking the SDK for tests) for the full pattern.

## Tracking feedback and follow-ups

External feedback (reviews, bug reports) is tracked with
[git-bug](https://github.com/git-bug/git-bug) — bugs are git objects
(`refs/bugs/*`), not a separate service, and bridge to GitHub Issues for
collaborators who don't use git-bug. See `docs/feedback_workflow.md` for
setup and the intake convention (one bug per discrete point, labeled,
closed with the resolution recorded). Run `git bug bug` to see current
open/closed items.

## What not to do

- Don't create migration scripts or version-conversion code — the schema is append-only; add new optional fields instead of changing existing ones.
- Don't add `print()` statements to `src/qpubench/` core; use `logging.getLogger(__name__)`.
- Don't commit result files (`results/*.ndjson`, `*.parquet`) — they are gitignored.
- Don't use `git push --force` on `main`.
