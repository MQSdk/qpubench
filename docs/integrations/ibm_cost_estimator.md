# IBM resource + cost estimator

Estimate what a circuit, or a whole benchmark study, will cost on real
IBM Quantum hardware, **before** submitting anything and **without**
needing an IBM Quantum account. Two modules:

- `src/qpubench/backends/ibm_cost_estimator.py`: real and Qiskit-dependent;
  transpiles + ALAP-schedules a `CircuitSpec` against a real IBM
  calibration snapshot, giving real depth/gate-count/duration numbers.
- `src/qpubench/schemas/mirrors/ibm_cost_estimator.py`: pure Pydantic, which turns
  QPU-seconds into a dollar breakdown across IBM's four access plans. No
  Qiskit import, usable standalone (e.g. if you already know your QPU-time
  budget from elsewhere).

---

## Installation

```sh
pip install 'qpubench[qiskit]'
```

## Resource estimation: real, verified

```python
from qpubench.backends.ibm_cost_estimator import estimate_circuit_resources

est = estimate_circuit_resources(
    my_circuit_spec, backend_name="ibm_brisbane", shots=4096,
)
print(est.depth, est.two_qubit_gate_count, est.estimated_qpu_time_s)
```

By default this resolves `"ibm_brisbane"` to the real
`qiskit_ibm_runtime.fake_provider.FakeBrisbane` calibration snapshot; no
credentials, no network. Pass a live backend (e.g.
`IBMAdapter(...).get_live_backend()`) via `backend=` to estimate against
current calibration data instead of a static snapshot.

**What's real here, not guessed:** `depth`/`gate_counts` come from actually
running Qiskit's preset pass manager against the target topology/basis
gates (`ecr`/`rz`/`sx`/`x` on Eagle-class chips like Brisbane). Circuit
duration comes from `QuantumCircuit.estimate_duration(backend.target)`
after `scheduling_method="alap"`, exactly the method IBM's own docs
recommend for local usage estimation (quantum.cloud.ibm.com/docs/en/
guides/estimate-job-run-time, checked 2026-07-09). `estimated_qpu_time_s`
applies that same page's documented formula:

```
usage_seconds = per_sub_job_overhead + (rep_delay + circuit_duration) * shots
```

with IBM's own stated defaults (`per_sub_job_overhead ~= 2s`,
`rep_delay = 250 microseconds`). IBM's doc notes the experimental
`scheduler_timing` return value "is NOT the time used for billing"; this
is IBM's own recommended proxy for it, not a guarantee of exact billed-
second parity.

Verified in this session: a 4-qubit test circuit transpiled against
`FakeBrisbane` gives `depth=14`, 3 real `ecr` (2-qubit) gates, a
3.52-microsecond circuit duration, and (at 4096 shots) an estimated 3.04s
of QPU time; see `tests/test_ibm_cost_estimator.py`.

## Cost breakdown: sourced, but verify before budgeting

```python
from qpubench.schemas.mirrors.ibm_cost_estimator import estimate_all_plans

for plan, breakdown in estimate_all_plans(total_qpu_seconds=180.0).items():
    print(plan.value, breakdown.cost_usd, breakdown.notes)
```

Or aggregate a whole study's worth of `CircuitResourceEstimate`s at once:

```python
from qpubench.schemas.mirrors.ibm_cost_estimator import aggregate_benchmark_cost

agg = aggregate_benchmark_cost(list_of_circuit_resource_estimates)
print(agg.total_qpu_seconds, agg.plan_breakdowns)
```

### The four plans

| Plan | Model | Rate | Minimum | Confirmed against |
|---|---|---|---|---|
| **Open** | Free quota | n/a | n/a | IBM's own docs: "up to 10 minutes per 28-day rolling window" |
| **Pay-As-You-Go** | Billed by the second | $96/min | none | Rate: analyst/press sources (below). Billing unit (seconds): IBM's own docs |
| **Flex** | Prepaid lump sum | $72/min | $30,000 (~417 min), valid 1 year | Minimum minutes ("at least 400") and validity ("within one year"): IBM's own docs. Rate/minimum $: analyst/press sources |
| **Premium** | Annual subscription | $48/min | 5,200 min/year (~$249,600/year) | Analyst/press sources only |

**Important: verify before making a real budget decision.**
`ibm.com/quantum/products` (the pricing page) returned HTTP 403 to
automated fetches in this session (bot protection), so the exact $/minute
figures above could not be confirmed directly against IBM's own pricing
page. What backs them:

