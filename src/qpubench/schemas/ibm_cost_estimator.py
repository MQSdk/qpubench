"""IBM Quantum resource + cost estimator — pricing models and plan math.

Pure Pydantic module (no ``qiskit``/``qiskit_ibm_runtime`` import — same
core-never-imports-a-quantum-library boundary as every other schema
module here); the real transpile-based resource estimation that fills in
``CircuitResourceEstimate`` lives in
``backends/ibm_cost_estimator.py``, lazy-importing Qiskit the same way
``backends/ibm_adapter.py`` does.

Two distinct things this module estimates
------------------------------------------
1. **QPU time** (``CircuitResourceEstimate.estimated_qpu_time_s``) — how
   many seconds of quantum-processor time a circuit/job will consume.
   Uses IBM's own documented formula, not a guess (confirmed against
   quantum.cloud.ibm.com/docs/en/guides/estimate-job-run-time, checked
   2026-07-09)::

       usage_seconds = per_sub_job_overhead + (rep_delay + circuit_duration) * shots

   with IBM's own stated defaults: ``per_sub_job_overhead ~= 2s``,
   ``rep_delay = 250e-6 s`` on most backends. ``circuit_duration`` is a
   real, per-circuit value — computed in ``backends/ibm_cost_estimator.py``
   via ALAP-scheduled transpilation (``QuantumCircuit.estimate_duration()``
   against the target backend), exactly the method that same IBM doc page
   recommends for local estimation. IBM's doc explicitly notes the
   experimental ``scheduler_timing`` return value "is NOT the time used
   for billing" — this formula is IBM's own recommended proxy for it, not
   a promise of exact billed-second parity.

2. **Dollar cost** (``PlanCostBreakdown``) — turning total QPU-seconds
   across a benchmark study into a cost under each of IBM's four access
   plans. Rate figures in ``IBMPricingRates.default()`` are **not**
   independently confirmed against ibm.com/quantum/products — that page
   returned HTTP 403 to automated fetches in this session (bot
   protection). What backs each number:

   - Confirmed directly from IBM's own docs
     (quantum.cloud.ibm.com/docs/en/guides/plans-overview,
     .../manage-cost, checked 2026-07-09): Open Plan's free quota
     ("up to 10 minutes per 28-day rolling window"); billing unit is
     seconds ("billed in arrears by seconds of usage"); Flex Plan's
     minimum purchase ("at least 400" minutes) and validity ("within one
     year of purchase").
   - The exact $/minute figures ($96 PAYG, $72 Flex, $48 Premium) and
     Flex's $30,000 minimum / Premium's 5,200 min/year minimum are cross-
     referenced from two independent analyst/press sources covering IBM's
     Flex Plan launch (Moor Insights & Strategy's research note; Quantum
     Computing Report), consistent with each other and with IBM's own
     "at least 400 minutes" / "$30,000" framing (400 min x $72 = $28,800;
     $30,000 / $72 ~= 417 min — internally consistent).

   **Verify current numbers at ibm.com/quantum/products before making a
   real budget decision** — this module could not confirm them against
   that page directly, and IBM pricing changes over time (the Flex Plan
   itself launched in 2026). Every rate is a field on `IBMPricingRates`,
   not a hardcoded constant, so pass your own confirmed values as an
   override once verified.

Schema version: 2.10.0
"""
from __future__ import annotations

import enum
import math

import pydantic


class IBMAccessPlan(str, enum.Enum):
    OPEN = "open"
    PAY_AS_YOU_GO = "pay_as_you_go"
    FLEX = "flex"
    PREMIUM = "premium"


