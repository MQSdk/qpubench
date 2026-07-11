"""Classiq SDK data schemas.

Covers Classiq's (https://docs.classiq.io/) constraint-driven circuit
synthesis pipeline and its chemistry / combinatorial-optimization
application layers, and harmonizes them with the Xenakis genetic-algorithm
circuit-search family (xenakis.py).

Classiq synthesis pipeline
---------------------------
ClassiqConstraints     Hard bounds (width / depth / gate count) plus the
                       objective the synthesis engine optimizes for.
ClassiqPreferences     Backend / transpilation preferences used at synthesis time.
ClassiqModel           High-level functional model (Qmod) + constraints/preferences —
                       the "build" input to Classiq's synthesize() call.
ClassiqSynthesisResult Synthesized QuantumProgram metadata; converts to CircuitSpec.

Execution
---------
ClassiqBackendPreferences / ClassiqExecutionPreferences   Execution-time backend selection.
ClassiqExecutionResult   Raw job result (counts), pre-conversion to QuantumResult.

Chemistry application
----------------------
ClassiqMoleculeSpec    Molecule spec (atoms as (symbol, xyz) pairs); converts
                       to/from XenakisMolecule (xenakis.py) and, via that,
                       MolecularGeometry (cebule.py).
ClassiqChemistryModel  Ground-state problem: fermion mapping + ansatz (UCC | HEA) + molecule.
ClassiqVQEResult       Chemistry VQE run result (mirrors GARunResult / UCCOptimizationResult).

Combinatorial optimization application
---------------------------------------
ClassiqCombinatorialOptimizationSpec  QAOA problem spec; problem_type vocabulary
                                      matches XenakisRunConfig.objective ("maxcut", ...).

Harmonization with Xenakis
---------------------------
Xenakis (xenakis.py) *searches* for a circuit: a genetic algorithm evolves a
population of genomes under soft complexity penalties (GAConfig.lambda_depth,
lambda_2q) until one scores well on a VQE / maxcut fitness function. Classiq
*synthesizes* a circuit directly from a high-level functional model under hard
Constraints (max_width, max_depth) plus an optimization_parameter objective —
no population, no generations, just a single constrained-optimization solve.

Both are circuit-optimization strategies and both converge on the same
qpubench CircuitSpec (GARunResult.best_circuit_spec() /
ClassiqSynthesisResult.to_circuit_spec()), so they plug into the same
BenchmarkRunner and can be benchmarked against each other on identical
problems. CircuitOptimizationComparison packages a head-to-head result;
ClassiqMoleculeSpec.from_xenakis_molecule() / .to_xenakis_molecule() bridge
the two chemistry-molecule representations so the same molecule can be
handed to either pipeline.

Schema version: 1.13.0
"""
from __future__ import annotations

import enum

import pydantic

from .circuit import CircuitSpec
from .primitives import CircuitFormat
from .record import VQAConfig
from .mqsdk_xenakis import GARunResult, XenakisMolecule


# ---------------------------------------------------------------------------
# Shared enumerations
# ---------------------------------------------------------------------------

class ClassiqOptimizationParameter(str, enum.Enum):
    """Synthesis objective the Classiq engine minimizes subject to Constraints.

    Provider-neutral simplification of Classiq's OptimizationParameter —
    exact wire values may vary by SDK version.
    """
    NONE      = "no_optimization"
    WIDTH     = "width"
    DEPTH     = "depth"
    CX_COUNT  = "cx_count"


class ClassiqTranspilationOption(str, enum.Enum):
    """How aggressively Classiq's synthesis engine decomposes/optimizes gates."""
    NONE      = "none"
    DECOMPOSE = "decompose"
    OPTIMIZE  = "optimize"


class ClassiqBackendProvider(str, enum.Enum):
    """Cloud/hardware providers reachable through Classiq's execution layer."""
    CLASSIQ_SIMULATOR = "classiq_simulator"
    IBM_QUANTUM        = "ibm_quantum"
    AZURE_QUANTUM      = "azure_quantum"
    AMAZON_BRAKET      = "amazon_braket"
    IONQ               = "ionq"


class ClassiqQuantumFormat(str, enum.Enum):
    """Export formats Classiq's synthesize() can emit for a QuantumProgram."""
    QASM   = "qasm"
    QASM3  = "qasm3"
    QSHARP = "qsharp"
    QIR    = "qir"


