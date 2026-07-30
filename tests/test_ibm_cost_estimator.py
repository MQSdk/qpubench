"""Tests for the IBM resource + cost estimator.

schemas.ibm_cost_estimator (plan-cost arithmetic): pure, always run — no
qiskit needed.

backends.ibm_cost_estimator (real transpile-based resource estimation):
skipped cleanly if qiskit-ibm-runtime isn't installed. Runs fully offline
against qiskit_ibm_runtime.fake_provider.FakeBrisbane — a real calibration
snapshot IBM ships for exactly this purpose, no credentials or network
needed (same "fake backend, real transpile logic" pattern as
test_backend_adapters.py's IBM/IQM tests).
"""
from __future__ import annotations

import pytest

from qpubench.schemas.mirrors.ibm_cost_estimator import (
    IBMAccessPlan,
    IBMPricingRates,
    aggregate_benchmark_cost,
    estimate_all_plans,
    estimate_flex,
    estimate_open_plan,
    estimate_pay_as_you_go,
    estimate_premium,
)


class TestPlanCostArithmetic:
    def test_open_plan_fits_free_quota(self) -> None:
        rates = IBMPricingRates.default()
        breakdown = estimate_open_plan(300.0, rates)   # 5 minutes
        assert breakdown.cost_usd == 0.0
        assert breakdown.fits_in_free_quota is True
        assert breakdown.windows_needed == 1

    def test_open_plan_exceeds_free_quota(self) -> None:
        rates = IBMPricingRates.default()
        breakdown = estimate_open_plan(1800.0, rates)   # 30 minutes > 10 min free
        assert breakdown.fits_in_free_quota is False
        assert breakdown.windows_needed == 3   # ceil(1800/600)
        assert breakdown.cost_usd == 0.0   # Open Plan has no paid overage

    def test_open_plan_promo_bonus_extends_quota(self) -> None:
        rates = IBMPricingRates.default()
        rates_with_promo = rates.model_copy(update={"open_plan_promo_bonus_seconds": 10_800})   # +180 min
        breakdown = estimate_open_plan(3000.0, rates_with_promo)   # 50 min, fits with promo
        assert breakdown.fits_in_free_quota is True

    def test_pay_as_you_go_matches_rate(self) -> None:
        rates = IBMPricingRates.default()
        # 60s at $96/min == $1.60/s -> $96.00
        breakdown = estimate_pay_as_you_go(60.0, rates)
        assert breakdown.cost_usd == pytest.approx(96.0)

    def test_pay_as_you_go_rounds_up_to_whole_second(self) -> None:
        rates = IBMPricingRates.default()
        breakdown = estimate_pay_as_you_go(0.1, rates)
        assert breakdown.cost_usd == pytest.approx(rates.pay_as_you_go_usd_per_minute / 60.0)

    def test_flex_floors_at_minimum_purchase(self) -> None:
        rates = IBMPricingRates.default()
        breakdown = estimate_flex(60.0, rates)   # 1 minute needed, way under minimum
        assert breakdown.cost_usd == rates.flex_minimum_purchase_usd
        assert breakdown.minutes_purchased is not None
        assert breakdown.minutes_purchased > 1.0
        assert "minimum" in " ".join(breakdown.notes).lower()

    def test_flex_scales_above_minimum(self) -> None:
        rates = IBMPricingRates.default()
        # minutes needed such that minutes*rate > minimum purchase
        minutes_needed = (rates.flex_minimum_purchase_usd / rates.flex_usd_per_minute) * 2
        breakdown = estimate_flex(minutes_needed * 60.0, rates)
        assert breakdown.cost_usd == pytest.approx(minutes_needed * rates.flex_usd_per_minute)

    def test_premium_reports_minimum_annual_commitment(self) -> None:
        rates = IBMPricingRates.default()
        breakdown = estimate_premium(600.0, rates)   # tiny study, 10 min
        expected = rates.premium_minimum_minutes_per_year * rates.premium_usd_per_minute
        assert breakdown.cost_usd == pytest.approx(expected)
        assert breakdown.meets_minimum_commitment is True

    def test_estimate_all_plans_returns_all_four(self) -> None:
        breakdown = estimate_all_plans(600.0)
        assert set(breakdown) == {
            IBMAccessPlan.OPEN, IBMAccessPlan.PAY_AS_YOU_GO,
            IBMAccessPlan.FLEX, IBMAccessPlan.PREMIUM,
        }
        for plan, b in breakdown.items():
            assert b.plan == plan