class IBMPricingRates(pydantic.BaseModel):
    """IBM Quantum access-plan pricing. See module docstring for exactly
    which fields are confirmed against IBM's own docs vs. cross-referenced
    analyst/press sources only — verify before budgeting.

    open_plan_free_seconds_per_window   free QPU-seconds per rolling
                                        window (600s = 10 min, confirmed).
    open_plan_window_days                 rolling-window length (28 days,
                                        confirmed).
    open_plan_promo_bonus_seconds          optional temporary promotional
                                        bonus (IBM ran a "+180 minutes over
                                        12 months" promo for active Open
                                        Plan users as of 2026-03-16) — NOT
                                        applied by default (`None`); pass
                                        explicitly if your account has it
                                        active, since promos expire.
    pay_as_you_go_usd_per_minute           $/minute, billed by the second
                                        (not independently confirmed —
                                        see module docstring).
    flex_usd_per_minute                     $/minute of prepaid Flex time
                                        (not independently confirmed).
    flex_minimum_purchase_usd                minimum lump-sum prepurchase
                                        (not independently confirmed).
    flex_validity_days                        prepaid minutes expire this
                                        many days after purchase (365,
                                        confirmed: "within one year").
    premium_usd_per_minute                     $/minute equivalent of the
                                        annual subscription (not
                                        independently confirmed).
    premium_minimum_minutes_per_year            minimum annual commitment,
                                        in minutes (not independently
                                        confirmed).
    """
    open_plan_free_seconds_per_window: float = 600.0
    open_plan_window_days: int = 28
    open_plan_promo_bonus_seconds: float | None = None

    pay_as_you_go_usd_per_minute: float = 96.0

    flex_usd_per_minute: float = 72.0
    flex_minimum_purchase_usd: float = 30_000.0
    flex_validity_days: int = 365

    premium_usd_per_minute: float = 48.0
    premium_minimum_minutes_per_year: float = 5_200.0

    @classmethod
    def default(cls) -> IBMPricingRates:
        """Best-available sourced defaults as of 2026-07-09 — see module
        docstring for exact provenance/confidence per field."""
        return cls()


class CircuitResourceEstimate(pydantic.BaseModel):
    """Real, per-job resource estimate for one circuit submitted to IBM
    Quantum Runtime — one instance per distinct (circuit, shots) pair in a
    benchmark study. Populated by
    ``backends.ibm_cost_estimator.estimate_circuit_resources`` (real
    Qiskit transpilation + `QuantumCircuit.estimate_duration()`), not
    constructed by hand.

    gate_counts                  raw `count_ops()` breakdown, including
                                non-gate instructions (`measure`, `delay`,
                                `barrier`) exactly as Qiskit reports them.
    two_qubit_gate_count /
    one_qubit_gate_count           dominant driver of both duration and
                                error rate on real hardware — unitary
                                gates only, `measure`/`delay`/`barrier`/
                                `reset` excluded (unlike `gate_counts`).
    circuit_duration_s              real ALAP-scheduled circuit duration
                                for ONE execution (one shot), from
                                `QuantumCircuit.estimate_duration()`.
    estimated_qpu_time_s          IBM's own documented formula (see module
                                docstring): `per_sub_job_overhead +
                                (rep_delay_s + circuit_duration_s) * shots`.
    """
    label: str = ""
    backend_name: str
    num_qubits: int
    depth: int
    gate_counts: dict[str, int] = {}
    two_qubit_gate_count: int
    one_qubit_gate_count: int
    shots: int
    circuit_duration_s: float
    rep_delay_s: float = 250e-6
    per_sub_job_overhead_s: float = 2.0
    estimated_qpu_time_s: float
    optimization_level: int = 1
    scheduling_method: str = "alap"

    @classmethod
    def compute_qpu_time_s(
        cls, *, circuit_duration_s: float, shots: int,
        rep_delay_s: float = 250e-6, per_sub_job_overhead_s: float = 2.0,
    ) -> float:
        """IBM's own documented usage formula — see module docstring."""
        return per_sub_job_overhead_s + (rep_delay_s + circuit_duration_s) * shots


