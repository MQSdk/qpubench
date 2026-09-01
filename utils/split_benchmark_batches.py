"""Cost the stage-1 screening matrix and cut it into batches.

Batches are NOT sized to a budget.  The campaign used to be cut against
IBM's access plans -- 10 free minutes, a 400-minute Flex purchase, a
5,200-minute Premium minimum -- because each was a separate purchase that
had to be filled before the next.  The campaign now holds one allocation
of 900 minutes, so filling tranches to a cap would be arithmetic without
a referent.

What the batches are for now is ORDER.  One cheap row runs first and
proves the path end to end; the rest of the screen follows once it has.
That is a real distinction -- before and after the pipeline is known to
work -- and it is the only one worth cutting the file on.

Requires: nothing beyond the standard library.

The per-row cost is MEASURED, not modelled.  Seven completed Estimator
jobs on ibm_aachen at 4,096 shots, with the default options the campaign
will submit under, have known billed quantum_seconds, and give

    billed seconds per cost-function evaluation = 11.0 + 1.125 x E

to within 4% at every point, over E = 2 to 81 (see the constants below).
E is the row's measurement circuits per evaluation
(Num_ExpVals_Per_Iter).  An evaluation is not one circuit: <H> costs one
circuit per measurement basis, and E is a property of the Hamiltonian
rather than of the circuit preparing the state.  Rows whose E is assumed
rather than measured are costed at a lower bound and marked in
Num_ExpVals_Source; see build_benchmark_matrix.EXPVALS_PER_ITER.

The fixed 11.0 seconds is readout-error calibration, which the default
Estimator options request once per job.  It dominates every small row, so
it is the campaign's largest single lever.

Rows in optimization_mode="network" take no quantum measurements at all,
so they cost nothing and are written to their own
batch0_classical_only.csv rather than being sorted into a plan budget.
Rows are otherwise sorted ascending by cost before batching, so each
tranche is the cheapest work available at that point.

Run:
    PYTHONPATH=src python utils/split_benchmark_batches.py
"""
from __future__ import annotations

import collections
import csv
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
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

# The campaign's whole allocation, and what each phase is meant to take.
# Reported against, never filled to: nothing here caps a batch.
#
#   stage 1  a screen at ~1.3 evaluations per parameter, reaching about
#            half the achievable descent -- enough to rank factors, not
#            enough to answer what the campaign asks.
#   stage 2  the same rows at 4n, where converged energies live.  The
#            larger share, because a ranking of combinations that were
#            never converged answers nothing.
#   reserve  not slack for its own sake.  Two things have already come in
#            far off estimate on this device: a job billed 14x what it was
#            estimated at, and counted measurement bases run about 2x what
#            the runtime actually groups into.  At 900 minutes, one such
#            surprise without a reserve ends the campaign mid-run.
CAMPAIGN_BUDGET_MIN = 900
STAGE_ALLOCATION_MIN = {"stage 1": 250, "stage 2": 450, "reserve": 200}

# How many of the cheapest rows run before the rest, to prove the path.
_PIPELINE_CHECK_ROWS = 1

# Billed QPU seconds per cost-function evaluation, fitted to completed
# ibm_aachen jobs whose billed quantum_seconds are known, all at 4,096
# shots with measure mitigation on and 32 randomizations.  Every one
# falls within 4% of this line, over E = 2 to 81, which brackets the 2
# to 37 the matrix occupies.
#
# The fit is anchored on billing rather than on IBM's pre-run estimate,
# which stands in no fixed ratio to what is billed, so scaling it by any
# single factor misstates the slope.
#
# Circuit depth does not enter across the range measured, but the line
# holds for shallow circuits only.  The campaign's deepest circuit is
# 120, inside that range.
_FIXED_S_PER_EVALUATION = 11.0
_S_PER_MEASUREMENT_BASIS = 1.125

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


def _eval_budget(row: dict[str, str]) -> int:
    """Cost-function evaluations the row is budgeted, from its own column.

    Falls back to Iterations for a matrix generated before Eval_Budget
    existed, where the two were the same number.
    """
    return int(row.get("Quantum_Eval_Budget") or row["Iterations"])


def evaluation_seconds(expvals_per_iter: int) -> float:
    """Billed QPU seconds for one cost-function evaluation."""
    return _FIXED_S_PER_EVALUATION + _S_PER_MEASUREMENT_BASIS * expvals_per_iter


