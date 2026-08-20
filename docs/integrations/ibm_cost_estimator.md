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
`data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv` end to end: the minimal case (H2/sto-3g,
4 qubits, 1 circuit) fits comfortably in the Open Plan's free quota
(~3s of an estimated 3.04s QPU-time budget vs. 600s free).

**What this transpiled figure is, and is not.** It is the cost of running
one circuit once: `overhead + (rep_delay + duration) x shots`. One
cost-function evaluation of `<H>` submits one circuit *per measurement
basis*, and that count is a property of the Hamiltonian. The campaign
therefore no longer sizes its batches from this estimate. It costs them
from the seven completed Estimator jobs on the target device whose billed
quantum_seconds are known,

    billed seconds per evaluation = 11.0 + 1.125 x measurement bases

which holds to within 4% from 2 measurement bases to 81, and puts a
4-qubit evaluation at 13 to 20 s against the 3.04 s a single transpiled
submission suggests. See
[the campaign README](../../data/benchmarks/ibm_tn-vqe_qesem/README.md#what-one-cost-function-evaluation-costs).
Two facts from those jobs are worth carrying into any use of this module:
the fixed 11 s is readout-error calibration requested once per job by the
default Estimator options, and across the depths measured the circuit
duration does not enter at all, so it is the Hamiltonian rather than the
ansatz depth that sets cost at these widths. That holds for shallow
circuits only: three depth-2389 jobs each billed fourteen times what this
line predicts.

**Iterations are per row, not a flat assumption.** Each row's
`Iterations` column holds `max(30, ceil(1.3 x n_params))`, a budget
proportional to the row's own free-parameter count. Two facts make a flat
value wrong: COBYLA cannot take a single descent step before it has built
an `n+1` simplex, and scipy overrides a smaller `maxiter` rather than
honouring it; and the evaluations needed to reach a given fraction of the
achievable descent grow linearly in the parameter count, so any additive
rule reaches a shrinking fraction as circuits widen.

### Turning this into a real campaign plan

`examples/guides/split_benchmark_batches.py` uses the same per-row
estimates to split the CSV into `data/benchmarks/ibm_tn-vqe_qesem/batch1_open_plan.csv`
(fits the Open Plan's free 10 min), `batch2_flex_plan.csv` (fits a fresh
400-min Flex purchase), and `batch3_premium_plan.csv` (fits a fresh
5,200-min Premium annual minimum); see
[`data/benchmarks/ibm_tn-vqe_qesem/README.md`](../../data/benchmarks/ibm_tn-vqe_qesem/README.md).