class PlanCostBreakdown(pydantic.BaseModel):
    """Cost of running `total_qpu_seconds` of QPU time under one IBM
    access plan.

    cost_usd                      what you'd actually pay (or the minimum
                                  commitment required, for Flex/Premium —
                                  see per-plan notes).
    fits_in_free_quota              Open Plan only: whether the whole
                                  study fits in one free window.
    windows_needed                  Open Plan only: how many 28-day
                                  windows you'd need if run for free,
                                  spread out over time.
    minutes_purchased / minutes_wasted   Flex only: minutes bought (>=
                                  minimum purchase) vs. minutes left over.
    meets_minimum_commitment         Premium only: whether this study's
                                  usage alone is small relative to the
                                  minimum annual commitment (almost always
                                  True — Premium is priced as annual
                                  capacity, not per-study).
    """
    plan: IBMAccessPlan
    total_qpu_seconds: float
    total_qpu_minutes: float
    cost_usd: float | None
    fits_in_free_quota: bool | None = None
    windows_needed: int | None = None
    minutes_purchased: float | None = None
    minutes_wasted: float | None = None
    meets_minimum_commitment: bool | None = None
    notes: list[str] = []


class BenchmarkCostEstimate(pydantic.BaseModel):
    """Aggregate resource + cost estimate for a full benchmark study
    (many circuits/jobs) across all four IBM access plans."""
    circuit_estimates: list[CircuitResourceEstimate]
    total_qpu_seconds: float
    total_qpu_minutes: float
    total_shots: int
    plan_breakdowns: dict[IBMAccessPlan, PlanCostBreakdown]


# ---------------------------------------------------------------------------
# Plan cost arithmetic — pure functions, no qiskit needed
# ---------------------------------------------------------------------------

def estimate_open_plan(
    total_qpu_seconds: float, rates: IBMPricingRates,
) -> PlanCostBreakdown:
    free_seconds = rates.open_plan_free_seconds_per_window
    if rates.open_plan_promo_bonus_seconds:
        free_seconds += rates.open_plan_promo_bonus_seconds
    fits = total_qpu_seconds <= free_seconds
    windows = 1 if fits else math.ceil(total_qpu_seconds / rates.open_plan_free_seconds_per_window)
    notes = [
        f"Free quota: {rates.open_plan_free_seconds_per_window / 60:.0f} min "
        f"per {rates.open_plan_window_days}-day rolling window.",
    ]
    if rates.open_plan_promo_bonus_seconds:
        notes.append(
            f"Includes a {rates.open_plan_promo_bonus_seconds / 60:.0f} min promotional "
            f"bonus — confirm it's still active on your account before relying on it."
        )
    if not fits:
        notes.append(
            f"Exceeds one free window — would need to be split across "
            f"{windows} separate {rates.open_plan_window_days}-day windows "
            f"(~{windows * rates.open_plan_window_days} days) to stay free, "
            f"or use Pay-As-You-Go for the excess."
        )
    return PlanCostBreakdown(
        plan=IBMAccessPlan.OPEN,
        total_qpu_seconds=total_qpu_seconds,
        total_qpu_minutes=total_qpu_seconds / 60,
        cost_usd=0.0,
        fits_in_free_quota=fits,
        windows_needed=windows,
        notes=notes,
    )


def estimate_pay_as_you_go(
    total_qpu_seconds: float, rates: IBMPricingRates,
) -> PlanCostBreakdown:
    billed_seconds = math.ceil(total_qpu_seconds)
    cost = billed_seconds * (rates.pay_as_you_go_usd_per_minute / 60.0)
    return PlanCostBreakdown(
        plan=IBMAccessPlan.PAY_AS_YOU_GO,
        total_qpu_seconds=total_qpu_seconds,
        total_qpu_minutes=total_qpu_seconds / 60,
        cost_usd=cost,
        notes=[
            f"${rates.pay_as_you_go_usd_per_minute:.0f}/min, billed by the "
            f"second, no minimum commitment.",
        ],
    )