def estimate_per_row_qpu_seconds(rows: list[dict[str, str]]) -> dict[int, float]:
    """Per-row QPU seconds, keyed by Case_ID.

    The row's own EVAL_BUDGET times what one evaluation costs at the row's
    own Num_ExpVals_Per_Iter.  A row whose measurement count is unknown
    has no cost here rather than a guessed one.

    Eval_Budget, not Iterations.  The two coincide under COBYLA and only
    under COBYLA: n_iterations is an iteration count, and an SPSA
    iteration is 2 evaluations while an ExcitationSolve iteration is a
    sweep costing 3n.  Costing on Iterations would understate those rows
    by exactly the conversion factor.
    """
    per_row: dict[int, float] = {}
    for row in rows:
        if is_classical_only(row) or not row["Num_ExpVals_Per_Iter"].isdigit():
            continue
        per_row[int(row["Case_ID"])] = (
            evaluation_seconds(int(row["Num_ExpVals_Per_Iter"]))
            * _eval_budget(row)
        )
    return per_row


def split_into_batches(
    rows: list[dict[str, str]], per_row_seconds: dict[int, float],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Cost-ordered split into (pipeline_check, screen, unestimable).

    The cheapest `_PIPELINE_CHECK_ROWS` go first, so the run that proves
    the submission path costs the least it can.  Everything else follows
    in ascending cost, which is an execution order rather than a budget:
    no row is dropped for not fitting, because there is no cap to fit.

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
    return (estimable[:_PIPELINE_CHECK_ROWS], estimable[_PIPELINE_CHECK_ROWS:],
            unestimable)


# Appended to every batch file, in this order, immediately before Notes.
# Notes is free prose and stays last, so a reader scrolling a row does not
# have to cross it to reach the numbers.
#
# Not "..._At_30_Iter" any more: the iteration count is per row, so the
# name would pin a number only some rows use.
_COST_COLUMNS = [
    "Est_QPU_Time_Per_Iter_S",      # one cost-function evaluation
    "Est_QPU_Time_S",               # x the row's own Eval_Budget
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
                f"{cost / _eval_budget(row):.3f}" if cost is not None else ""
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

    pipeline_check, screen, unestimable = split_into_batches(rows, per_row_seconds)

    classical_only = [r for r in rows if is_classical_only(r)]
    if classical_only:
        out_path = _OUT_DIR / "batch0_classical_only.csv"
        _write_csv(out_path, classical_only, per_row_seconds)
        print(f"  {out_path.name}: {len(classical_only)} rows, 0.00 min "
              f"-- optimization_mode='network', no quantum measurements")

    total_s = 0.0
    for name, batch_rows, purpose in (
        ("batch1_pipeline_check", pipeline_check,
         "cheapest row, run first to prove the submission path"),
        ("batch2_screen", screen, "the rest of the stage-1 screen"),
    ):
        if not batch_rows:
            continue
        batch_s = sum(per_row_seconds[int(r["Case_ID"])] for r in batch_rows)
        total_s += batch_s
        out_path = _OUT_DIR / f"{name}.csv"
        _write_csv(out_path, batch_rows, per_row_seconds)
        print(f"  {out_path.name}: {len(batch_rows)} rows, "
              f"{batch_s / 60:.2f} min -- {purpose}")

    stage1 = STAGE_ALLOCATION_MIN["stage 1"]
    print(f"\n  stage 1 costs {total_s / 60:.2f} min of the {stage1} allotted it, "
          f"and {100 * total_s / 60 / CAMPAIGN_BUDGET_MIN:.0f}% of the "
          f"{CAMPAIGN_BUDGET_MIN} minute campaign")
    if total_s / 60 > stage1:
        print(f"  OVER its allocation by {total_s / 60 - stage1:.2f} min -- "
              f"either take a combination out of STAGE1_HARDWARE or move the "
              f"minutes from stage 2 deliberately")
    for phase, minutes in STAGE_ALLOCATION_MIN.items():
        print(f"    {phase:9} {minutes:>4} min")

    if unestimable:
        out_path = _OUT_DIR / "batch3_unmeasured.csv"
        _write_csv(out_path, unestimable, per_row_seconds)
        print(f"  {out_path.name}: {len(unestimable)} rows -- no measurement count")


if __name__ == "__main__":
    main()
