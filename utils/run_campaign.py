"""Run a campaign stage in batches: submit many, collect later.

Built for stage 0, which is 1152 simulated runs and therefore not
something to start in one go and hope: batches let a slice be run,
inspected and resumed.  It takes any of the campaign's CSV files, so the
stage-1 batches go through the same path.

SUBMISSION AND COLLECTION ARE SEPARATE, and that is the point.  Cebule
dispatches to outside HPC infrastructure, so a task spends most of its
life queued rather than running.  Submitting one and blocking until it
returns spends that queue time doing nothing, in the one process that
could have been submitting the rest -- 1152 runs done that way is a
serial sum of queue times.  So `--submit` creates tasks and returns, and
`--collect` harvests whatever has finished since.

Requires: `pip install 'qpubench[cebule]'` to submit.  A dry run needs
only numpy and this repository, and is the default -- nothing is sent
without `--submit`.

    # what batches are there, and how big
    PYTHONPATH=src python utils/run_campaign.py --group-by Molecule,Basis,Mapper

    # build and validate every input, sending nothing
    PYTHONPATH=src python utils/run_campaign.py

    # send one chemistry cell, all at once, and return
    PYTHONPATH=src python utils/run_campaign.py --submit \\
        --where Molecule=H2 --where Basis=6-31g --where Mapper=JW

    # later, as often as you like: harvest whatever has finished
    PYTHONPATH=src python utils/run_campaign.py --collect

    # keep at most 50 tasks queued, topping up as they land
    PYTHONPATH=src python utils/run_campaign.py --collect --submit --max-in-flight 50

    # prove the path first: one run, then stop
    PYTHONPATH=src python utils/run_campaign.py --submit --limit 1

Three files carry the state, all beside each other under `results/`:

    <stem>.ndjson           finished runs, one JSON line each
    <stem>.pending.ndjson   task ids submitted and not yet collected
    <stem>.failed.ndjson    tasks that came back with status 'error'

Resuming needs no flag.  A run is skipped if it is in any of the three,
so repeating a command never double-submits and never re-collects.  A
failure stays failed until `--retry-failed` says otherwise, so a
deterministic error is not resubmitted on every pass.

WHICH BACKEND A RUN USES IS THE RUN'S OWN `Backend_Platform`, not a
choice made here.  Stage 0 crosses the backend as a factor, half its rows
on `aer_simulator` and half on `fake_aachen`, so overriding it would run
one arm twice and the other never.  `--backend` exists for the one case
the column cannot express -- executing a hardware-targeted stage-1 row on
a simulator first -- and hardware is refused unless `--allow-hardware`
says otherwise, because a stage-0 row costed at nothing would be billed
like anything else.
"""
from __future__ import annotations

import argparse
import collections
import csv
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _campaign_runner as runner

_DEFAULT_CSV = runner.CAMPAIGN / "stage0_simulator_screen.csv"
# get_backend routes anything prefixed 'ibm' to real hardware.
_HARDWARE_PREFIX = "ibm"


def _load(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Regenerate it with:\n"
            f"    PYTHONPATH=src python utils/build_benchmark_matrix.py --stage 0"
        )
    with path.open() as f:
        return list(csv.DictReader(f))


def _select(
    runs: list[dict[str, str]], filters: list[str],
) -> list[dict[str, str]]:
    """The runs matching every --where COLUMN=VALUE, in file order."""
    selected = runs
    for pair in filters:
        column, _, value = pair.partition("=")
        if not value:
            raise SystemExit(f"--where wants COLUMN=VALUE; got {pair!r}")
        if column not in runs[0]:
            raise SystemExit(
                f"--where {column}=...: no such column. Available: "
                + ", ".join(sorted(runs[0]))
            )
        selected = [r for r in selected if r[column] == value]
        if not selected:
            raise SystemExit(
                f"--where {pair}: nothing matches. Values present for "
                f"{column}: " + ", ".join(sorted({r[column] for r in runs}))
            )
    return selected