def estimate_flex(
    total_qpu_seconds: float, rates: IBMPricingRates,
) -> PlanCostBreakdown:
    minutes_needed = total_qpu_seconds / 60.0
    cost = max(rates.flex_minimum_purchase_usd, minutes_needed * rates.flex_usd_per_minute)
    minutes_purchased = cost / rates.flex_usd_per_minute
    notes = [
        f"Prepaid lump sum, minimum ${rates.flex_minimum_purchase_usd:,.0f} "
        f"(buys {rates.flex_minimum_purchase_usd / rates.flex_usd_per_minute:.0f} min), "
        f"valid {rates.flex_validity_days} days from purchase.",
    ]
    if cost == rates.flex_minimum_purchase_usd:
        notes.append(
            f"Study only needs {minutes_needed:.1f} min — the "
            f"${rates.flex_minimum_purchase_usd:,.0f} minimum floors the "
            f"cost regardless; only cost-effective if amortized across a "
            f"larger research program using the same purchase."
        )
    return PlanCostBreakdown(
        plan=IBMAccessPlan.FLEX,
        total_qpu_seconds=total_qpu_seconds,
        total_qpu_minutes=minutes_needed,
        cost_usd=cost,
        minutes_purchased=minutes_purchased,
        minutes_wasted=minutes_purchased - minutes_needed,
        notes=notes,
    )


def estimate_premium(
    total_qpu_seconds: float, rates: IBMPricingRates,
) -> PlanCostBreakdown:
    minutes_needed = total_qpu_seconds / 60.0
    minimum_annual_cost = rates.premium_minimum_minutes_per_year * rates.premium_usd_per_minute
    meets_minimum = minutes_needed <= rates.premium_minimum_minutes_per_year
    return PlanCostBreakdown(
        plan=IBMAccessPlan.PREMIUM,
        total_qpu_seconds=total_qpu_seconds,
        total_qpu_minutes=minutes_needed,
        cost_usd=minimum_annual_cost,
        meets_minimum_commitment=meets_minimum,
        notes=[
            f"Annual subscription, minimum "
            f"{rates.premium_minimum_minutes_per_year:,.0f} min/year "
            f"(${minimum_annual_cost:,.0f}/year) — priced as yearly "
            f"capacity, not per study. This study needs only "
            f"{minutes_needed:.1f} min, {minutes_needed / rates.premium_minimum_minutes_per_year:.2%} "
            f"of the minimum commitment.",
            "No published overage rate beyond the included annual minutes "
            "was found — contact IBM sales for usage above the commitment.",
        ],
    )


def estimate_all_plans(
    total_qpu_seconds: float, rates: IBMPricingRates | None = None,
) -> dict[IBMAccessPlan, PlanCostBreakdown]:
    rates = rates or IBMPricingRates.default()
    return {
        IBMAccessPlan.OPEN: estimate_open_plan(total_qpu_seconds, rates),
        IBMAccessPlan.PAY_AS_YOU_GO: estimate_pay_as_you_go(total_qpu_seconds, rates),
        IBMAccessPlan.FLEX: estimate_flex(total_qpu_seconds, rates),
        IBMAccessPlan.PREMIUM: estimate_premium(total_qpu_seconds, rates),
    }


def aggregate_benchmark_cost(
    circuit_estimates: list[CircuitResourceEstimate],
    rates: IBMPricingRates | None = None,
) -> BenchmarkCostEstimate:
    """Roll up a list of per-job `CircuitResourceEstimate`s (one per
    circuit/shots pair in a benchmark study) into a total QPU-time figure
    and a cost breakdown across all four plans."""
    total_seconds = sum(e.estimated_qpu_time_s for e in circuit_estimates)
    total_shots = sum(e.shots for e in circuit_estimates)
    return BenchmarkCostEstimate(
        circuit_estimates=circuit_estimates,
        total_qpu_seconds=total_seconds,
        total_qpu_minutes=total_seconds / 60,
        total_shots=total_shots,
        plan_breakdowns=estimate_all_plans(total_seconds, rates),
    )


__all__ = [
    "BenchmarkCostEstimate",
    "CircuitResourceEstimate",
    "IBMAccessPlan",
    "IBMPricingRates",
    "PlanCostBreakdown",
    "aggregate_benchmark_cost",
    "estimate_all_plans",
    "estimate_flex",
    "estimate_open_plan",
    "estimate_pay_as_you_go",
    "estimate_premium",
]
