"""GSOpt benchmark framework data schemas.

GSOpt (github.com/bestquark/gsopt) is a fixed-budget ground-state optimisation
benchmark harness.  It drives agent-based mutation loops across five benchmark
categories and records structured JSON results from each run.

Schema coverage
---------------
GSOptBenchmarkLane  benchmark category enum (vqe, tn, dmrg, afqmc, gibbs)
VQEAnsatzType       hea_ry_ring | hea_ryrz_ring | uccsd
VQEOptimizerType    cobyla | powell | nelder_mead  (classical optimisers)
ActiveSpaceSpec     active electrons / orbitals + index arrays
VQERunConfig        the "config" sub-object in simple_vqe.py JSON output
GSOptBenchmarkResult  full JSON output of simple_vqe.py / evaluate.py
GSOptBenchmarkMeta  .gsopt.json metadata file format

Reference energies
    REFERENCE_ENERGIES — FCI/CCSD(T) reference energies for the five GSOpt
                         VQE molecules: BH, LiH, BeH2, H2O, N2

Interop with qpubench
---------------------
GSOptBenchmarkResult.to_quantum_result()  → QuantumResult
GSOptBenchmarkResult.to_vqa_config()      → dict for VQAConfig(**...)
GSOptBenchmarkResult.energy_error         → float (vs REFERENCE_ENERGIES)
GSOptBenchmarkResult.chemical_accuracy_achieved → bool (<1 mHartree)
"""
from __future__ import annotations

from typing import Any

import enum

import pydantic

from .primitives import ComputingModel, JobStatus
from .result import ExpectationResult, QuantumResult


# ---------------------------------------------------------------------------
# Reference energies  (examples/vqe/reference_energies.py)
# ---------------------------------------------------------------------------

REFERENCE_ENERGIES: dict[str, float] = {
    "BH":   -24.775702988648234,
    "LiH":  -7.864518501418702,
    "BeH2": -15.566235181521328,
    "H2O":  -74.97042716151374,
    "N2":   -107.6231017720174,
}

_MOLECULE_ALIASES: dict[str, str] = {
    "bh": "BH", "lih": "LiH", "beh2": "BeH2", "h2o": "H2O", "n2": "N2",
}


def reference_energy(molecule: str) -> float | None:
    """Return the FCI/CCSD(T) reference energy for a named molecule, or None."""
    canonical = _MOLECULE_ALIASES.get(molecule.strip().lower(), molecule.strip())
    return REFERENCE_ENERGIES.get(canonical)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class GSOptBenchmarkLane(str, enum.Enum):
    """Top-level benchmark category in the GSOpt framework."""
    VQE   = "vqe"    # CUDA-Q quantum circuits
    TN    = "tn"     # tensor-network ground-state
    DMRG  = "dmrg"   # density-matrix renormalisation group
    AFQMC = "afqmc"  # auxiliary-field quantum Monte Carlo (PySCF + ipie)
    GIBBS = "gibbs"  # Gibbs / MCMC exact-reference experiments


class VQEAnsatzType(str, enum.Enum):
    """Quantum ansatz variants available in GSOpt VQE benchmarks.

    HEA_RY_RING    hardware-efficient ansatz: RY rotations + ring CNOT topology
    HEA_RYRZ_RING  HEA with both RY and RZ rotations in ring topology
    UCCSD          unitary coupled-cluster singles and doubles
    CUSTOM         user-defined ansatz (serialise via CircuitSpec)
    """
    HEA_RY_RING   = "hea_ry_ring"
    HEA_RYRZ_RING = "hea_ryrz_ring"
    UCCSD         = "uccsd"
    CUSTOM        = "custom"


class VQEOptimizerType(str, enum.Enum):
    """Classical parameter optimisers used in GSOpt VQE benchmarks.

    COBYLA       — Constrained Optimisation BY Linear Approximations
    POWELL       — Powell's conjugate direction method
    NELDER_MEAD  — Nelder-Mead simplex method
    """
    COBYLA      = "cobyla"
    POWELL      = "powell"
    NELDER_MEAD = "nelder_mead"


