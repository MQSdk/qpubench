# Kubeflow integration

Kubeflow is different from every other integration in this repo: it is not a
schema bridge to a quantum SDK or chemistry library; it is an orchestration
layer for *running* qpubench's own algorithmic steps as scheduled,
observable, resourced units of compute. Two separate pieces of the Kubeflow
project are relevant, and they play different roles here.

## Two Kubeflow SDKs, two roles

**Kubeflow Pipelines (`kfp`)**: the classic multi-step DAG SDK. Owns the
pipeline graph, the Central Dashboard visualization, per-step logs and
artifacts, and step-level caching. This is what qpubench uses for "run
algorithmic steps as components."

**The new unified Kubeflow SDK** (`kubeflow-trainer` / `kubeflow-optimizer`,
`TrainerClient`/`OptimizerClient`, `sdk.kubeflow.org`), a single-job
abstraction (`CustomTrainer(func, func_args, num_nodes, resources_per_node)`
submitted via `TrainerClient().train(...)`) plus a Katib-backed
hyperparameter-search client (`OptimizerClient().optimize(...)`). As of this
writing it has **no native multi-step DAG concept**; Pipelines support is
listed as "Planned" in its own docs, not yet merged in.

Because of that gap, and because `TrainerClient`/`CustomTrainer` are named
and shaped around ML training, a frame that doesn't match quantum chemistry
or quantum-circuit pipeline steps and would confuse domain experts reading a
dashboard full of "TrainJob" nodes for work that trains nothing, qpubench's
pipelines are built natively in **`kfp`**, full stop. The unified SDK is
reserved for a narrow, opt-in role: called from *inside* the body of one
specific `kfp` component, never as the top-level abstraction, and never
surfaced in a pipeline's step names or the dashboard's node labels.

## Component taxonomy

Every qpubench algorithmic pipeline decomposes into two kinds of step:

| Kind | Shape | Examples |
|---|---|---|
| **Transform** | pydantic-in → pydantic-out, no `BackendAdapter` involved | SCF, active-space selection, Jordan-Wigner mapping, circuit synthesis, resource estimation, Cebule MOL_MAP/TN_QC_OPT/QASM_GEN |
| **Execution** | drives `BenchmarkRunner.run()`/`.sweep()` against a registered `BackendAdapter`/`AlgorithmAdapter` | a GPU simulator run (Qrack, TN_QC_OPT), a real QPU job (IBM, IQM, QESEM, Bloqade/Aquila) |

Both kinds compile to the same `@dsl.component` shape in `kfp`; only the
resource request and `base_image` differ per backend. That includes real
QPU hardware: since Kubeflow cannot reach a QPU directly, an Execution
component targeting IBM/IQM/QESEM/Aquila does exactly what
`BackendAdapter.run()` already does outside Kubeflow: call the vendor SDK,
submit to *their* queue, poll, return. Kubeflow's role for that component is
purely "a scheduled, credentialed, observable place to host the outbound
client and its long poll," not compute acceleration; size its resource
request accordingly (minimal CPU, generous timeout) and inject vendor
credentials via `kfp-kubernetes`'s `use_secret_as_env`/`use_secret_as_volume`
rather than plain pipeline parameters (which get recorded in the run's
parameter history).

**Component boundaries sit at existing schema-artifact boundaries**, the
natural stage outputs already modeled in each schema module, never at the
granularity of an optimizer's inner loop. TN_QC_OPT's `n_iterations`,
ADAPT-VQE's macro/micro-iterations, and any VQE parameter-optimization loop
stay inside **one** component/pod. Exploding an iterative loop into one kfp
node per iteration would make per-node K8s scheduling overhead dwarf the
actual compute.

## Where the unified SDK earns its keep (and where it doesn't)

Most GPU/CPU-heavy simulator steps don't need `TrainerClient` at all; a
plain `kfp` component can request a GPU directly
(`.set_accelerator_type("nvidia.com/gpu").set_accelerator_limit(1)`), which
covers single-node Qrack/Aer/TN_QC_OPT runs. Reserve
`TrainerClient`/`CustomTrainer` for the narrower case of genuine **multi-node**
coordination (a statevector simulation sharded across several GPU nodes, a
large `sweep()` batch dispatched as coordinated parallel workers), and
`OptimizerClient` for genuine **hyperparameter search** over qpubench's own
config space (`AdaptVQERunConfig.pool_type`/`optimizer`/`gradient_threshold`,
transpiler settings); call it from inside that one component's body and
label the dashboard node by what it does ("GPU Statevector Sweep",
"ADAPT-VQE Hyperparameter Search"), never "TrainJob".

