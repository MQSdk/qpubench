"""Xenakis & extensions data schemas.

Covers all three circuit-genome representations found in the Xenakis project
family and makes them interoperable with qpubench CircuitSpec / BenchmarkRecord.

Genome families
---------------
LayerGenome    Structured layer-based genome (QST-HACK-GA-simplified / qarchga).
               Serialised as best_genome.json; gates have explicit names, wires,
               and optional float parameters.

BitstringGenome  Original Xenakis binary-string genome.
                 Each gene is (6-bit gate code) + (5-bit qubit seed).
                 Decoding requires the Xenakis library; this model is a
                 data-holder only.

QNEATGenome    NEAT-style innovation-numbered gate genes (QST-HACK-Xenakis+qNEAT).
               Produces a Qiskit QuantumCircuit via get_circuit(); this model
               captures the structural data without the Qiskit dependency.

GA metadata
-----------
GAConfig            Genetic algorithm hyper-parameters.
GenomeConfig        Genome initialisation parameters.
XenakisMolecule     Molecule spec for VQE objectives (Xenakis/qarchga YAML format).
XenakisRunConfig    Full config snapshot (config_snapshot.yaml).
GAGenerationRecord  Per-generation evolution statistics (history.csv row).
GARunResult         Complete GA run output linking history + best genome.
"""
from __future__ import annotations

import enum
from typing import Any

import pydantic

from .circuit import CircuitSpec
from .primitives import CircuitFormat


# ---------------------------------------------------------------------------
# Layer-based genome  (qarchga — QST-HACK-GA-simplified)
# ---------------------------------------------------------------------------

class GateSpec(pydantic.BaseModel):
    """A single gate in a structured layer-based genome.

    Matches the dict format used by qarchga Genome.to_struct():
        {"name": "rx", "wires": [0], "param": 1.234}

    name   PennyLane / Qiskit gate name (lower-case): "rx", "ry", "rz", "cx",
           "h", "swap", "cz", "rxx", "rzz", etc.
    wires  qubit indices (1-qubit gates: len=1; 2-qubit: len=2; etc.)
    param  rotation angle in radians for parametric gates; None for fixed gates.
    """
    name:  str
    wires: list[int]
    param: float | None = None


class GenomeLayer(pydantic.BaseModel):
    """One time-step (layer) in a structured circuit genome."""
    gates: list[GateSpec]


class LayerGenome(pydantic.BaseModel):
    """Structured layer-based circuit genome (qarchga representation).

    Matches the best_genome.json output of QST-HACK-GA-simplified:
        {"n_qubits": 4, "age": 12, "layers": [[{"name":"rz","wires":[3],"param":2.27}]]}

    age        number of generations this genome has survived (age-fitness selection)
    depth      total number of layers (populated from len(layers))
    n_2q_gates total 2-qubit gate count (populated after evaluation)
    """
    n_qubits:  int
    layers:    list[GenomeLayer]
    age:       int   = 0
    n_2q_gates: int | None = None

    @property
    def depth(self) -> int:
        return len(self.layers)

    @property
    def gate_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for layer in self.layers:
            for gate in layer.gates:
                counts[gate.name] = counts.get(gate.name, 0) + 1
        return counts

    @classmethod
    def from_struct(cls, d: dict) -> LayerGenome:
        """Parse a qarchga Genome.to_struct() / best_genome.json dict."""
        parsed_layers: list[GenomeLayer] = []
        for raw_layer in d["layers"]:
            gates = [
                GateSpec(
                    name=g["name"],
                    wires=list(g["wires"]),
                    param=g.get("param"),
                )
                for g in raw_layer
            ]
            parsed_layers.append(GenomeLayer(gates=gates))
        return cls(
            n_qubits=int(d["n_qubits"]),
            age=int(d.get("age", 0)),
            layers=parsed_layers,
        )

    def to_struct(self) -> dict:
        """Serialise back to the qarchga Genome.to_struct() format."""
        return {
            "n_qubits": self.n_qubits,
            "age": self.age,
            "layers": [
                [{"name": g.name, "wires": g.wires, "param": g.param}
                 for g in layer.gates]
                for layer in self.layers
            ],
        }

    def to_circuit_spec(self) -> CircuitSpec:
        """Convert to a qpubench CircuitSpec (OpenQASM 2.0).

        Gate names are assumed to be valid QASM 2.0 / qelib1.inc identifiers.
        Parametric gates emit their stored angle directly.  The serialized
        field carries a well-formed QASM 2.0 string ready for execution.
        """
        lines = [
            "OPENQASM 2.0;",
            'include "qelib1.inc";',
            f"qreg q[{self.n_qubits}];",
        ]
        for layer in self.layers:
            for gate in layer.gates:
                wire_str = ", ".join(f"q[{w}]" for w in gate.wires)
                if gate.param is not None:
                    lines.append(f"{gate.name}({gate.param:.15f}) {wire_str};")
                else:
                    lines.append(f"{gate.name} {wire_str};")
        return CircuitSpec(
            num_qubits=self.n_qubits,
            format=CircuitFormat.QASM2,
            serialized="\n".join(lines),
            gate_counts=self.gate_counts,
        )


