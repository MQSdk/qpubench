"""ExcitationSolve optimizer data schemas.

ExcitationSolve (github.com/dlr-wf/ExcitationSolve, ``pip install
excitationsolve``, Communications Physics 2025, doi:10.1038/s42005-025-02375-9)
is a gradient-free optimizer for VQE ansätze built from excitation operators
(G³ = G).  It fits a 2nd-order Fourier series to exactly 5 energy probe points
per parameter, then locates the global minimum analytically via the companion
matrix method.

Upstream updates tracked here (checked against the ``main`` branch, 2026-07)
---------------------------------------------------------------------------
* Follow-up paper Haas et al. 2026 (arXiv:2602.10776) adds *operator-selection
  and warm-start strategies* for the adaptive variant — reflected by the
  ``operator_selection`` field on ``ExcitationAdaptResult`` and the
  ``warm_start_double_excitations`` config flag below.
* ``optimal_theta`` / ``optimal_theta_pyscf`` return the analytic optimal
  parameter (and its energy lowering) for a single double excitation applied
  to a Hartree-Fock reference — a cheap warm start captured by
  ``AdaptVQEStep.optimal_theta`` when used.
* ``parameter_occ`` is a new optimizer argument (per-parameter occurrence /
  ordering hint), carried on ``ExcitationSolveConfig`` below.

Schema coverage
---------------
ExcitationSolveConfig       Hyper-parameters for ExcitationSolveQiskit /
                            excitationsolve_pennylane / ExcitationSolveScipy.

ParameterSample             One (parameter_variation, energy_sample) probe point.

ExcitationSolveSweep        Full sweep data for a single parameter:
                            5+ probe points → Fourier coefficients → optimal.

ExcitationSolveIteration    One pass through all parameters (one "sweep round").

ExcitationSolveResult       Complete optimizer output; bridges to QuantumResult
                            and VQAConfig via helper methods.

AdaptVQEStep                One ADAPT-VQE macro-step (select + append one gate).

ExcitationAdaptResult       Complete ExcitationAdaptive ADAPT-VQE run.

Algorithm name conventions
--------------------------
AlgorithmSpec.name:  "ExcitationSolve" | "ExcitationSolve2D" | "ExcitationAdapt"
AlgorithmSpec.optimizer: "excitation_solve"
AlgorithmSpec.use_analytic_grad: False   (gradient-free by design)
AlgorithmSpec.opt_maxiter: maxiter
AlgorithmSpec.opt_thresh:  tol
AlgorithmSpec.num_samples: num_samples (new field, ≥5 for 1D, 25 for 2D)
"""
from __future__ import annotations

import enum

import pydantic

from .result import ExpectationResult, QuantumResult
from .primitives import ComputingModel, JobStatus


# ---------------------------------------------------------------------------
# Optimizer configuration
# ---------------------------------------------------------------------------

class ExcitationSolveMode(str, enum.Enum):
    """Variant of the ExcitationSolve algorithm."""
    ONE_D  = "1d"    # 1D sweep: one parameter at a time (default)
    TWO_D  = "2d"    # 2D sweep: two parameters jointly (25 probe points)
    ADAPT  = "adapt" # ADAPT-VQE integration (ExcitationAdaptiveOptimizer)


class ExcitationSolveConfig(pydantic.BaseModel):
    """Hyper-parameters for any ExcitationSolve backend.

    Matches ExcitationSolveQiskit constructor arguments and the
    excitationsolve_pennylane / ExcitationSolveScipy equivalents.

    num_samples   probe points per parameter sweep; must be ≥5 (1D) or 25 (2D).
                  When >5, a least-squares fit replaces the exact 5-point solve.
    tol           energy convergence threshold between consecutive iterations.
    hf_energy     optional Hartree-Fock reference for tracking chemical accuracy.
    save_parameters  store the full parameter vector after every iteration.
    mode          1D (default), 2D (two-parameter joint sweep), or ADAPT.
    parameter_occ    optional per-parameter occurrence / ordering hint passed
                     through to the upstream optimizer (``parameter_occ``);
                     None leaves the default sweep order.
    warm_start_double_excitations  initialise double-excitation parameters from
                     the analytic ``optimal_theta`` / ``optimal_theta_pyscf``
                     value relative to the Hartree-Fock reference before the
                     first sweep (Haas et al. 2026 warm start).
    """
    maxiter:         int              = 100
    tol:             float            = 1.0e-12
    num_samples:     int              = 5       # ≥5 for 1D; exactly 25 for 2D
    hf_energy:       float | None     = None
    save_parameters: bool             = False
    mode:            ExcitationSolveMode = ExcitationSolveMode.ONE_D
    parameter_occ:   list[int] | None = None    # upstream parameter_occ arg
    warm_start_double_excitations: bool = False  # optimal_theta HF warm start

    @pydantic.field_validator("num_samples")
    @classmethod
    def _min_samples(cls, v: int) -> int:
        if v < 5:
            raise ValueError(f"num_samples must be ≥5, got {v}")
        return v