class TestAggregateBenchmarkCost:
    def test_aggregates_multiple_jobs(self) -> None:
        from qpubench.schemas.mirrors.ibm_cost_estimator import CircuitResourceEstimate

        estimates = [
            CircuitResourceEstimate(
                label=f"job{i}", backend_name="ibm_brisbane", num_qubits=4,
                depth=10, two_qubit_gate_count=3, one_qubit_gate_count=20,
                shots=4096, circuit_duration_s=3.5e-6,
                estimated_qpu_time_s=3.0,
            )
            for i in range(3)
        ]
        agg = aggregate_benchmark_cost(estimates)
        assert agg.total_qpu_seconds == pytest.approx(9.0)
        assert agg.total_shots == 3 * 4096
        assert len(agg.plan_breakdowns) == 4


class TestEstimateCircuitResourcesReal:
    def setup_method(self) -> None:
        pytest.importorskip("qiskit")
        pytest.importorskip("qiskit_ibm_runtime")

    def _bell_like_circuit(self):
        from qiskit import QuantumCircuit, qasm3

        from qpubench.schemas.circuit import CircuitSpec
        from qpubench.schemas.primitives import CircuitFormat

        qc = QuantumCircuit(4)
        qc.h(0)
        qc.cx(0, 1)
        qc.cx(1, 2)
        qc.cx(2, 3)
        qc.measure_all()
        return CircuitSpec(num_qubits=4, format=CircuitFormat.QASM3, serialized=qasm3.dumps(qc))

    def test_real_transpile_against_fake_brisbane(self) -> None:
        from qpubench.backends.ibm_cost_estimator import estimate_circuit_resources

        spec = self._bell_like_circuit()
        est = estimate_circuit_resources(spec, backend_name="ibm_brisbane", shots=4096)

        assert est.num_qubits == 4
        assert est.two_qubit_gate_count >= 3   # at least the 3 real CX->ECR-mapped gates
        assert est.one_qubit_gate_count > 0
        assert est.circuit_duration_s > 0
        assert est.depth > 0

    def test_qpu_time_matches_ibm_formula(self) -> None:
        from qpubench.backends.ibm_cost_estimator import estimate_circuit_resources
        from qpubench.schemas.mirrors.ibm_cost_estimator import CircuitResourceEstimate

        spec = self._bell_like_circuit()
        est = estimate_circuit_resources(spec, backend_name="ibm_brisbane", shots=1000)

        expected = CircuitResourceEstimate.compute_qpu_time_s(
            circuit_duration_s=est.circuit_duration_s, shots=1000,
            rep_delay_s=est.rep_delay_s, per_sub_job_overhead_s=est.per_sub_job_overhead_s,
        )
        assert est.estimated_qpu_time_s == pytest.approx(expected)
        # sanity: dominated by the 2s per-sub-job overhead at these shot counts
        assert est.estimated_qpu_time_s == pytest.approx(2.0, abs=1.0)

    def test_more_shots_increases_qpu_time(self) -> None:
        from qpubench.backends.ibm_cost_estimator import estimate_circuit_resources

        spec = self._bell_like_circuit()
        low = estimate_circuit_resources(spec, backend_name="ibm_brisbane", shots=100)
        high = estimate_circuit_resources(spec, backend_name="ibm_brisbane", shots=100_000)
        assert high.estimated_qpu_time_s > low.estimated_qpu_time_s

    def test_unknown_backend_name_raises_with_helpful_message(self) -> None:
        from qpubench.backends.ibm_cost_estimator import estimate_circuit_resources

        spec = self._bell_like_circuit()
        with pytest.raises(ValueError, match="FakeNotarealbackend"):
            estimate_circuit_resources(spec, backend_name="ibm_notarealbackend", shots=100)

    def test_end_to_end_feeds_into_plan_breakdown(self) -> None:
        """The real point of this module: circuit -> real QPU-seconds ->
        real dollar breakdown across all four plans, without ever needing
        an IBM Quantum account."""
        from qpubench.backends.ibm_cost_estimator import estimate_circuit_resources

        spec = self._bell_like_circuit()
        est = estimate_circuit_resources(spec, backend_name="ibm_brisbane", shots=4096)
        agg = aggregate_benchmark_cost([est])

        assert agg.total_qpu_seconds == pytest.approx(est.estimated_qpu_time_s)
        open_breakdown = agg.plan_breakdowns[IBMAccessPlan.OPEN]
        assert open_breakdown.fits_in_free_quota is True   # a handful of seconds << 600s free
