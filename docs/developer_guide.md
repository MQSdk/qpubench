# Developer guide

Why the code is written the way it is. This page explains the Python
constructs qpubench leans on and the reasoning behind each one — read it
before your first change to `src/qpubench/`, and it should save you from
"why is this method empty?" and "why is that module named with an
underscore?".

For *what* the package contains, see [schemas](schemas.md) and
[backends](backends.md). This page is about *how* it is built.

---

## Two constraints that explain most of the design

Almost every choice below follows from two rules in
[`AGENTS.md`](../AGENTS.md):

1. **The core package imports no quantum SDK.** `pip install qpubench` pulls
   in Pydantic and nothing else, and the whole test suite must pass on that
   install. Qiskit, PennyLane, PySCF and friends are optional extras.
2. **Adapters must be writable outside this repo.** Your adapter can live in
   your own project, or in a third-party package, and still work with
   `BenchmarkRunner`.

Rule 1 is why SDK imports sit inside functions. Rule 2 is why the adapter
interfaces are Protocols instead of base classes.

---

## `Protocol` instead of an abstract base class

`backends/base.py` and `store.py` define interfaces like this:

```python
@runtime_checkable
class BackendAdapter(Protocol):
    @property
    def spec(self) -> BackendSpec: ...

    def validate(self, circuit: CircuitSpec) -> list[str]: ...

    def run(self, circuit: CircuitSpec, options: ExecutionOptions) -> QuantumResult: ...
```

**What a Protocol is.** A `typing.Protocol` describes the *shape* a class must
have — which methods, with which signatures. Any class with that shape
satisfies it. This is "structural" typing, as opposed to the "nominal" typing
of an abstract base class, where a class only counts if it explicitly
inherits.

**Why we use one here.** With an ABC, every adapter author would have to
`from qpubench.backends.base import BackendAdapter` and subclass it — a hard
dependency from their package onto ours, and one more thing to get wrong. With
a Protocol, they write a plain class with `spec`, `validate` and `run`, import
nothing, and it works. That is what makes rule 2 above achievable.

**Why the method bodies are `...`.** A Protocol carries no behaviour to
inherit, so there is nothing for a body to *do*. `...` (the `Ellipsis`
literal) is Python's conventional marker for a deliberately empty body — the
same role `pass` plays, but read by convention as "this is a declaration, not
a stub awaiting work". These are not unfinished methods. Nothing ever calls
them; they exist so that a type checker, and a human reading the file, can see
the required signature in one place.

**When to use an ABC instead.** If you have real shared behaviour to inherit —
a base class with working methods subclasses build on — use an ABC. qpubench's
interfaces have no shared behaviour, only a shape, so a Protocol is the
lighter and less coupling-prone choice.

### `@runtime_checkable`

By default a Protocol only exists at type-check time; `isinstance()` against
it raises `TypeError`. `@runtime_checkable` lifts that restriction.

`BenchmarkRunner.run()` needs it:

```python
if isinstance(adapter, AlgorithmAdapter):
    result, vqa, vqa_result = adapter.run_algorithm(circuit, options)
else:
    result = adapter.run(circuit, options)
```

The runner has to decide, at runtime, which of the two execution paths an
adapter wants — and it must do so without importing the adapter's class or
being told. `@runtime_checkable` plus `isinstance()` is how.

**The caveat you must know.** A runtime protocol check tests only that the
*method names* exist. It does not check signatures or types. So a class with a
`run_algorithm` method taking entirely the wrong arguments will still pass
`isinstance(adapter, AlgorithmAdapter)` and then fail confusingly inside the
call. This is why `AGENTS.md` warns that "`AlgorithmAdapter` detection is
duck-typed": if your algorithm adapter is missing one of the two required
method names, the runner silently takes the `BackendAdapter` path instead.
mypy catches the signature mismatches that `isinstance` cannot — run
`mypy src/` before committing.

---

## `super()`

`super()` returns a proxy to the next class in the method resolution order —
in practice, "the class I inherit from". It is how you extend a method
rather than replace it.

`observability.py` has the one instance worth explaining:

```python
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "record_payload", None)
        if payload is None:
            return super().format(record)
        return json.dumps(payload)
```

We override `logging.Formatter.format` to emit a benchmark record as one JSON
line. But the same handler may receive log records from anywhere else in the
process, which have no `record_payload` — and reformatting those as JSON would
be wrong, while reimplementing the standard formatting (timestamps, level
names, `%`-style templates, exception tracebacks) would be worse. So we handle
our case and hand everything else back to the implementation we inherited from.

Modern Python needs no arguments: `super()` inside a method body infers both
the class and the instance. The old `super(JSONFormatter, self)` form is
equivalent and only needed outside a class body.

---

## `@property`

`@property` makes a method callable as though it were an attribute:
`adapter.spec`, not `adapter.spec()`.

Every adapter exposes `spec` this way. Two reasons:

- **It is part of the protocol contract**, and reading a static description of
  a machine should look like reading an attribute, not like invoking an
  action. `adapter.spec` and `record.backend` then read the same way.
- **It stays lazy and computed.** `IBMAdapter` builds its `BackendSpec` in
  `__init__`, but an adapter that needs to derive one from live device data can
  do that inside the property without changing how callers use it.

The schema layer uses it for the same reason —
`BenchmarkRecord.vqa_result.chemical_accuracy` and `CircuitSpec.total_gates`
are derived values, not stored fields, so they never go stale and never get
serialised into a record where they could disagree with the data they came
from.

---

## `@staticmethod` and `@classmethod`

Both put a function inside a class without giving it an instance.

- **`@classmethod`** receives the class as its first argument (`cls`) and is
  the idiomatic way to write an *alternative constructor*. `BackendSpec` has
  around thirty of them — `BackendSpec.aer_statevector()`,
  `BackendSpec.ibm(...)`, `BackendSpec.qrack(...)` — because the alternative is
  making every caller remember which combination of `provider`,
  `computing_model` and `qubit_modality` describes a given machine.
  `S3Store.huggingface(...)` is the same pattern for a store.
  `CircuitSpec.from_openqasm3(...)` is one for a schema.
- **`@staticmethod`** receives neither the class nor the instance. Use it for a
  function that belongs to a class *conceptually* but needs none of its state —
  `IQMAdapter.fetch_calibration(...)` queries a device's calibration data and
  needs no adapter instance to do it.

Rule of thumb: reach for `@classmethod` when the function returns an instance
of the class; `@staticmethod` when it just happens to live there; a
module-level function when neither is true. Prefer the module-level function
when in doubt — a `@staticmethod` that nothing about the class informs is
usually just a function in disguise.

---

## `CircuitSpec.bind()` and immutability

```python
def bind(self, values: dict[str, float]) -> CircuitSpec:
    """Return a copy with parameter bindings applied."""
    bindings = [ParameterBinding(name=k, value=v) for k, v in values.items()]
    return self.model_copy(update={"parameter_bindings": bindings})
```

A parametric circuit — a VQE ansatz, a QAOA layer — is a *template*:
`CircuitSpec` holds the gate structure with named free parameters, and
`parameter_bindings` holds the numbers to substitute. `bind()` pairs them.

**The important detail is that it returns a new object.** It does not mutate
`self`. A VQE optimizer evaluates the same ansatz at hundreds of parameter
points, and each evaluation must be recorded as its own `BenchmarkRecord`. If
`bind()` mutated in place, every stored record would end up referring to the
same object and reporting the *last* parameter values — every energy in the
convergence history attributed to the final iteration's angles. Returning a
copy makes the natural loop correct:

```python
for theta in optimizer_steps:
    record = runner.run(ansatz.bind({"theta": theta}), "aer", shots=4096)
```

`model_copy` is Pydantic's own shallow-copy-with-updates, so the copy costs
little and stays a validated model. The same "return a modified copy" style
appears in `runner.py`
(`result.model_copy(update={"total_time_s": ...})`) for the same reason.

The adapter side of the contract is in `backends/_qiskit_common.py`: bindings
are matched onto the SDK's free parameters *by name*, so a template and its
bindings can travel separately through the record store and still be
reassembled correctly.

---

