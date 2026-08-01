"""Split data/IBM_VQE_Test_Benchmark.csv into sequential batch files sized
to fit each IBM access plan's QPU-time budget: a first, cheapest tranche
that fits in the Open Plan's free 10 minutes, a next tranche sized to a
fresh Flex Plan purchase (400 minutes), and a third tranche sized to a
fresh Premium Plan annual minimum (5,200 minutes) — each budget is
independent (not cumulative with the others), matching the real workflow
of exhausting one plan/purchase before moving to the next.

Requires: pip install 'qpubench[qiskit]'

Real, not guessed: per-row QPU-time uses the same real ALAP-scheduled
transpilation + IBM usage formula as
`backends.ibm_cost_estimator.estimate_circuit_resources`
(`examples/guides/estimate_ibm_cost.py`), and builds the ansatz each row
actually names at that row's `Ansatz_Reps` (`_ansatz_builders.py`) —
EfficientSU2,
RealAmplitudes, StronglyEntanglingLayers (Cebule TN_QC_OPT's circuit
side) and a real Trotterized UCCSD all transpile to very different
depths, so an earlier revision's "assume EfficientSU2 everywhere" was the
single largest source of error in these estimates.

Still assumptions, clearly carried over from `estimate_ibm_cost.py`:
4,096 shots per circuit and 30 VQE iterations per case, both still-open
campaign decisions — see that script's docstring and `data/README.md`.

Rows are sorted ascending by estimated per-row QPU time before batching,
so each tranche is the cheapest calculations available at that point —
appropriate for "run a cheap smoke test first, then scale up" campaign
structure.

Run:
    python examples/guides/split_benchmark_batches.py
"""
from __future__ import annotations

import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _ansatz_builders import circuit_spec

from qpubench.backends.ibm_cost_estimator import estimate_circuit_resources
from qpubench.schemas.mirrors.ibm_cost_estimator import CircuitResourceEstimate

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CSV_PATH = _REPO_ROOT / "data" / "IBM_VQE_Test_Benchmark.csv"
_OUT_DIR = _REPO_ROOT / "data" / "batches"
_BACKEND_NAME = "ibm_brisbane"

# --- Illustrative assumptions, matching estimate_ibm_cost.py exactly -----
_ASSUMED_SHOTS_PER_CIRCUIT = 4096
_ASSUMED_VQE_ITERATIONS = 30

# Each plan's OWN budget in seconds -- independent, not cumulative with
# the others (a fresh Flex purchase isn't reduced by what Open already
# gave you for free).
_PLAN_BUDGETS_S = [
    ("batch1_open_plan", 10 * 60),        # Open Plan free quota
    ("batch2_flex_plan", 400 * 60),        # Flex Plan minimum purchase
    ("batch3_premium_plan", 5200 * 60),    # Premium Plan annual minimum
]


def _load_rows() -> list[dict[str, str]]:
    with _CSV_PATH.open() as f:
        return list(csv.DictReader(f))


def _row_active_electrons(row: dict[str, str]) -> int:
    """Electrons the ansatz builder sees.

    Only UCCSD reads this, and only on JW rows, where qubits are spin
    orbitals and the count carries over directly.
    """
    return int(row["Active_Electrons"])


def estimate_per_row_qpu_seconds(rows: list[dict[str, str]]) -> dict[int, float]:
    """Real per-row QPU-time estimate (at `_ASSUMED_VQE_ITERATIONS`
    iterations), keyed by `Case_ID`. Real transpile calls are cached per
    (ansatz, qubits, reps, electrons) key -- the matrix has far more rows
    than distinct circuits.
    """
    cache: dict[tuple[str, int, int, int], CircuitResourceEstimate] = {}
    per_row: dict[int, float] = {}
    for row in rows:
        if not row["N_Qubit"] or not row["Ansatz"]:
            continue
        num_qubits = int(row["N_Qubit"])
        reps = int(row["Ansatz_Reps"])
        ansatz = row["Ansatz"]
        num_electrons = _row_active_electrons(row)
        key = (ansatz, num_qubits, reps, num_electrons)
        if key not in cache:
            spec = circuit_spec(
                ansatz, num_qubits, reps=reps, num_electrons=num_electrons
            )
            cache[key] = estimate_circuit_resources(
                spec, backend_name=_BACKEND_NAME, shots=_ASSUMED_SHOTS_PER_CIRCUIT,
                label=f"{ansatz}, {num_qubits}q, {reps} reps",
            )
        per_row[int(row["Case_ID"])] = cache[key].estimated_qpu_time_s * _ASSUMED_VQE_ITERATIONS
    print(f"  ({len(cache)} distinct circuits really transpiled)")
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
    """
    estimable = [r for r in rows if int(r["Case_ID"]) in per_row_seconds]
    unestimable = [r for r in rows if int(r["Case_ID"]) not in per_row_seconds]
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


def _write_csv(path: pathlib.Path, rows: list[dict[str, str]], per_row_seconds: dict[int, float]) -> None:
    if not rows:
        return
    fieldnames = [*rows[0].keys(), "Est_QPU_Time_S_At_30_Iter", "Est_QPU_Time_Cumulative_S"]
    cumulative = 0.0
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        for row in rows:
            cost = per_row_seconds.get(int(row["Case_ID"]))
            if cost is not None:
                cumulative += cost
            out = dict(row)
            out["Est_QPU_Time_S_At_30_Iter"] = f"{cost:.3f}" if cost is not None else ""
            out["Est_QPU_Time_Cumulative_S"] = f"{cumulative:.3f}" if cost is not None else ""
            w.writerow(out)


def main() -> None:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _load_rows()
    print(f"Loaded {len(rows)} rows from {_CSV_PATH.name}")

    per_row_seconds = estimate_per_row_qpu_seconds(rows)
    batches, overflow, unestimable = split_into_batches(rows, per_row_seconds)

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
              f"-- exceeds Open+Flex+Premium combined, needs a separate arrangement")
    else:
        print("  No overflow -- every estimable row fits within Open+Flex+Premium.")

    if unestimable:
        out_path = _OUT_DIR / "batch0_unestimable.csv"
        _write_csv(out_path, unestimable, per_row_seconds)
        print(f"  {out_path.name}: {len(unestimable)} rows -- no circuit could be built")
    else:
        print("  No unestimable rows -- every row has a qubit count and a named ansatz.")


if __name__ == "__main__":
    main()
