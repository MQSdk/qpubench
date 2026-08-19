"""Split the stage-1 screening matrix into batches sized to each IBM
access plan's QPU-time budget: a first, cheapest tranche inside the Open
Plan's free 10 minutes, a second sized to a Flex Plan purchase (400
minutes), and a third sized to a Premium Plan annual minimum (5,200
minutes).  Each budget is independent, matching the real workflow of
exhausting one plan before moving to the next.

Requires: nothing beyond the standard library.

The per-row cost is MEASURED, not modelled.  Fitting 559 completed
Estimator jobs on ibm_aachen at 4,096 shots, with the default options the
campaign will submit under, gives

    billed seconds per cost-function evaluation = 12.0 + 0.70 x E

where E is the row's measurement circuits per evaluation
(Num_ExpVals_Per_Iter).  An evaluation is not one circuit: <H> costs one
circuit per measurement basis, and E is a property of the Hamiltonian
rather than of the circuit preparing the state.  Rows whose E is assumed
rather than measured are costed at a lower bound and marked in
Num_ExpVals_Source; see build_benchmark_matrix.EXPVALS_PER_ITER.

The fixed 12.0 seconds is readout-error calibration, which the default
Estimator options request once per job.  It dominates every small row, so
it is the campaign's largest single lever.

Rows in optimization_mode="network" take no quantum measurements at all,
so they cost nothing and are written to their own
batch0_classical_only.csv rather than being sorted into a plan budget.
Rows are otherwise sorted ascending by cost before batching, so each
tranche is the cheapest work available at that point.

Run:
    PYTHONPATH=src python examples/guides/split_benchmark_batches.py
"""
from __future__ import annotations

import collections
import csv
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CAMPAIGN_DIR = _REPO_ROOT / "data" / "benchmarks" / "ibm_tn-vqe_qesem"
_CSV_PATH = _CAMPAIGN_DIR / "stage1_screening_matrix.csv"
# The tranches sit beside the matrix they were cut from, which is where
# a reader expects them.
_OUT_DIR = _CAMPAIGN_DIR
# The device the campaign buys time on, in IBM's European data centre.
# qiskit-ibm-runtime ships an offline calibration snapshot of it
# (FakeAachen, from 0.47.0), which resolve_calibration_backend picks up,
# so re-cutting the batches needs no credentials and two runs agree.
# The snapshot is of THIS device: costing it against another device's
# would estimate the wrong machine, since the two-qubit gate differs
# between processor generations and the transpiled circuit differs before
# any duration is read off it.
_BACKEND_NAME = "ibm_aachen"

# Shots and iterations both come from each row's own columns, matching
# estimate_ibm_cost.py exactly.
# What TN-VQE's own transpile(circuit, backend) call resolves to under
# Qiskit 2.x -- not the estimator's signature default of 1.
_OPTIMIZATION_LEVEL = 2
_CLASSICAL_ONLY_MODE = "network"

# Each plan's OWN budget in seconds -- independent, not cumulative with
# the others (a fresh Flex purchase isn't reduced by what Open already
# gave you for free).
_PLAN_BUDGETS_S = [
    ("batch1_open_plan", 10 * 60),        # Open Plan free quota
    ("batch2_flex_plan", 400 * 60),        # Flex Plan minimum purchase
    ("batch3_premium_plan", 5200 * 60),    # Premium Plan annual minimum
]

# Billed QPU seconds per cost-function evaluation, fitted to 559 completed
# Estimator jobs on ibm_aachen (all at 4,096 shots, measure mitigation on,
# 32 randomizations).  IBM's own pre-run estimate over those jobs reads
# 15.04 + 0.878 x E seconds, and the jobs whose billed quantum_seconds are
# known came in at 0.80 of it.
_FIXED_S_PER_EVALUATION = 12.03
_S_PER_MEASUREMENT_BASIS = 0.702

def _load_rows() -> list[dict[str, str]]:
    with _CSV_PATH.open() as f:
        return list(csv.DictReader(f))


def _row_active_electrons(row: dict[str, str]) -> int:
    """Electrons the ansatz builder sees.

    Only a reference-determinant ansatz such as UCCSD reads this, and only
    on JW rows, where qubits are spin orbitals and the count carries over
    directly; the hardware-efficient families the campaign screens ignore
    it.
    """
    return int(row["Active_Electrons"])


def is_classical_only(row: dict[str, str]) -> bool:
    """True for rows that take no quantum measurements at all.

    optimization_mode="network" freezes phi and optimises theta by
    classical tensor-network contraction, so the row has no QPU cost --
    distinct from a row whose cost merely could not be worked out.
    """
    return row.get("Optimization_Mode") == _CLASSICAL_ONLY_MODE


def evaluation_seconds(expvals_per_iter: int) -> float:
    """Billed QPU seconds for one cost-function evaluation."""
    return _FIXED_S_PER_EVALUATION + _S_PER_MEASUREMENT_BASIS * expvals_per_iter


def estimate_per_row_qpu_seconds(rows: list[dict[str, str]]) -> dict[int, float]:
    """Per-row QPU seconds, keyed by Case_ID.

    The row's own Iterations times what one evaluation costs at the row's
    own Num_ExpVals_Per_Iter.  A row whose measurement count is unknown
    has no cost here rather than a guessed one.
    """
    per_row: dict[int, float] = {}
    for row in rows:
        if is_classical_only(row) or not row["Num_ExpVals_Per_Iter"].isdigit():
            continue
        per_row[int(row["Case_ID"])] = (
            evaluation_seconds(int(row["Num_ExpVals_Per_Iter"]))
            * int(row["Iterations"])
        )
    return per_row


