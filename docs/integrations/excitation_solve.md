# ExcitationSolve integration

[ExcitationSolve](https://github.com/dlr-wf/ExcitationSolve) (*Communications Physics* 2025) is a gradient-free VQE optimizer for excitation-operator ansätze (G³ = G). It fits a 2nd-order Fourier series to 5 energy probe points per parameter and locates the global minimum analytically via the companion matrix method.

Schemas: `src/qpubench/schemas/excitation_solve.py`

---

## Core algorithm summary

**1D mode** (default):

1. For each parameter `θ_i`, evaluate energy at 5 shifts: `{θ_i + k·π/2 : k=0,1,2,3,4}`.
2. Fit `E(θ) = a₀ + a₁cos(θ/2) + b₁sin(θ/2) + a₂cos(θ) + b₂sin(θ)` (5 coefficients).
3. Find global minimum analytically via companion matrix.
4. Update `θ_i`. Sweep through all parameters until convergence.

**2D mode**: jointly optimise two parameters using 25 probe points and 25 Fourier basis terms.

**ADAPT mode** (`ExcitationAdaptiveOptimizer`): selects the best operator from a pool each step by testing 5 energy probes for each candidate.

---

## Configuration

```python
from qpubench.schemas import ExcitationSolveConfig, ExcitationSolveMode, AlgorithmSpec

# Optimizer config (maps to ExcitationSolveQiskit constructor)
cfg = ExcitationSolveConfig(
    maxiter=200,
    tol=1e-10,
    num_samples=5,        # ≥5 for 1D; exactly 25 for 2D; 5 per candidate for ADAPT
    hf_energy=-1.1175,    # optional HF reference for chemical accuracy tracking
    save_parameters=True,
    mode=ExcitationSolveMode.ONE_D,
)

# In AlgorithmSpec for use with BenchmarkRunner
spec = AlgorithmSpec(
    name="ExcitationSolve",
    optimizer="excitation_solve",
    use_analytic_grad=False,      # gradient-free by design
    opt_maxiter=200,              # = ExcitationSolveConfig.maxiter
    opt_thresh=1e-10,             # = ExcitationSolveConfig.tol
    num_samples=5,                # = ExcitationSolveConfig.num_samples
)
```

---

## Recording a 1D optimisation run

```python
from qpubench.schemas import (
    ExcitationSolveSweep, ExcitationSolveIteration,
    ExcitationSolveResult, ParameterSample, VQAConfig,
)
import numpy as np

# --- Record one parameter sweep (for parameter index 0) ---
shifts = np.array([0, np.pi/2, -np.pi/2, np.pi, -np.pi])
energies = np.array([-1.10, -1.05, -1.08, -1.12, -1.09])   # from circuit evaluations

sweep = ExcitationSolveSweep(
    parameter_index=0,
    samples=[ParameterSample(parameter_variation=s, energy_sample=e)
             for s, e in zip(shifts.tolist(), energies.tolist())],
    optimized_parameter=2.31,
    optimized_energy=-1.136,
    fourier_coefficients=[…],     # a₀, a₁, b₁, a₂, b₂ from np.linalg.solve
)

# --- Record one iteration (one sweep over all parameters) ---
iteration = ExcitationSolveIteration(
    iteration=3,
    energy=-1.1355,
    nfev=75,                      # cumulative function evaluations
    delta_energy=1.2e-4,
    parameters=[2.31, -1.05, 0.78],    # full parameter vector (if save_parameters=True)
    sweeps=[sweep],
)

# --- Full optimizer result (returned by minimize()) ---
result = ExcitationSolveResult(
    optimized_parameters=[2.31, -1.05, 0.78],
    final_energy=-1.1361,
    n_function_evaluations=375,
    n_iterations=25,
    converged=True,
    hf_energy=-1.1175,
    history=[iteration, …],
    config=cfg,
)

# Convergence trace
print(result.convergence_values())    # [energy per iteration]
print(result.nfev_history())          # [cumulative nfev per iteration]
print(result.energy_error_vs_hf)      # |final - hf|

# Bridge to qpubench
quantum_result = result.to_quantum_result()
vqa = VQAConfig(
    problem_type="chemistry",
    molecule="H2",
    algorithm="ExcitationSolve",
    optimizer="excitation_solve",
    num_parameters=3,
    nfev=result.n_function_evaluations,
    hf_energy=result.hf_energy,
    convergence_values=result.convergence_values(),
    final_eigenvalue=result.final_energy,
    ground_truth=-1.1373,
)
```

---

## Recording ADAPT-VQE runs

```python
from qpubench.schemas import AdaptVQEStep, ExcitationAdaptResult

# Each call to optimizer.step_and_cost() produces one AdaptVQEStep
step = AdaptVQEStep(
    step_index=2,
    prior_cost=-1.10,
    max_gradient=0.042,           # maximum energy improvement across pool
    selected_operator="SingleExcitation(0->2)",
    n_pool_evaluated=12,          # operators tested this step
    n_function_evaluations=60,    # = n_pool_evaluated * 5
    drain_pool=True,
)

adapt_result = ExcitationAdaptResult(
    steps=[step, …],
    final_energy=-1.136,
    final_parameters=[0.31, -0.18, 0.52],
    n_operators_added=3,
    converged=True,
    config=cfg,
)

print(adapt_result.grad_norm_history())   # max_gradient per step
print(adapt_result.energy_history())      # prior_cost per step

quantum_result = adapt_result.to_quantum_result()
```

---

## 2D mode

Use `ExcitationSolveMode.TWO_D` and set `num_samples=25`. Record the sweep with `parameter_indices`:

```python
cfg_2d = ExcitationSolveConfig(mode=ExcitationSolveMode.TWO_D, num_samples=25)

sweep_2d = ExcitationSolveSweep(
    parameter_indices=[0, 1],     # two parameters jointly
    samples=[
        ParameterSample(parameter_variation=[s1, s2], energy_sample=e)
        for (s1, s2), e in zip(shifts_2d, energies_2d)
    ],
    optimized_parameter=[1.57, -0.78],   # 2-element list
    optimized_energy=-1.137,
    fourier_coefficients=[…],    # 25 tensor-product basis coefficients
)
```

---

## Fewer than 5 samples (noisy circuit)

When `num_samples > 5`, ExcitationSolve performs a least-squares fit instead of an exact 5-point reconstruction. Record this the same way — just pass more `ParameterSample` entries:

```python
cfg_noisy = ExcitationSolveConfig(num_samples=9)   # 9 probe points per parameter
```