# ---------------------------------------------------------------------------
# Active space
# ---------------------------------------------------------------------------

class ActiveSpaceSpec(pydantic.BaseModel):
    """Active space definition for molecular quantum chemistry calculations.

    Matches the "cas" sub-object in GSOpt simple_vqe.py JSON output.

    active_electrons  correlated electrons in the active space
    active_orbitals   spatial orbitals in the active space
    occupied_indices  MO indices of doubly-occupied core (outside active space)
    active_indices    MO indices of the active-space orbitals

    Note: corresponds to VQAConfig.active_electrons / active_orbitals (new
    fields added in schema v1.3.0) at the BenchmarkRecord level.
    """
    active_electrons: int
    active_orbitals:  int
    occupied_indices: list[int] = []
    active_indices:   list[int] = []


# ---------------------------------------------------------------------------
# VQE run configuration
# ---------------------------------------------------------------------------

class VQERunConfig(pydantic.BaseModel):
    """Configuration of a single GSOpt VQE run (the "config" JSON sub-object).

    name          human-readable run identifier (ansatz + layers + molecule)
    ansatz        circuit structure; VQEAnsatzType value or custom string
    layers        number of ansatz repetition layers
    optimizer     classical optimizer; VQEOptimizerType value or custom string
    max_steps     maximum optimizer iterations
    init_scale    standard deviation of random parameter initialisation
    seed          RNG seed for reproducibility
    initial_parameters  parameter vector at the start of optimisation

    Optimizer-specific tolerances (None = optimizer default):
      cobyla_rhobeg      initial trust-region radius for COBYLA
      powell_xtol        x-convergence tolerance for Powell
      nelder_mead_xatol  absolute tolerance on simplex x-coordinates
    """
    name:               str
    ansatz:             str
    layers:             int
    optimizer:          str
    max_steps:          int
    init_scale:         float
    seed:               int
    initial_parameters: list[float] = []
    cobyla_rhobeg:      float | None = None
    powell_xtol:        float | None = None
    nelder_mead_xatol:  float | None = None


# ---------------------------------------------------------------------------
# Benchmark result
# ---------------------------------------------------------------------------