def split_into_batches(
    rows: list[dict[str, str]], per_row_seconds: dict[int, float],
) -> tuple[list[list[dict[str, str]]], list[dict[str, str]], list[dict[str, str]]]:
    """Ascending-cost greedy fill into the three plan-sized tranches.

    Returns (batches, overflow_rows, unestimable_rows) where `batches`
    has one list per entry in `_PLAN_BUDGETS_S`, `overflow_rows` is
    anything left over after all three budgets are full (empty unless the
    total workload exceeds Open+Flex+Premium combined), and
    `unestimable_rows` is every row no circuit could be built for.

    Classical-only rows are excluded by the caller, not counted here as
    unestimable: their cost is genuinely zero, which is a different fact
    from "we could not work it out".
    """
    estimable = [r for r in rows if int(r["Case_ID"]) in per_row_seconds]
    unestimable = [
        r for r in rows
        if int(r["Case_ID"]) not in per_row_seconds and not is_classical_only(r)
    ]
    estimable.sort(key=lambda r: per_row_seconds[int(r["Case_ID"])])

    batches: list[list[dict[str, str]]] = [[] for _ in _PLAN_BUDGETS_S]
    batch_totals = [0.0] * len(_PLAN_BUDGETS_S)
    overflow: list[dict[str, str]] = []

    row_iter = iter(estimable)
    row = next(row_iter, None)
    for i, (_, budget_s) in enumerate(_PLAN_BUDGETS_S):
        while row is not None:
            cost = per_row_seconds[int(row["Case_ID"])]
            if batch_totals[i] + cost > budget_s:
                break
            batches[i].append(row)
            batch_totals[i] += cost
            row = next(row_iter, None)
    while row is not None:
        overflow.append(row)
        row = next(row_iter, None)

    return batches, overflow, unestimable


# Appended to every batch file, in this order, immediately before Notes.
# Notes is free prose and stays last, so a reader scrolling a row does not
# have to cross it to reach the numbers.
#
# Not "..._At_30_Iter" any more: the iteration count is per row, so the
# name would pin a number only some rows use.
_COST_COLUMNS = [
    "Est_QPU_Time_Per_Iter_S",      # one cost-function evaluation
    "Est_QPU_Time_S",               # x the row's own Iterations
    "Est_QPU_Time_Cumulative_S",    # running total within this batch
]


def _write_csv(path: pathlib.Path, rows: list[dict[str, str]], per_row_seconds: dict[int, float]) -> None:
    if not rows:
        return
    fieldnames = [
        *(name for name in rows[0] if name != "Notes"), *_COST_COLUMNS, "Notes",
    ]
    cumulative = 0.0
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        for row in rows:
            cost = per_row_seconds.get(int(row["Case_ID"]))
            if cost is not None:
                cumulative += cost
            out = dict(row)
            # Per evaluation, not per circuit: with --circuits-per-eval N
            # this is what one evaluation of <H> costs, all N measurement
            # circuits together.
            out["Est_QPU_Time_Per_Iter_S"] = (
                f"{cost / int(row['Iterations']):.3f}" if cost is not None else ""
            )
            out["Est_QPU_Time_S"] = f"{cost:.3f}" if cost is not None else ""
            out["Est_QPU_Time_Cumulative_S"] = f"{cumulative:.3f}" if cost is not None else ""
            w.writerow(out)


def main() -> None:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _load_rows()
    print(f"Loaded {len(rows)} rows from {_CSV_PATH.name}")

    per_row_seconds = estimate_per_row_qpu_seconds(rows)
    sources = collections.Counter(
        row["Num_ExpVals_Source"] for row in rows if not is_classical_only(row)
    )
    print(f"  costed at {_FIXED_S_PER_EVALUATION:.2f} s + "
          f"{_S_PER_MEASUREMENT_BASIS:.3f} s x Num_ExpVals_Per_Iter per evaluation")
    for source, count in sorted(sources.items()):
        print(f"    {count:>4} rows: {source}")

    batches, overflow, unestimable = split_into_batches(rows, per_row_seconds)

    classical_only = [r for r in rows if is_classical_only(r)]
    if classical_only:
        out_path = _OUT_DIR / "batch0_classical_only.csv"
        _write_csv(out_path, classical_only, per_row_seconds)
        print(f"  {out_path.name}: {len(classical_only)} rows, 0.00 min "
              f"-- optimization_mode='network', no QPU time, no plan budget")

    for (name, budget_s), batch_rows in zip(_PLAN_BUDGETS_S, batches):
        total_s = sum(per_row_seconds[int(r["Case_ID"])] for r in batch_rows)
        out_path = _OUT_DIR / f"{name}.csv"
        _write_csv(out_path, batch_rows, per_row_seconds)
        print(f"  {out_path.name}: {len(batch_rows)} rows, "
              f"{total_s:.1f}s ({total_s / 60:.2f} min) of {budget_s / 60:.0f} min budget")

    if overflow:
        out_path = _OUT_DIR / "batch4_overflow.csv"
        _write_csv(out_path, overflow, per_row_seconds)
        total_s = sum(per_row_seconds[int(r["Case_ID"])] for r in overflow)
        print(f"  {out_path.name}: {len(overflow)} rows, {total_s:.1f}s "
              f"({total_s / 60:.1f} min) -- exceeds Open+Flex+Premium combined")
    else:
        print("  No overflow -- every costed row fits within Open+Flex+Premium.")

    if unestimable:
        out_path = _OUT_DIR / "batch5_unmeasured.csv"
        _write_csv(out_path, unestimable, per_row_seconds)
        print(f"  {out_path.name}: {len(unestimable)} rows -- no measurement count")


if __name__ == "__main__":
    main()
