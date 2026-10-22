"""Price the reduced hardware plans from the noisy-simulator mirrors.

Requires: pip install 'qpubench[qiskit]'.

For each run in hardware_runs.csv, finds its readout-corrected mirrors on
the noisy simulator (`--backend`, default fake_aachen) at the planned shots,
takes the sweep at which the longest cold-start mirror converged, and
prices three plans on `--device` with utils/estimate_ibm_cost.py's job
model, from the mirrors' recorded calls:

  as defined   every run at its own sweep count
  B            every run optimised from scratch, stopped where it converged
  C            VQE runs as 10 evaluations at the noiseless optimum; TN-VQE
               runs warm-started, for as many sweeps as their warm-start
               mirror needed (2 assumed where none is collected yet)

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
           "Converged_Params_File", "Converged_Params_SHA256"}
_VQE_EVALUATIONS = 10
_ASSUMED_WARM_SWEEPS = 2


def converged_sweep(energies: list[float], fci: float, tol_mha: float) -> tuple[int, float]:
    """(first sweep within tol of the plateau, plateau in mHa above FCI)."""
    errors = [(e - fci) * 1e3 for e in energies]
    plateau = statistics.median(errors[len(errors) // 2:])
    return next(k for k in range(1, len(errors)) if abs(errors[k] - plateau) <= tol_mha), plateau


def calls(record: dict, sweeps: int) -> list[int]:
    """Circuits sent by each call up to the end of `sweeps` sweeps."""
    return record["circuits_measured"][:record["iteration_boundaries"][sweeps]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", default="ibm_aachen")
    parser.add_argument("--backend", default="fake_aachen",
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
    rep_delay = (args.rep_delay * 1e-6 if args.rep_delay is not None
                 else cost.default_rep_delay(args.device))
    key_columns = [c for c in matrix[0] if c not in _IGNORE]

    def mirrors(h: dict[str, str], warm: bool) -> list[dict[str, str]]:
        return sorted(
            (r for r in matrix
             if r["Backend_Platform"] == args.backend and r["Error_Mitigation"] != "none"
             and r["Shots"] == h["Shots"] and bool(r["Converged_Params_File"]) == warm
             and all(r[c] == h[c] for c in key_columns)
             and records.get(r["Case_ID"], {}).get("sweep_energies")),
            key=lambda r: int(r["Iterations"]))

    plans: dict[str, list[tuple[dict[str, str], list[int]]]] = {
        "As defined": [], "B": [], "C": []}
    for h in hardware:
        cold = mirrors(h, warm=False)
        if not cold:
            raise SystemExit(f"hardware case {h['Case_ID']}: no collected {args.backend} mirror")
        longest, planned = records[cold[-1]["Case_ID"]], int(h["Iterations"])
        sweeps, plateau = converged_sweep(longest["sweep_energies"], args.fci, args.tol)
        print(f"hardware case {h['Case_ID']} ({h['Ansatz']} {h['Ansatz_Reps']}, {h['Method']}): "
              f"converged at sweep {sweeps}, plateau {plateau:.2f} mHa (case {cold[-1]['Case_ID']})")
        plans["As defined"].append((h, calls(longest, min(planned, len(longest["sweep_energies"]) - 1))))
        plans["B"].append((h, calls(longest, sweeps)))

        if h["Method"] == "VQE":
            per_call = next(n for n in longest["circuits_measured"] if n > 0)
            plans["C"].append((h, [per_call] * _VQE_EVALUATIONS))
            continue
        warm = mirrors(h, warm=True)
        if warm:
            record = records[warm[-1]["Case_ID"]]
            warm_sweeps, plateau = converged_sweep(record["sweep_energies"], args.fci, args.tol)
            print(f"  warm start (case {warm[-1]['Case_ID']}): converged at sweep {warm_sweeps}, "
                  f"plateau {plateau:.2f} mHa")
            plans["C"].append((h, calls(record, warm_sweeps)))
        else:
            print(f"  no warm-start mirror collected; assuming {_ASSUMED_WARM_SWEEPS} sweeps")
            plans["C"].append((h, calls(longest, _ASSUMED_WARM_SWEEPS)))

    for name, plan in plans.items():
        rows = [dict(h, Quantum_Eval_Budget=str(len(measured))) for h, measured in plan]
        if args.tups_shots and name != "As defined":
            rows = [dict(r, Shots=str(args.tups_shots)) if r["Ansatz"] == "tUPS" else r
                    for r in rows]
        stand_in = {h["Case_ID"]: {"circuits_measured": measured} for h, measured in plan}
        with contextlib.redirect_stdout(io.StringIO()):
            priced = cost.estimate_full_csv_study(rows, campaign, args.device,
                                                  campaign.HARDWARE_CSV, rep_delay, stand_in)
        print(f"\n{name}: {sum(s for *_, s in priced) / 3600:.1f} h on {args.device}")
        for row, jobs, circuits, _, seconds in priced:
            print(f"  case {row['Case_ID']}: {jobs:4d} jobs x {circuits:4.1f} circuits "
                  f"at {int(row['Shots']) // 1000}k shots  {seconds / 3600:5.2f} h")


if __name__ == "__main__":
    main()