class GSOptBenchmarkResult(pydantic.BaseModel):
    """Full JSON result produced by a GSOpt benchmark run (simple_vqe.py output).

    This is the canonical structure written to stdout and scored by evaluate.py.
    Reference fields (target_energy, final_error, chem_acc_step) are retained
    for full fidelity; the evaluator strips them before publishing the score.

    score         primary metric value (= final_energy for VQE; lower is better)
    metric        name of the scoring field (default "final_energy")
    lower_is_better  True for energy minimisation tasks
    chemical_accuracy  threshold used to declare success (default 1e-3 Hartree)
    circuit_depth     transpiled depth (None for non-gate-based tasks)
    qubit_hamiltonian_terms  Pauli terms in the qubit Hamiltonian
    """
    task:                    str
    molecule:                str
    cas:                     ActiveSpaceSpec
    metric:                  str   = "final_energy"
    lower_is_better:         bool  = True
    score:                   float
    chemical_accuracy:       float = 1.0e-3
    supported_molecules:     list[str] = []
    config:                  VQERunConfig
    hf_energy:               float
    iterations:              int
    nfev:                    int
    final_energy:            float
    target_energy:           float | None = None
    final_error:             float | None = None
    chem_acc_step:           int | None   = None
    circuit_depth:           int | None   = None
    wall_seconds:            float
    wall_budget_seconds:     float
    best_parameters:         list[float] = []
    occupied_indices:        list[int]   = []
    active_indices:          list[int]   = []
    qubit_hamiltonian_terms: int | None  = None

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def reference_energy(self) -> float | None:
        """FCI/CCSD(T) ground truth for this molecule, or None if not tabulated."""
        return reference_energy(self.molecule)

    @property
    def energy_error(self) -> float | None:
        """Absolute energy error vs reference (None if reference unknown)."""
        ref = self.reference_energy
        return None if ref is None else abs(self.final_energy - ref)

    @property
    def chemical_accuracy_achieved(self) -> bool | None:
        """True if energy_error < chemical_accuracy threshold."""
        err = self.energy_error
        return None if err is None else err < self.chemical_accuracy

    @property
    def correlation_energy_fraction(self) -> float | None:
        """Fraction of correlation energy captured: (E_HF−E_VQE)/(E_HF−E_ref)."""
        ref = self.reference_energy
        if ref is None:
            return None
        denom = self.hf_energy - ref
        return None if abs(denom) < 1.0e-15 else (self.hf_energy - self.final_energy) / denom

    # ------------------------------------------------------------------
    # qpubench interop
    # ------------------------------------------------------------------

    def to_quantum_result(self) -> QuantumResult:
        """Convert to a qpubench QuantumResult for use in BenchmarkRecord."""
        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=[
                ExpectationResult(
                    observable_index=0,
                    value=self.final_energy,
                    std_error=0.0,
                    num_shots=None,
                )
            ],
            status=JobStatus.SUCCEEDED,
            total_time_s=self.wall_seconds,
            metadata={
                "score":                 self.score,
                "metric":                self.metric,
                "nfev":                  self.nfev,
                "iterations":            self.iterations,
                "wall_budget_seconds":   self.wall_budget_seconds,
                "qubit_hamiltonian_terms": self.qubit_hamiltonian_terms,
            },
        )

    def to_vqa_config(self) -> dict[str, Any]:
        """Return keyword arguments for constructing a VQAConfig.

        Usage::
            from qpubench.schemas import VQAConfig
            vqa = VQAConfig(**gsopt_result.to_vqa_config())
        """
        return dict(
            problem_type="chemistry",
            molecule=self.molecule,
            basis=None,
            num_electrons=None,
            active_electrons=self.cas.active_electrons,
            active_orbitals=self.cas.active_orbitals,
            hf_energy=self.hf_energy,
            algorithm=self.config.ansatz,
            optimizer=self.config.optimizer,
            num_parameters=len(self.best_parameters),
            n_layers_circuit=self.config.layers,
            final_eigenvalue=self.final_energy,
            ground_truth=self.target_energy,
            nfev=self.nfev,
        )


# ---------------------------------------------------------------------------
# Benchmark metadata  (.gsopt.json)
# ---------------------------------------------------------------------------

class GSOptBenchmarkMeta(pydantic.BaseModel):
    """Contents of a .gsopt.json benchmark metadata file.

    lane                 benchmark category (see GSOptBenchmarkLane)
    display_name         name shown in the GSOpt TUI
    objective            plain-text goal description passed to the mutation agent
    default_iterations   iterations per evaluation (passed to source script)
    default_wall_seconds wall-time budget per evaluation in seconds
    source               editable source file path (relative to benchmark dir)
    evaluator            fixed scorer file that outputs JSON with a "score" field
    figs_script          optional visualisation script path
    baseline             optional Optuna baseline script path
    """
    lane:                  str
    display_name:          str
    objective:             str
    default_iterations:    int   = 100
    default_wall_seconds:  float = 20.0
    source:                str   = "simple_vqe.py"
    evaluator:             str   = "evaluate.py"
    figs_script:           str | None = None
    baseline:              str | None = None


__all__ = [
    "REFERENCE_ENERGIES",
    "ActiveSpaceSpec",
    "GSOptBenchmarkLane",
    "GSOptBenchmarkMeta",
    "GSOptBenchmarkResult",
    "VQEAnsatzType",
    "VQEOptimizerType",
    "VQERunConfig",
    "reference_energy",
]
