# Xenakis integration

[Xenakis](https://github.com/mqsdk/xenakis) is an automated quantum circuit composer using genetic algorithms. Three sub-project variants are modelled in `src/qpubench/schemas/mqsdk_xenakis.py`.

---

## Sub-projects and genome types

| Sub-project | Location | Genome type | Key files |
|---|---|---|---|
| Original Xenakis | `QST-HACK-Xenakis-exploration/` | `BitstringGenome` | `genetic_algorithm.py`, `sweep_results.csv` |
| qarchga (GA simplified) | `QST-HACK-GA-simplified/` | `LayerGenome` | `best_genome.json`, `history.csv` |
| Xenakis+qNEAT | `QST-HACK-Xenakis+qNEAT/` | `QNEATGenome` | `qNEAT/genome.py`, `benchmark.py` |

---

## `LayerGenome` (qarchga)

Structured layer-based genome. Directly round-trips with `best_genome.json`.

```python
import json
from qpubench.schemas import LayerGenome, CircuitSpec

# Parse best_genome.json
with open("results/run_20260129_230314/best_genome.json") as f:
    raw = json.load(f)

genome = LayerGenome.from_struct(raw)
print(f"Depth:      {genome.depth}")
print(f"Gate counts: {genome.gate_counts}")   # {'rz': 1}

# Convert to a CircuitSpec for qpubench execution
spec: CircuitSpec = genome.to_circuit_spec()
print(spec.serialized)
# OPENQASM 2.0;
# include "qelib1.inc";
# qreg q[4];
# rz(2.269239756377628) q[3];
```

### Serialisation round-trip

```python
struct = genome.to_struct()           # back to best_genome.json format
genome2 = LayerGenome.from_struct(struct)
assert genome2.depth == genome.depth
```

---

## `BitstringGenome` (original Xenakis)

Binary string genome from `sweep_results.csv`. Decoding to an actual circuit requires the Xenakis library — this model is a **data holder only**.

```python
from qpubench.schemas import BitstringGenome

# From a sweep_results.csv row (population=20, n_gates=4, n_qubits=4)
genome = BitstringGenome.from_sweep_row(
    genome="10000000011111010110110111011011011001100010",
    n_qubits=4,
    n_gates=4,
    fitness=1.135789,
    energy=-1.1361891625101652,
    is_best=True,
)
# gene_length is inferred: len(bitstring) / n_gates = 11 (6 gate + 5 qubit bits)
print(genome.gene_length)   # 11
```

---

## `QNEATGenome`

NEAT-style genome with innovation-numbered gate genes.

```python
from qpubench.schemas import (
    QNEATGenome, QNEATLayerEntry, QNEATGateGene, QNEATGateType,
)

genome = QNEATGenome(
    n_qubits=4,
    layers=[
        QNEATLayerEntry(layer_index=0, gates=[
            QNEATGateGene(innovation_number=1, gate_type=QNEATGateType.ROT,
                          qubit=0, parameters=[0.1, 0.2, 0.3]),
            QNEATGateGene(innovation_number=2, gate_type=QNEATGateType.CNOT,
                          qubit=1, parameters=[]),
        ]),
    ],
    fitness=-1.113,
)

# Compatibility distance between two genomes
dist = genome.compatibility_distance(other_genome)

# Convert to LayerGenome (ROT → rx/ry/rz) then to CircuitSpec
spec = genome.to_circuit_spec()
```

---

## GA run configuration and history

### Config snapshot

```python
from qpubench.schemas import (
    XenakisRunConfig, GAConfig, GenomeConfig, XenakisMolecule,
)

config = XenakisRunConfig(
    seed=7,
    backend="pennylane",
    objective="vqe_molecule",
    molecule=XenakisMolecule(
        name="H2",
        symbols=["H", "H"],
        coordinates_angstrom=[(0.0, 0.0, 0.0), (0.0, 0.0, 0.7414)],
        basis="sto-3g",
    ),
    ga=GAConfig(
        generations=25,
        population_size=40,
        elitism=2,
        selection="tournament",
        tournament_k=4,
        crossover_rate=0.65,
        mutation_rate=0.35,
        lambda_depth=0.01,
        lambda_2q=0.03,
    ),
    genome=GenomeConfig(
        max_layers=14,
        init_layers=(4, 8),
        gate_set_1q=["rx", "ry", "rz"],
        gate_set_2q=["cx"],
    ),
    param_restarts=2,
    local_opt_steps=30,
)
```

### History CSV

```python
from qpubench.schemas import GAGenerationRecord

# Parse a history.csv row
record = GAGenerationRecord(
    generation=5,
    best_fitness=1.0858713,
    mean_fitness=0.5245426,
    best_depth=3,
    best_n2q=0,
    unique=40,
)
```

### Full GA run result

```python
from qpubench.schemas import GARunResult

result = GARunResult(
    run_id="run_20260129_230314",
    algo="qarchga",
    config=config,
    history=[...],               # list[GAGenerationRecord]
    best_genome=genome,          # LayerGenome
    best_fitness=1.1066843,
    best_energy=-1.1067,
    run_dir="results/run_20260129_230314/",
)

# Get a CircuitSpec from whatever genome type was stored
spec = result.best_circuit_spec()

# Link to a BenchmarkRecord
from qpubench.schemas import BenchmarkRecord, VQAConfig

vqa = VQAConfig(
    problem_type="chemistry",
    molecule="H2",
    basis="sto-3g",
    ga_run_id=result.run_id,
    final_eigenvalue=result.best_energy,
)
```

---

## `XenakisMolecule` ↔ `MolecularGeometry`

`XenakisMolecule` uses `coordinates_angstrom` as a list of `(x, y, z)` tuples (matching the YAML config format). `MolecularGeometry` (Cebule) uses a flat list.

```python
flat = mol.flat_coordinates()   # [x0, y0, z0, x1, y1, z1, …]
```

---

## Tagging benchmark records from evolutionary runs

Use `VQAConfig.ga_run_id`, `genome_hash`, and `best_complexity` to link a qpubench record back to a Xenakis run:

```python
from qpubench.schemas.utils.hashing import stable_hash   # qarchga utility

vqa = VQAConfig(
    problem_type="chemistry",
    molecule="H2",
    algorithm="qarchga",
    optimizer="tournament_selection",
    ga_run_id="run_20260129_230314",
    genome_hash=stable_hash(genome.to_struct()),
    best_complexity=0.01 * genome.depth + 0.03 * genome.count_2q(),
    final_eigenvalue=-1.1067,
)
```