# ---------------------------------------------------------------------------
# Per-sweep data
# ---------------------------------------------------------------------------

class ParameterSample(pydantic.BaseModel):
    """One energy probe point for a single excitation parameter.

    For 1D sweeps:  parameter_variation is a scalar (float).
    For 2D sweeps:  parameter_variation is a 2-element list [θ₁, θ₂].
    The parameter_variation must lie within the period of the excitation
    operator:  |max − min| ≤ 4π (one period, i.e. two sub-periods of π).
    """
    parameter_variation: float | list[float]
    energy_sample:       float


class ExcitationSolveSweep(pydantic.BaseModel):
    """Complete Fourier-series reconstruction for a single parameter (1D) or
    parameter pair (2D).

    samples                 probe points used for the fit (len ≥ 5 for 1D, 25 for 2D)
    fourier_coefficients    fitted Fourier coefficients:
                              1D → [a₀, a₁, b₁, a₂, b₂]  (5 values)
                              2D → 25-element tensor product basis coefficients
    optimized_parameter     global minimum location returned by the solver
                              (scalar for 1D; [θ₁*, θ₂*] for 2D)
    optimized_energy        energy at the global minimum
    parameter_index         index into the parameter vector (1D only)
    parameter_indices       pair of parameter indices (2D only)
    """
    samples:               list[ParameterSample]
    fourier_coefficients:  list[float] | None = None
    optimized_parameter:   float | list[float]
    optimized_energy:      float
    parameter_index:       int | None         = None    # 1D
    parameter_indices:     list[int] | None   = None    # 2D; len=2

    @pydantic.model_validator(mode="after")
    def _check_index(self) -> ExcitationSolveSweep:
        if self.parameter_index is None and self.parameter_indices is None:
            raise ValueError(
                "Exactly one of parameter_index (1D) or parameter_indices (2D) "
                "must be set."
            )
        return self


# ---------------------------------------------------------------------------
# Per-iteration and full result
# ---------------------------------------------------------------------------

class ExcitationSolveIteration(pydantic.BaseModel):
    """One complete pass through all parameters (one "sweep round").

    energy        best energy after this iteration
    nfev          cumulative function evaluations up to this point
    delta_energy  |energy − energy_prev|; None for iteration 0
    parameters    full parameter vector (only if ExcitationSolveConfig.save_parameters)
    sweeps        per-parameter sweep data (optional; may be omitted for brevity)
    """
    iteration:    int
    energy:       float
    nfev:         int
    delta_energy: float | None              = None
    parameters:   list[float] | None        = None
    sweeps:       list[ExcitationSolveSweep] | None = None


class ExcitationSolveResult(pydantic.BaseModel):
    """Complete ExcitationSolve optimizer output.

    Captures the data returned by:
      • ExcitationSolveQiskit.minimize() → OptimizerResult
      • excitationsolve_pennylane() loops
      • ExcitationSolveScipy.minimize()

    optimized_parameters  scaled by 0.5 (Qiskit convention) for the optimized
                          point; stored as-is from the optimizer.
    converged             True if |Δenergy| < tol before maxiter was reached.
    """
    optimized_parameters:  list[float]
    final_energy:          float
    n_function_evaluations: int
    n_iterations:          int
    converged:             bool              = False
    hf_energy:             float | None      = None
    history:               list[ExcitationSolveIteration] = []
    config:                ExcitationSolveConfig | None    = None

    @property
    def energy_error_vs_hf(self) -> float | None:
        if self.hf_energy is None:
            return None
        return abs(self.final_energy - self.hf_energy)

    def to_expectation_result(self) -> ExpectationResult:
        """Wrap final_energy as an ExpectationResult (observable_index=0)."""
        return ExpectationResult(
            observable_index=0,
            value=self.final_energy,
            std_error=0.0,
            num_shots=None,
        )

    def to_quantum_result(self) -> QuantumResult:
        """Convert to a qpubench QuantumResult for BenchmarkRecord."""
        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=[self.to_expectation_result()],
            status=JobStatus.SUCCEEDED,
            metadata={
                "n_iterations": self.n_iterations,
                "converged": self.converged,
                "n_function_evaluations": self.n_function_evaluations,
            },
        )

    def convergence_values(self) -> list[float]:
        """Energy per iteration — compatible with VQAConfig.convergence_values."""
        return [it.energy for it in self.history]

    def nfev_history(self) -> list[int]:
        """Cumulative function evaluations per iteration."""
        return [it.nfev for it in self.history]