# ---------------------------------------------------------------------------
# Bitstring genome  (original Xenakis — QST-HACK-Xenakis-exploration)
# ---------------------------------------------------------------------------

class BitstringGenome(pydantic.BaseModel):
    """Original Xenakis binary-string circuit genome.

    The bitstring encodes n_gates consecutive genes; each gene is:
        bits [0:6]  gate type code (maps to PennyLane gate via string_to_gate)
        bits [6:]   qubit permutation seed (binary, length = gene_length - 6)

    gene_length = 6 + ceil(log2(n_qubits!)) bits; for the canonical H2 run
    with 4 qubits this is 6+5=11 bits, so str_len = n_gates * 11.

    Decoding to an actual circuit requires the Xenakis library; this model
    stores the genome string and its evaluation results only.

    Fields from sweep_results.csv:
        population, generations, n_gates, generation, genome, fitness, energy, is_best
    """
    genome_bitstring: str
    n_gates:          int
    gene_length:      int    # bits per gate (6 gate + qubit bits)
    n_qubits:         int
    fitness:          float | None = None
    energy:           float | None = None   # raw VQE energy (Hartree)
    is_best:          bool  = False

    @pydantic.model_validator(mode="after")
    def _check_length(self) -> BitstringGenome:
        expected = self.n_gates * self.gene_length
        if len(self.genome_bitstring) != expected:
            raise ValueError(
                f"genome_bitstring length {len(self.genome_bitstring)} "
                f"!= n_gates({self.n_gates}) × gene_length({self.gene_length}) "
                f"= {expected}"
            )
        return self

    @classmethod
    def from_sweep_row(
        cls,
        genome: str,
        n_qubits: int,
        n_gates: int,
        *,
        fitness: float | None = None,
        energy: float | None = None,
        is_best: bool = False,
    ) -> BitstringGenome:
        """Construct from a sweep_results.csv / ga_trace history row."""
        gene_length = len(genome) // n_gates
        return cls(
            genome_bitstring=genome,
            n_gates=n_gates,
            gene_length=gene_length,
            n_qubits=n_qubits,
            fitness=fitness,
            energy=energy,
            is_best=is_best,
        )


# ---------------------------------------------------------------------------
# qNEAT genome  (QST-HACK-Xenakis+qNEAT)
# ---------------------------------------------------------------------------

class QNEATGateType(str, enum.Enum):
    """Gate types available in the qNEAT circuit genome.

    The enum value equals the number of rotation parameters:
      ROT  = 3  (rx(θ₀) ry(θ₁) rz(θ₂) on a single qubit)
      CNOT = 0  (CNOT from qubit q to (q+1) mod n_qubits)
    """
    ROT  = "ROT"   # 3 parameters
    CNOT = "CNOT"  # 0 parameters

    @property
    def n_params(self) -> int:
        return 3 if self == QNEATGateType.ROT else 0


class QNEATGateGene(pydantic.BaseModel):
    """A single gate gene in a qNEAT genome (qNEAT.gate.GateGene).

    innovation_number  NEAT-style global counter; used for compatibility distance.
    gate_type          ROT or CNOT.
    qubit              target qubit index.
    parameters         rotation angles (len = gate_type.n_params).
    """
    innovation_number: int
    gate_type:         QNEATGateType
    qubit:             int
    parameters:        list[float] = []

    @pydantic.model_validator(mode="after")
    def _check_params(self) -> QNEATGateGene:
        expected = self.gate_type.n_params
        if len(self.parameters) != expected:
            raise ValueError(
                f"{self.gate_type} expects {expected} parameters, "
                f"got {len(self.parameters)}"
            )
        return self


