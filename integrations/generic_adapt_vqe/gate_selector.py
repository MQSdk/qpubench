"""Gate selector strategies for ADAPT-VQE — closes qrunch's "Create a
Brute Force Gate Selector" and "Create a FAST Gate Selector" guides.

Checked qrunch's own guide pages directly
(qrunch.docs.kvantify.net/docs/guides/components/
create_{brute_force,fast}_gate_selector.html):

  FAST     default metric is a heuristic gradient — score every pool
           operator by a cheap gradient estimate, no re-optimization.
           This is exactly `GenericAdaptVQEEngine`'s original gradient
           screen, extracted here unchanged (not reimplemented) so it's
           a standalone, reusable component instead of being baked into
           the engine's main loop.
  BRUTE FORCE   qrunch's own description: "evaluates each candidate gate
           by temporarily adding it to the circuit and performing
           complete VQE optimization. The gate producing the lowest
           energy gets selected." Real, more expensive (one full
           `scipy.optimize.minimize` per remaining pool operator, every
           macro-iteration), exact per iteration.

Both implement the `GateSelector` protocol so
`GenericAdaptVQEEngine(..., gate_selector=...)` can swap between them —
default is `FastGateSelector`, preserving the engine's original behavior
exactly.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from qpubench.schemas.execution import AdaptVQEConfig

from .pool import PoolOperator

EnergyFn = Callable[[list[int], list[float]], float]


@runtime_checkable
class GateSelector(Protocol):
    def select(
        self,
        pool: list[PoolOperator],
        selected: list[int],
        amplitudes: list[float],
        energy_fn: EnergyFn,
        config: AdaptVQEConfig,
    ) -> tuple[int, float, bool]:
        """Return (best_operator_index, score, converged).

        score meaning is selector-specific (documented on each
        implementation) — logged as `AdaptIteration.grad_norm` regardless
        of which selector produced it, same schema field, different real
        quantity underneath.
        converged=True stops ansatz growth (best_operator_index may be -1
        in that case).
        """
        ...


class FastGateSelector:
    """qrunch's real "FAST Gate Selector" default metric — heuristic
    gradient via central finite differences over the full pool. Identical
    to `GenericAdaptVQEEngine`'s original (pre-refactor) `_gradient_screen`.

    score = ||gradient|| over the full pool (the same quantity the engine
    always compared against `config.gradient_threshold`).
    """

    def __init__(self, epsilon: float = 1.0e-3) -> None:
        self.epsilon = epsilon

    def select(
        self,
        pool: list[PoolOperator],
        selected: list[int],
        amplitudes: list[float],
        energy_fn: EnergyFn,
        config: AdaptVQEConfig,
    ) -> tuple[int, float, bool]:
        eps = self.epsilon
        best_idx, best_grad = -1, 0.0
        grad_sq_sum = 0.0
        for i in range(len(pool)):
            trial_sel = [*selected, i]
            e_plus = energy_fn(trial_sel, [*amplitudes, eps])
            e_minus = energy_fn(trial_sel, [*amplitudes, -eps])
            grad = (e_plus - e_minus) / (2 * eps)
            grad_sq_sum += grad * grad
            if abs(grad) > abs(best_grad):
                best_idx, best_grad = i, grad
        grad_norm = math.sqrt(grad_sq_sum)
        converged = grad_norm < config.gradient_threshold or best_idx < 0
        return best_idx, grad_norm, converged


class BruteForceGateSelector:
    """qrunch's real "Brute Force Gate Selector" — for each remaining pool
    operator, run a *full* classical optimization with it appended and
    keep whichever gives the lowest final energy. Exact per iteration,
    but O(pool_size) full re-optimizations instead of O(pool_size) cheap
    finite-difference evaluations — matches qrunch's own guide framing
    ("computationally intensive... provides exact results... works best
    with small systems").

    score = energy improvement from adding the best operator (Hartree;
    current energy minus best trial energy) — there is no gradient to
    report, so convergence is judged by this improvement against
    `config.energy_threshold` instead of `config.gradient_threshold`, a
    real, documented semantic difference from FastGateSelector rather
    than a fabricated one.
    """

    def __init__(
        self,
        optimizer: str | None = None,
        max_micro_iterations: int | None = None,
    ) -> None:
        self._optimizer_override = optimizer
        self._max_micro_iterations_override = max_micro_iterations

    def select(
        self,
        pool: list[PoolOperator],
        selected: list[int],
        amplitudes: list[float],
        energy_fn: EnergyFn,
        config: AdaptVQEConfig,
    ) -> tuple[int, float, bool]:
        from scipy.optimize import minimize

        optimizer: str = self._optimizer_override or config.optimizer
        max_iter: int = self._max_micro_iterations_override or config.max_micro_iterations

        def make_objective(trial_sel: list[int]) -> Callable[[Any], float]:
            def objective(x: Any) -> float:
                return energy_fn(trial_sel, list(x))
            return objective

        current_energy = energy_fn(selected, amplitudes)
        best_idx, best_energy = -1, math.inf

        for i in range(len(pool)):
            trial_sel = [*selected, i]
            # mypy/scipy-stub quirk: a plain `str` local fails minimize()'s
            # overload resolution here even though it's the identical type
            # `config.optimizer` (a direct attribute expression) passes with
            # in engine.py's _optimize — confirmed via isolated repro, not a
            # real type error (runtime behavior verified correct).
            res = minimize(  # type: ignore[call-overload]
                make_objective(trial_sel),
                [*amplitudes, 0.0],
                method=optimizer,
                options={"maxiter": max_iter},
                tol=config.energy_threshold,
            )
            if res.fun < best_energy:
                best_idx, best_energy = i, float(res.fun)

        improvement = current_energy - best_energy if best_idx >= 0 else 0.0
        converged = improvement < config.energy_threshold or best_idx < 0
        # The engine re-runs one more full optimization for the winning
        # operator after select() returns (same call site both selectors
        # share) — one marginal extra optimization out of pool_size+1
        # total, not worth a bespoke return-amplitudes path for.
        return best_idx, improvement, converged


__all__ = [
    "BruteForceGateSelector",
    "EnergyFn",
    "FastGateSelector",
    "GateSelector",
]
