# Cross-schema review — what 32 mirrors have taught the core

Written 2026-07-29, after adding the HQS stack (struqture, qoqo, qoqo_qasm,
ActiveSpaceFinder) and QuEST. Those five were unusually informative because
they are *narrow*: each does one thing that no framework-shaped package
bothers to isolate, which makes the gaps in qpubench's core visible in a way
that broad SDKs do not.

This document is an assessment, not a change log. Nothing here has been
applied to the core schemas — the point is to decide what should be, and in
what order. Findings are ranked by how much they cost to leave alone.

Every finding below is filed as a git-bug issue labelled `schema-review`
(`git bug bug --status open`), and sequenced into phases in
[roadmap.md](roadmap.md). This document holds the *evidence*; the roadmap
holds the *plan*; git-bug holds the *status*. When a finding is applied, say
so here as well as closing its bug — a review that still lists a fixed gap is
worse than no review.

Contents:

- [A. Findings on the core record format](#a-findings-on-the-core-record-format)
- [B. General patterns across the mirror layer](#b-general-patterns-across-the-mirror-layer)
- [C. Suggested order of work](#c-suggested-order-of-work)

---

## A. Findings on the core record format

### A1. There is no way to *request* noise, only to describe it

*Tracked as `3f526e2` — `git bug bug show 3f526e2`*

**Severity: high. This is the largest single gap.**

`BackendSpec.qubit_characteristics` records T1, T2 and readout error — a
property a real device *has*. Nothing anywhere lets a caller say "simulate
this circuit under this noise model". `ExecutionOptions` has
`error_mitigation` (how to *remove* noise) and no counterpart for adding it.

The five new upstreams make this hard to ignore, because three of them model
noise as a first-class input and they do not agree on the shape:

| Package | Form | Positioned? |
|---|---|---|
| struqture `LindbladOpenSystem` | continuous-time generator; rates keyed by an ordered pair (L_i, L_j) | no — it is a generator |
| qoqo `QoqoNoiseModelSpec` | five models keyed by *when* noise applies: continuous / on-gate / on-idle / at-readout / overrotation | yes, via in-circuit PRAGMAs |
| QuEST `QuESTNoiseChannel` | nine discrete `mix*` channels | yes, by call position |

And they were already implicit elsewhere: Qiskit Aer noise models, Mitiq's
noise-scaling, QESEM's device characterisation, `quantum_motion_hardware`.

Two things are missing, and they are separable:

1. **A vocabulary.** The "when" axis (continuous / on-gate / on-idle /
   at-readout) is the one nothing in qpubench has, and it is exactly the axis
   that determines whether two noisy benchmarks are comparable. A
   `schemas/catalogs/noise_models.py` would sit alongside
   `catalogs/fragmentation.py` and `catalogs/distributed_execution.py` — the
   established shape for a cross-cutting vocabulary that several mirrors
   specialise.
2. **A field to put it in.** `ExecutionOptions.noise_model: dict[str, Any] |
   None`, following the exact pattern already used by
   `distributed_run_config` (accept a model, store its dump, rehydrate
   explicitly). Additive; no version break.

One subtlety worth capturing in that vocabulary: `QoqoOverrotationDescription`
is a *coherent* error — a miscalibrated rotation accumulates over repetitions
instead of averaging out, and no Lindblad rate or Kraus probability expresses
it. A noise vocabulary that only has stochastic channels will silently fail to
represent it.

### A2. Nothing records how counts became an expectation value

*Tracked as `0477a99` — `git bug bug show 0477a99`*

**Severity: high.**

A `BenchmarkRecord` can hold `ShotResult.counts` and
`ExpectationResult.value` side by side and states no relationship between
them. The derivation — which basis rotations ran, which qubits each Pauli
product spans, what linear combination produced the energy — is entirely
outside the schema.

qoqo makes it explicit and typed (`QoqoPauliZProductInput` +
`QoqoExpectationRule`), which is what surfaced this. The consequence of the
gap is concrete: two records reporting the same energy for the same
Hamiltonian may have used different groupings, different shot allocations
across groups, or different readout-error handling, and nothing in the record
distinguishes them.

`QoqoPauliZProductInput.use_flipped_measurement` is a good example of what
falls through: it cancels readout asymmetry by running every basis twice with
all qubits flipped. That is error mitigation expressed as *measurement
structure* rather than as a post-processing pass, so it has no
`ErrorMitigationStrategy` value and doubles the circuit count invisibly.

Suggested shape: an optional `derivation` on `ExpectationResult`, or a core
`MeasurementPlan` on `CircuitSpec`. Worth designing against qoqo's model
rather than inventing one — it is the only mature version of this in the
mirror set.

### A3. Simulator runtime is being smuggled through `auth`

*Tracked as `2ac2335` — `git bug bug show 2ac2335`*

**Severity: medium-high. The QuEST factory added in this batch follows the
existing pattern deliberately, rather than diverging from it quietly — the
point was to make the pattern visible, not to entrench it.**

<a id="simulator_runtime"></a>

`BackendSpec` has `auth: dict[str, str]`, documented as "provider-specific
credentials as opaque strings". It has been carrying non-credentials for a
while (`BackendSpec.qrack(gpu=...)` writes `auth={"gpu": "True"}`,
`cudaq(target=...)` writes `auth={"target": ...}`), and the new
`BackendSpec.quest()` factory writes precision, density-matrix mode, GPU and
node count there too.

QuEST is what makes this untenable, because its runtime axes are not
decoration:

- **deployment** — OpenMP × CUDA/HIP × MPI × cuQuantum, independently
  combinable; a distributed run's timing is not comparable to a single-node
  one at the same qubit count
- **precision** — `FLOAT_PRECISION` 1/2/4, compile-time; a single-precision
  run reporting agreement to 1e-8 is reporting noise
- **memory mode** — state vector (2ⁿ) vs density matrix (4ⁿ)

None of that is a credential, and stringly-typing it into `auth` means it
cannot be validated, compared or aggregated. It also affects Aer (`method`,
`device`), Qrack, cuQuantum and PennyLane-Lightning — QuEST is just the first
upstream honest enough to enumerate all of it.

Suggested: a typed `SimulatorRuntimeSpec` on `BackendSpec` (precision, device,
threads, nodes, method, memory mode), leaving `auth` for actual secrets.
`QuESTQuregSpec` is a ready-made model of the fields.

### A4. `CircuitFormat` under-specifies OpenQASM

*Tracked as `8da64e9` — `git bug bug show 8da64e9`*

**Severity: medium. Cheapest fix on this list.**

`CircuitFormat.QASM3` treats OpenQASM 3.0 as one format. qoqo_qasm's
`QasmVersion` is a version *and* a dialect — `3.0Vanilla`, `3.0Roqoqo`,
`3.0Braket` — and the same circuit emits materially different text under each.
Two records can both claim `format=QASM3` while one is portable and the other
only loads under Braket.

Worse, the Vanilla dialects *drop* pragmas: a circuit carrying
`PragmaDamping` translates successfully into QASM3 and describes a noiseless
experiment. `QoqoQasmTranslationResult` splits `succeeded` from `is_faithful`
for exactly this reason.

Suggested: `CircuitSpec.format_dialect: str | None`. One optional field; the
enum stays as-is.

### A5. Version metadata is global where the upstreams make it per-type

*Tracked as `dd6b4ac` — `git bug bug show dd6b4ac`*

**Severity: medium. Conceptually the most interesting finding.**

qpubench has one monotone `SCHEMA_VERSION` plus an append-only policy
(AGENTS.md: "add new optional fields instead of changing existing ones").
That works, but it means a stored record says only *when* it was written, not
*what a reader needs to understand it*.

Both HQS packages solved this the same way, independently:

- struqture embeds `{type_name, min_version, version}` in every serialised
  object and refuses a load when the reader's major differs from the writer's
  declared minimum, or its minor is older
- every qoqo type exposes `current_version()` and `min_supported_version()`

The win is that the contract is *per type*: adding a field to one type does
not invalidate stored payloads of every other type, and a payload only demands
the version it actually needs. `type_name` is deliberately a free string, not
an enum, so a payload from a *newer* library still parses far enough to
produce a useful error.

qpubench does not need the full scheme. The cheap 80% is one additive field:
`BenchmarkRecord.min_reader_version`, defaulting to a constant bumped only
when a genuinely breaking addition lands. That turns "this record is from
v6.1.0" into "this record needs a reader ≥ v6.1.0", which is the question a
loader actually has.

`StruqtureSerialisationMeta.can_be_read_by()` implements the rule if it is
ever wanted wholesale.

### A6. Four representations of an active space

*Tracked as `c02f436` — `git bug bug show c02f436`*

**Severity: medium. Not a bug — a naming/discoverability problem.**

Adding ActiveSpaceFinder made this the fourth:

| Where | Type | What it holds |
|---|---|---|
| record level | `VQAConfig.active_electrons` / `.active_orbitals` | the two numbers |
| chosen space | `bestquark_gsopt.ActiveSpaceSpec` | occupied + active MO indices |
| one selector | `microsoft_qdk.ActiveSpaceSelectionConfig` / `…Result` | spin-resolved alpha/beta indices |
| selection provenance | `hqs_active_space_finder.ASFActiveSpace` | indices **plus the MO basis they refer to** |

They genuinely sit at different pipeline stages, so collapsing them would lose
information. But `ActiveSpaceSpec` living in `bestquark_gsopt` is wrong: it is
not GSOpt-specific, and a caller looking for "the active space type" will not
find it there. Promoting it to `schemas/catalogs/active_space.py` and having
the mirrors convert into it is a rename, not a redesign.

ASF also contributes a correctness point the other three miss: orbital indices
are meaningless without the orbitals. The MP2-natural-orbital step reorders and
remixes MOs, so index 7 in an ASF result is not index 7 in the preceding SCF.
`ASFActiveSpace.mo_coeff_ref` records the link; nothing else does.

### A7. Vendor names are still leaking into core types

*Tracked as `4ea960d` — `git bug bug show 4ea960d`*

**Severity: medium. Regression pressure, not a defect.**

`VQAConfig.vendor_data` and `QuantumResult.vendor_results` were added as the
extension point precisely so vendor fields would stop accreting on core
models. The pre-existing ones were never retired, and because the schema is
append-only they cannot be — but they are now a template that invites more:

- `VQAConfig.n_layers_network` / `n_layers_circuit` — "Cebule TN depth"
- `VQAConfig.ga_run_id` / `genome_hash` — Xenakis
- `VQAConfig.classiq_synthesis_id` — Classiq
- `VQAResult.best_complexity` — "Xenakis complexity score"
- `QuantumResult.wall_budget_seconds` — "(GSOpt)"
- `ErrorMitigationStrategy` — 11 of its 15 values are vendor names

Suggested: state the rule explicitly in AGENTS.md ("new vendor-specific fields
go in `vendor_data` / `vendor_results`; the existing ones are grandfathered")
and mark the grandfathered fields as such in their docstrings. No code change.

### A8. Energies carry no unit

*Tracked as `c292fb6` — `git bug bug show c292fb6`*

**Severity: low, but the failure mode is silent.**

`VQAResult.final_eigenvalue`, `hf_energy`, `fci_energy`, `ground_truth`,
`bestquark_gsopt.REFERENCE_ENERGIES` and every mirror's energy field are
Hartree *by convention*. Nothing states it, and `chemical_accuracy` hardcodes
`1.6e-3` — which is only the 1 kcal/mol threshold if the energy is in Hartree.

Contrast the coordinate fields, which do carry units:
`microsoft_qdk.MoleculeStructureSpec.units`, `pyscf_pyscf` `unit="angstrom"`,
`molssi_qcschema.QCMolecule` (Bohr, documented). And `catalogs/reactions.py`
carries Cantera's explicit `units:` block.

Suggested: `energy_unit: str = "hartree"` on `VQAResult`. Additive, and makes
`chemical_accuracy` honest.

### A9. Bound parameters cannot be symbolic, and have no order

*Tracked as `fc412a8` — `git bug bug show fc412a8`*

**Severity: low-medium.**

`ParameterBinding` is name → float. Both HQS packages are strictly richer:
qoqo gate arguments are `CalculatorFloat` (number or expression string) and
struqture coefficients are `CalculatorComplex`. A circuit with free
expressions is a valid, storable object in both.

The subtler half is ordering. `QoqoQuantumProgramSpec.input_parameter_names`
is an *ordered* list, which is what makes "the same function called with a
different vector" expressible. `parameter_bindings` is name-keyed and
therefore order-free — fine for one bind, but it cannot express the shape
every variational outer loop actually has, which is why
`VQAResult.convergence_parameters` is a bare `list[list[float]]` with no
statement of what position i means.

Suggested: `ParameterBinding.expression: str | None` (additive), and document
that `CircuitSpec.parameters` list order defines the vector order for
`convergence_parameters`.

### A10. Four timing fields, no stated relationship

*Tracked as `7131e33` — `git bug bug show 7131e33`*

**Severity: low.**

`QuantumResult` has `qpu_time_s`, `total_time_s`, `wall_seconds` and
`wall_budget_seconds`. The names do not say how they relate, and
`total_time_s` vs `wall_seconds` in particular reads as the same quantity
twice. Worth one docstring paragraph rather than a schema change.

---

## B. General patterns across the mirror layer

These are observations about the schema layer as a whole, now that it is 32
mirrors and 9 catalogues.

### B1. The mirror count is outrunning the conversion count

*Tracked as `02e4944` — `git bug bug show 02e4944`*

11 of 32 mirrors define any conversion into a core type (`to_circuit_spec`,
`to_backend_spec`, `to_quantum_result`, `to_vqa_config`,
`to_sparse_pauli_observable`, …). Four of those 11 are from this batch.

That ratio matters because a mirror with no conversion is a *documented
format*, not an integration: it records what an upstream produces, but nothing
in a `BenchmarkRecord` can compare it to anything else. The value of the
schema layer is concentrated in the conversion functions, not in the mirrors.

Suggested rule for `AGENTS.md`: **every new mirror must either provide at
least one conversion into a core type, or state in its module docstring why it
cannot.** Some genuinely cannot — `questkit_quest` says outright that a QuEST
run has no serialisable circuit, and `hqs_qoqo_qasm` is a translation-config
model with nothing to convert. Saying so is the deliverable; saying nothing is
the failure.

### B2. Ten escape hatches, six naming conventions

*Tracked as `0ff0dd6` — `git bug bug show 0ff0dd6`*

Across five core models:

```
VQAConfig.vendor_data                dict[str, Any]
QuantumResult.vendor_results         dict[str, Any]
QuantumResult.metadata               dict[str, Any]
AlgorithmSpec.extra_params           dict[str, Any]
ExecutionOptions.mitigation_options  dict[str, Any]
ExecutionOptions.distributed_run_config   dict[str, Any] | None
CircuitSpec.measurement_pattern      dict[str, Any] | None
CircuitSpec.photonic_circuit         dict[str, Any] | None
CircuitSpec.fragmentation            dict[str, Any] | None
CircuitSpec.distribution             dict[str, Any] | None
```

Each has its own `mode="before"` validator doing the same
`model_dump()`-if-BaseModel dance, in four near-identical copies. The four
`CircuitSpec` slots are a different *kind* of thing from the others — they are
typed slots that happen to be stored untyped, rather than open extension
points — and the naming does not distinguish them.

Suggested: one shared validator helper, and a documented two-way split —
`*_data` / `*_results` for open extension, named slots for
"one specific schema, stored as a dict to keep the core import-free".
Cosmetic, but the layer is now large enough that a newcomer cannot infer the
rule from the names.

### B3. Observables in the core are Pauli-only, and that is correct

Worth writing down as a decision rather than leaving it as an accident. The
mirror set now contains at least four other observable forms:

- struqture's four algebras (spins, bosons, fermions, mixed), pre-mapping
- QuEST's `FullStateDiagMatr` (diagonal in the computational basis)
- qoqo's `CheatedInput` — arbitrary sparse matrices in the computational basis
- `microsoft_qdk.FermionicHamiltonianSpec`, `mqsdk_qse`, `molssi_qcschema`

`SparsePauliObservable` should stay what it is: the thing a *quantum execution
measures*. Everything upstream of the qubit mapping belongs in a mirror, with
an explicit conversion — which is what `StruqtureOperator.to_sparse_pauli_observable()`
and `StruqtureMappedHamiltonian` now provide. The alternative (a general
operator type in the core) would drag second-quantised algebra into a package
whose core has no quantum dependencies at all.

### B4. Integer encodings for Paulis are a recurring, silent hazard

*Tracked as `44aed8a` — `git bug bug show 44aed8a`*

Three incompatible schemes now appear in one package:

| Convention | I | X | Y | Z |
|---|---|---|---|---|
| Qrack / Q# (`PauliLabel.to_qrack_int`) | 0 | 1 | **3** | **2** |
| QuEST base-4 (`QuESTPauliStr.to_base4_masks`) | 0 | 1 | **2** | **3** |
| Qiskit C bit-packed (`to_qiskit_c_bit_term`) | 0 | 0b0010 | 0b0011 | 0b0001 |

Y and Z swap between the first two. The failure mode is a plausible-looking
wrong energy, not an exception. AGENTS.md already calls out the Qrack case as
a critical constraint; it should now name all three, and the rule should be
generalised: **never store a Pauli as an integer in a schema field** — store
`PauliLabel` and convert at the adapter boundary. Both existing conversions
follow this; it should be stated so the next one does too.

Bit-order has the same shape and is already flagged for MBQC (byproduct
register: bit 0 = Z, bit 1 = X) and Qiskit (`to_qiskit_pauli_list` reverses).
Same rule, same reason.

### B5. The "when", not the "what", is what makes runs comparable

A theme running through A1, A2 and A4. In each case qpubench captures *what*
happened and loses *when*:

- noise: which channels, not where in the circuit they were applied
- measurement: the value, not the basis rotations and combination that made it
- QASM: the text, not whether pragmas survived the translation into it

qoqo is the counterexample throughout, because its design decision — put
directives in the circuit as ordered operations — preserves position by
construction. If one idea from this batch is worth importing into the core, it
is that one.

### B6. Two axes still hold up

`ComputingModel` × `QubitModality` absorbed all five new packages without
strain: struqture is paradigm-agnostic (it is algebra), qoqo and qoqo_qasm are
`GATE_BASED` on any modality, ASF is classical chemistry (both axes `—`), and
QuEST is `GATE_BASED` with no modality. No new enum value was needed anywhere,
which after 32 mirrors is a reasonable signal the axes are the right ones.

The `AlgorithmFamily` docstring's honesty note still holds too: `ADAPT_VQE` is
the only family with more than one registered adapter. Nothing in this batch
changed that — none of the five ship an algorithm — but B1 is the more useful
framing of the same underlying fact.

---

## C. Suggested order of work

Ranked by (cost to leave alone) ÷ (cost to fix). All are additive; none breaks
a stored record.

**[roadmap.md](roadmap.md) is the authoritative sequencing** — it groups these
into three phases with acceptance criteria, and is the file to update as items
land. This table is the summary.

| # | Change | Bug | Effort |
|---|---|---|---|
| 1 | `CircuitSpec.format_dialect: str \| None` — [A4](#a4-circuitformat-under-specifies-openqasm) | `8da64e9` | one field |
| 2 | `VQAResult.energy_unit: str = "hartree"` — [A8](#a8-energies-carry-no-unit) | `c292fb6` | one field |
| 3 | `BenchmarkRecord.min_reader_version` — [A5](#a5-version-metadata-is-global-where-the-upstreams-make-it-per-type) | `dd6b4ac` | one field + a constant |
| 4 | AGENTS.md rules: mirrors must convert or explain ([B1](#b1-the-mirror-count-is-outrunning-the-conversion-count)); no integer Paulis in fields ([B4](#b4-integer-encodings-for-paulis-are-a-recurring-silent-hazard)); vendor fields are grandfathered ([A7](#a7-vendor-names-are-still-leaking-into-core-types)) | `02e4944` `44aed8a` `4ea960d` | docs only |
| 5 | `SimulatorRuntimeSpec` on `BackendSpec`, unstuffing `auth` — [A3](#a3-simulator-runtime-is-being-smuggled-through-auth) | `2ac2335` | one model + factory updates |
| 6 | Promote `ActiveSpaceSpec` to `catalogs/active_space.py` — [A6](#a6-four-representations-of-an-active-space) | `c02f436` | move + re-export |
| 7 | `catalogs/noise_models.py` + `ExecutionOptions.noise_model` — [A1](#a1-there-is-no-way-to-request-noise-only-to-describe-it) | `3f526e2` | a real design task |
| 8 | Measurement-derivation model — [A2](#a2-nothing-records-how-counts-became-an-expectation-value) | `0477a99` | the largest; design against qoqo |

Two further items are tracked but sit outside the ranked path because they are
tidying rather than capability: [A9](#a9-bound-parameters-cannot-be-symbolic-and-have-no-order)
(`fc412a8`), [A10](#a10-four-timing-fields-no-stated-relationship) (`7131e33`)
and [B2](#b2-ten-escape-hatches-six-naming-conventions) (`0ff0dd6`).

Items 1–4 are an afternoon and remove most of the silent-failure surface.
Items 7 and 8 are the ones that change what the benchmark can *say*, and both
deserve their own design pass rather than being bolted on.
