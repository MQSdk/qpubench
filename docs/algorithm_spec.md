# Algorithms & `AlgorithmSpec`

This page is the conceptual companion to the field-level reference in
[schemas.md → `AlgorithmSpec`](schemas.md#algorithmspec). It explains how
qpubench names algorithms, where their hyperparameters live, and how the same
algorithm run through different libraries stays comparable in one store.

> **Status.** `AlgorithmFamily` is still provisional and being refined — see
> the [ToDo](schemas.md#primitives) in the schema reference. Treat the member
> set as subject to change.

---

## The core split: identity vs. hyperparameters

qpubench deliberately separates *which algorithm you ran* from *how it was
configured*:

- **`AlgorithmSpec`** (in [`execution`](schemas.md#execution)) carries only
  **identity** — a library-specific `name` (e.g. `"ADAPTVQE"`, `"UCCNVQE"`),
  an optional package-agnostic `family` (`AlgorithmFamily`), and an
  `extra_params` escape hatch. It holds no tuning knobs.
- **Hyperparameters** live in a **family- or library-specific config** next to
  the code that consumes them —
  [`AdaptVQERunConfig`](schemas.md#adaptvqerunconfig) (the package-agnostic
  ADAPT-VQE contract), `dlr_excitation_solve.ExcitationSolveConfig`,
  `mqsdk_xenakis.GAConfig`, `mqsdk_cebule.TNQCOptInput`,
  `microsoft_qdk.QPEConfig`, `evangelistalab_qforte.QForteAlgorithmConfig`, …

Why not one big config struct? Because each library's knobs are genuinely
different, and a shared grab-bag would either lie about what a given adapter
honours or collapse under optional fields. Keeping the config next to its
consumer mirrors the same split used for backends and error mitigation.

---

## `AlgorithmFamily` — the comparison key

`family` is what makes *"the same algorithm, different engine"* a first-class
comparison. Set it, and records from different implementing adapters converge
on one label you can group by in the store.

It only pays off once **two or more** adapters accept the same shared config
for a family. Today that is true for exactly one family:

| `AlgorithmFamily` | Implementing adapters | Shared config |
|---|---|---|
| `ADAPT_VQE` | `evangelistalab_qforte`, `ibm_qiskit_adapt_vqe`, `microsoft_qdk_adapt_vqe` | `AdaptVQERunConfig` |
| `UCC_VQE` / `UCC_PQE` / `SPQE` | `evangelistalab_qforte` only | `QForteAlgorithmConfig` |
| `QAOA` | none yet (runs as a plain optimization loop, like vanilla VQE) | `QAOARunConfig` |
| `EXCITATION_SOLVE` | `dlr_excitation_solve` only | `ExcitationSolveConfig` |
| `TN_QC_OPT` | `mqsdk_cebule` only | `TNQCOptInput` |
| `GA_CIRCUIT_SEARCH` | `mqsdk_xenakis` only | `GAConfig` / `GenomeConfig` |
| `QPE` | none (schema/metadata only) | `microsoft_qdk.QPEConfig` |

The single-implementation families still carry a `family` tag — not because a
comparison is possible today, but so a *second* implementation has a name to
converge on instead of inventing its own ad-hoc label. `QAOA` is the same case
as vanilla VQE: no `AlgorithmAdapter` drives it — you run the fixed cost/mixer
ansatz through any backend in a plain optimization loop (see
[Variational quantum algorithms](vqa.md#running-qaoa)) — but its runtime
hyperparameter contract, `QAOARunConfig`, already exists so a future QAOA
adapter has one shared config to accept.

---

## `VQAConfig` vs. `AdaptVQERunConfig` — two objects, two jobs

`VQAConfig` is the single config that describes a variational run (VQE,
ADAPT-VQE, or QAOA). A natural question is *why isn't the ADAPT-VQE
configuration just an argument on `VQAConfig`?* Because the two live on
different objects, at different layers, and answer different questions:

- **`VQAConfig`** (on `BenchmarkRecord.vqa`, in [`record`](schemas.md#record))
  is experiment **metadata** — it labels *what* you ran (`problem_type`,
  `molecule`, `basis`, `algorithm`, `ansatz`, `optimizer` name) so records are
  filterable and comparable in the store. By contract it has `extra="forbid"`
  and **changes nothing about execution**. A QAOA run names itself here with
  `problem_type="optimization"` and `algorithm="QAOA"`; its actual knobs (p,
  mixer, optimizer) live in `QAOARunConfig`, not as new `VQAConfig` fields —
  same layering as ADAPT-VQE below.

  ```python
  from qpubench.schemas import VQAConfig

  vqa = VQAConfig(
      problem_type="chemistry",
      molecule="H2", basis="sto-3g",
      algorithm="VQE",          # or "ADAPTVQE", "QAOA", ...
      ansatz="UCCSD",
      optimizer="COBYLA",
  )
  ```

- **`AdaptVQERunConfig`** (on `ExecutionOptions.adapt_vqe_run_config`, in
  [`execution`](schemas.md#execution)) is a **runtime hyperparameter contract**
  — the knobs an adapter actually *reads to drive* the adaptive loop (operator
  pool, gradient/energy thresholds, macro/micro iteration caps). It sits on
  `ExecutionOptions`, next to `ZNEConfig`/`TranspilerConfig`, because that is
  the "how to execute" layer.

**Why it is not folded into `VQAConfig`:**

1. **Layer separation.** `VQAConfig` is record metadata with no execution
   effect; `AdaptVQERunConfig` drives execution. Merging them would put an
   execution-driving struct inside an object defined to have none.
2. **Package-agnostic reuse.** `AdaptVQERunConfig` is one shared contract that
   three different ADAPT-VQE adapters (`evangelistalab_qforte`,
   `ibm_qiskit_adapt_vqe`, `microsoft_qdk_adapt_vqe`) all accept unchanged — the
   "switch the adapter, keep the config" story. It belongs on `ExecutionOptions`
   where every adapter reads it, not on a per-record metadata object. Keeping
   each algorithm family's real knobs in their own config (keyed by
   `AlgorithmFamily`) also stops `VQAConfig` ballooning into a grab-bag of every
   algorithm's parameters — the same reason QAOA's knobs went into
   `QAOARunConfig` rather than onto `VQAConfig`.

So `VQAConfig` **names** the experiment and a family's run-config **configures**
the run: an ADAPT-VQE benchmark uses both (metadata in `VQAConfig`, adaptive
knobs in `ExecutionOptions.adapt_vqe_run_config`), a QAOA benchmark likewise
pairs `VQAConfig` with `ExecutionOptions.qaoa_run_config`, while a fixed-ansatz
VQE uses `VQAConfig` alone (no extra knobs to set). Each energy evaluation is an
ordinary `CircuitSpec` run through a `BackendAdapter`; the runner derives
`VQAResult.final_eigenvalue` from the measured expectation values.

> `CircuitFormat` has no `VQE` member — VQE is an *algorithm*, not a way of
> serializing a circuit. See the [`CircuitFormat` note](schemas.md#primitives).

---

## Adding a new algorithm

1. **Pick or propose an `AlgorithmFamily`.** Reuse an existing member if your
   algorithm is the same family as an existing one (so records compare); add a
   member only for a genuinely new family (and update the ToDo discussion).
2. **Put hyperparameters in a config next to your adapter**, not in
   `AlgorithmSpec`. If your family already has a shared config (e.g.
   `AdaptVQERunConfig`), accept that so you inherit the "switch the adapter, keep
   the config" story.
3. **Set `AlgorithmSpec(name=..., family=...)`** on `ExecutionOptions`.
4. **Return a `VQAResult`** (algorithm adapters) or let the runner derive one
   from expectation values (circuit-path runs).

See [Backends & adapters](backends.md) for the adapter protocols and how to
test an adapter with the SDK mocked out.
