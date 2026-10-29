"""Price the reduced hardware plans from the noisy-simulator mirrors.

Requires: pip install 'qpubench[qiskit]'.

For each run in hardware_runs.csv, finds its readout-corrected mirrors on
the noisy simulator (`--backend`, default fake_berlin) at the planned shots,
takes the sweep at which the longest cold-start mirror converged, and
prices four plans on `--device` (default: the campaign's PRICING_DEVICE,
with its PRICING_CALIBRATION and PRICING_SHOT_TIME_US) with
utils/estimate_ibm_cost.py's job model, from the mirrors' recorded calls.
A warm start with no mirror on `--backend` takes one from another noisy
simulator, and says so.

  as defined   every run at its own sweep count
  B            every run optimised from scratch, stopped where it converged
  C            VQE runs as 10 evaluations at the noiseless optimum; TN-VQE
               runs warm-started, for as many sweeps as their warm-start
               mirror needed (2 assumed where none is collected yet)
  D            every run warm-started, VQE included (1 sweep assumed for
               VQE where no warm-start mirror is collected yet)

A run counts as converged at the first sweep whose exact energy is within
`--tol` of its plateau, the median over the second half of the run.

Run:
    PYTHONPATH=src python campaigns/ibm_tn-vqe_qesem/price_plans.py
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import pathlib
import statistics
import sys

_REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "utils"))

import _campaign  # noqa: E402
import estimate_ibm_cost as cost  # noqa: E402

# What a hardware run is, apart from where, how long and from where it starts.
_IGNORE = {"Case_ID", "Stage", "Notes", "Backend_Platform", "Error_Mitigation", "Shots",
           "Iterations", "Quantum_Eval_Budget", "Qiskit_Version", "Repeats_Case_ID",
           "Cost_Evals_Per_Iteration", "Opt_Options", "Phi_Init",
           "Converged_Params_File", "Converged_Params_SHA256", "Reduce_Job_Submissions"}
_VQE_EVALUATIONS = 10
_ASSUMED_WARM_SWEEPS = {"VQE": 1, "TN-VQE": 2}


def converged_sweep(energies: list[float], fci: float, tol_mha: float) -> tuple[int, float]:
    """(first sweep within tol of the plateau, plateau in mHa above FCI)."""
    errors = [(e - fci) * 1e3 for e in energies]
    plateau = statistics.median(errors[len(errors) // 2:])
    return next(k for k in range(1, len(errors)) if abs(errors[k] - plateau) <= tol_mha), plateau


def calls(record: dict, sweeps: int) -> dict:
    """A stand-in record of the calls up to the end of `sweeps` sweeps: the
    circuits each sent, and the batch each went out in."""
    end = record["iteration_boundaries"][sweeps]
    return {"circuits_measured": record["circuits_measured"][:end],
            "batch_sizes": (record.get("batch_sizes") or [])[:end] or None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", default=None,
                        help="price on this device instead, at its own snapshot and rep_delay")
    parser.add_argument("--backend", default="fake_berlin",
                        help="the noisy simulator whose mirrors set the sweep counts")
    parser.add_argument("--fci", type=float, default=-1.151683, help="H2/6-31g FCI (Ha)")
    parser.add_argument("--tol", type=float, default=0.5, help="convergence tolerance (mHa)")
    parser.add_argument("--rep-delay", type=float, default=None, metavar="US")
    parser.add_argument("--tups-shots", type=int, default=None,
                        help="price plans B and C with the tUPS runs at these shots")
    args = parser.parse_args()

    campaign = _campaign.load("ibm_tn-vqe_qesem")
    matrix = list(csv.DictReader(open(campaign.CSV)))
    hardware = list(csv.DictReader(open(campaign.HARDWARE_CSV)))
    results = campaign.RESULTS_DIR / f"{campaign.CSV.stem}.ndjson"
    records = {str(r["Case_ID"]): r for r in map(json.loads, results.read_text().splitlines())}
    if args.device is None:
        device = campaign.PRICING_DEVICE
        calibration = getattr(campaign, "PRICING_CALIBRATION", device)
        shot_time_us = getattr(campaign, "PRICING_SHOT_TIME_US", None)
    else:
        device, calibration, shot_time_us = args.device, args.device, None
    shot_time = shot_time_us * 1e-6 if shot_time_us is not None else None
    rep_delay = (args.rep_delay * 1e-6 if args.rep_delay is not None
                 else cost.default_rep_delay(calibration))
    key_columns = [c for c in matrix[0] if c not in _IGNORE]

    def mirrors(h: dict[str, str], warm: bool, backend: str | None = None,
                ) -> list[dict[str, str]]:
        """Collected readout-corrected mirrors of `h` on `backend` (any noisy
        simulator if None), shortest first."""
        return sorted(
            (r for r in matrix
             if (r["Backend_Platform"] == backend if backend
                 else r["Backend_Platform"].startswith("fake_"))
             and r["Error_Mitigation"] != "none"
             and r["Shots"] == h["Shots"] and bool(r["Converged_Params_File"]) == warm
             and all(r[c] == h[c] for c in key_columns)
             and records.get(r["Case_ID"], {}).get("sweep_energies")),
            key=lambda r: int(r["Iterations"]))

    plans: dict[str, list[tuple[dict[str, str], dict]]] = {
        "As defined": [], "B": [], "C": [], "D": []}
    for h in hardware:
        cold = mirrors(h, warm=False, backend=args.backend)
        if not cold:
            raise SystemExit(f"hardware case {h['Case_ID']}: no collected {args.backend} mirror")
        longest, planned = records[cold[-1]["Case_ID"]], int(h["Iterations"])
        sweeps, plateau = converged_sweep(longest["sweep_energies"], args.fci, args.tol)
        print(f"hardware case {h['Case_ID']} ({h['Ansatz']} {h['Ansatz_Reps']}, {h['Method']}): "
              f"converged at sweep {sweeps}, plateau {plateau:.2f} mHa (case {cold[-1]['Case_ID']})")

        def covering(k: int) -> dict:
            """The jobs of k sweeps: from a batched mirror that ran that long
            if there is one, the way the device will run them."""
            batched = [r for r in cold if r["Reduce_Job_Submissions"] == "true"
                       and len(records[r["Case_ID"]]["sweep_energies"]) - 1 >= k]
            if batched:
                print(f"  {k} sweep(s) priced from batched case {batched[-1]['Case_ID']}")
                return calls(records[batched[-1]["Case_ID"]], k)
            return calls(longest, k)

        plans["As defined"].append((h, covering(min(planned, len(longest["sweep_energies"]) - 1))))
        plans["B"].append((h, covering(sweeps)))

        warm = mirrors(h, warm=True, backend=args.backend) or mirrors(h, warm=True)
        if warm:
            record = records[warm[-1]["Case_ID"]]
            warm_sweeps, plateau = converged_sweep(record["sweep_energies"], args.fci, args.tol)
            print(f"  warm start (case {warm[-1]['Case_ID']}, {warm[-1]['Backend_Platform']}): "
                  f"converged at sweep {warm_sweeps}, "
                  f"plateau {plateau:.2f} mHa")
            warm_calls = calls(record, warm_sweeps)
        else:
            assumed = _ASSUMED_WARM_SWEEPS[h["Method"]]
            print(f"  no warm-start mirror collected; assuming {assumed} sweep(s)")
            warm_calls = calls(longest, assumed)
        plans["D"].append((h, warm_calls))
        if h["Method"] == "VQE":
            per_call = next(n for n in longest["circuits_measured"] if n > 0)
            plans["C"].append((h, {"circuits_measured": [per_call] * _VQE_EVALUATIONS}))
        else:
            plans["C"].append((h, warm_calls))

    for name, plan in plans.items():
        rows = [dict(h, Quantum_Eval_Budget=str(len(stand_in["circuits_measured"])))
                for h, stand_in in plan]
        if args.tups_shots and name != "As defined":
            rows = [dict(r, Shots=str(args.tups_shots)) if r["Ansatz"] == "tUPS" else r
                    for r in rows]
        stand_ins = {h["Case_ID"]: stand_in for h, stand_in in plan}
        with contextlib.redirect_stdout(io.StringIO()):
            priced = cost.estimate_full_csv_study(rows, campaign, calibration,
                                                  campaign.HARDWARE_CSV, rep_delay, stand_ins,
                                                  shot_time_s=shot_time)
        print(f"\n{name}: {sum(s for *_, s in priced) / 3600:.1f} h on {device}")
        for row, jobs, circuits, _, seconds in priced:
            print(f"  case {row['Case_ID']}: {jobs:4d} jobs x {circuits:4.1f} circuits "
                  f"at {int(row['Shots']) // 1000}k shots  {seconds / 3600:5.2f} h")


if __name__ == "__main__":
    main()