class ClassiqFermionMapping(str, enum.Enum):
    """Fermion-to-qubit mapping used by a ClassiqChemistryModel.

    Values match VQAConfig.mapper's free-string vocabulary ("Parity" |
    "JordanWigner" | "BravyiKitaev" | "MQS") so .value can be assigned
    directly to VQAConfig.mapper without translation.
    """
    JORDAN_WIGNER = "JordanWigner"
    PARITY        = "Parity"
    BRAVYI_KITAEV = "BravyiKitaev"


class ClassiqAnsatzType(str, enum.Enum):
    UCC = "ucc"   # unitary coupled cluster (chemistry-informed excitations)
    HEA = "hea"   # hardware-efficient ansatz (repeated rotation + entangling layers)


# ---------------------------------------------------------------------------
# Synthesis pipeline
# ---------------------------------------------------------------------------

class ClassiqConstraints(pydantic.BaseModel):
    """Hard synthesis bounds and the objective Classiq optimizes for.

    max_gate_count is keyed by native gate name, e.g. {"cx": 100}.
    optimization_parameter is the *soft* counterpart of Xenakis's
    GAConfig.lambda_depth / lambda_2q — Classiq treats it as a single hard
    objective rather than a weighted penalty term.
    """
    max_width:              int | None                     = None
    max_depth:              int | None                     = None
    max_gate_count:         dict[str, int]                 = {}
    optimization_parameter: ClassiqOptimizationParameter    = ClassiqOptimizationParameter.NONE


class ClassiqPreferences(pydantic.BaseModel):
    """Synthesis-time backend and transpilation preferences.

    Distinct from ClassiqExecutionPreferences: these steer how the circuit
    is *built*, not where it later *runs*.
    """
    backend_service_provider: ClassiqBackendProvider | None    = None
    backend_name:              str | None                       = None
    random_seed:               int | None                       = None
    transpilation_option:      ClassiqTranspilationOption       = ClassiqTranspilationOption.DECOMPOSE
    output_format:             list[ClassiqQuantumFormat]       = [ClassiqQuantumFormat.QASM3]
    optimization_timeout_s:    float | None                     = None


class ClassiqModel(pydantic.BaseModel):
    """High-level functional model — the "build" input to Classiq's synthesize().

    qmod_source holds the native Qmod text (or a JSON dump of the
    @qfunc-decorated Python model) produced by the Classiq SDK. Building the
    functional model itself requires the Classiq SDK; this model captures
    the build request envelope only, mirroring how BitstringGenome
    (xenakis.py) holds a genome string without decoding it.
    """
    name:              str
    qmod_source:       str | None                       = None
    constraints:       ClassiqConstraints                = pydantic.Field(default_factory=ClassiqConstraints)
    preferences:       ClassiqPreferences                = pydantic.Field(default_factory=ClassiqPreferences)
    classiq_version:   str | None                        = None


class ClassiqSynthesisResult(pydantic.BaseModel):
    """Synthesized QuantumProgram metadata returned by Classiq's synthesize().

    width / depth / gate_count describe the circuit actually produced —
    the outcome of optimizing under ClassiqConstraints, comparable to
    LayerGenome.depth / gate_counts (xenakis.py) for the same problem.
    """
    program_id:              str | None                     = None
    qasm3:                   str | None                     = None
    qasm2:                   str | None                     = None
    width:                   int | None                      = None
    depth:                   int | None                      = None
    gate_count:              dict[str, int]                  = {}
    cx_count:                int | None                      = None
    synthesis_duration_s:    float | None                    = None
    constraints_satisfied:   bool                             = True
    transpilation_option:    ClassiqTranspilationOption | None = None

    def to_circuit_spec(self) -> CircuitSpec:
        """Convert to a qpubench CircuitSpec (OpenQASM 3.0 preferred)."""
        if self.width is None:
            raise ValueError("ClassiqSynthesisResult.width must be populated")
        if self.qasm3 is not None:
            return CircuitSpec.from_openqasm3(
                self.qasm3, num_qubits=self.width, gate_counts=self.gate_count,
            )
        if self.qasm2 is not None:
            return CircuitSpec(
                num_qubits=self.width,
                format=CircuitFormat.QASM2,
                serialized=self.qasm2,
                gate_counts=self.gate_count,
            )
        raise ValueError("ClassiqSynthesisResult carries neither qasm3 nor qasm2 output")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class ClassiqBackendPreferences(pydantic.BaseModel):
    backend_service_provider: ClassiqBackendProvider = ClassiqBackendProvider.CLASSIQ_SIMULATOR
    backend_name:              str | None              = None


