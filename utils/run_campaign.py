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
# Statuses taken to mean "still going", used only to decide whether a
# still-pending task is worth remarking on.  Nothing is ever declared
# finished on the strength of this set -- see TERMINAL_STATUSES.
#
# "new" is confirmed against Cebule and is the one that matters most: it
# means the task is queued and has NOT yet been assigned a core.  So the
# per-status counts printed below separate work that is waiting for
# capacity from work that is actually running, which is the difference
# between a queue that is merely long and one that is not moving -- and
# the number to watch when choosing --max-processors.  The rest are
# unconfirmed near neighbours, here so that a plausible spelling does not
# raise a false alarm.
_ACTIVE_STATUSES_CONFIRMED = frozenset({"new"})
_EXPECTED_ACTIVE_STATUSES = _ACTIVE_STATUSES_CONFIRMED | frozenset({
    "queued", "running", "pending", "created", "started", "submitted",
    "in_progress", "processing", "waiting",
})


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
    """The runs matching every --where COLUMN=VALUE, in file order.

    The separator is ONE `=`, and a second one is caught rather than
    matched against.  `--where Ansatz==UCCSD` otherwise partitions into
    ("Ansatz", "=UCCSD"), which matches nothing and reports "nothing
    matches" while listing UCCSD among the values present -- the right
    answer with no indication of why it was not found.
    """
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
        if value.startswith("="):
            raise SystemExit(
                f"--where {pair}: the separator is a single '='. Did you "
                f"mean --where {column}={value.lstrip('=')}?"
            )
        matched = [r for r in selected if r[column] == value]
        if not matched:
            # Which values are present is reported for the SELECTION so
            # far, not for the whole file, because with several --where
            # flags the useful question is what this one had left to
            # match against.  A value that exists in the file but not in
            # the selection means the filters conflict, which the second
            # line says outright.
            here = sorted({r[column] for r in selected})
            message = [
                f"--where {pair}: nothing matches. Values present for "
                f"{column} in the {len(selected)} runs selected so far: "
                + ", ".join(here)
            ]
            if value in {r[column] for r in runs}:
                message.append(
                    f"  {value!r} does exist in {len(runs)} rows of the file, "
                    f"so it is the combination of --where flags that is empty, "
                    f"not this one on its own."
                )
            raise SystemExit("\n".join(message))
        selected = matched
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
        "--forget-pending", action="append", default=[], metavar="CASE_ID",
        help="treat these in-flight Case_IDs as ended whatever status they "
             "report, moving them out of pending. For a task you cancelled "
             "whose status this script does not recognise. Repeatable, and "
             "takes effect on a --collect pass",
    )
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="resubmit runs recorded in <stem>.failed.ndjson, which are "
             "otherwise skipped so a deterministic error is not retried "
             "on every pass",
    )
    parser.add_argument(
        "--max-processors", type=int, default=None, metavar="N",
        help="processors Cebule may give each task. Omitted from the "
             "submission entirely when unset, leaving upstream's own "
             "default rather than pinning one on its behalf",
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

    if args.max_processors is not None and args.max_processors < 1:
        raise SystemExit(
            f"--max-processors must be at least 1; got {args.max_processors}. "
            "Omit it to leave Cebule's own default in place."
        )

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
    forget = set(args.forget_pending)
    unknown_forget = forget - {p["Case_ID"] for p in pending}
    if unknown_forget:
        raise SystemExit(
            f"--forget-pending {', '.join(sorted(unknown_forget))}: not in "
            f"{pending_file.name}. Nothing to forget."
        )
    if forget and not args.collect:
        raise SystemExit("--forget-pending takes effect on a --collect pass")
    # A failure is superseded by anything that happened after it: the run
    # was collected, or it is back in flight.  Without that subtraction a
    # cancelled-then-retried-then-completed run is reported as failed for
    # ever, because the log that records the cancellation is append-only.
    superseded = done | {p["Case_ID"] for p in pending}
    failed = runner.failed_case_ids(results, superseded)
    if args.retry_failed:
        failed = set()
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
        unfinished: collections.Counter[str] = collections.Counter()
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
            elif status in runner.TERMINAL_STATUSES or case in forget:
                # Terminal without a result: an error, a cancellation, or a
                # Case_ID named by --forget-pending. All three end the same
                # way -- the task will never produce a result, so it moves
                # out of pending rather than being polled forever.
                runner.append_failure(results, entry, status, error)
                failed.add(case)
                errored += 1
                verb = "FORGOT" if case in forget else "ENDED"
                print(f"  {verb} {case}: status {status!r}"
                      + (f": {error}" if error else ""))
            else:
                unfinished[status] += 1
                still_pending.append(entry)
        runner.write_pending(pending_file, still_pending)
        pending = still_pending
        print(f"\ncollected {collected}, {errored} ended without a result, "
              f"{len(pending)} still in flight")
        # Which statuses the still-pending tasks report, so a task stuck on
        # a status this script does not recognise as terminal is VISIBLE
        # rather than silently polled forever.  A cancellation whose
        # spelling is not in TERMINAL_STATUSES shows up here, and the fix
        # is to add it there -- or to pass --forget-pending for a one-off.
        if unfinished:
            print("  still-pending statuses: "
                  + ", ".join(f"{status!r} x{n}"
                              for status, n in sorted(unfinished.items())))
            if unfinished.get("new"):
                print(f"  {unfinished['new']} of those are 'new': queued, with "
                      f"no core assigned yet.")
            unknown = set(unfinished) - _EXPECTED_ACTIVE_STATUSES
            if unknown:
                print(f"  {', '.join(repr(s) for s in sorted(unknown))} is not a "
                      f"status this script knows to mean 'still running'. If the "
                      f"task is over, --forget-pending CASE_ID clears it.")
        print()
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
            args.backend, args.max_processors,
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