## Deferred imports (SDK imports inside functions)

```python
def run(self, circuit, options):
    from qiskit_aer.primitives import EstimatorV2, SamplerV2   # deferred
    ...
```

This looks wrong — PEP 8 says imports go at the top — and here it is
deliberate. It is what enforces rule 1. `qpubench.backends.aer_adapter` must be
*importable* without qiskit-aer installed, so that `from qpubench.backends
import AerAdapter` in `__init__.py` does not explode for a user who only
wanted the schema layer. The SDK is imported at the moment it is actually
needed, and only then.

The same technique appears with a different motive in `runner.py`, which
imports `NDJSONStore` and `StubGateAdapter` inside methods to avoid a circular
import between `runner` and `store`.

Consequence for tests: a missing SDK surfaces as an `ImportError` at
`run()`-time, not at import time. Adapter tests therefore mock at the import
level rather than requiring the SDK — see the testing section of `AGENTS.md`.

---

## Module naming conventions

### Leading underscore: `_qiskit_common.py`

A leading underscore marks a module as **internal to the package**. It is not
part of the public API, nothing outside `qpubench.backends` should import it,
and it may be renamed or removed without a deprecation cycle.

`backends/_qiskit_common.py` holds one function, `load_qiskit_circuit()`,
which turns a `CircuitSpec`'s QASM text into a `qiskit.QuantumCircuit`. The
Aer, IBM, IQM and Braket adapters all need exactly that step, and four private
copies would drift apart. Factoring it out is right; *exporting* it would not
be — it is a shared implementation detail of those four adapters, not a
capability qpubench offers.

The same convention applies inside modules: `_matches()`, `_flatten_record()`
and `_resolve_region()` in `store.py` are helpers, not API. Public names are
listed in each package's `__init__.py` `__all__`.

### Schema module layout and naming

`schemas/` is split three ways, and which directory a module belongs in
follows from one question: *how many upstreams does it speak for?*

| Directory | Upstreams | Naming |
|---|---|---|
| `schemas/` | none — these are qpubench's own record types | plain (`circuit.py`, `record.py`) |
| `schemas/catalogs/` | several, or none | named for what it catalogues (`basis_sets.py`, `optimizer_catalog.py`) |
| `schemas/mirrors/` | exactly one | `<org_or_maintainer>_<package>.py` (`erikkjellgren_slowquant.py`, `quera_bloqade.py`, `qedma_qesem.py`) |

The mirror convention makes the filename answer "whose format is this?" — which
matters when dozens of modules mirror dozens of upstreams and several model the
same concept incompatibly.

**Do not force the `<org>_<package>` form onto a catalogue.** It has nothing
sensible to say when a module draws on several upstreams, and it degenerates
outright for GitHub Pages community registries, where the organisation and the
project routinely share a name:
`quantum-advantage-tracker/quantum-advantage-tracker.github.io` would yield
`quantum_advantage_tracker_quantum_advantage_tracker.py`. That module is
`catalogs/quantum_advantage_tracker.py`, named for its subject, with the
registry URL recorded in its docstring. Use the same rule for any future
community-registry mirror: name it for the thing, cite the URL in the module
docstring, and put it in `catalogs/`.

Adding a module means adding it to `schemas/__init__.py` (public API), to the
index in [schemas.md](schemas.md), and to the tests — see the checklist in
`AGENTS.md`.

---

## Comments and docstrings

Every module, class and function gets a `"""docstring"""`. Prefer expanding
the docstring over adding a `#` comment: a docstring is reachable from
`help()`, from an IDE tooltip and from generated documentation, while a `#`
comment is visible only to whoever has the file open. Reserve `#` for
genuinely line-local notes — a non-obvious constant, a workaround for a
specific upstream bug.

Docstrings here carry a particular kind of content: **verified facts about the
outside world**. When an adapter's docstring says a value was "confirmed
against qiskit-ibm-runtime 0.47", that is load-bearing — it records that
someone checked, and against which version. Keep those notes and update the
version when you re-verify. Do not, on the other hand, write docstrings about
this repository's own history ("this is the first real implementation of…") —
that belongs in git history and the bug tracker, not in a module that a user
reads to learn what the code does.