class ClassiqExecutionPreferences(pydantic.BaseModel):
    num_shots:            int                          = 1000
    backend_preferences:  ClassiqBackendPreferences     = pydantic.Field(
        default_factory=ClassiqBackendPreferences
    )
    random_seed:          int | None                    = None
    job_name:             str | None                    = None


class ClassiqExecutionResult(pydantic.BaseModel):
    """Raw job result from Classiq's execute(), pre-conversion to QuantumResult.

    Mirrors the provider-native-result layering used elsewhere (e.g.
    FireOpalResult.mitigated_counts in error_mitigation.py): counts are kept
    in Classiq's own dict[str, int] shape here; adapters convert to
    qpubench's ShotResult when populating QuantumResult.
    """
    job_id:            str | None        = None
    counts:            dict[str, int]    = {}
    backend_name:      str | None        = None
    execution_time_s:  float | None      = None


# ---------------------------------------------------------------------------
# Chemistry application
# ---------------------------------------------------------------------------

class ClassiqMoleculeSpec(pydantic.BaseModel):
    """Molecule specification (classiq.applications.chemistry.Molecule shape).

    atoms      one (symbol, (x, y, z)) tuple per atom, Angstroms.
    spin       2S (twice the total spin); spin=0 for a closed-shell singlet.
               Contrast with XenakisMolecule.multiplicity = 2S + 1.
    """
    atoms:  list[tuple[str, tuple[float, float, float]]]
    charge: int = 0
    spin:   int = 0

    @property
    def multiplicity(self) -> int:
        return self.spin + 1

    @classmethod
    def from_xenakis_molecule(cls, mol: XenakisMolecule) -> ClassiqMoleculeSpec:
        """Bridge from the Xenakis VQE-objective molecule format (xenakis.py)."""
        return cls(
            atoms=list(zip(mol.symbols, mol.coordinates_angstrom)),
            charge=mol.charge,
            spin=mol.multiplicity - 1,
        )

    def to_xenakis_molecule(
        self,
        *,
        name: str,
        basis: str = "sto-3g",
        active_electrons: int | None = None,
        active_orbitals:  int | None = None,
    ) -> XenakisMolecule:
        """Bridge to the Xenakis VQE-objective molecule format (xenakis.py)."""
        return XenakisMolecule(
            name=name,
            symbols=[a[0] for a in self.atoms],
            coordinates_angstrom=[a[1] for a in self.atoms],
            charge=self.charge,
            multiplicity=self.multiplicity,
            basis=basis,
            active_electrons=active_electrons,
            active_orbitals=active_orbitals,
        )


class ClassiqChemistryModel(pydantic.BaseModel):
    """Ground-state chemistry problem (mapping + ansatz + molecule).

    ucc_excitations   excitation orders included in the UCC ansatz pool,
                      e.g. [1, 2] for singles + doubles. Ignored for HEA.
    hea_reps          number of repeated rotation/entangling layers; only
                      meaningful when ansatz == HEA.
    """
    molecule:               ClassiqMoleculeSpec
    mapping:                ClassiqFermionMapping    = ClassiqFermionMapping.JORDAN_WIGNER
    basis:                  str                       = "sto-3g"
    freeze_core:            bool                      = False
    z2_symmetry_reduction:  bool                      = False
    ansatz:                 ClassiqAnsatzType         = ClassiqAnsatzType.UCC
    ucc_excitations:        list[int]                 = [1, 2]
    hea_reps:               int | None                = None


