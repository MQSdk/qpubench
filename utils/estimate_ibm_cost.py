"""Resource + cost estimator walkthrough: what would a campaign's matrix
actually cost to run on real IBM Quantum hardware, under each of the
four access plans?

Requires: pip install 'qpubench[qiskit]'

Every row that takes quantum measurements is priced as if it ran on the
device, whatever its `Backend_Platform` says, so a simulator row prices
its own hardware repeat.  Rows with `Method="TN"` are skipped: they take
no quantum measurements.

Every call that measures anything is one job, billed

    job overhead + circuits x shots x (rep_delay + circuit duration)

with the device's own default rep_delay (or `--rep-delay`), and the
circuit duration from real transpilation of the row's own ansatz against
the device calibration, at `optimization_level=2` (what TN-VQE's own
`transpile(circuit, backend)` resolves to).

Where the row has a collected run, its jobs are the run's own: the
record's `circuits_measured` gives each call's circuit count, with what
tn-vqe's phi cache served left out, and calls beyond the row's
`Quantum_Eval_Budget` are dropped.  On the pauli path that count is of
Pauli observables, which the runtime measures in fewer bases, so a pauli
job is priced at the qubit-wise-commuting bases of the operator instead.

A row with no run costs `Quantum_Eval_Budget` jobs, each measuring

  grouped   one circuit per XOR pattern of the operator's matrix
            elements, plus one per pattern with imaginary elements --
            tn-vqe's own scheme, counted on the operator itself
  pauli     the runtime's qubit-wise-commuting bases, the row's
            `Num_ExpVals_Per_Iter`

A TN-VQE row measures the network-transformed operator, which has more
terms than H.  Its operator is read off the run's record when there is
one; otherwise grouped rows take the 2^n ceiling and pauli rows the
untransformed count, a floor, and the table marks them.

The device priced against is the campaign's PRICING_DEVICE (see
`_campaign.py`), or `--device`. A device with no offline snapshot can be
transpiled against another's (`--calibration`, or the campaign's
PRICING_CALIBRATION) and given its own measured time per shot
(`--shot-time`, or PRICING_SHOT_TIME_US), which then replaces
rep_delay + circuit duration.

Run:
    PYTHONPATH=src python utils/estimate_ibm_cost.py [--campaign NAME] [--device ibm_...]
        [--platform NAME ...] [--ansatz NAME ...]
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _campaign
from _ansatz_builders import SUPPLIED_ANSATZE, circuit_spec

from qpubench.backends.ibm_cost_estimator import (
    estimate_circuit_resources,
    resolve_calibration_backend,
)
from qpubench.schemas.mirrors.ibm_cost_estimator import (
    CircuitResourceEstimate,
    IBMPricingRates,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_CALIBRATIONS: dict[str, object] = {}


def _calibration(device: str):
    """The device's calibration source, resolved once and reused.

    Offline where qiskit-ibm-runtime ships a snapshot for the device; if
    it has none, this falls back to the live device and the connection
    opens on the first transpile.
    """
    if device not in _CALIBRATIONS:
        _CALIBRATIONS[device] = resolve_calibration_backend(device)
    return _CALIBRATIONS[device]

_DEFAULT_SHOTS = 4096          # for the minimal-case demo, which has no row
# What TN-VQE's own transpile(circuit, backend) resolves to under Qiskit 2.x.
_OPTIMIZATION_LEVEL = 2
# IBM's stated default, for a device whose calibration names none.
_FALLBACK_REP_DELAY_S = 250e-6
# Fixed seconds per job.  The Estimator's default options request a readout
# calibration in every job, measured at 11 s on the device; the Sampler
# behind 'grouped' requests none, leaving IBM's stated ~2 s.
_JOB_OVERHEAD_S = {"pauli": 11.0, "grouped": 2.0}
# Arbitrary non-zero angles: zeros let the transpiler delete rotations and
# cancel the entangling gates between them.
_PHI_PROBE = 0.1234


def _load_csv_cases(csv_path: pathlib.Path) -> list[dict[str, str]]:
    with csv_path.open() as f:
        return [
            row for row in csv.DictReader(f)
            if row["N_Qubit"] and row["Method"] != "TN"
        ]


def default_rep_delay(device: str) -> float:
    """The device's own default rep_delay in seconds. It differs by
    processor family (250 us on Heron, 4 ms on Nighthawk), and it sets
    the cost of every shot."""
    configuration = getattr(_calibration(device), "configuration", None)
    value = getattr(configuration(), "default_rep_delay", None) if configuration else None
    return float(value) if value else _FALLBACK_REP_DELAY_S


def estimate_minimal_open_plan_study(
    device: str, rep_delay_s: float,
) -> CircuitResourceEstimate:
    """A 4-qubit, one-rep EfficientSU2 circuit (the size of H2/sto-3g under
    JW) -- "the minimal possible benchmark study" the Open Plan's free
    quota is sized for."""
    spec = circuit_spec("EfficientSU2", 4, reps=1)
    return estimate_circuit_resources(
        spec, backend_name=device, backend=_calibration(device),
        shots=_DEFAULT_SHOTS, rep_delay_s=rep_delay_s,
        optimization_level=_OPTIMIZATION_LEVEL,
        label="H2/sto-3g/JW EfficientSU2 (minimal case)",
    )


def _supplied_circuit_spec(qasm_path: pathlib.Path, num_qubits: int):
    """A `CircuitSpec` for a SUPPLIED ansatz (UCCSD, tUPS), read from its
    pinned QASM rather than built generically."""
    import numpy as np
    from qiskit import qasm3

    from qpubench.schemas.circuit import CircuitSpec
    from qpubench.schemas.primitives import CircuitFormat

    qc = qasm3.loads((_REPO_ROOT / qasm_path).read_text())
    if qc.num_parameters:
        qc = qc.assign_parameters(np.full(qc.num_parameters, _PHI_PROBE))
    qc.measure_all()
    return CircuitSpec(
        num_qubits=num_qubits, format=CircuitFormat.QASM3, serialized=qasm3.dumps(qc)
    )


def _sparse_pauli_op(labels: list[str], coefficients: list, num_qubits: int):
    """A SparsePauliOp from dense ("IIXZ") or sparse ("X2 Z3") labels."""
    from qiskit.quantum_info import SparsePauliOp

    coefficients = [complex(*c) if isinstance(c, list) else c for c in coefficients]
    if all(len(label) == num_qubits and " " not in label for label in labels) and all(
        set(label) <= set("IXYZ") for label in labels
    ):
        return SparsePauliOp(labels, coefficients)
    terms = []
    for label, c in zip(labels, coefficients):
        factors = label.split()
        terms.append(("".join(f[0] for f in factors), [int(f[1:]) for f in factors], c))
    return SparsePauliOp.from_sparse_list(terms, num_qubits)


def grouped_circuit_count(op, tol: float = 1e-10) -> int:
    """Circuits tn-vqe's grouped scheme measures `op` with: one per XOR
    pattern of its non-zero matrix elements, and one more per pattern
    carrying imaginary elements."""
    import numpy as np

    h = op.to_matrix()
    rows, cols = np.nonzero(np.abs(h) > tol)
    circuits = set()
    for r, c in zip(rows, cols):
        if r > c:
            continue
        if abs(h[r, c].real) > tol:
            circuits.add((r ^ c, False))
        if abs(h[r, c].imag) > tol:
            circuits.add((r ^ c, True))
    return len(circuits)


def qwc_circuit_count(op) -> int:
    """Qubit-wise-commuting bases of `op`, identity excluded (greedy)."""
    op = op.simplify()
    labels = [p.to_label() for p in op.paulis]
    op = op[[i for i, label in enumerate(labels) if set(label) != {"I"}]]
    return len(op.group_commuting(qubit_wise=True)) if len(op) else 0


def _collected_records(campaign, csv_path: pathlib.Path) -> dict[str, dict]:
    """The last collected record per Case_ID, or nothing if none exist."""
    path = campaign.RESULTS_DIR / f"{csv_path.stem}.ndjson"
    if not path.exists():
        return {}
    records = {}
    for line in path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            records[str(record.get("Case_ID"))] = record
    return records


def circuits_per_evaluation(
    row: dict[str, str], campaign, record: dict,
) -> tuple[int, str]:
    """(circuits one evaluation submits, where that count came from)."""
    num_qubits = int(row["N_Qubit"])
    grouped = row["Measurement_Method"] == "grouped"
    count = grouped_circuit_count if grouped else qwc_circuit_count

    if row["Method"] == "TN-VQE":
        if record.get("h_tn_opt_qubit"):
            labels, coefficients = record["h_tn_opt_qubit"]
            return count(_sparse_pauli_op(labels, coefficients, num_qubits)), "run record"
        if grouped:
            return 2 ** num_qubits, "ceiling 2^n"
        return int(row["Num_ExpVals_Per_Iter"]), "floor (untransformed H)"

    if grouped:
        path = campaign.hamiltonian_file(row)
        if path is not None:
            payload = json.loads(path.read_text())
            op = _sparse_pauli_op(payload["h_operators"], payload["h_coeff_values"], num_qubits)
            return count(op), "XOR patterns of H"
        return 2 ** num_qubits, "ceiling 2^n"
    return int(row["Num_ExpVals_Per_Iter"]), row["Num_ExpVals_Source"]


def jobs_from_record(record: dict, max_measuring_calls: int | None = None,
                     ) -> list[tuple[int, int]]:
    """(measuring calls, circuits) per job of a collected run: one job per
    call, or per batch where the run batched them (`batch_sizes`), until
    `max_measuring_calls` calls that measured anything. Calls the phi cache
    served entirely measure nothing and add no job."""
    measured = record["circuits_measured"]
    sizes = record.get("batch_sizes") or [1] * len(measured)
    jobs, i, used = [], 0, 0
    while i < len(measured):
        batch = measured[i:i + max(sizes[i], 1)]
        i += len(batch)
        calls = sum(1 for n in batch if n > 0)
        if not calls:
            continue
        if max_measuring_calls is not None and used + calls > max_measuring_calls:
            break
        jobs.append((calls, sum(batch)))
        used += calls
    return jobs


def _record_for(
    row: dict[str, str], records: dict, twin_records: dict,
) -> tuple[dict, str]:
    """(the row's own run, or else the run of the row it repeats; a label
    saying which)."""
    if row["Case_ID"] in records:
        return records[row["Case_ID"]], ""
    twin = row.get("Repeats_Case_ID", "")
    if twin in twin_records:
        return twin_records[twin], f" (case {twin})"
    return {}, ""


def estimate_full_csv_study(
    rows: list[dict[str, str]], campaign, device: str, csv_path: pathlib.Path,
    rep_delay_s: float, records: dict[str, dict] | None = None,
    shot_time_s: float | None = None,
) -> list[tuple[dict[str, str], int, float, str, float]]:
    """(row, jobs, circuits per job, count source, QPU seconds) per row.

    `device` is the calibration transpiled against. `records`, by Case_ID,
    stands in for the collected runs, for pricing a run cut short or
    otherwise changed. `shot_time_s`, where given, is the device's time
    per shot in place of rep_delay + circuit duration.

    Transpiles are cached per distinct circuit; the measurement basis
    change adds a few gates against the rep_delay, so it is left out.
    """
    cache: dict[tuple, CircuitResourceEstimate] = {}
    if records is None:
        records = _collected_records(campaign, csv_path)
        twin_records = _collected_records(campaign, campaign.CSV)
    else:
        twin_records = {}
    priced = []
    for row in rows:
        ansatz = row["Ansatz"]
        num_qubits = int(row["N_Qubit"])
        reps = int(row["Ansatz_Reps"])
        num_electrons = int(row["Active_Electrons"])
        shots = int(row["Shots"])

        key = (ansatz, num_qubits, reps, num_electrons, row["Qasm_Ansatz_File"])
        if key not in cache:
            if ansatz in SUPPLIED_ANSATZE:
                spec = _supplied_circuit_spec(
                    pathlib.Path(row["Qasm_Ansatz_File"]), num_qubits,
                )
            else:
                spec = circuit_spec(ansatz, num_qubits, reps=reps, num_electrons=num_electrons)
            cache[key] = estimate_circuit_resources(
                spec, backend_name=device, backend=_calibration(device),
                shots=1, optimization_level=_OPTIMIZATION_LEVEL,
                label=f"{ansatz}, {num_qubits}q, {reps} reps",
            )
        duration = cache[key].circuit_duration_s

        overhead = _JOB_OVERHEAD_S[row["Measurement_Method"]]
        per_shot = shot_time_s if shot_time_s is not None else rep_delay_s + duration
        per_circuit = shots * per_shot
        record, whose = _record_for(row, records, twin_records)
        measured = record.get("circuits_measured")
        if measured:
            jobs = jobs_from_record(record, int(row["Quantum_Eval_Budget"]))
            batched = bool(record.get("batch_sizes")) and any(c > 1 for c, _ in jobs)
            if row.get("Reduce_Job_Submissions") == "true" and not batched:
                whose += ", unbatched"
            if row["Measurement_Method"] == "grouped":
                circuits = sum(n for _, n in jobs) / len(jobs)
                source = "run metadata" + whose
            else:
                per_call, source = circuits_per_evaluation(row, campaign, record)
                circuits = per_call * sum(c for c, _ in jobs) / len(jobs)
                source = "run jobs, QWC bases" + whose
            num_jobs = len(jobs)
        else:
            circuits, source = circuits_per_evaluation(row, campaign, record)
            num_jobs = int(row["Quantum_Eval_Budget"])
        seconds = num_jobs * (overhead + circuits * per_circuit)
        if row["Error_Mitigation"] == "readout_tensored":
            # One calibration job: every qubit in |0>, then every qubit in |1>.
            seconds += overhead + 2 * shots * (
                shot_time_s if shot_time_s is not None else rep_delay_s)
        priced.append((row, num_jobs, circuits, source, seconds))
    print(f"  ({len(cache)} distinct circuits really transpiled; "
          f"the rest reused from cache)")
    return priced


def _print_plan_breakdown(total_seconds: float, rates: IBMPricingRates) -> None:
    from qpubench.schemas.mirrors.ibm_cost_estimator import estimate_all_plans

    for plan, breakdown in estimate_all_plans(total_seconds, rates).items():
        cost = f"${breakdown.cost_usd:,.2f}" if breakdown.cost_usd is not None else "n/a"
        print(f"  {plan.value:16s} {cost:>14s}   {breakdown.notes[0] if breakdown.notes else ''}")


def _print_rows(priced: list[tuple[dict[str, str], int, float, str, float]]) -> None:
    print(f"  {'Case':>4} {'Platform':14} {'Ansatz':16} {'Method':7} {'Optimizer':16}"
          f"{'Shots':>8} {'Jobs':>6} {'Circ':>5}  {'source':24}{'QPU h':>8}")
    for row, jobs, circuits, source, seconds in priced:
        ansatz = f"{row['Ansatz']} x{row['Ansatz_Reps']}"
        print(f"  {row['Case_ID']:>4} {row['Backend_Platform']:14} {ansatz:16} "
              f"{row['Method']:7} {row['Optimizer']:16}{int(row['Shots']):>8,} "
              f"{jobs:>6} {circuits:>5.1f}  {source:24}"
              f"{seconds / 3600:>8.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    _campaign.add_argument(parser)
    parser.add_argument(
        "--device", default=None, metavar="NAME",
        help="IBM device to price against (default: the campaign's PRICING_DEVICE)",
    )
    parser.add_argument(
        "--calibration", default=None, metavar="NAME",
        help="device whose calibration to transpile against, for a device with no "
             "offline snapshot (default: the campaign's PRICING_CALIBRATION, else --device)",
    )
    parser.add_argument(
        "--rep-delay", type=float, default=None, metavar="US",
        help="rep_delay in microseconds (default: the device's own default)",
    )
    parser.add_argument(
        "--shot-time", type=float, default=None, metavar="US",
        help="the device's time per shot in microseconds, replacing rep_delay + "
             "circuit duration (default: the campaign's PRICING_SHOT_TIME_US, if set)",
    )
    parser.add_argument(
        "--csv", type=pathlib.Path, default=None,
        help="price this matrix instead of the campaign's own CSV",
    )
    parser.add_argument(
        "--platform", action="append", metavar="NAME",
        help="price only rows with this Backend_Platform (repeatable)",
    )
    parser.add_argument(
        "--ansatz", action="append", metavar="NAME",
        help="price only rows with this Ansatz (repeatable)",
    )
    args = parser.parse_args()
    campaign = _campaign.load(args.campaign)
    csv_path = args.csv or campaign.CSV
    device = args.device or getattr(campaign, "PRICING_DEVICE", None)
    if device is None:
        raise SystemExit("name a device with --device; the campaign sets no PRICING_DEVICE")
    calibration = args.calibration or (
        getattr(campaign, "PRICING_CALIBRATION", None) if args.device is None else None
    ) or device
    shot_time_us = args.shot_time if args.shot_time is not None else (
        getattr(campaign, "PRICING_SHOT_TIME_US", None) if args.device is None else None)
    shot_time_s = shot_time_us * 1e-6 if shot_time_us is not None else None

    print(f"Pricing {csv_path.resolve().relative_to(_REPO_ROOT)} against {device}"
          + (f", transpiled against {calibration}'s calibration" if calibration != device else "")
          + ".\n")

    print("=== Minimal possible benchmark study (H2/sto-3g/JW, 1 circuit) ===")
    rep_delay_s = (args.rep_delay * 1e-6 if args.rep_delay is not None
                   else default_rep_delay(calibration))
    if shot_time_s is not None:
        print(f"{shot_time_us:,.2f} us per shot (set), in place of rep_delay + circuit duration\n")
    else:
        print(f"rep_delay {rep_delay_s * 1e6:,.0f} us"
              + (" (set)" if args.rep_delay is not None else " (the device default)") + "\n")
    minimal = estimate_minimal_open_plan_study(calibration, rep_delay_s)
    minimal_s = (minimal.estimated_qpu_time_s if shot_time_s is None
                 else minimal.per_sub_job_overhead_s + _DEFAULT_SHOTS * shot_time_s)
    print(f"  {minimal.num_qubits} qubits, depth={minimal.depth}, "
          f"{minimal.two_qubit_gate_count} 2Q gates, "
          f"estimated QPU time = {minimal_s:.3f}s")
    _print_plan_breakdown(minimal_s, IBMPricingRates.default())

    rows = [
        row for row in _load_csv_cases(csv_path)
        if (not args.platform or row["Backend_Platform"] in args.platform)
        and (not args.ansatz or row["Ansatz"] in args.ansatz)
    ]
    print(f"\n=== {len(rows)} measuring rows, each at its run's jobs or its Quantum_Eval_Budget, "
          f"priced as hardware runs ===")
    priced = estimate_full_csv_study(rows, campaign, calibration, csv_path, rep_delay_s,
                                     shot_time_s=shot_time_s)
    _print_rows(priced)
    total = sum(seconds for *_, seconds in priced)
    print(f"\n  {total:,.0f}s ({total / 3600:,.1f} h) total QPU time")
    _print_plan_breakdown(total, IBMPricingRates.default())


if __name__ == "__main__":
    main()
