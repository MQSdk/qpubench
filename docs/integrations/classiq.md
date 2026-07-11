# Classiq integration

[Classiq](https://docs.classiq.io/) is a quantum software platform: you describe an
algorithm as a high-level functional model, hand it hard constraints (max width,
max depth, an optimization objective), and its synthesis engine solves for an
optimized circuit that satisfies them. This is modelled in
`src/qpubench/schemas/classiq_classiq.py`.

Classiq sits next to [Xenakis](xenakis.md) as a second circuit-optimization
strategy: Xenakis *searches* (a GA evolves a population of genomes under soft
complexity penalties); Classiq *synthesizes* (a single constrained-optimization
solve under hard bounds). Both converge on a qpubench `CircuitSpec`, so they can
be registered with the same `BenchmarkRunner` and compared head-to-head.

---

## Synthesis pipeline

```python
from qpubench.schemas import (
    ClassiqModel, ClassiqConstraints, ClassiqPreferences,
    ClassiqOptimizationParameter, ClassiqSynthesisResult,
)

model = ClassiqModel(
    name="ghz_state",
    qmod_source="...",   # native Qmod text, produced by the Classiq SDK
    constraints=ClassiqConstraints(
        max_width=5,
        max_depth=20,
        optimization_parameter=ClassiqOptimizationParameter.DEPTH,
    ),
    preferences=ClassiqPreferences(backend_name="ibm_brisbane"),
)

# synthesize(model) happens through the Classiq SDK (see integrations/classiq/);
# its response maps onto ClassiqSynthesisResult:
result = ClassiqSynthesisResult(
    program_id="e3b0c4...",
    qasm3="OPENQASM 3;\nqubit[5] q;\nh q[0];\n...",
    width=5,
    depth=12,
    gate_count={"h": 1, "cx": 4},
    cx_count=4,
    synthesis_duration_s=2.3,
)

# Converts to the same CircuitSpec every other integration produces:
spec = result.to_circuit_spec()
```

`ClassiqSynthesisResult.to_circuit_spec()` picks `qasm3` over `qasm2` when both
are present — OpenQASM 3.0 is qpubench's preferred format (`CircuitSpec.from_openqasm3`).

---

## Execution

```python
from qpubench.schemas import (
    ClassiqExecutionPreferences, ClassiqBackendPreferences,
    ClassiqBackendProvider, ClassiqExecutionResult,
)

prefs = ClassiqExecutionPreferences(
    num_shots=2000,
    backend_preferences=ClassiqBackendPreferences(
        backend_service_provider=ClassiqBackendProvider.IBM_QUANTUM,
        backend_name="ibm_brisbane",
    ),
)

# execute(quantum_program) happens through the Classiq SDK; its response maps onto:
exec_result = ClassiqExecutionResult(job_id="job-123", counts={"00000": 1024, "11111": 976})
```

`ClassiqExecutionResult` mirrors the raw-provider-result layering used elsewhere
in this repo (e.g. `FireOpalResult.mitigated_counts` in `error_mitigation.py`):
it holds Classiq's native `dict[str, int]` counts, converted to a qpubench
`ShotResult` by the adapter before being attached to `QuantumResult`.

**Hybrid path**: because synthesis and execution are separate steps, you can
synthesize with Classiq and execute the resulting `CircuitSpec` on *any*
qpubench `BackendAdapter` (Aer, Qrack, IBM, IQM) instead of Classiq's own
`execute()` — useful for isolating "is this a synthesis win or an execution win?"

---

## Chemistry application

```python
from qpubench.schemas import (
    ClassiqMoleculeSpec, ClassiqChemistryModel, ClassiqFermionMapping,
    ClassiqAnsatzType, ClassiqVQEResult,
)

molecule = ClassiqMoleculeSpec(
    atoms=[("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.7414))],
    charge=0,
    spin=0,   # 2S; closed-shell singlet
)

model = ClassiqChemistryModel(
    molecule=molecule,
    mapping=ClassiqFermionMapping.JORDAN_WIGNER,
    basis="sto-3g",
    ansatz=ClassiqAnsatzType.UCC,
    ucc_excitations=[1, 2],   # singles + doubles
)

# After running Classiq's VQE loop:
vqe = ClassiqVQEResult(
    final_energy=-1.1373,
    hf_energy=-1.1167,
    optimized_parameters=[0.051, -0.032],
    convergence_values=[-1.10, -1.13, -1.1373],
)

# Populates qpubench's shared VQAConfig using the SAME fields Xenakis, QForte,
# and Cebule already write to (mapper, ansatz, n_cnot, num_parameters) —
# no Classiq-specific duplicate fields needed:
vqa = vqe.to_vqa_config(molecule="H2", model=model)
```

---

## Combinatorial optimization (QAOA)

```python
from qpubench.schemas import ClassiqCombinatorialOptimizationSpec

spec = ClassiqCombinatorialOptimizationSpec(
    problem_type="maxcut",       # same vocabulary as XenakisRunConfig.objective
    num_qaoa_layers=3,
    graph_edges=[(0, 1), (1, 2), (2, 0), (2, 3)],
)
```

`problem_type` intentionally reuses `XenakisRunConfig.objective`'s vocabulary
(`"maxcut"`, `"vqe_molecule"`) — the same maxcut instance can be handed to a
Xenakis GA search (`objective="maxcut"`) and to Classiq's QAOA synthesis, and
tagged identically in `BenchmarkRecord.tags`.

---

## Harmonization with Xenakis

### Shared molecule format

`XenakisMolecule` (xenakis.py) stores coordinates as a list of `(x, y, z)`
tuples; `ClassiqMoleculeSpec` stores `(symbol, (x, y, z))` pairs. Convert
between them directly — no intermediate format needed:

```python
from qpubench.schemas import ClassiqMoleculeSpec, XenakisMolecule

xen_mol = XenakisMolecule(
    name="H2", symbols=["H", "H"],
    coordinates_angstrom=[(0.0, 0.0, 0.0), (0.0, 0.0, 0.7414)],
)

classiq_mol = ClassiqMoleculeSpec.from_xenakis_molecule(xen_mol)
back_again  = classiq_mol.to_xenakis_molecule(name="H2", basis="sto-3g")
```

`ClassiqMoleculeSpec.spin` (2S) and `XenakisMolecule.multiplicity` (2S + 1) are
converted automatically by both directions.

### Comparing a GA-searched circuit against a Classiq-synthesized one

```python
from qpubench.schemas import CircuitOptimizationComparison
from qpubench.schemas import GARunResult, ClassiqSynthesisResult

comparison = CircuitOptimizationComparison(
    problem_label="H2 UCCSD ansatz, sto-3g",
    ga_result=ga_run_result,            # GARunResult (xenakis.py)
    classiq_result=classiq_synth_result,  # ClassiqSynthesisResult (classiq.py)
)

print(comparison.depth_delta)        # GA depth − Classiq depth
print(comparison.search_cost_label)  # "GA: 40 generations vs Classiq: 2.30s synthesis"
```

This is the practical difference between the two families: Xenakis trades wall
time for a searched circuit (measured in GA generations); Classiq trades a
single solve's latency for a synthesized one under hard bounds. Neither
dominates universally — `CircuitOptimizationComparison` exists to make that
comparison a first-class, serializable object rather than an ad-hoc script.

### Linking a Classiq run to a `BenchmarkRecord`

Mirrors `VQAConfig.ga_run_id` (Xenakis) with `VQAConfig.classiq_synthesis_id`:

```python
from qpubench.schemas import BenchmarkRecord, VQAConfig

vqa = VQAConfig(
    problem_type="chemistry",
    molecule="H2",
    algorithm="classiq_vqe",
    mapper="JordanWigner",
    ansatz="ucc",
    classiq_synthesis_id=result.program_id,
    final_eigenvalue=-1.1373,
)
```

---

## Optional dependency

```sh
pip install "qpubench[classiq]"
```

Requires separate authentication with `classiq.authenticate()` (device-code
flow against the Classiq cloud) before `synthesize()` / `execute()` calls will
succeed — see [docs.classiq.io](https://docs.classiq.io/) for setup. qpubench
itself never imports the `classiq` package directly; see
`integrations/classiq/` for the adapter that does.