class ClassiqVQEResult(pydantic.BaseModel):
    """Chemistry VQE run result (mirrors GARunResult / UCCOptimizationResult).

    synthesis   the ClassiqSynthesisResult for the final bound ansatz circuit,
                when the caller chose to synthesize it explicitly rather than
                relying on Classiq's own execute() pipeline end-to-end.
    """
    final_energy:           float
    hf_energy:               float | None      = None
    optimized_parameters:    list[float]        = []
    convergence_values:      list[float]        = []
    num_iterations:          int | None         = None
    synthesis:               ClassiqSynthesisResult | None = None

    def to_vqa_config(
        self,
        *,
        molecule: str,
        model: ClassiqChemistryModel,
    ) -> VQAConfig:
        """Populate qpubench's shared VQAConfig from a Classiq chemistry run.

        Reuses VQAConfig's existing generic fields (mapper, ansatz, n_cnot,
        num_parameters) rather than introducing Classiq-specific duplicates —
        the same fields QForte and Cebule already populate.
        """
        synthesis_id = self.synthesis.program_id if self.synthesis else None
        n_cnot = self.synthesis.cx_count if self.synthesis else None
        return VQAConfig(
            problem_type="chemistry",
            molecule=molecule,
            basis=model.basis,
            hf_energy=self.hf_energy,
            algorithm="classiq_vqe",
            mapper=model.mapping.value,
            ansatz=model.ansatz.value,
            num_parameters=len(self.optimized_parameters),
            n_cnot=n_cnot,
            convergence_values=self.convergence_values,
            final_eigenvalue=self.final_energy,
            classiq_synthesis_id=synthesis_id,
        )


# ---------------------------------------------------------------------------
# Combinatorial optimization application
# ---------------------------------------------------------------------------

class ClassiqCombinatorialOptimizationSpec(pydantic.BaseModel):
    """QAOA combinatorial-optimization problem spec.

    problem_type vocabulary intentionally matches XenakisRunConfig.objective
    ("maxcut", ...) so the same problem tag flows through both a Xenakis GA
    search and a Classiq QAOA synthesis run.

    graph_edges / graph_weights   maxcut-style graph; empty weights = unweighted.
    alpha_cvar                   CVaR risk parameter for the QAOA cost function;
                                  1.0 = standard expectation value.
    """
    problem_type:      str                     = "maxcut"
    num_qaoa_layers:    int                     = 1
    penalty_energy:     float                   = 2.0
    max_iteration:       int                     = 60
    alpha_cvar:          float                   = 1.0
    graph_edges:         list[tuple[int, int]]  = []
    graph_weights:       list[float]             = []


# ---------------------------------------------------------------------------
# Harmonization with Xenakis
# ---------------------------------------------------------------------------

class CircuitOptimizationComparison(pydantic.BaseModel):
    """Head-to-head comparison of a Xenakis GA search vs a Classiq synthesis
    run solving the same circuit-optimization problem (see module docstring).

    Either side may be absent (e.g. before both runs have completed);
    properties degrade to None rather than raising.
    """
    problem_label:    str
    ga_result:        GARunResult | None            = None
    classiq_result:    ClassiqSynthesisResult | None  = None

    @property
    def depth_delta(self) -> int | None:
        """GA best-genome depth minus Classiq depth; positive = GA is deeper."""
        ga_depth = (
            self.ga_result.best_genome.depth
            if self.ga_result is not None and self.ga_result.best_genome is not None
            else None
        )
        cl_depth = self.classiq_result.depth if self.classiq_result is not None else None
        if ga_depth is None or cl_depth is None:
            return None
        return ga_depth - cl_depth

    @property
    def search_cost_label(self) -> str:
        """Best-effort description of the search/synthesis cost on each side."""
        parts: list[str] = []
        if self.ga_result is not None:
            parts.append(f"GA: {len(self.ga_result.history)} generations")
        if self.classiq_result is not None and self.classiq_result.synthesis_duration_s is not None:
            parts.append(f"Classiq: {self.classiq_result.synthesis_duration_s:.2f}s synthesis")
        return " vs ".join(parts) if parts else "no data"


__all__ = [
    "CircuitOptimizationComparison",
    "ClassiqAnsatzType",
    "ClassiqBackendPreferences",
    "ClassiqBackendProvider",
    "ClassiqChemistryModel",
    "ClassiqCombinatorialOptimizationSpec",
    "ClassiqConstraints",
    "ClassiqExecutionPreferences",
    "ClassiqExecutionResult",
    "ClassiqFermionMapping",
    "ClassiqModel",
    "ClassiqMoleculeSpec",
    "ClassiqOptimizationParameter",
    "ClassiqPreferences",
    "ClassiqQuantumFormat",
    "ClassiqSynthesisResult",
    "ClassiqTranspilationOption",
    "ClassiqVQEResult",
]
