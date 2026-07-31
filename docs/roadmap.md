# Roadmap: schema layer

**Status: planned work, nothing here is implemented.** This is the tracked
backlog for the core record format, derived from
[schema_review.md](schema_review.md) (the analysis) and mirrored one-to-one
into git-bug (the tracker).

Three documents, three jobs; don't duplicate between them:

| Document | Answers |
|---|---|
| [schemas.md](schemas.md) | What exists today, model by model |
| [schema_review.md](schema_review.md) | What is missing, and the evidence for it |
| **roadmap.md** (this file) | What to do about it, in what order |
| `git bug bug --status open` | Live status of each item |

Everything below is **additive**. No item on this list breaks a stored record,
since the schema is append-only by policy (see AGENTS.md), so these are new
optional fields, new modules, and documentation, never renames or type
changes.

---

## Tracked items

Every finding is filed as a git-bug issue labelled `schema-review`:

```sh
git bug bug --status open          # current state of all of them
git bug bug show <id>              # full context for one
```

| ID | Finding | Kind | Effort |
|---|---|---|---|
| `8da64e9` | [A4](schema_review.md#a4-circuitformat-under-specifies-openqasm): `CircuitFormat.QASM3` under-specifies the dialect | enhancement | one field |
| `c292fb6` | [A8](schema_review.md#a8-energies-carry-no-unit): energies carry no unit; `chemical_accuracy` hardcodes a Hartree threshold | enhancement | one field |
| `dd6b4ac` | [A5](schema_review.md#a5-version-metadata-is-global-where-the-upstreams-make-it-per-type): version metadata is global where upstreams make it per-type | enhancement | one field + constant |
| `44aed8a` | [B4](schema_review.md#b4-integer-encodings-for-paulis-are-a-recurring-silent-hazard): three incompatible integer encodings for Paulis; Y and Z swap silently | docs | docs only |
| `02e4944` | [B1](schema_review.md#b1-the-mirror-count-is-outrunning-the-conversion-count): mirrors outrunning conversions (11 of 32) | docs | docs + audit |
| `4ea960d` | [A7](schema_review.md#a7-vendor-names-are-still-leaking-into-core-types): vendor names still leaking into core types | docs | docs only |
| `7131e33` | [A10](schema_review.md#a10-four-timing-fields-no-stated-relationship): four timing fields, no stated relationship | docs | one docstring |
| `2ac2335` | [A3](schema_review.md#a3-simulator-runtime-is-being-smuggled-through-auth): simulator runtime smuggled through `BackendSpec.auth` | enhancement | model + factory updates |
| `c02f436` | [A6](schema_review.md#a6-four-representations-of-an-active-space): `ActiveSpaceSpec` lives in the wrong module | enhancement | move + re-export |
| `fc412a8` | [A9](schema_review.md#a9-bound-parameters-cannot-be-symbolic-and-have-no-order): `ParameterBinding` cannot be symbolic, has no defined order | enhancement | one field + docs |
| `0ff0dd6` | [B2](schema_review.md#b2-ten-escape-hatches-six-naming-conventions): ten `dict[str, Any]` escape hatches, six naming conventions | enhancement | helper + convention |
| `3f526e2` | [A1](schema_review.md#a1-there-is-no-way-to-request-noise-only-to-describe-it): no way to *request* a noise model | enhancement | **design task** |
| `0477a99` | [A2](schema_review.md#a2-nothing-records-how-counts-became-an-expectation-value): nothing records how counts became an expectation value | enhancement | **design task** |

---

## Phase 1: remove the silent-failure surface

**An afternoon. Four items, all additive, no design decisions.**

These share a property worth naming: each one currently fails *quietly*. A
wrong dialect loads somewhere and not elsewhere; a non-Hartree energy passes
`chemical_accuracy` against the wrong constant; a swapped Y/Z integer produces
a plausible wrong energy rather than an exception. None of them raise.

1. **`CircuitSpec.format_dialect: str | None`** (`8da64e9`)
   Values from `hqs_qoqo_qasm.QasmDialect`. The enum stays as-is; this is one
   optional field naming which of the five OpenQASM dialects a `serialized`
   string actually is.

2. **`VQAResult.energy_unit: str = "hartree"`** (`c292fb6`)
   Then make `chemical_accuracy` either convert or refuse a non-Hartree energy
   rather than comparing 1.6e-3 against an unknown scale.

3. **`BenchmarkRecord.min_reader_version`** (`dd6b4ac`)
   Defaulting to a module constant, bumped only on a genuinely breaking
   addition. Turns "this record is from v6.1.0" into "this record needs a
   reader ≥ v6.1.0", the question a loader actually has.
   `hqs_struqture.StruqtureSerialisationMeta.can_be_read_by()` has the full
   rule if the per-type version is ever wanted.

4. **AGENTS.md rules** (`44aed8a`, `02e4944`, `4ea960d`)
   Three short additions, all codifying existing practice rather than changing
   it:
   - never store a Pauli as an integer in a schema field; store `PauliLabel`,
     convert at the adapter boundary. Fold the existing Qrack and MBQC
     bit-order warnings into one section covering all three encodings.
   - every new mirror must provide at least one conversion into a core type,
     **or state in its module docstring why it cannot**. Both are acceptable;
     silence is not.
   - new vendor-specific fields go in `vendor_data` / `vendor_results`; the
     existing vendor-named core fields are grandfathered, not precedent.

Also here: the `QuantumResult` timing docstring (`7131e33`).

**Done when:** `pytest tests/test_docs_consistency.py` still passes, the
schema version is bumped to 6.2.0, and the four bugs are closed with the
resolution recorded in the bug body.

## Phase 2: structural tidying

**A day or two. Mechanical, but touches many call sites.**

5. **`SimulatorRuntimeSpec` on `BackendSpec`** (`2ac2335`)
   Precision, device, threads, nodes, method, memory mode.
   `questkit_quest.QuESTDeployment` / `QuESTQuregSpec` are ready-made models of
   the fields. The work is in the ~34 factory constructors that currently
   overload `auth`: `quest()`, `qrack()`, `cudaq()` at minimum. Leave `auth`
   for actual secrets. Keep the old `auth` keys populated for one version so
   stored records keep resolving.

6. **Promote `ActiveSpaceSpec` to `catalogs/active_space.py`** (`c02f436`)
   A move plus a re-export, not a redesign; everything is already re-exported
   from `qpubench.schemas`, so no import path breaks. Give the canonical type
   an optional MO-basis reference, the one thing `ASFActiveSpace` carries and
   the other three representations lose.

7. **`ParameterBinding.expression: str | None`** (`fc412a8`)
   Plus documenting that `CircuitSpec.parameters` list order defines the vector
   order for `VQAResult.convergence_parameters`. The ordering half matters more
   than the symbolic half and costs nothing.

8. **One escape-hatch convention** (`0ff0dd6`)
   A shared dump-if-`BaseModel` validator helper, and a documented split in
   `developer_guide.md` between open extension points (`*_data`, `*_results`)
   and typed-but-untyped slots (`CircuitSpec.measurement_pattern` and friends,
   stored as dicts only to keep the core import-free).

## Phase 3: the two that change what a benchmark can say

**Each deserves its own design pass. Do not bolt these on.**

9. **Noise as an input** (`3f526e2`)
   Two separable pieces:
   - `schemas/catalogs/noise_models.py`, the vocabulary. The load-bearing axis
     is *when* noise applies (continuous / on-gate / on-idle / at-readout),
     because that is what determines whether two noisy benchmarks are
     comparable, and it is the axis nothing in qpubench currently has.
   - `ExecutionOptions.noise_model: dict[str, Any] | None`, the field,
     following the existing `distributed_run_config` pattern.

   Design against all three existing shapes, which disagree:
   `hqs_struqture.StruqtureOpenSystem` (continuous-time generator),
   `hqs_qoqo.QoqoNoiseModelSpec` (five models keyed by when),
   `questkit_quest.QuESTNoiseChannel` (nine positioned discrete channels).

   Two traps to design around: off-diagonal Lindblad rates M_ij (coherences
   between decay channels) have no representation in a flat channel list, and
   `QoqoOverrotationDescription` is a *coherent* error that accumulates rather
   than averaging out; no rate or Kraus probability expresses it.

10. **Measurement derivation** (`0477a99`)
    The link between `ShotResult.counts` and `ExpectationResult.value`. Design
    against qoqo's model (`QoqoPauliZProductInput` + `QoqoPauliProductMask` +
    `QoqoExpectationRule`) rather than inventing one; it is the only mature
    version of this in the mirror set. Shape is likely an optional
    `derivation` on `ExpectationResult` or a `MeasurementPlan` on
    `CircuitSpec`.

    Note the case that motivates it beyond bookkeeping:
    `use_flipped_measurement` cancels readout asymmetry by running every basis
    twice with all qubits flipped. That is error mitigation expressed as
    measurement *structure*, so it has no `ErrorMitigationStrategy` value and
    doubles the circuit count invisibly.

---

## Not on this list, and why

- **A general operator type in the core.** Finding
  [B3](schema_review.md#b3-observables-in-the-core-are-pauli-only-and-that-is-correct)
  is a decision, not a todo: `SparsePauliObservable` stays what it is, the
  thing a quantum execution *measures*. Second-quantised, diagonal and
  dense-matrix observables belong in mirrors with an explicit conversion,
  which is what `StruqtureOperator.to_sparse_pauli_observable()` and
  `StruqtureMappedHamiltonian` now provide. The alternative would drag
  fermionic algebra into a core that has no quantum dependencies at all.
- **New `ComputingModel` / `QubitModality` values.** Finding
  [B6](schema_review.md#b6-two-axes-still-hold-up): the two axes absorbed all
  five packages in the 2026-07-29 batch without strain. No change needed.
- **Removing any of the grandfathered vendor fields.** The schema is
  append-only. `4ea960d` documents them; it does not delete them.

---

## How to close an item

Per [feedback_workflow.md](feedback_workflow.md): the bug body should say
*what changed*, that is the file, model and field, so `git bug bug show <id>` is enough on
its own, without digging through `git log`. Then:

```sh
git bug bug comment new <id> -m "Resolved in <commit>: added CircuitSpec.format_dialect …"
git bug bug status close <id>
```

Update the corresponding finding in `schema_review.md` to say it has been
applied, and strike it from the phase list here. A review document that still
lists a fixed gap is worse than no review document.
