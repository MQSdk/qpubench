"""Resource + cost estimator walkthrough: what would a campaign's matrix
actually cost to run on real IBM Quantum hardware, under each of the
four access plans?

Requires: pip install 'qpubench[qiskit]'

Every row that takes quantum measurements is priced as if it ran on the
device, whatever its `Backend_Platform` says, so a simulator row prices
its own hardware repeat.  Rows with `Method="TN"` are skipped: they take
no quantum measurements.

One row costs `Quantum_Eval_Budget` jobs.  tn-vqe caches measurements
per phi, so an evaluation that changes only theta reuses them; the
budget counts the evaluations that do reach the QPU.  Each job bills

    job overhead + circuits x shots x (rep_delay + circuit duration)

where the circuit duration comes from real transpilation of the row's
own ansatz against the device calibration, at `optimization_level=2`
(what TN-VQE's own `transpile(circuit, backend)` resolves to), and the
circuit count from the Hamiltonian the row measures:

  grouped   one circuit per XOR pattern of the operator's matrix
            elements, plus one per pattern with imaginary elements --
            tn-vqe's own scheme, counted on the operator itself
  pauli     the runtime's qubit-wise-commuting bases, the row's
            `Num_ExpVals_Per_Iter`

A TN-VQE row measures the network-transformed operator, which has more
terms than H.  Its count is read off the run's collected record when
there is one; otherwise grouped rows take the 2^n ceiling and pauli
rows the untransformed count, a floor, and the table marks them.

The device priced against is the campaign's PRICING_DEVICE (see
`_campaign.py`), or `--device`.

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
_REP_DELAY_S = 250e-6
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


def estimate_minimal_open_plan_study(device: str) -> CircuitResourceEstimate:
    """A 4-qubit, one-rep EfficientSU2 circuit (the size of H2/sto-3g under
    JW) -- "the minimal possible benchmark study" the Open Plan's free
    quota is sized for."""
    spec = circuit_spec("EfficientSU2", 4, reps=1)
    return estimate_circuit_resources(
        spec, backend_name=device, backend=_calibration(device),
        shots=_DEFAULT_SHOTS,
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


def _collected_records(campaign) -> dict[str, dict]:
    """The last collected record per Case_ID, or nothing if none exist."""
    path = campaign.RESULTS_DIR / f"{campaign.CSV.stem}.ndjson"
    if not path.exists():
        return {}
    records = {}
    for line in path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            records[str(record.get("Case_ID"))] = record
    return records


def circuits_per_evaluation(
    row: dict[str, str], campaign, records: dict[str, dict],
) -> tuple[int, str]:
    """(circuits one evaluation submits, where that count came from)."""
    num_qubits = int(row["N_Qubit"])
    grouped = row["Measurement_Method"] == "grouped"
    count = grouped_circuit_count if grouped else qwc_circuit_count

    if row["Method"] == "TN-VQE":
        record = records.get(row["Case_ID"])
        if record and record.get("h_tn_opt_qubit"):
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


def estimate_full_csv_study(
    rows: list[dict[str, str]], campaign, device: str,
) -> list[tuple[dict[str, str], int, str, float]]:
    """(row, circuits per evaluation, count source, QPU seconds) per row.

    Transpiles are cached per distinct circuit; the measurement basis
    change adds a few gates against a 250 us rep_delay, so it is left out.
    """
    cache: dict[tuple, CircuitResourceEstimate] = {}
    records = _collected_records(campaign)
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

        circuits, source = circuits_per_evaluation(row, campaign, records)
        per_job = (_JOB_OVERHEAD_S[row["Measurement_Method"]]
                   + circuits * shots * (_REP_DELAY_S + duration))
        priced.append((row, circuits, source, per_job * int(row["Quantum_Eval_Budget"])))
    print(f"  ({len(cache)} distinct circuits really transpiled; "
          f"the rest reused from cache)")
    return priced


def _print_plan_breakdown(total_seconds: float, rates: IBMPricingRates) -> None:
    from qpubench.schemas.mirrors.ibm_cost_estimator import estimate_all_plans

    for plan, breakdown in estimate_all_plans(total_seconds, rates).items():
        cost = f"${breakdown.cost_usd:,.2f}" if breakdown.cost_usd is not None else "n/a"
        print(f"  {plan.value:16s} {cost:>14s}   {breakdown.notes[0] if breakdown.notes else ''}")


def _print_rows(priced: list[tuple[dict[str, str], int, str, float]]) -> None:
    print(f"  {'Case':>4} {'Platform':14} {'Ansatz':16} {'Method':7} {'Optimizer':16}"
          f"{'Shots':>8} {'Evals':>6} {'Circ':>5}  {'source':24}{'QPU h':>8}")
    for row, circuits, source, seconds in priced:
        ansatz = f"{row['Ansatz']} x{row['Ansatz_Reps']}"
        print(f"  {row['Case_ID']:>4} {row['Backend_Platform']:14} {ansatz:16} "
              f"{row['Method']:7} {row['Optimizer']:16}{int(row['Shots']):>8,} "
              f"{row['Quantum_Eval_Budget']:>6} {circuits:>5}  {source:24}"
              f"{seconds / 3600:>8.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    _campaign.add_argument(parser)
    parser.add_argument(
        "--device", default=None, metavar="NAME",
        help="IBM device to price against (default: the campaign's PRICING_DEVICE)",
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
    device = args.device or getattr(campaign, "PRICING_DEVICE", None)
    if device is None:
        raise SystemExit("name a device with --device; the campaign sets no PRICING_DEVICE")

    print(f"Pricing {campaign.CSV.relative_to(_REPO_ROOT)} against {device}.\n")

    print("=== Minimal possible benchmark study (H2/sto-3g/JW, 1 circuit) ===")
    minimal = estimate_minimal_open_plan_study(device)
    print(f"  {minimal.num_qubits} qubits, depth={minimal.depth}, "
          f"{minimal.two_qubit_gate_count} 2Q gates, "
          f"estimated QPU time = {minimal.estimated_qpu_time_s:.3f}s")
    _print_plan_breakdown(minimal.estimated_qpu_time_s, IBMPricingRates.default())

    rows = [
        row for row in _load_csv_cases(campaign.CSV)
        if (not args.platform or row["Backend_Platform"] in args.platform)
        and (not args.ansatz or row["Ansatz"] in args.ansatz)
    ]
    print(f"\n=== {len(rows)} measuring rows, each at its own Quantum_Eval_Budget, "
          f"priced as hardware runs ===")
    priced = estimate_full_csv_study(rows, campaign, device)
    _print_rows(priced)
    total = sum(seconds for *_, seconds in priced)
    print(f"\n  {total:,.0f}s ({total / 3600:,.1f} h) total QPU time")
    _print_plan_breakdown(total, IBMPricingRates.default())


if __name__ == "__main__":
    main()