- **Confirmed directly from IBM's own docs**
  (quantum.cloud.ibm.com/docs/en/guides/plans-overview and
  .../manage-cost, checked 2026-07-09): Open Plan's free quota; that
  billing is in seconds; Flex's minimum minutes and 1-year validity.
- **Cross-referenced from two independent analyst/press sources**
  covering the Flex Plan's 2026 launch (Moor Insights & Strategy's
  research note; Quantum Computing Report) for the exact $/minute figures
  and Flex/Premium minimums, internally consistent with each other and
  with IBM's own "at least 400 minutes" / "$30,000" framing (400 min x
  $72/min = $28,800; $30,000 / $72/min ~= 417 min).

Every rate is a field on `IBMPricingRates`, not a hardcoded constant;
override with your own confirmed numbers:

```python
from qpubench.schemas.mirrors.ibm_cost_estimator import IBMPricingRates, estimate_all_plans

my_rates = IBMPricingRates(pay_as_you_go_usd_per_minute=100.0)   # if IBM's rate changed
estimate_all_plans(total_qpu_seconds=180.0, rates=my_rates)
```

### How each plan is evaluated

- **Open**: cost is always `$0`; if the study fits in one free 10-minute
  window (`fits_in_free_quota`), great; otherwise `windows_needed` reports
  how many 28-day windows it'd take to run entirely for free (there's no
  paid overage on this plan).
- **Pay-As-You-Go**: `ceil(seconds) x ($96/60)`, with no minimum, so this is
  usually the right comparison point for "what's the actual marginal
  cost."
- **Flex**: `max($30,000, minutes_needed x $72)`; a single small
  benchmark study will drastically underuse the $30k minimum; only
  cost-effective if amortized across a larger research program using the
  same prepaid balance within its 1-year validity.
- **Premium**: reports the **minimum annual commitment**
  (`5,200 min/year x $48/min`), not a per-study marginal cost; Premium is
  priced as yearly capacity. `meets_minimum_commitment` is `True` when the
  study's usage is small relative to that annual allowance (true for
  essentially any single study). No published overage rate beyond the
  included annual minutes was found.

---

## End-to-end example: costing the VQE benchmark CSV

`examples/guides/estimate_ibm_cost.py` runs this against
`data/IBM_VQE_Test_Benchmark.csv` end to end: the minimal case (H2/sto-3g,
4 qubits, 1 circuit) fits comfortably in the Open Plan's free quota
(~3s of an estimated 3.04s QPU-time budget vs. 600s free). The CSV holds
the stage-1 screening matrix: 294 rows across all 7 bases, both mappers,
both measurement methods and four ansatz families (see `data/README.md`).
At 30
illustrative VQE iterations per row, that's 8,820 circuit submissions,
~47,607s (~793 min) of QPU time: **~$76,173 on Pay-As-You-Go**, ~$57,128
on Flex (above its $30,000 minimum), and ~15% of Premium's 5,200 min/year
minimum commitment.

**The ansatz dominates, which is why it is now built for real.** Each row
names its own ansatz and `Ansatz_Reps`, and the estimator builds that
circuit rather than substituting EfficientSU2 everywhere as an earlier
revision did. The difference is not cosmetic: at 12 qubits a real
Trotterized UCCSD transpiles to ~1,554s per row against ~92s for
EfficientSU2, so the 14 UCCSD/12-qubit rows alone account for ~363 of the
campaign's 793 minutes: 46% of the budget in 5% of the rows. Only 14
distinct circuits are actually transpiled across all 294 rows, cached per
(ansatz, qubits, reps, electrons).

The CSV's `Qiskit_Opt_Level`/`Shots` sweep columns are still blank (see
`data/README.md`), so the example clearly labels its shot count (4096)
and iteration count (30) as illustrative assumptions at the top of the
script; swap in the real choices once decided; the resource-estimation
and cost-breakdown logic itself doesn't change.

### Turning this into a real campaign plan

`examples/guides/split_benchmark_batches.py` uses the same per-row
estimates to split the CSV into `data/batches/batch1_open_plan.csv`
(fits the Open Plan's free 10 min), `batch2_flex_plan.csv` (fits a fresh
400-min Flex purchase), and `batch3_premium_plan.csv` (fits a fresh
5,200-min Premium annual minimum); see
[`data/batches/README.md`](../../data/batches/README.md).
