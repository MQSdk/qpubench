# Fragmentation — decomposing the problem

Fragmentation makes an intractable molecule tractable by splitting it into
subsystems, solving each one, and recombining. qpubench models this with one
general schema plus two project mirrors:

| Module | Upstream | Role |
|---|---|---|
| `qpubench.schemas.fragmentation` | — (framework-general) | The shared vocabulary every method reduces to |
| `qpubench.schemas.fragmentqc_fragment` | [fragment-qc/fragment](https://gitlab.com/fragment-qc/fragment) | MBE / GMBE via PIE trees, multilevel layers, adaptive screening |
| `qpubench.schemas.qiskitcommunity_fragment_methods` | [qiskit-community/quantum-fragment-methods](https://github.com/qiskit-community/quantum-fragment-methods) | EWF embedding with per-fragment quantum solvers |

Neither upstream package is a dependency. These are Pydantic v2 mirrors —
`pytest tests/` passes with `pip install .` alone.

## The shared abstraction

Every fragmentation method — MBE, GMBE, DMET, EWF, ONIOM — is:

1. a set of **fragments**, in real space or orbital space;
2. an **expansion**: `(fragment, signed coefficient)` terms whose weighted sum
   reconstructs a supersystem property;
3. a **solver** per fragment, classical or quantum;
4. optionally **screening rules** that drop terms below a threshold (the
   *adaptive* part) and **layers** solving different orders at different levels
   of theory (the *multilevel* part).

`FragmentExpansionTerm` is deliberately the most general form — an arbitrary
real coefficient on an arbitrary fragment. A 2-body MBE, a generalized MBE over
overlapping fragments and an ONIOM subtractive scheme all fit without a
method-specific schema.

```python
from qpubench.schemas.fragmentation import (
    FragmentationScheme, FragmentationSpec, FragmentExpansionTerm, FragmentSpec,
)

spec = FragmentationSpec(
    name="water-trimer-2body",
    scheme=FragmentationScheme.MBE,
    max_order=2,
    basis="cc-pVDZ",
    fragments=[
        FragmentSpec(fragment_id=f"m{i}", order=1, atom_indices=[3 * i, 3 * i + 1, 3 * i + 2])
        for i in range(3)
    ] + [
        FragmentSpec(fragment_id="d01", order=2, primary_ids=["m0", "m1"]),
        FragmentSpec(fragment_id="d02", order=2, primary_ids=["m0", "m2"]),
        FragmentSpec(fragment_id="d12", order=2, primary_ids=["m1", "m2"]),
    ],
    expansion=[
        *(FragmentExpansionTerm(fragment_id=f"m{i}", coefficient=-1.0, order=1) for i in range(3)),
        FragmentExpansionTerm(fragment_id="d01", coefficient=1.0, order=2),
        FragmentExpansionTerm(fragment_id="d02", coefficient=1.0, order=2),
        FragmentExpansionTerm(fragment_id="d12", coefficient=1.0, order=2),
    ],
)

spec.coefficient_sum      # 0.0 ... wait — see below
spec.terms_by_order()     # {1: 3, 2: 3}
```

### Completeness is a diagnostic, not a constraint

A valid expansion covering the whole supersystem has coefficients summing to
**1** (every atom counted exactly once). For a 3-monomer 2-body MBE the
monomer coefficient is `-(n-2) = -1`, giving `3·(-1) + 3·(+1) = 0` — which is
correct for the *interaction* energy, not the total. Use `coefficient_sum` and
`is_complete()` to see which of the two you built:

```python
spec.is_complete()        # False -> this expansion is not covering the supersystem
```

A shortfall on a run that *should* be complete usually means screening dropped
terms — which is expected for an adaptive run. That is why it is reported
rather than enforced.

## Adaptive screening

Screening is what makes high-order expansions tractable: terms whose metric
falls outside the threshold are never submitted. Thresholds are keyed by n-body
order because screening almost always tightens with order.

```python
from qpubench.schemas.fragmentation import FragmentScreeningRule, ScreeningMetric

rule = FragmentScreeningRule(
    name="energy_trimming",
    metric=ScreeningMetric.ENERGY_DELTA,
    thresholds={2: 1e-4, 3: 1e-5, 4: 1e-6},
    backend="xtb",                    # the *cheap* estimator
)
rule.threshold_for(3)                 # 1e-05
rule.threshold_for(9)                 # None (falls back to `cutoff`)
```

Screening is only worthwhile when the estimator is far cheaper than the solver
it protects — hence the explicit `backend` field.

## Multilevel layers

Layers stack a high-accuracy method on a small fragment set over a cheaper one
on a larger set, with `sign=-1.0` on the subtractive layer so the cheap
contribution inside the accurate region cancels.

```python
from qpubench.schemas.fragmentation import FragmentationLayer, SolverKind

layers = [
    FragmentationLayer(level=0, max_order=4, method="mp2",     basis="cc-pVDZ"),
    FragmentationLayer(level=1, max_order=2, method="ccsd(t)", basis="cc-pVTZ", sign=-1.0),
    FragmentationLayer(level=2, max_order=2, method="sqd",     solver_kind=SolverKind.QUANTUM),
]
```

## Solver assignment

Rules are tried highest `priority` first; the first match wins. A quantum
solver claims the fragments that fit the QPU, a classical fallback catches the
rest.

```python
from qpubench.schemas.fragmentation import FragmentSolverAssignment, SolverKind

spec.solver_rules = [
    FragmentSolverAssignment(
        solver_name="sqd", solver_kind=SolverKind.QUANTUM,
        priority=10, max_qubits=48, backend_name="ibm_pittsburgh",
    ),
    FragmentSolverAssignment(solver_name="ccsd", priority=0, condition="default fallback"),
]

spec.assign_solver(spec.fragments[0]).solver_name   # "sqd"
spec.quantum_fragments()                            # fragments headed for the QPU
spec.max_fragment_qubits                            # the QPU width this plan needs
```

`matches()` only evaluates the machine-checkable `max_*` limits — `condition`
is documentation. A limit compared against an unset fragment field does not
reject, so a fragment with no `num_qubits` estimate is not excluded by
`max_qubits`.

## Fragme∩t (`fragmentqc_fragment`)

Fragme∩t is driven by a declarative `strategy.yaml`. The mirror's field names
match it verbatim, so a real file round-trips:

```python
import yaml
from qpubench.schemas.fragmentqc_fragment import FragmentStrategy

strategy = FragmentStrategy.model_validate(yaml.safe_load(open("strategy.yaml")))
spec = strategy.to_fragmentation_spec("my_calculation")
spec.is_multilevel, spec.is_adaptive
```

The idea worth importing wholesale is the **PIE tree** — nodes keyed by a set
of primary indices, each with an integer coefficient. Every expansion is the
same object; only the coefficients differ.

```python
from qpubench.schemas.fragmentqc_fragment import FragmentPIENode, FragmentPIETree

tree = FragmentPIETree(
    primaries=[[0, 1, 2], [3, 4, 5], [6, 7, 8]],
    nodes=[
        FragmentPIENode(key=[0, 1], coefficient=1),
        FragmentPIENode(key=[0, 2], coefficient=1),
        FragmentPIENode(key=[1, 2], coefficient=1),
        FragmentPIENode(key=[0],    coefficient=-1),
        FragmentPIENode(key=[1],    coefficient=-1),
        FragmentPIENode(key=[2],    coefficient=-1),
    ],
    order=2,
)
tree.to_expansion()     # -> list[FragmentExpansionTerm]
tree.to_fragments()     # -> list[FragmentSpec], atoms unioned from the primaries
```

Nodes with `coefficient == 0` are structural: they exist so their children's
overlaps resolve, and are never submitted. `nonzero_nodes` is what actually
runs.

Mods map to screening rules where they *are* screening rules:

```python
mod.to_screening_rule()      # -> FragmentScreeningRule, or None
```

Basis mods (`UseSupersystemBasis`, `ClusterBasis`, …) and MIC mods change *how*
a term is computed, not *whether* it is, so they return `None` — map over every
mod and filter.

> Upstream's own `fragment/schemas/` models are Pydantic **v1**
> (`pydantic.validator`, `orm_mode`). These are independent v2 mirrors.

## quantum-fragment-methods (`qiskitcommunity_fragment_methods`)

The mirror that connects fragmentation to a QPU. Load a real `config.yaml`:

```python
import yaml
from qpubench.schemas.qiskitcommunity_fragment_methods import QFMWorkflowConfig

cfg = QFMWorkflowConfig.from_config_dict(yaml.safe_load(open("config.yaml")))
cfg.sqd.total_samples            # n_batches * samples_per_batch
cfg.ewf.to_screening_rule()      # bath truncation as a general screening rule
spec = cfg.to_fragmentation_spec()
```

### Credentials are dropped, deliberately

The upstream `qpu.credentials` block holds an API token and a CRN instance id.
`QFMQPUConfig` mirrors `channel` and `instance` — a benchmark record *should*
state which service it ran on — but has **no token field**, and
`from_config_dict()` never reads one. You can pass a real config file in
verbatim without leaking a secret into a stored record.

### RDMs are not stored

`QFMSolverResult` records `has_rdm1` / `has_rdm2` but not the matrices
themselves: benchmark records must stay JSON-serialisable, and RDMs at
protein scale are far too large.

## Composing with distributed execution

Fragmentation decomposes the *problem*; [distributed
execution](distributed_qc.md) decomposes the *circuit* solving each fragment.
`FragmentResult.record_id` is the join:

```python
frag_result.record_id            # -> BenchmarkRecord.experiment_id
```

That record may itself carry a `CircuitCutSpec` or `CircuitPartitionSpec` — a
fragment too wide for one QPU is cut or partitioned like any other circuit.

## Attaching to a benchmark record

```python
from qpubench import CircuitSpec, QuantumResult
from qpubench.schemas.fragmentation import FragmentationSpec

circuit = CircuitSpec(num_qubits=48, fragmentation=spec)     # model or dict
result  = frag_result.to_quantum_result()                    # vendor_results key set

# rehydrate
FragmentationSpec.model_validate(circuit.fragmentation)
```

`to_quantum_result()` takes an explicit `computing_model` because a fragmented
calculation may be entirely classical, or mix classical and quantum fragments.