def _group(runs: list[dict[str, str]], columns: str) -> None:
    """Print the batches one grouping gives, and how big each is."""
    keys = [c.strip() for c in columns.split(",")]
    for key in keys:
        if key not in runs[0]:
            raise SystemExit(
                f"--group-by {key}: no such column. Available: "
                + ", ".join(sorted(runs[0]))
            )
    counts = collections.Counter(tuple(r[k] for k in keys) for r in runs)
    width = max(len(" ".join(v)) for v in counts) + 2
    print(f"{len(counts)} batches over {', '.join(keys)}:\n")
    for value, count in sorted(counts.items()):
        where = " ".join(f"--where {k}={v}" for k, v in zip(keys, value))
        print(f"  {' '.join(value):{width}}{count:>5} runs   {where}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[2:]),
    )
    parser.add_argument(
        "--csv", type=pathlib.Path, default=_DEFAULT_CSV,
        help="campaign file to run (default: the stage-0 simulator screen)",
    )
    parser.add_argument(
        "--where", action="append", default=[], metavar="COLUMN=VALUE",
        help="run only rows matching this. Repeatable; conditions are ANDed",
    )
    parser.add_argument(
        "--group-by", metavar="COLUMN[,COLUMN...]",
        help="print the batches this grouping gives, with the --where flags "
             "that select each, and exit",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="stop after submitting N runs this pass (resume by repeating)",
    )
    parser.add_argument(
        "--submit", action="store_true",
        help="create the tasks and return without waiting for them. Without "
             "it every input is built and validated and nothing is sent",
    )
    parser.add_argument(
        "--collect", action="store_true",
        help="harvest every pending task that has finished, and return. "
             "Combine with --submit to collect first, then top up",
    )
    parser.add_argument(
        "--max-in-flight", type=int, default=None, metavar="N",
        help="submit only enough to bring the pending count up to N. Use it "
             "to keep a steady queue rather than sending everything at once",
    )
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="resubmit runs recorded in <stem>.failed.ndjson, which are "
             "otherwise skipped so a deterministic error is not retried "
             "on every pass",
    )
    parser.add_argument(
        "--backend", default=None, metavar="NAME",
        help="override every run's own Backend_Platform. Read the note above "
             "before using it on a stage that crosses the backend",
    )
    parser.add_argument(
        "--allow-hardware", action="store_true",
        help="permit a backend that bills QPU time. Required for anything "
             "reaching a real device",
    )
    args = parser.parse_args()

    runs = _load(args.csv)
    if args.group_by:
        _group(runs, args.group_by)
        return

    selected = _select(runs, args.where)
    backends = {runner.backend_for(r, args.backend) for r in selected}
    hardware = sorted(b for b in backends if b.startswith(_HARDWARE_PREFIX))
    if hardware and not args.allow_hardware:
        raise SystemExit(
            f"{len(selected)} selected runs resolve to {', '.join(hardware)}, "
            "which bills QPU time. Pass --allow-hardware to mean it, or "
            "--backend aer_simulator to simulate them first."
        )

    results = runner.RESULTS_DIR / f"{args.csv.stem}.ndjson"
    pending_file = runner.pending_path(results)
    batch = args.csv.stem
    by_case = {r["Case_ID"]: r for r in runs}

    done = runner.completed_case_ids(results)
    pending = runner.read_pending(pending_file)
    failed = set() if args.retry_failed else runner.failed_case_ids(results)
    mine = {r["Case_ID"] for r in selected}

    print(f"file:     {args.csv.name}")
    print(f"selected: {len(selected)} of {len(runs)} runs"
          + (f"   ({', '.join(args.where)})" if args.where else ""))
    print(f"backends: {', '.join(sorted(backends))}"
          + ("   (PURCHASED QPU TIME)" if hardware else "   (simulated)"))
    print(f"state:    {len(done & mine)} done, "
          f"{len([p for p in pending if p['Case_ID'] in mine])} in flight, "
          f"{len(failed & mine)} failed"
          + ("" if args.retry_failed else " (skipped; --retry-failed to resend)"))
    if not (args.submit or args.collect):
        print("mode:     dry run -- inputs are built, nothing is sent")
    print()

    session = runner.open_session() if (args.submit or args.collect) else None

    # --- Collect first, so a --collect --submit pass tops up the queue
    # against a pending count that is already current.
    if args.collect and pending:
        still_pending, collected, errored = [], 0, 0
        for entry in pending:
            status, result, error = runner.poll_task(session, entry["task_id"])
            case = entry["Case_ID"]
            if result is not None:
                run = by_case[case]
                elapsed = time.time() - entry["submitted_at"]
                runner.append_record(
                    results, run, result, entry["task_id"], elapsed, batch,
                    args.backend, submitted_at=entry["submitted_at"],
                )
                done.add(case)
                collected += 1
                print(f"  collected {case}: E = {result.vqe_energy:.6f} Ha, "
                      f"{elapsed / 60:.1f} min elapsed")
            elif status in runner.TERMINAL_STATUSES:
                runner.append_failure(results, entry, status, error)
                failed.add(case)
                errored += 1
                print(f"  FAILED {case}: status {status!r}: {error}")
            else:
                still_pending.append(entry)
        runner.write_pending(pending_file, still_pending)
        pending = still_pending
        print(f"\ncollected {collected}, {errored} failed, "
              f"{len(pending)} still in flight\n")
    elif args.collect:
        print("nothing pending to collect\n")

    # --- Submit, without waiting for anything.
    in_flight = {p["Case_ID"] for p in pending}
    room = (
        None if args.max_in_flight is None
        else max(0, args.max_in_flight - len(pending))
    )
    taken = skipped = unbuildable = 0
    # A bare --collect means "harvest and stop": previewing what a submit
    # would send is noise on a pass that was not asked to send anything.
    # With neither flag the preview IS the point, which is the dry run.
    submitting = args.submit or not args.collect

    for run in selected if submitting else []:
        case = run["Case_ID"]
        # Tested per run against sets this loop keeps current, so repeating
        # a command never re-submits a run that is finished, in flight, or
        # recorded as failed.
        if case in done or case in in_flight or case in failed:
            skipped += 1
            continue
        # Counted on a dry run too, so that `--limit 1` previews exactly the
        # run `--submit --limit 1` would send.
        if args.limit is not None and taken >= args.limit:
            print(f"stopping after {taken} run(s), as --limit asked")
            break
        if room is not None and taken >= room:
            print(f"stopping at {args.max_in_flight} in flight, as "
                  f"--max-in-flight asked")
            break

        task_input = runner.build_input(run, args.backend)
        if task_input is None:
            print(f"  skip {case}: {runner.unbuildable_reason(run)}")
            unbuildable += 1
            continue

        label = runner.run_label(run, args.backend)
        taken += 1
        if not args.submit:
            print(f"  would submit {case}: {label}")
            continue

        task_id = runner.submit_task(
            session, run, task_input, f"{batch}-case{case}", results, batch,
            args.backend,
        )
        in_flight.add(case)
        print(f"  submitted {case}: {label}   [{task_id}]")

    if submitting:
        verb = "submitted" if args.submit else "would be submitted"
        print(f"\n{taken} {verb} this pass, {skipped} already done, in flight "
              f"or failed, {unbuildable} unbuildable")

    # The closing tally splits what is outstanding by WHY, because the three
    # need different commands: in-flight wants --collect, failed wants
    # --retry-failed or a look at the failure, and not-started wants the
    # same command again.
    waiting = len(in_flight & mine)
    broken = len(failed & mine)
    unstarted = len(mine - done - in_flight - failed)
    print(f"\n{len(done & mine)}/{len(mine)} collected"
          + (f", {waiting} in flight" if waiting else "")
          + (f", {broken} failed" if broken else "")
          + (f", {unstarted} not started" if unstarted else ""))
    if waiting:
        print("  --collect to harvest the ones in flight")
    if unstarted:
        print("  repeat with --submit to send the rest")
    if broken:
        print(f"  see {runner.failed_path(results).relative_to(runner.REPO)}; "
              f"--retry-failed to resend")


if __name__ == "__main__":
    main()
