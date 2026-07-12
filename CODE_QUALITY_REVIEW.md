# Code quality tracking

Living tracking document for this project's code quality: what has been
reviewed and fixed, what remains to do, and the major (breaking) refactors
that are known but deliberately deferred.

*Originally a point-in-time review (2026-07-11, commit `3566c89`, branch
`main`, reviewer: Claude Code). Fix session applied 2026-07-12 on top of
commit `05847d6`.*

---

## Current status

| Gate | Status | Enforced by |
|---|---|---|
| `pytest tests/` | ✅ 339 passed, 8 skipped (no quantum SDK needed) | CI |
| `ruff check` | ✅ 0 errors (was 63) | CI |
| `mypy --strict src/qpubench` | ✅ 0 errors (was 40) | CI |
| Doc/code numeric consistency | ✅ guarded by `tests/test_docs_consistency.py` | CI |

CI: `.github/workflows/ci.yml` — ruff + mypy strict + pytest on Python
3.11 and 3.12, on every push to `main` and every PR.

**Overall verdict (unchanged from the original review):** this is a healthy,
well-designed codebase. The architecture is genuinely simple — three
protocol-based layers (schemas / adapters / stores) with a single mandatory
dependency (`pydantic`), structural `Protocol`s instead of inheritance, SDK
imports deferred inside methods, and honest docstrings that say what is real
versus stubbed. Vendor-prefixed schema naming (`erikkjellgren_slowquant.py`)
is a good provenance convention.

---

## Major issues — breaking refactors (deferred, tracked)

These are known architectural debts. Each would break the public API or
stored data, so they belong in a dedicated breaking-change release, not a
cleanup pass.

### 1. Core schemas import vendor schemas

`circuit.py` pulls in `johnrscott_mbqc_fpga` and `dtu_photonic`;
`execution.py` pulls in `qedma_qesem`; `record.py` pulls in `advantage`.
The "stable core" therefore transitively loads vendor modules on every
import, and adding a vendor field means touching core files.

*Why deferred:* the vendor fields (`CircuitSpec.measurement_pattern`,
`CircuitSpec.photonic_circuit`, `BenchmarkRecord.advantage`, …) are public
API and appear in persisted records; decoupling requires either a plugin/
registration mechanism or dropping the fields — both breaking.

### 2. Split VQAConfig's existing vendor fields out

`VQAConfig` accumulated Cebule/Xenakis/Classiq-specific fields
(`n_layers_network`, `ga_run_id`, `classiq_synthesis_id`, …) even though the
v2.1.0 changelog says the `AlgorithmSpec` grab-bag was split for exactly this
reason.

*Mitigated (2026-07-12):* a `vendor_data: dict[str, Any]` extension point was
added — **new** vendor-only metadata goes there (keyed by vendor, e.g.
`vendor_data={"cebule": {...}}`) instead of growing the model.
*Still open:* migrating the **existing** vendor fields into `vendor_data`
breaks stored records and callers; do it together with refactor 1.

### 3. Alignment-based formatting (optional)

Column-aligned field declarations (`shots:                int | None
= None`) read nicely but every field addition re-indents whole blocks and
inflates diffs — and alignment is already inconsistent. Adopting
`ruff format` repo-wide is a one-time whole-repo churn; decide deliberately,
don't drift into it.

---

## Open ToDos

- [ ] **Implement `QrackAdapter.run`** — still a stub raising
      `NotImplementedError`. The implementation plan (Estimator + Sampler
      paths) and the Qrack-specific gotchas live in
      `integrations/qrack/IMPLEMENTATION_NOTES.md`.
- [ ] **Qibo support** — currently marked "planned" in the docs, credentials
      template, and `BackendSpec` docstring. Either build the adapter +
      schema module + extra, or drop the mentions.
- [ ] **IQM Estimator path** — blocked upstream: `iqm-client[qiskit]`
      exposes no `EstimatorV2` equivalent (as of 34.x). Revisit on SDK
      updates.
- [ ] **Extend `test_docs_consistency.py`** as new hand-stated facts appear
      in docs (it currently guards schema version and module count).

---

## Conventions to hold the line on

- **Schema version single source of truth:** `SCHEMA_VERSION` in
  `src/qpubench/schemas/record.py`. Docs reference it; the doc-consistency
  test fails if the README badge or `docs/schemas.md` header drifts.
- **No exact test/module counts in prose docs** — they drift. Say "full
  schema test suite" and let badges/tests carry the numbers.
- **New vendor VQA metadata → `VQAConfig.vendor_data`**, never new top-level
  fields (see refactor 2 above).
- **No `arbitrary_types_allowed`** in schema models (AGENTS.md rule; the one
  violation was removed).
- **Lazy SDK imports** stay inside methods; the deliberate `E402` cases are
  allowlisted per-file in `pyproject.toml` so real import-order errors still
  surface.
- **`results/` and `temporary/` are gitignored** — never commit benchmark
  outputs or scratch notes.

---

## Resolved findings (fix session 2026-07-12)

