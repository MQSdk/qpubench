"""Run a campaign stage in batches, checkpointing after every run.

Built for stage 0, which is 1152 simulated runs and therefore not
something to start in one go and hope: batches let a slice be run,
inspected and resumed.  It takes any of the campaign's CSV files, so the
stage-1 batches go through the same path.

Requires: `pip install 'qpubench[cebule]'` to submit.  A dry run needs
only numpy and this repository, and is the default -- nothing is sent
without `--submit`.

    # what batches are there, and how big
    PYTHONPATH=src python utils/run_campaign.py --group-by Molecule,Basis,Mapper

    # build and validate every input, sending nothing
    PYTHONPATH=src python utils/run_campaign.py

    # run one chemistry cell for real
    PYTHONPATH=src python utils/run_campaign.py --submit \\
        --where Molecule=H2 --where Basis=6-31g --where Mapper=JW

    # prove the path first: one run, then stop
    PYTHONPATH=src python utils/run_campaign.py --submit --limit 1

Resuming is automatic and needs no flag.  Every finished run is appended
to `results/<csv stem>.ndjson` as one line, and a later pass skips every
Case_ID already there -- so an interrupted batch is resumed by repeating
the command, and re-running a completed batch does nothing.

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
        help="actually submit. Without it every input is built and validated "
             "and nothing is sent",
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
    done = runner.completed_case_ids(results)
    batch = args.csv.stem

    print(f"file:     {args.csv.name}")
    print(f"selected: {len(selected)} of {len(runs)} runs"
          + (f"   ({', '.join(args.where)})" if args.where else ""))
    print(f"backends: {', '.join(sorted(backends))}"
          + ("   (PURCHASED QPU TIME)" if hardware else "   (simulated)"))
    print(f"done:     {len(done & {r['Case_ID'] for r in selected})} of these "
          f"already in {results.relative_to(runner.REPO)}")
    print(f"submit:   {args.submit}"
          + ("" if args.submit else "   (dry run: inputs are built, nothing is sent)"))
    print()

    session = runner.open_session() if args.submit else None
    taken = skipped_done = unbuildable = 0

    for run in selected:
        case = run["Case_ID"]
        # Tested per run at the moment the decision is made, against a set
        # this loop keeps current, so an interrupted pass resumed by
        # repeating the command never re-submits a finished run.
        if case in done:
            skipped_done += 1
            continue
        # Counted on a dry run too, so that `--limit 1` previews exactly the
        # run `--submit --limit 1` would send.
        if args.limit is not None and taken >= args.limit:
            print(f"stopping after {taken} run(s), as --limit asked")
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

        print(f"  submitting {case}: {label} ...", end=" ", flush=True)
        result, wall_s, task_id = runner.submit_run(
            session, run, task_input, f"{batch}-case{case}",
        )
        runner.append_record(
            results, run, result, task_id, wall_s, batch, args.backend,
        )
        done.add(case)
        print(f"E = {result.vqe_energy:.6f} Ha, {wall_s:.1f} s wall clock")

    verb = "submitted" if args.submit else "would be submitted"
    print(f"\n{taken} {verb} this pass, {skipped_done} already done and "
          f"skipped, {unbuildable} unbuildable")
    remaining = len([r for r in selected if r["Case_ID"] not in done])
    if remaining:
        print(f"{remaining} of the selection still to run -- repeat the same "
              f"command to continue")


if __name__ == "__main__":
    main()
