# Repository review — code quality, simplicity, and documentation

*Date: 2026-07-11 · Reviewed at commit `3566c89` (branch `main`) · Reviewer: Claude Code*

Scope: full review of `src/`, `tests/`, `integrations/`, `examples/`, and all
documentation, plus `ruff check`, `mypy --strict`, and a full `pytest` run
(333 passed, 8 skipped). Companion changes made in the same session:
license switched from MIT to LGPL-3.0-or-later, and a GitHub Pages
onboarding site added (`docs/index.md` + `docs/_config.yml`).

---

## Overall verdict

**This is a healthy, well-designed codebase.** The architecture is genuinely
simple — three protocol-based layers (schemas / adapters / stores) with a
single mandatory dependency (`pydantic`), structural `Protocol`s instead of
inheritance, SDK imports deferred inside methods, and honest docstrings that
say what is real versus stubbed. Tests run without any quantum SDK, and the
vendor-prefixed schema naming (`erikkjellgren_slowquant.py`) is a good
provenance convention. The findings below are improvements, not alarms.

---

## Code quality findings

### Correctness / behavior

1. **`CircuitSpec.circuit_depth` is not depth** —
   `src/qpubench/schemas/circuit.py:127` returns
   `sum(gate_counts.values())`, i.e. total **gate count**. The docstring and
   `docs/schemas.md` both call it a depth proxy, but for wide circuits it
   overstates depth badly. Rename it (`total_gates`) or document it as gate
   count.

2. **Documented auto-transpile does not exist** — `docs/backends.md:37`
   claims "The runner will call `transpile()` automatically if present", but
   `BenchmarkRunner` never references `TranspilableBackend`
   (`runner.py` has no such dispatch). Either implement the auto-call or fix
   the doc.

3. **Unhelpful error for unknown backend** — `BenchmarkRunner.run`
   (`src/qpubench/runner.py:78`) raises a bare `KeyError` for an
   unregistered backend name. A message listing registered names would save
   users real time.

4. **Self-violation of a stated constraint** — `circuit.py:59` sets
   `model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)`, which
   `AGENTS.md:62` explicitly forbids. All fields there are Pydantic models,
   so the flag looks removable.

5. **Missing `__init__.py`** — `src/qpubench/hamiltonian_sources/` has no
   `__init__.py` while every sibling package does. It works as a namespace
   package, but it is inconsistent and can confuse tooling (mypy strict,
   some packagers).

### Simplicity / layering

6. **Core schemas import vendor schemas** — `circuit.py` pulls in
   `johnrscott_mbqc_fpga` and `dtu_photonic`; `execution.py` pulls in
   `qedma_qesem`; `record.py` pulls in `advantage`. The "stable core"
   therefore transitively loads vendor modules on every import, and adding a
   vendor field means touching core files.

7. **`VQAConfig` has re-grown into a grab-bag** —
   `src/qpubench/schemas/record.py` accumulates Cebule/Xenakis/Classiq-
   specific fields even though the v2.1.0 changelog says the `AlgorithmSpec`
   grab-bag was split for exactly this reason. A generic
   `vendor_data: dict` extension point (or per-vendor sub-models) would stop
   the core from accreting.

8. **Duplicated query logic** — the double-underscore `query()` filter logic
   is duplicated verbatim between `NDJSONStore.query` (`store.py:73`) and
   `S3Store.query` (`store.py:271`). A small shared helper would keep the
   three stores' semantics from drifting — ParquetStore's already differ
   (single-underscore column names; unknown filters silently ignored).

9. **`ParquetStore.save` is O(n²)** — it rewrites the entire file per record
   (read → concat → write, `store.py:124-130`). For sweeps this is quadratic
   I/O. Batch writes, or document it as an export format rather than a live
   store.

10. **Dead line** — `record.py:116` has an empty
    `model_config = pydantic.ConfigDict()`.

11. **Shipped stub adapter** — `QrackAdapter.run` is a
    `NotImplementedError` stub carrying a ~90-line pseudocode docstring
    (`qrack_adapter.py:94-187`). The docs are honest about this, but a stub
    installed next to seven real adapters is a trap; consider moving the
    pseudocode to an issue or `integrations/`.

### Hygiene

12. **ruff: 63 errors** — 31 unused imports (mostly `tests/` and
    `integrations/`; 7 in `qrack_adapter.py`), 25
    module-import-not-at-top-of-file (mostly deliberate lazy-import
    patterns — worth `# noqa` or per-file ignores so real errors stand
    out), 1 redefinition, 2 unused variables, 4 ambiguous names
    (`PauliLabel.I` is legitimately named — noqa it).