One operational detail to verify before wiring either in: a `kfp` component
pod calling `TrainerClient().train()` or `OptimizerClient().optimize()`
needs its service account granted RBAC on `trainjobs.trainer.kubeflow.org`
(and Katib's experiment CRD), not granted by default to kfp-launched pods.

## Worked example: the Cebule pipeline(s)

[`integrations/kubeflow/`](../../integrations/kubeflow/) implements the
Cebule SDK's documented task chain, since `MolMapResult.to_sparse_pauli_observable`
in `schemas/mirrors/mqsdk_cebule.py` explicitly notes TN_QC_OPT is "a follow-up" to
MOL_MAP, as `kfp` DAG nodes:

```
mol_map_component  →  tn_qc_opt_component  →  qasm_gen_component  →  execute_circuits_component
   (Transform)          (Transform, one           (Transform)          (Execution, stub
                         job for the whole                              BackendAdapter by
                         optimizer loop)                                 default)
```

See `integrations/kubeflow/README.md` for setup, compilation, and
submission, and its "Known placeholders" section for the gaps left
honestly unfilled (qpubench ships no Pauli-term ↔ dense-matrix conversion
in either direction, and confirming `mqsdk.TaskType`'s import path against
your installed version) rather than papered over with invented conversion
logic; its "TODO: closing the three `NotImplementedError` gaps"
checklist right below that section is the concrete work item list
(two `SparsePauliObservable` conversion methods to add in
`schemas/observable.py`, plus which of the four pipelines' Execution
components each one unblocks).

## Mapper category = new DAG; sweep point = parameter inside one DAG

`data/IBM_VQE_Test_Benchmark.csv` (see `data/README.md`) is the concrete
test of the component-boundary rule above: it has four `Mapper` categories
(`JW`, `mol_map`, `tn_qc_opt`, `tn_qc_opt+mol_map`), each requiring a
different set of components, so each gets its **own** `@dsl.pipeline` in
`integrations/kubeflow/pipelines.py`. Everything else in that CSV,
`TN_Layers_Network`, `TN_Layers_Circuit`, `Rotation_Type`,
`Measurement_Method`, `Shots`, `Qiskit_Opt_Level`, is a parameter value
that doesn't change which components run, so none of it gets its own
pipeline:

- `TN_Layers_Network`/`TN_Layers_Circuit`/`Rotation_Type`/
  `Measurement_Method` are Cebule TN_QC_OPT task-call parameters, swept
  via nested `dsl.ParallelFor` inside the one relevant pipeline, so a
  single pipeline *run* fans out into every sweep point as branches of the
  same dashboard graph, not one run (let alone one pipeline) per
  combination.
- `Shots`/`Qiskit_Opt_Level` are execution options, not different Cebule
  calls, resolved inside the Execution component itself via
  `BenchmarkRunner.sweep()`'s cartesian product, the same "stays inside one
  component/job" treatment TN_QC_OPT's own `n_iterations` optimizer loop
  already gets.

Running the CSV's full 2,436-row matrix (or any `data/batches/` tranche)
against real hardware means: pick the pipeline matching each row's
`Mapper`, then group rows by every other column into one
`create_run_from_pipeline_package(...)` call per Mapper with all the
distinct sweep values as list-valued arguments, not one run per row.

## Why not build a custom DAG driver over `TrainerClient` instead

An earlier iteration of this design considered a qpubench-side sequential
driver issuing ordered `TrainerClient().train()` calls itself, using its own
dependency-graph bookkeeping. That was dropped: it would have reimplemented
what `kfp` already does natively, namely automatic DAG construction from data
dependencies, branching, artifact passing, step caching, and dashboard
visualization, while still exposing ML-training vocabulary for steps that
train nothing. `kfp` gives all of that for free; the unified SDK's value is
narrow and worth invoking only where noted above.
