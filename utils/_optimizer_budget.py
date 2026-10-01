"""How many iterations to give tn-vqe's optimizers for a given evaluation budget.

Imported, not run. A campaign chooses how many evaluations a run may
spend; this module turns that into the `n_iterations` each optimizer
takes, so that every optimizer on a row spends the same budget its own
way. The cost model is tn-vqe's (COBYLA, SPSA, ExcitationSolve), not a
campaign's; the multiplier that sizes the budget is the campaign's.

Two quantities differ here because Cebule caches: a QUANTUM evaluation
re-measures the circuit, while a cost-function evaluation that changes
only theta is recombined classically from the cached measurements. The
budget is spent in quantum evaluations, the resource that is billed.
"""
from __future__ import annotations

import math

# A floor on every budget, so small rows still get a usable run.
MIN_EVALUATIONS = 30

# COBYLA builds an n+1 point simplex before its first descent step, and
# tn-vqe rejects n_iterations below n+2 for it outright.
SIMPLEX_OVERHEAD = 2

# Cost per iteration, in cost-function evaluations.
#   COBYLA           1: scipy's COBYLA takes maxiter as an evaluation cap.
#   SPSA             2: a plus- and a minus-perturbation per step.
#   ExcitationSolve  a sweep over every parameter. Each phi parameter is fit
#                    to frequencies {1, 2} from five samples, one reused from
#                    the previous fit; theta is taken at five, unverified.
EVALS_PER_ITERATION_FIXED = {"COBYLA": 1, "SPSA": 2}
EXCITATIONSOLVE_EVALS_PER_PHI = 4
EXCITATIONSOLVE_EVALS_PER_THETA = 5

# Evaluations spent outside the iterations, read off tn-vqe's spsa.py and
# excitation_solve.py and matched against collected cost_history lengths.
#   SPSA             12 gain calibration + 1 start + 2 x 3 closing repeats
#   ExcitationSolve  4n flatness check + n first-sweep validation
#                    + 1 start + 1 closing evaluation
SPSA_FIXED_EVALS = 19
EXCITATIONSOLVE_FIXED_EVALS_PER_PHI = 5
EXCITATIONSOLVE_FIXED_EVALS = 2


def evaluation_budget(
    num_params: int, evals_per_param: float, *, cap: int | None = None,
) -> int:
    """Evaluations a run may spend: `max(MIN_EVALUATIONS, ceil(evals_per_param * n))`.

    Proportional to the free-parameter count rather than n plus a
    constant, because the evaluations needed to reach a given fraction of
    the achievable descent grow in proportion to n; an additive rule gives
    wider rows a shrinking fraction. `cap` bounds it absolutely.
    """
    budget = max(MIN_EVALUATIONS, math.ceil(evals_per_param * num_params))
    if cap is not None:
        budget = min(budget, cap)
    # Kept after the cap, since only a cap can push the budget under the
    # simplex, and tn-vqe would reject such a run rather than shorten it.
    if budget < num_params + SIMPLEX_OVERHEAD:
        raise ValueError(
            f"{budget} evaluations for {num_params} free parameters is below "
            f"COBYLA's simplex of {num_params + SIMPLEX_OVERHEAD}"
        )
    return budget


def evals_per_iteration(
    optimizer: str, num_phi: int, num_theta: int,
) -> tuple[int, int]:
    """(quantum evaluations, cost-function evaluations) per iteration.

    `num_phi` is 0 where phi is frozen (`network` mode), so such a run
    reports no quantum cost.
    """
    if optimizer == "ExcitationSolve":
        quantum = EXCITATIONSOLVE_EVALS_PER_PHI * num_phi
        cost = quantum + EXCITATIONSOLVE_EVALS_PER_THETA * num_theta
        return quantum, max(1, cost)
    per = EVALS_PER_ITERATION_FIXED[optimizer]
    return (per if num_phi else 0), per


def fixed_evals(optimizer: str, num_phi: int) -> int:
    """Evaluations `optimizer` spends outside its iterations."""
    if optimizer == "SPSA":
        return SPSA_FIXED_EVALS
    if optimizer == "ExcitationSolve":
        return EXCITATIONSOLVE_FIXED_EVALS_PER_PHI * num_phi + EXCITATIONSOLVE_FIXED_EVALS
    return 0


def iteration_budget(
    budget: int, optimizer: str, num_phi: int, num_theta: int,
) -> int:
    """`n_iterations` for an optimizer, given a quantum-evaluation budget.

    The optimizer's fixed evaluations come off the budget first, so every
    optimizer's whole run fits the same budget. A run with no quantum cost
    (`network` mode) is budgeted on cost-function evaluations instead.

    Floored at 1: a single ExcitationSolve sweep is still a run worth
    having where the budget does not quite cover it.
    """
    quantum, cost = evals_per_iteration(optimizer, num_phi, num_theta)
    remaining = budget - fixed_evals(optimizer, num_phi)
    return max(1, remaining // (quantum or cost))
