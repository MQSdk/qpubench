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
(`examples/guides/estimate_ibm_cost.py`), with the same illustrative
assumptions clearly carried over (4096 shots/circuit, 30 VQE iterations/
case, EfficientSU2 ansatz with reps = TN_Layers_Circuit for tn_qc_opt rows
else 1) — see that script's docstring and `data/README.md` for why these
remain assumptions, not confirmed values, pending the still-open
`Shots`/`Qiskit_Opt_Level`/`n_iterations` questions.

Rows are sorted ascending by estimated per-row QPU time before batching,
so each tranche is the cheapest calculations available at that point —
appropriate for "run a cheap smoke test first, then scale up" campaign
structure. The ~435 rows with no known `N_Qubit` (mol_map-derived, not
computable without a real Cebule MOL_MAP run) can't be cost-estimated at
all and are written to a separate file rather than silently dropped or
guessed into a batch.

Run:
    python examples/guides/split_benchmark_batches.py
"""
from __future__ import annotations

import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.backends.ibm_cost_estimator import estimate_circuit_resources
from qpubench.schemas.ibm_cost_estimator import CircuitResourceEstimate

_CSV_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "IBM_VQE_Test_Benchmark.csv"
_OUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "batches"
_BACKEND_NAME = "ibm_brisbane"

# --- Illustrative assumptions, matching estimate_ibm_cost.py exactly -----
_ASSUMED_SHOTS_PER_CIRCUIT = 4096
_ASSUMED_ANSATZ_REPS = 1
_ASSUMED_VQE_ITERATIONS = 30

# Each plan's OWN budget in seconds -- independent, not cumulative with
# the others (a fresh Flex purchase isn't reduced by what Open already
# gave you for free).
_PLAN_BUDGETS_S = [
    ("batch1_open_plan", 10 * 60),        # Open Plan free quota
    ("batch2_flex_plan", 400 * 60),        # Flex Plan minimum purchase
    ("batch3_premium_plan", 5200 * 60),    # Premium Plan annual minimum
]


def _ansatz_circuit_spec(num_qubits: int, *, reps: int):
    from qiskit import qasm3
    from qiskit.circuit.library import efficient_su2

    from qpubench.schemas.circuit import CircuitSpec
    from qpubench.schemas.primitives import CircuitFormat

    qc = efficient_su2(num_qubits, reps=reps)
    bound = qc.assign_parameters([0.0] * qc.num_parameters)
    bound.measure_all()
    return CircuitSpec(num_qubits=num_qubits, format=CircuitFormat.QASM3, serialized=qasm3.dumps(bound))


def _load_rows() -> list[dict[str, str]]:
    with _CSV_PATH.open() as f:
        return list(csv.DictReader(f))


def _row_ansatz_reps(row: dict[str, str]) -> int:
    if row["Mapper"].startswith("tn_qc_opt") and row["TN_Layers_Circuit"]:
        return int(row["TN_Layers_Circuit"])
    return _ASSUMED_ANSATZ_REPS


def estimate_per_row_qpu_seconds(rows: list[dict[str, str]]) -> dict[int, float]:
    """Real per-row QPU-time estimate (at `_ASSUMED_VQE_ITERATIONS`
    iterations), keyed by `Case_ID`. Real transpile calls are cached per
    (num_qubits, ansatz reps) pair -- most of the 783 estimable rows share
    one of a much smaller number of distinct pairs.
    """
    cache: dict[tuple[int, int], CircuitResourceEstimate] = {}
    per_row: dict[int, float] = {}
    for row in rows:
        if not row["N_Qubit"]:
            continue
        num_qubits = int(row["N_Qubit"])
        reps = _row_ansatz_reps(row)
        key = (num_qubits, reps)
        if key not in cache:
            spec = _ansatz_circuit_spec(num_qubits, reps=reps)
            cache[key] = estimate_circuit_resources(
                spec, backend_name=_BACKEND_NAME, shots=_ASSUMED_SHOTS_PER_CIRCUIT,
                label=f"{num_qubits}q, {reps} ansatz reps",
            )
        per_row[int(row["Case_ID"])] = cache[key].estimated_qpu_time_s * _ASSUMED_VQE_ITERATIONS
    print(f"  ({len(cache)} distinct (qubits, ansatz reps) pairs really transpiled)")
    return per_row


def split_into_batches(
    rows: list[dict[str, str]], per_row_seconds: dict[int, float],
) -> tuple[list[list[dict[str, str]]], list[dict[str, str]], list[dict[str, str]]]:
    """Ascending-cost greedy fill into the three plan-sized tranches.

    Returns (batches, overflow_rows, unestimable_rows) where `batches`
    has one list per entry in `_PLAN_BUDGETS_S`, `overflow_rows` is
    anything left over after all three budgets are full (empty unless the
    total workload exceeds Open+Flex+Premium combined), and
    `unestimable_rows` is every row with no known `N_Qubit`.
    """
    unestimable = [r for r in rows if not r["N_Qubit"]]
    estimable = [r for r in rows if r["N_Qubit"]]
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

    out_path = _OUT_DIR / "batch0_unestimable_needs_mol_map_run.csv"
    _write_csv(out_path, unestimable, per_row_seconds)
    print(f"  {out_path.name}: {len(unestimable)} rows -- N_Qubit unknown, "
          f"not batchable until a real Cebule MOL_MAP run fills it in")


if __name__ == "__main__":
    main()
