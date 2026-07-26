"""GSOpt benchmark framework data schemas.

GSOpt (github.com/bestquark/gsopt) is a fixed-budget ground-state optimisation
benchmark harness.  It drives agent-based mutation loops across five benchmark
categories and records structured JSON results from each run.

GSOpt is *method-agnostic*: VQE is one of its five lanes, alongside tensor
networks, DMRG, AFQMC and Gibbs sampling — several of which are not quantum
algorithms and not variational at all.  So each lane gets its own run config
(GSOpt*RunConfig below) rather than everything being bent into a VQE shape.
None of them is a cross-implementation contract: for that see
`execution.VQERunConfig` / `AdaptVQERunConfig` / `QAOARunConfig`, which are
package-agnostic hyperparameters keyed by AlgorithmFamily.

Schema coverage
---------------
GSOptBenchmarkLane  benchmark category enum (vqe, tn, dmrg, afqmc, gibbs)
VQEAnsatzType       hea_ry_ring | hea_ryrz_ring | uccsd
VQEOptimizerType    cobyla | powell | nelder_mead  (classical optimisers)
ActiveSpaceSpec     active electrons / orbitals + index arrays

Per-lane "config" sub-objects (each mirrors that lane's RunConfig dataclass):
GSOptRunConfig       base — `name`, the only field all lanes share
GSOptVQERunConfig    vqe lane   (examples/vqe/*, CUDA-Q)
GSOptTNRunConfig     tn + dmrg lanes (MPS sweeping)
GSOptAFQMCRunConfig  afqmc lane (PySCF + ipie)
GSOptGibbsRunConfig  gibbs lane (MCMC thermal sampling)
GSOptLaneRunConfig   union of the above, as used by GSOptBenchmarkResult

GSOptBenchmarkResult  full JSON output of simple_vqe.py / evaluate.py
GSOptBenchmarkMeta  .gsopt.json metadata file format

Reference energies
    REFERENCE_ENERGIES — FCI/CCSD(T) reference energies for the five GSOpt
                         VQE molecules: BH, LiH, BeH2, H2O, N2

Interop with qpubench
---------------------
GSOptBenchmarkResult.to_quantum_result()  → QuantumResult
GSOptBenchmarkResult.to_vqa_config()      → dict for VQAConfig(**...) (inputs)
GSOptBenchmarkResult.to_vqa_result()      → dict for VQAResult(**...) (computed outputs)
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
# Per-lane run configurations
# ---------------------------------------------------------------------------
#
# GSOpt is a ground-state *benchmark harness*, not a VQE framework: each lane
# drives a different ground-state method (see GSOptBenchmarkLane), and each
# lane's source script defines its own frozen `RunConfig` dataclass, emitted
# as the "config" sub-object of that lane's JSON.  The only field every lane
# shares is `name`, so the lane configs below are siblings under a thin base
# rather than variations on one VQE-shaped object.
#
# These are *records of one run's parameterisation*, lane-specific by
# construction — not the package-agnostic runtime contracts in `execution`
# (VQERunConfig / AdaptVQERunConfig / QAOARunConfig), which describe how to
# drive an algorithm across implementations.

class GSOptRunConfig(pydantic.BaseModel):
    """Base for every lane's "config" JSON sub-object.

    Carries only what all five lanes agree on.  Subclasses add the fields
    their lane's RunConfig dataclass actually defines; the agent-driven
    mutation loop is what perturbs those fields between evaluations.

    name  human-readable run identifier (e.g. "simple_dmrg", "uccsd_2_BH")
    """
    name: str


class GSOptVQERunConfig(GSOptRunConfig):
    """GSOpt VQE lane (examples/vqe/*, CUDA-Q circuits).

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


class GSOptTNRunConfig(GSOptRunConfig):
    """GSOpt tensor-network lanes — TN (examples/tn/simple_tn.py) and DMRG
    (examples/dmrg/*/simple_dmrg.py).

    Both lanes optimise an MPS by sweeping, so they share one config; the
    DMRG lane's RunConfig is a strict subset of the TN lane's, and the fields
    it does not define are left None.  Per-lane defaults differ (the DMRG
    benchmarks run tighter and longer — e.g. cutoff 1e-10 and max_sweeps 64
    against the TN lane's 1e-6 and 12), so the shared fields below are
    required rather than carrying a default that would be wrong for one lane.

    bond_schedule   MPS bond dimensions applied across successive sweeps
    cutoff          singular-value truncation cutoff
    solver_tol      local eigensolver tolerance
    max_sweeps      sweep cap
    init_bond_dim   bond dimension of the initial state
    init_seed       RNG seed for the initial state

    TN-lane-only (None on a DMRG config):
      method        update scheme, e.g. "dmrg2" (two-site) | "dmrg1"
      init_state    initial MPS, e.g. "random" | "product"
      tau           imaginary-time step for TEBD-style updates
      chi           working bond dimension for the imaginary-time stage
      local_eig_ncv Krylov subspace size for the local eigensolver
    """
    bond_schedule:  list[int]
    cutoff:         float
    solver_tol:     float
    max_sweeps:     int
    init_bond_dim:  int
    init_seed:      int
    method:         str | None   = None
    init_state:     str | None   = None
    tau:            float | None = None
    chi:            int | None   = None
    local_eig_ncv:  int | None   = None


class GSOptAFQMCRunConfig(GSOptRunConfig):
    """GSOpt AFQMC lane (examples/afqmc/molecular_benchmark.py, PySCF + ipie).

    Splits into an SCF trial-wavefunction stage and the AFQMC walker
    propagation itself; the mutation agent tunes both.

    SCF / trial stage:
      trial          trial wavefunction: "rhf" | "uhf"
      scf_conv_tol   SCF convergence tolerance
      scf_max_cycle  SCF iteration cap
      diis_space     DIIS subspace size
      level_shift    virtual-orbital level shift
      damping        SCF damping factor
      init_guess     "minao" | "atom" | "1e" | "huckel" | "mod_huckel"
      chol_cut       Cholesky decomposition threshold for the ERI tensor

    Walker propagation:
      num_walkers_per_rank  walkers per MPI rank
      num_steps_per_block   propagation steps per block
      num_blocks            number of blocks (statistics)
      timestep              imaginary-time step Δτ
      stabilize_freq        re-orthogonalisation frequency
      pop_control_freq      population-control frequency
    """
    trial:                str
    scf_conv_tol:         float
    scf_max_cycle:        int
    diis_space:           int
    level_shift:          float
    damping:              float
    init_guess:           str
    chol_cut:             float
    num_walkers_per_rank: int
    num_steps_per_block:  int
    num_blocks:           int
    timestep:             float
    stabilize_freq:       int
    pop_control_freq:     int


class GSOptGibbsRunConfig(GSOptRunConfig):
    """GSOpt Gibbs lane (examples/gibbs/simple_gibbs_mcmc.py).

    Samples a thermal state by MCMC and scores against the exact
    distribution, so it is the one lane whose metric is a distribution
    distance rather than an energy.  Unlike the other lanes the script emits
    these flat at the top level of its JSON rather than under a "config"
    key — pass them here explicitly when normalising a Gibbs result.

    Physical model (script defaults in parentheses):
      length     chain length L (8)
      beta       inverse temperature β (0.8)
      coupling   nearest-neighbour coupling J (1.0)
      field      transverse/longitudinal field h (0.3)

    MCMC settings, what the mutation agent mainly optimises (defaults):
      num_chains       parallel chains (64)
      burn_in_sweeps   discarded warm-up sweeps (50)
      sample_sweeps    sweeps retained for statistics (200)
      thinning         keep every n-th sweep, autocorrelation control (2)
      seed             RNG seed (42)

    All fields are required: this records what a given run actually used, and
    defaulting them would additionally make a bare {"name": ...} object
    validate as a Gibbs config and shadow GSOptRunConfig in
    GSOptLaneRunConfig's union resolution.
    """
    length:         int
    beta:           float
    coupling:       float
    field:          float
    num_chains:     int
    burn_in_sweeps: int
    sample_sweeps:  int
    thinning:       int
    seed:           int


GSOptLaneRunConfig = (
    GSOptVQERunConfig
    | GSOptTNRunConfig
    | GSOptAFQMCRunConfig
    | GSOptGibbsRunConfig
    | GSOptRunConfig
)
"""Any lane's run config. Ordered most-specific-first so pydantic's smart
union resolves a parsed `config` object to the lane model that actually
matches, falling back to the bare base when it matches none."""


# ---------------------------------------------------------------------------
# Benchmark result
# ---------------------------------------------------------------------------

class GSOptBenchmarkResult(pydantic.BaseModel):
    """Full JSON result produced by a GSOpt benchmark run (simple_vqe.py output).

    This is the canonical structure written to stdout and scored by evaluate.py.
    Reference fields (target_energy, final_error, chem_acc_step) are retained
    for full fidelity; the evaluator strips them before publishing the score.

    Scope: this models the **molecular** lanes' result shape — `molecule`,
    `cas` and `hf_energy` are required, which fits VQE and AFQMC.  The
    spin-model lanes (TN, DMRG, Gibbs) report a different shape entirely
    (`model`, `nsites`/`chain_length`, `energy_per_site`, `entropy_midchain`,
    or a distribution distance for Gibbs) and are not modelled yet.  `config`
    already accepts any lane's run config, so the config layer is lane-complete
    ahead of the result layer.

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
    config:                  GSOptLaneRunConfig
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
        """Return keyword arguments for constructing a VQAConfig (inputs only).

        VQE lane only — `algorithm` / `optimizer` / `n_layers_circuit` are read
        off the run config, which only the VQE lane defines.  Raises TypeError
        on any other lane rather than silently emitting a half-populated
        VQAConfig.

        Usage::
            from qpubench.schemas import VQAConfig, VQAResult
            vqa        = VQAConfig(**gsopt_result.to_vqa_config())
            vqa_result = VQAResult(**gsopt_result.to_vqa_result())
        """
        if not isinstance(self.config, GSOptVQERunConfig):
            raise TypeError(
                "to_vqa_config() needs a GSOptVQERunConfig (the VQE lane); "
                f"this result carries {type(self.config).__name__}. Non-VQE "
                "lanes are not variational runs, so VQAConfig does not describe "
                "them — build a BenchmarkRecord from to_quantum_result() instead."
            )
        return dict(
            problem_type="chemistry",
            molecule=self.molecule,
            basis=None,
            num_electrons=None,
            active_electrons=self.cas.active_electrons,
            active_orbitals=self.cas.active_orbitals,
            algorithm=self.config.ansatz,
            optimizer=self.config.optimizer,
            n_layers_circuit=self.config.layers,
        )

    def to_vqa_result(self) -> dict[str, Any]:
        """Return keyword arguments for constructing a VQAResult (computed outputs)."""
        return dict(
            hf_energy=self.hf_energy,
            num_parameters=len(self.best_parameters),
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
    "GSOptAFQMCRunConfig",
    "GSOptBenchmarkLane",
    "GSOptBenchmarkMeta",
    "GSOptBenchmarkResult",
    "GSOptGibbsRunConfig",
    "GSOptLaneRunConfig",
    "GSOptRunConfig",
    "GSOptTNRunConfig",
    "GSOptVQERunConfig",
    "VQEAnsatzType",
    "VQEOptimizerType",
    "reference_energy",
]