class QNEATLayerEntry(pydantic.BaseModel):
    """All gates assigned to one layer index in a qNEAT genome."""
    layer_index: int
    gates:       list[QNEATGateGene]


class QNEATGenome(pydantic.BaseModel):
    """qNEAT genome with NEAT-style innovation numbers (qNEAT.genome.Genome).

    layers        ordered list of layer entries (sorted by layer_index)
    fitness       evaluated fitness value (negative VQE energy, or None)
    n_qubits      circuit width

    Compatibility distance between two genomes is based on the symmetric
    difference of their innovation numbers.
    """
    n_qubits: int
    layers:   list[QNEATLayerEntry]
    fitness:  float | None = None

    def innovation_numbers(self) -> set[int]:
        return {g.innovation_number for entry in self.layers for g in entry.gates}

    def compatibility_distance(self, other: QNEATGenome) -> float:
        s1 = self.innovation_numbers()
        s2 = other.innovation_numbers()
        disjoint = len(s1.symmetric_difference(s2))
        return disjoint / max(1, len(s1 | s2))

    def to_layer_genome(self) -> LayerGenome:
        """Best-effort conversion to LayerGenome (ROT → rz/ry/rz gates; CNOT → cx)."""
        genome_layers: list[GenomeLayer] = []
        for entry in sorted(self.layers, key=lambda e: e.layer_index):
            gates: list[GateSpec] = []
            for gene in entry.gates:
                if gene.gate_type == QNEATGateType.CNOT:
                    target = (gene.qubit + 1) % self.n_qubits
                    gates.append(GateSpec(name="cx", wires=[gene.qubit, target]))
                else:
                    # ROT → three consecutive single-qubit rotations
                    rx, ry, rz = gene.parameters
                    gates.extend([
                        GateSpec(name="rx", wires=[gene.qubit], param=rx),
                        GateSpec(name="ry", wires=[gene.qubit], param=ry),
                        GateSpec(name="rz", wires=[gene.qubit], param=rz),
                    ])
            genome_layers.append(GenomeLayer(gates=gates))
        return LayerGenome(n_qubits=self.n_qubits, layers=genome_layers)

    def to_circuit_spec(self) -> CircuitSpec:
        """Convert to a CircuitSpec via to_layer_genome()."""
        return self.to_layer_genome().to_circuit_spec()


# ---------------------------------------------------------------------------
# GA run configuration  (matches config_snapshot.yaml)
# ---------------------------------------------------------------------------

class GAConfig(pydantic.BaseModel):
    """Genetic algorithm hyper-parameters (qarchga ga: block).

    selection options: "tournament" | "rank" | "roulette" | "age_pareto"
    lambda_depth / lambda_2q: regularisation weights on circuit complexity.
    """
    generations:     int
    population_size: int
    elitism:         int   = 0
    selection:       str   = "tournament"
    tournament_k:    int   = 3
    crossover_rate:  float = 0.70
    mutation_rate:   float = 0.30
    lambda_depth:    float = 0.0   # penalty per layer
    lambda_2q:       float = 0.0   # penalty per 2-qubit gate


class GenomeConfig(pydantic.BaseModel):
    """Genome initialisation parameters (qarchga genome: block).

    n_qubits  None = determined automatically from the molecular Hamiltonian.
    init_layers  (lo, hi) — initial layer count drawn uniformly from [lo, hi].
    """
    n_qubits:    int | None         = None
    max_layers:  int                = 14
    init_layers: tuple[int, int]    = (3, 6)
    gate_set_1q: list[str]          = pydantic.Field(default_factory=lambda: ["rx", "ry", "rz"])
    gate_set_2q: list[str]          = pydantic.Field(default_factory=lambda: ["cx"])


