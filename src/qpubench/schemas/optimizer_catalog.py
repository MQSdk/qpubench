"""Minimizer / stopping-criterion catalogue.

Closes qrunch's "Choose a Minimizer" / "Choose a Stopping Criterion" guides'
missing piece: ``AdaptVQEConfig.optimizer`` (``execution.py``) is a
free-text field each adapter maps onto its own supported set (e.g.
``integrations/generic_adapt_vqe`` maps it directly onto a
``scipy.optimize.minimize`` method name) — there was no catalogue/registry
object to "choose" from the way qrunch documents it. ``MINIMIZER_CATALOG``
and ``STOPPING_CRITERION_CATALOG`` are that catalogue: a lookup table over
the same free-text values, not a new execution mechanism.

Schema version: 2.4.0
"""
from __future__ import annotations

import pydantic


class MinimizerCatalogEntry(pydantic.BaseModel):
    """One classical optimizer choice, as understood by
    ``scipy.optimize.minimize`` (the real solver
    ``integrations/generic_adapt_vqe/engine.py`` calls with
    ``AdaptVQEConfig.optimizer`` as the method name).

    name                catalogue key, matches AdaptVQEConfig.optimizer.
    scipy_method        the exact string passed to
                        ``scipy.optimize.minimize(method=...)``.
    supports_gradient   whether this method can use an analytic/finite-
                        difference gradient (``AdaptVQEConfig.
                        use_analytic_gradient``) rather than being purely
                        derivative-free.
    stochastic          whether repeated runs from the same starting point
                        can return different results (relevant for noisy
                        hardware-evaluated energies).
    """
    name: str
    scipy_method: str
    supports_gradient: bool
    stochastic: bool = False
    description: str = ""


MINIMIZER_CATALOG: dict[str, MinimizerCatalogEntry] = {
    e.name: e
    for e in [
        MinimizerCatalogEntry(
            name="BFGS", scipy_method="BFGS", supports_gradient=True,
            description="Quasi-Newton; fast convergence near the minimum, needs a usable gradient.",
        ),
        MinimizerCatalogEntry(
            name="L-BFGS-B", scipy_method="L-BFGS-B", supports_gradient=True,
            description="Limited-memory BFGS with bound constraints; scales better than BFGS for many parameters.",
        ),
        MinimizerCatalogEntry(
            name="Nelder-Mead", scipy_method="Nelder-Mead", supports_gradient=False,
            description="Derivative-free simplex method; robust to noisy (shot-based) energy evaluations.",
        ),
        MinimizerCatalogEntry(
            name="Powell", scipy_method="Powell", supports_gradient=False,
            description="Derivative-free direction-set method; another noise-tolerant option.",
        ),
        MinimizerCatalogEntry(
            name="COBYLA", scipy_method="COBYLA", supports_gradient=False,
            stochastic=False,
            description="Derivative-free, constraint-capable; a common VQE default on real hardware.",
        ),
        MinimizerCatalogEntry(
            name="SLSQP", scipy_method="SLSQP", supports_gradient=True,
            description="Sequential least-squares; supports equality/inequality constraints.",
        ),
        MinimizerCatalogEntry(
            name="trust-constr", scipy_method="trust-constr", supports_gradient=True,
            description="Trust-region method with constraint support; more robust but more energy evaluations per step.",
        ),
    ]
}


class StoppingCriterionCatalogEntry(pydantic.BaseModel):
    """One convergence criterion, mapped to the ``AdaptVQEConfig`` field it
    actually controls (``execution.py`` — no separate stopping-criterion
    object exists; this catalogue documents the mapping qrunch's guide
    treats as a distinct concept).

    name         catalogue key.
    field_name   the AdaptVQEConfig field this criterion configures.
    applies_to   "macro" (ADAPT-VQE ansatz growth) or "micro" (per-iteration
                 classical optimizer).
    """
    name: str
    field_name: str
    applies_to: str
    description: str = ""


STOPPING_CRITERION_CATALOG: dict[str, StoppingCriterionCatalogEntry] = {
    e.name: e
    for e in [
        StoppingCriterionCatalogEntry(
            name="gradient_norm", field_name="gradient_threshold", applies_to="macro",
            description="Stop growing the ADAPT-VQE ansatz once the pool gradient norm falls below this.",
        ),
        StoppingCriterionCatalogEntry(
            name="energy_tolerance", field_name="energy_threshold", applies_to="micro",
            description="Per-iteration classical optimizer convergence tolerance (scipy's `tol`).",
        ),
        StoppingCriterionCatalogEntry(
            name="max_ansatz_depth", field_name="max_macro_iterations", applies_to="macro",
            description="Hard cap on the number of ADAPT-VQE operators added, regardless of gradient norm.",
        ),
        StoppingCriterionCatalogEntry(
            name="max_optimizer_steps", field_name="max_micro_iterations", applies_to="micro",
            description="Hard cap on classical optimizer steps per macro-iteration.",
        ),
    ]
}


__all__ = [
    "MINIMIZER_CATALOG",
    "STOPPING_CRITERION_CATALOG",
    "MinimizerCatalogEntry",
    "StoppingCriterionCatalogEntry",
]
