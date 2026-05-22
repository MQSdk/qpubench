# GSOpt integration

[GSOpt](https://github.com/bestquark/gsopt) is a fixed-budget ground-state optimisation benchmark harness. It drives agent-based mutation loops across five benchmark categories and records structured JSON results from each run.

Schemas: `src/qpubench/schemas/gsopt.py`

---

## Benchmark categories

| `GSOptBenchmarkLane` | Method | Backend |
|---|---|---|
| `VQE` | Variational Quantum Eigensolver | CUDA-Q quantum circuits |
| `TN` | Tensor network ground-state | Classical |
| `DMRG` | Density-matrix renormalisation group | Classical |
| `AFQMC` | Auxiliary-field quantum Monte Carlo | PySCF + ipie |
| `GIBBS` | Gibbs / MCMC exact-reference | Classical |

---

## VQE benchmark molecules

Five molecules are available in `examples/vqe/`:

| Molecule | `active_electrons` | `active_orbitals` | Reference energy (Ha) |
|---|---|---|---|
| `BH` | 2 | 3 | −24.775702988648234 |
| `LiH` | 2 | 4 | −7.864518501418702 |
| `BeH2` | 4 | 4 | −15.566235181521328 |
| `H2O` | 6 | 4 | −74.97042716151374 |
| `N2` | 6 | 6 | −107.6231017720174 |

```python
from qpubench.schemas import REFERENCE_ENERGIES, reference_energy

print(reference_energy("BH"))      # −24.775702988648234
print(reference_energy("bh"))      # same (case-insensitive)
print(reference_energy("H2O"))     # −74.97042716151374
print(reference_energy("unknown")) # None
```

---

## Parsing `simple_vqe.py` output

GSOpt VQE benchmarks write a JSON object to stdout. Parse it directly into `GSOptBenchmarkResult`:

```python
import json, subprocess
from qpubench.schemas import GSOptBenchmarkResult

# Run the benchmark
proc = subprocess.run(
    ["uv", "run", "python", "examples/vqe/bh/simple_vqe.py"],
    capture_output=True, text=True, cwd="/path/to/gsopt",
)
data   = json.loads(proc.stdout)
result = GSOptBenchmarkResult.model_validate(data)

# Derived metrics
print(f"Final energy:   {result.final_energy:.6f} Ha")
print(f"Energy error:   {result.energy_error:.6f} Ha")    # vs REFERENCE_ENERGIES
print(f"Chem accuracy:  {result.chemical_accuracy_achieved}")
print(f"Corr. fraction: {result.correlation_energy_fraction:.3%}")
print(f"Wall time:      {result.wall_seconds:.1f}s / {result.wall_budget_seconds:.1f}s")
```

---

## Bridge to `BenchmarkRecord`

```python
from qpubench.schemas import (
    BenchmarkRecord, VQAConfig, BackendSpec, CircuitSpec, ExecutionOptions,
)
from qpubench.schemas.primitives import CircuitFormat

# Convert GSOpt result → qpubench record
quantum_result = result.to_quantum_result()
vqa            = VQAConfig(**result.to_vqa_config())

backend = BackendSpec.cudaq(target="nvidia", num_qubits=result.cas.active_orbitals * 2)
circuit = CircuitSpec(
    num_qubits=backend.num_qubits,
    format=CircuitFormat.QASM2,
    # serialized would hold the ansatz QASM if captured
)
options = ExecutionOptions(shots=None)   # statevector (CUDA-Q default)

record = BenchmarkRecord(
    circuit=circuit,
    backend=backend,
    options=options,
    result=quantum_result,
    vqa=vqa,
    num_qubits=circuit.num_qubits,
    circuit_depth=result.circuit_depth,
    tags=["gsopt", result.task, result.molecule.lower()],
)
```

---

## VQE run configuration

The `config` sub-object from `simple_vqe.py` JSON maps to `VQERunConfig`:

```python
from qpubench.schemas import VQERunConfig, VQEAnsatzType, VQEOptimizerType

config = VQERunConfig(
    name="uccsd_2_BH",
    ansatz=VQEAnsatzType.UCCSD,         # or "uccsd" string
    layers=2,
    optimizer=VQEOptimizerType.COBYLA,  # or "cobyla" string
    max_steps=100,
    init_scale=0.01,
    seed=42,
    initial_parameters=[0.1, -0.2, 0.05],
    cobyla_rhobeg=0.1,
)

# ansatz enum values
VQEAnsatzType.HEA_RY_RING.value    # "hea_ry_ring"
VQEAnsatzType.HEA_RYRZ_RING.value  # "hea_ryrz_ring"
VQEAnsatzType.UCCSD.value          # "uccsd"
```

---

## Active space

```python
from qpubench.schemas import ActiveSpaceSpec

cas = ActiveSpaceSpec(
    active_electrons=2,
    active_orbitals=3,
    occupied_indices=[0],       # doubly-occupied core MO indices
    active_indices=[1, 2, 3],  # active-space MO indices
)
```

Map to `VQAConfig` active-space fields:

```python
vqa = VQAConfig(
    problem_type="chemistry",
    molecule="BH",
    active_electrons=cas.active_electrons,
    active_orbitals=cas.active_orbitals,
    nfev=result.nfev,
)
```

---

## Benchmark metadata (`.gsopt.json`)

Each benchmark directory contains a `.gsopt.json` file that GSOpt reads to configure the run:

```python
import json
from qpubench.schemas import GSOptBenchmarkMeta

with open("examples/vqe/bh/.gsopt.json") as f:
    meta = GSOptBenchmarkMeta.model_validate(json.load(f))

print(meta.lane)                  # "vqe"
print(meta.display_name)          # "BH VQE"
print(meta.default_wall_seconds)  # 20.0
print(meta.source)                # "simple_vqe.py"
print(meta.evaluator)             # "evaluate.py"
```

---

## CUDA-Q backend

GSOpt VQE benchmarks run on CUDA-Q. Register the backend with `BackendSpec.cudaq()`:

```python
from qpubench.schemas import BackendSpec

backend = BackendSpec.cudaq(target="nvidia")   # GPU
backend = BackendSpec.cudaq(target="qpp-cpu")  # CPU simulator
```

Install CUDA-Q per [NVIDIA's instructions](https://nvidia.github.io/cuda-quantum/). It is not available on PyPI or conda-forge.

---

## Scoring

The evaluator (`evaluate.py`) sets:

- `score` = `final_energy` (lower is better)
- Strips reference fields: `target_energy`, `final_error`, `abs_final_error`, `chem_acc_step`

`GSOptBenchmarkResult` retains all fields including the stripped ones for qpubench's internal use (offline comparison against `REFERENCE_ENERGIES`).