### Correctness / behavior

1. ~~`CircuitSpec.circuit_depth` is not depth~~ — **renamed to
   `total_gates`** and documented as a gate count, not a depth proxy.
   (`BenchmarkRecord.circuit_depth` is a separate, correctly-named field.)
2. ~~Documented auto-transpile does not exist~~ — `docs/backends.md` now
   states the runner does **not** call `transpile()` automatically; adapters
   that need it (IBM, IQM, Braket) invoke it inside `run()`.
3. ~~Unhelpful error for unknown backend~~ — `BenchmarkRunner.run` now raises
   `KeyError` with the unknown name and the list of registered backends.
4. ~~Self-violation of `arbitrary_types_allowed` ban~~ — removed from
   `circuit.py`; all fields were Pydantic models anyway.
5. ~~Missing `__init__.py` in `hamiltonian_sources/`~~ — added
   (docstring-only, preserving the lazy-import design).
6. **Bonus fix:** `microsoft_qdk.py`'s `_params_match_type` validator
   computed the expected parameter block but never compared it — a Hubbard
   block on an Ising `hamiltonian_type` passed silently. Now rejected.

### Simplicity / layering

7. ~~Duplicated query logic~~ — `NDJSONStore.query` and `S3Store.query` share
   one `_matches()` helper. (Note: `ParquetStore.query` semantics still
   differ by design — flat column names, unknown filters ignored — and are
   now documented as such in `docs/persistence.md`.)
8. ~~`ParquetStore.save` is O(n²)~~ — documented as an export/analysis
   format; `save_many()` added for single-rewrite batch loads.
9. ~~Dead `model_config = pydantic.ConfigDict()`~~ — removed from
   `record.py`.
10. ~~Shipped stub adapter with 90-line pseudocode docstring~~ — pseudocode
    moved to `integrations/qrack/IMPLEMENTATION_NOTES.md`; the stub carries a
    short pointer docstring.

### Hygiene

11. ~~ruff: 63 errors~~ — 0. Unused imports removed, `l` → `line` renames,
    `PauliLabel.I` noqa'd, per-file `E402` ignores for deliberate lazy
    imports.
12. ~~mypy strict failing (40 errors)~~ — 0. Per-module
    `ignore_missing_imports` overrides in `pyproject.toml` for untyped
    optional SDKs; stale inline ignore codes fixed; `qml.qnode` decorator
    sites annotated.
13. ~~Committed files that shouldn't be~~ — `results/mbqc_example.ndjson`
    and `temporary/Feedback_*.txt` untracked; `results/` and `temporary/`
    gitignored.
14. ~~No CI enforcement~~ — GitHub Actions workflow added (see status table).

### Documentation

15. ~~Schema version drift~~ (code said 2.3.0 *and* 2.7.0; README 2.3.0;
    AGENTS.md 1.11.0; docs 2.7.0) — unified to **2.7.0**, single source in
    `record.py`, guarded by `tests/test_docs_consistency.py`.
16. ~~Module count drift~~ (31 / 36 / 19 across docs; actual 38) — corrected
    everywhere including presentation slides; guarded by the same test.
17. ~~Stale test counts ("156")~~ — replaced with non-drifting phrasing.
18. ~~docs/backends.md stale about its own adapters~~ — PennyLane Lightning
    and Mitiq ZNE listed as real adapters; support matrix updated.
19. ~~docs/schemas.md stale enum tables~~ — `ErrorMitigationStrategy`
    (15 values), `CebuleTaskType` (28), `CircuitFormat` (+`QMOD`), and the
    `CircuitSpec` table (+`photonic_circuit`) updated.
20. ~~docs/persistence.md wrong Parquet column~~ — `circuit_modality` →
    `circuit_computing_model` + `circuit_qubit_modality`.
21. ~~`.env.example` rejected IBM channel~~ — now
    `ibm_channel="ibm_quantum_platform"`; Cebule `EMAIL`/`PASSWORD` added;
    `docs/installation.md` sample synced to the actual file.
22. ~~README repo-layout stale snapshot~~ — now lists
    `hamiltonian_sources/`, `tensor_network/`, `observability.py`, the real
    backend adapters, and all integration directories.
23. ~~Qibo vaporware~~ — marked "planned" in docs, `.env.example`, and
    `BackendSpec` docstring (full support tracked in Open ToDos).

---

## Earlier session changes (2026-07-11, separate from findings)

- **License**: `LICENSE` replaced with canonical GNU LGPL v3 text; `COPYING`
  added with GPL v3 (the LGPL incorporates it by reference);
  `pyproject.toml` classifier, `conda-recipe/meta.yaml`, and README badge +
  license section updated. Prior git history remains MIT for anyone who
  cloned earlier; relicensing applies going forward.
- **GitHub Pages**: `docs/index.md` (new-user onboarding front page) and
  `docs/_config.yml` (Cayman theme + `jekyll-relative-links`). Enable via
  repo Settings → Pages → deploy from branch `main`, folder `/docs`.