---

## Credentials

No credential is ever a function argument. Adapters take a `*_ref` parameter
naming the *environment variable* to read — `IBMAdapter(..., token_ref="MY_VAR")`
— and read it at the point of use, so nothing is held on the object or
serialised into a `BenchmarkRecord`. `BackendSpec.auth` stores variable names
only. `S3Store` actively rejects `aws_secret_access_key=` and friends as
constructor arguments. See the credentials section of the
[README](../README.md#credentials) and `.env.example`.

---

## Why the models are hand-written

Pydantic is the only mandatory runtime dependency, so the framework is
essentially a Pydantic schema library with adapters and stores around it. It
uses Pydantic in a specific way that is worth stating outright, because the
obvious alternative is common in scientific-workflow tooling: **qpubench
contains no `create_model()` call.** Every model is written by hand.

Stacks that generate models at runtime do so because their task interfaces are
defined by another team, vary per task, and are ephemeral — validating input
just before execution is the whole job, and hand-writing hundreds of models
would not scale. qpubench's schemas are the opposite kind of object. A
`BenchmarkRecord` is archival data: it round-trips through NDJSON/Parquet/S3
(`store.py` re-validates every line with `model_validate_json`) and must still
be readable years after the code that wrote it. A runtime-generated model
undermines exactly that guarantee, and it also costs the thing that makes this
repo navigable — every field being greppable and visible to mypy.

So the design is a **static, versioned core plus dynamically-validated vendor
extension points**:

- The core (`circuit`, `execution`, `result`, `record`, `backend`,
  `observable`, `primitives`) is hand-written, carries `SCHEMA_VERSION`, and
  uses `extra="forbid"` on the VQA models so stale callers fail loudly instead
  of silently dropping data.
- Where shapes genuinely vary — dozens of mirrored upstreams — nothing is
  generated either. Vendor payloads travel through namespaced `dict[str, Any]`
  slots guarded by a `mode="before"` validator that auto-dumps any Pydantic
  model passed in, and are re-validated against the vendor's own static schema
  on the way out:

  ```python
  record.result.vendor_results["qforte_result"] = qforte_run_result  # a BaseModel
  # ... stored as its dict dump, rehydrated by the consumer:
  MBQCPattern.model_validate(spec.measurement_pattern)
  ```

The short version: *we don't generate models — we defer them.* The core stays
vendor-neutral and JSON-serialisable, and a vendor schema module can evolve
without touching `record.py`.

### The rule this implies

New vendor-specific metadata goes in `VQAConfig.vendor_data`, new vendor result
payloads in `QuantumResult.vendor_results[<key>]`, new vendor mitigation
options in `ExecutionOptions.mitigation_options`. **Never add a top-level
vendor field to a core model, and never import a vendor module from one.**

### The honest cost

The established-keys list in `result.py` is documentation-enforced, not
type-enforced — nothing stops a typo'd vendor key. That is the trade accepted
in exchange for the archival guarantees above; if it ever needs closing, the
narrow fix is generating a per-vendor typed *view* of `vendor_results` from a
key registry, not generating the records themselves. Related: the open
escape-hatch-convention item in [roadmap.md](roadmap.md), which covers the
split between open extension points (`*_data`, `*_results`) and slots that are
dicts only to keep the core import-free (`CircuitSpec.measurement_pattern` and
friends).

---

## Making a schema change

Schema modules are the stable core; stored records outlive the code that wrote
them. Before changing one, read the "Critical constraints" section of
[`AGENTS.md`](../AGENTS.md) — in particular:

- Renaming or retyping a field requires bumping `SCHEMA_VERSION` in
  `schemas/record.py`. Existing stored records break silently otherwise.
- Where a rename is worth doing anyway, add a
  `validation_alias=pydantic.AliasChoices("new_name", "old_name")` so old
  records still load. `BenchmarkRecord.qpubench_schema_version` is the worked
  example.
- Do not add `model_config = ConfigDict(arbitrary_types_allowed=True)`. Every
  field must be JSON-serialisable, or records stop round-tripping through the
  stores.