class XenakisMolecule(pydantic.BaseModel):
    """Molecule specification for Xenakis VQE objectives (qarchga YAML format).

    coordinates_angstrom  one (x, y, z) tuple per atom (Angstroms).
                          Contrast with MolecularGeometry (cebule.py) which
                          uses a flat coordinate list.

    active_electrons / active_orbitals  None = full active space (PennyLane default).

    Conversion to MolecularGeometry (flat list):
        geom = MolecularGeometry(
            geometry=[c for xyz in mol.coordinates_angstrom for c in xyz],
            symbols=mol.symbols,
            basis=mol.basis,
            multiplicity=mol.multiplicity,
            charge=mol.charge,
        )
    """
    name:                str
    symbols:             list[str]
    coordinates_angstrom: list[tuple[float, float, float]]
    charge:              int        = 0
    multiplicity:        int        = 1
    basis:               str        = "sto-3g"
    active_electrons:    int | None = None
    active_orbitals:     int | None = None

    @pydantic.model_validator(mode="after")
    def _check_symbols(self) -> XenakisMolecule:
        if len(self.symbols) != len(self.coordinates_angstrom):
            raise ValueError(
                f"symbols length {len(self.symbols)} != "
                f"coordinates_angstrom length {len(self.coordinates_angstrom)}"
            )
        return self

    def flat_coordinates(self) -> list[float]:
        """Return coordinates as a flat list (MolecularGeometry / PennyLane convention)."""
        return [c for xyz in self.coordinates_angstrom for c in xyz]


class XenakisRunConfig(pydantic.BaseModel):
    """Complete run configuration snapshot (config_snapshot.yaml).

    backend     "pennylane" | "qiskit"
    objective   "vqe_molecule" | "maxcut"
    """
    seed:              int          = 0
    backend:           str          = "pennylane"
    objective:         str          = "vqe_molecule"
    molecule:          XenakisMolecule | None = None
    ga:                GAConfig
    genome:            GenomeConfig
    param_restarts:    int          = 1    # random restarts for local parameter search
    local_opt_steps:   int          = 0    # coordinate-descent steps per restart


# ---------------------------------------------------------------------------
# GA run results
# ---------------------------------------------------------------------------

class GAGenerationRecord(pydantic.BaseModel):
    """Per-generation evolution statistics.

    Covers both output formats:

    qarchga history.csv columns:
        gen, best_fitness, mean_fitness, best_depth, best_n2q, unique

    Xenakis-exploration GenRecord / sweep_results.csv columns:
        algo, run_id, molecule, generation, best_energy, best_fitness,
        best_complexity, pop_size
    """
    generation:       int
    best_fitness:     float
    mean_fitness:     float | None = None
    best_energy:      float | None = None   # raw VQE energy (Hartree)
    best_depth:       int | None   = None   # circuit depth of best genome
    best_n2q:         int | None   = None   # 2-qubit gate count of best genome
    unique:           int | None   = None   # distinct genomes in the population
    best_complexity:  float | None = None   # Xenakis ad-hoc complexity score
    algo:             str | None   = None   # "xenakis" | "qneat" | "qarchga" | …
    run_id:           str | None   = None
    molecule:         str | None   = None
    pop_size:         int | None   = None


class GARunResult(pydantic.BaseModel):
    """Complete genetic algorithm run result.

    best_genome       The winning genome in LayerGenome form.  For bitstring
                      or qNEAT runs use best_genome_bitstring / best_qneat_genome
                      respectively; callers that only need the circuit can call
                      best_circuit_spec() which picks the right conversion.

    run_dir           Filesystem path to the results folder written by the GA
                      engine (contains config_snapshot.yaml, history.csv,
                      best_genome.json, and optional plots/).
    """
    run_id:               str
    algo:                 str          = "xenakis"  # "xenakis" | "qarchga" | "qneat"
    config:               XenakisRunConfig | None = None
    history:              list[GAGenerationRecord]
    best_genome:          LayerGenome | None       = None
    best_genome_bitstring: BitstringGenome | None  = None
    best_qneat_genome:    QNEATGenome | None       = None
    best_fitness:         float
    best_energy:          float | None = None   # raw VQE energy of best genome
    run_dir:              str | None   = None

    def best_circuit_spec(self) -> CircuitSpec | None:
        """Return the best genome as a CircuitSpec, regardless of genome type."""
        if self.best_genome is not None:
            return self.best_genome.to_circuit_spec()
        if self.best_qneat_genome is not None:
            return self.best_qneat_genome.to_circuit_spec()
        # BitstringGenome cannot be decoded without the Xenakis library
        return None

    def final_generation_record(self) -> GAGenerationRecord | None:
        if not self.history:
            return None
        return max(self.history, key=lambda r: r.generation)


__all__ = [
    "BitstringGenome",
    "GAConfig",
    "GAGenerationRecord",
    "GARunResult",
    "GateSpec",
    "GenomeConfig",
    "GenomeLayer",
    "LayerGenome",
    "QNEATGateGene",
    "QNEATGateType",
    "QNEATGenome",
    "QNEATLayerEntry",
    "XenakisMolecule",
    "XenakisRunConfig",
]