# ---------------------------------------------------------------------------
# ADAPT-VQE extension  (ExcitationAdaptiveOptimizer)
# ---------------------------------------------------------------------------

class AdaptVQEStep(pydantic.BaseModel):
    """One macro-step of the ExcitationAdaptiveOptimizer.

    Corresponds to one call of step_and_cost():
      (optimized_circuit, prior_cost, max_gradient) = optimizer.step_and_cost(...)

    prior_cost         energy before this step's operator was appended
    max_gradient       maximum energy improvement across the operator pool
                       (used for convergence; analogous to gradient norm in
                       standard ADAPT-VQE)
    selected_operator  name / label of the gate selected from the pool; None
                       if the pool was exhausted or no improvement found
    n_pool_evaluated   number of candidate operators evaluated this step
    n_function_evaluations  circuit calls in this step (≈ 5 × n_pool_evaluated)
    drain_pool         whether already-used operators were excluded from pool
    params_zero        whether parameters were initialised to zero this step
    optimal_theta      analytic optimal parameter for the selected double
                       excitation from ``optimal_theta`` / ``optimal_theta_pyscf``
                       (warm start), if it was used this step; else None
    """
    step_index:             int
    prior_cost:             float
    max_gradient:           float
    selected_operator:      str | None  = None
    n_pool_evaluated:       int         = 0
    n_function_evaluations: int         = 0
    drain_pool:             bool        = False
    params_zero:            bool        = False
    optimal_theta:          float | None = None    # analytic HF warm-start value


class ExcitationAdaptResult(pydantic.BaseModel):
    """Complete ADAPT-VQE run using ExcitationAdaptiveOptimizer.

    steps                   per-macro-step records
    final_energy            energy of the converged circuit
    final_parameters        parameter vector of the converged circuit
    n_operators_added       number of operators appended to the ansatz
    converged               True if max_gradient < convergence threshold before
                            the operator pool was exhausted
    config                  ExcitationSolve config used within each step
    operator_selection      label of the operator-selection strategy used
                            (Haas et al. 2026, arXiv:2602.10776), e.g.
                            "max_gradient" (default) or "warm_start"; free-text
                            so new upstream strategies need no schema change
    """
    steps:              list[AdaptVQEStep]
    final_energy:       float
    final_parameters:   list[float]
    n_operators_added:  int
    converged:          bool                       = False
    config:             ExcitationSolveConfig | None = None
    operator_selection: str | None                 = None

    def grad_norm_history(self) -> list[float]:
        """Max gradient per step — mirrors AdaptIteration.grad_norm."""
        return [s.max_gradient for s in self.steps]

    def energy_history(self) -> list[float]:
        """Prior cost per step (energy before each operator was added)."""
        return [s.prior_cost for s in self.steps]

    def to_quantum_result(self) -> QuantumResult:
        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=[
                ExpectationResult(
                    observable_index=0,
                    value=self.final_energy,
                    std_error=0.0,
                )
            ],
            status=JobStatus.SUCCEEDED,
            metadata={
                "n_operators_added": self.n_operators_added,
                "converged": self.converged,
                "n_steps": len(self.steps),
            },
        )


__all__ = [
    "AdaptVQEStep",
    "ExcitationAdaptResult",
    "ExcitationSolveConfig",
    "ExcitationSolveIteration",
    "ExcitationSolveMode",
    "ExcitationSolveResult",
    "ExcitationSolveSweep",
    "ParameterSample",
]