13. **mypy strict is configured but failing** — 40 errors, all missing-stub
    noise from optional SDKs plus two stale `type: ignore` codes
    (`store.py:223,294` — should be `[import-untyped]`, not
    `[import-not-found]`) and two untyped-decorator hits in
    `pennylane_lightning_adapter.py`. Add per-module
    `ignore_missing_imports` overrides to `pyproject.toml` so the strict
    gate is actually passable.

14. **Committed files that shouldn't be** — `results/mbqc_example.ndjson`
    (AGENTS.md itself says result files "are gitignored" — they are not;
    `.gitignore` has no `results/` entry) and `temporary/Feedback_1.txt` /
    `temporary/Feedback_2.txt`.

15. **No CI enforcement** — `AGENTS.md` asks for `ruff check` and `mypy`
    before committing, but nothing enforces it. A minimal GitHub Actions
    workflow (pytest + ruff) would prevent regression.

16. **Alignment-based formatting** — column-aligned field declarations
    (`shots:                int | None              = None`) read nicely but
    every field addition re-indents whole blocks and inflates diffs — and
    alignment is already inconsistent (e.g. `primitives.py:159-165`).
    `ruff format` has never been run consistently.

---

## Documentation findings

The docs are unusually good on substance — honest about stubs and gaps,
verified against installed SDK versions. The problem is **numeric drift**:
the same facts are stated in many places and almost every copy has a
different value.

### Conflicting facts across documents

| Claim | README | docs/schemas.md | AGENTS.md | Actual |
|---|---|---|---|---|
| Schema version | 2.3.0 (badge + 3 places) | 2.7.0 | 1.11.0 | `record.py:14` says **2.3.0**, but `primitives.py:99` says "as of schema v2.7.0" — the code disagrees with itself |
| Schema module count | 31 | 36 | 19 | **38** |
| Test count | 156 (×2) | — | 156 | **341 collected / 313 test functions** |

### Specific stale content

- **docs/backends.md is stale about its own adapters**: the "real adapters"
  section (lines 59-73) lists only aer/braket/ibm/iqm, and the support
  matrix says PennyLane = "Copy template" (line 215) — but
  `pennylane_lightning_adapter.py` and `unitaryfund_mitiq_adapter.py` are
  real, exported, and tested.
- **docs/schemas.md enum tables are stale**: `ErrorMitigationStrategy` shows
  6 values (code has 15), `CebuleTaskType` shows 4 (code has ~30),
  `CircuitFormat` is missing `QMOD`, and the `CircuitSpec` field table omits
  `photonic_circuit`.
- **docs/persistence.md:88** documents a `circuit_modality` Parquet column;
  the code writes `circuit_computing_model` and `circuit_qubit_modality`
  (`store.py:333-334`).
- **`.env.example` vs docs**: `.env.example` has
  `ibm_channel="ibm_quantum"`, which `backend.py:109-113` itself documents
  as now **rejected** by qiskit-ibm-runtime (must be
  `ibm_quantum_platform`). Also `docs/installation.md:132-152` shows a
  `.env` with Cebule `EMAIL`/`PASSWORD` that isn't in the actual
  `.env.example`, which instead has `qrack_device_id` /
  `mbqc_bitstream_path`.
- **README repo-layout section** is a stale snapshot: says 31 schema
  modules, omits `hamiltonian_sources/`, `tensor_network/`,
  `observability.py`, the seven real backend adapters, and the
  `examples/guides|demos|tutorials` tree (43 example files, not 3).
- **Qibo is vaporware in the docs**: it appears in credentials,
  `BackendSpec` docstrings, and the support matrix, but has no adapter, no
  schema module, and no extra — either add a "planned" marker or drop it.

### Structural suggestion

These counts drift because they are hand-maintained in five places. Either
derive them (a doc-check test that greps `SCHEMA_VERSION` and the module
count against the docs) or state each fact in exactly one place and link to
it everywhere else.

### What was checked and found fine

- All relative links in `docs/*.md` and `README.md` resolve (including the
  17 detail pages in `docs/integrations/`).
- `docs/compatibility.md` conventions (Qrack Pauli ints, MBQC bit order)
  match the code.
- The README quick-start example was executed verbatim and works.

---

## Session changes (already applied, separate from findings)

- **License**: `LICENSE` replaced with canonical GNU LGPL v3 text; `COPYING`
  added with GPL v3 (the LGPL incorporates it by reference);
  `pyproject.toml` classifier, `conda-recipe/meta.yaml`, and README badge +
  license section updated. Note: prior git history remains MIT for anyone
  who cloned earlier; relicensing applies going forward.
- **GitHub Pages**: `docs/index.md` (new-user onboarding front page) and
  `docs/_config.yml` (Cayman theme + `jekyll-relative-links`). Enable via
  repo Settings → Pages → deploy from branch `main`, folder `/docs`.
