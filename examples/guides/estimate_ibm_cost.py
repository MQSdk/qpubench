"""Resource + cost estimator walkthrough: what would the stage-1
screening matrix actually cost to run on real IBM Quantum hardware,
under each of the four access plans?

Requires: pip install 'qpubench[qiskit]'

Two things this script deliberately keeps separate:

1. **Real, verified**: per-circuit resource estimation
   (`backends.ibm_cost_estimator.estimate_circuit_resources`) — real ALAP-
   scheduled transpilation against the target device's own calibration
   plus IBM's own documented usage formula. Circuit depth/gate counts/duration are real Qiskit output, not
   guessed. The ansatz is real too: each row names its own `Ansatz` and
   `Ansatz_Reps`, and `_ansatz_builders.py` builds that circuit rather
   than substituting a hardware-efficient stand-in, which matters a lot
   (a real Trotterized UCCSD costs ~17x EfficientSU2 at 12 qubits).
2. **Recorded inputs, no longer assumptions**: `Shots` and `Iterations`
   are both filled per row (`n_shots` is a real TNQCOptInput field), and
   transpilation runs at `optimization_level=2` — what TN-VQE's own bare
   `transpile(circuit, backend)` call resolves to under Qiskit 2.x. The
   `Qiskit_Opt_Level` column is gone: TN-VQE passes no optimization_level
   and offers no way to set one, so it was a column nothing could fill.

The iteration count used to be a flat 30 applied to every row, and that
was not a conservative assumption but an invalid one. COBYLA needs an
initial simplex of n+1 points before it can take a single step, and
scipy raises a maxiter set below that rather than honouring it — so a
12-qubit TN row billed at 30 submissions really consumed 144 and moved
the objective by exactly zero. `Iterations` is now a per-row campaign
input, and this script bills what the CSV says.

Rows in `optimization_mode="network"` are skipped: they take no quantum
measurements, so they have no QPU cost to estimate (see
`split_benchmark_batches.py`, which writes them to their own file).

Run:
    PYTHONPATH=src python examples/guides/estimate_ibm_cost.py
"""
from __future__ import annotations

import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _ansatz_builders import circuit_spec

from qpubench.backends.ibm_cost_estimator import (
    estimate_circuit_resources,
    resolve_calibration_backend,
)
from qpubench.schemas.mirrors.ibm_cost_estimator import (
    CircuitResourceEstimate,
    IBMPricingRates,
    aggregate_benchmark_cost,
)

_CSV_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "data" / "benchmarks" / "ibm_tn-vqe_qesem" / "stage1_screening_matrix.csv"
)
# IBM's European data centre, where this campaign's time is bought, does
# not host ibm_brisbane (an Eagle device in the US, whatever the name
# suggests).  qiskit-ibm-runtime ships no Fake* snapshot for ibm_aachen,
# so the estimate comes from its LIVE calibration and $IBM_QUANTUM_TOKEN
# is required to run this script.
_BACKEND_NAME = "ibm_aachen"


_CALIBRATION = None


def _calibration():
    """The live `ibm_aachen` backend, opened once and reused.

    Resolved lazily, so importing this module needs no credentials; the
    connection opens on the first transpile and is shared by the rest.
    """
    global _CALIBRATION
    if _CALIBRATION is None:
        _CALIBRATION = resolve_calibration_backend(_BACKEND_NAME)
    return _CALIBRATION

# Shots and iterations both come from each row's own columns now.
_DEFAULT_SHOTS = 4096          # for the minimal-case demo, which has no row
# What TN-VQE's own transpile(circuit, backend) resolves to under Qiskit 2.x.
_OPTIMIZATION_LEVEL = 2


def _load_csv_cases() -> list[dict[str, str]]:
    with _CSV_PATH.open() as f:
        return [
            row for row in csv.DictReader(f)
            if row["N_Qubit"] and row["Optimization_Mode"] != "network"
        ]


def estimate_minimal_open_plan_study() -> CircuitResourceEstimate:
    """The smallest real case in the CSV (H2/sto-3g/JW, 4 qubits) — "the
    minimal possible benchmark study" the Open Plan's free quota is sized
    for."""
    spec = circuit_spec("EfficientSU2", 4, reps=1)
    return estimate_circuit_resources(
        spec, backend_name=_BACKEND_NAME, backend=_calibration(),
        shots=_DEFAULT_SHOTS,
        optimization_level=_OPTIMIZATION_LEVEL,
        label="H2/sto-3g/JW EfficientSU2 (minimal case)",
    )


def estimate_full_csv_study() -> list[CircuitResourceEstimate]:
    """One resource estimate per CSV row, at that row's own `Iterations`,
    each iteration submitting one circuit.

    Many rows differ only in `Measurement_Method`, `TN_Layers_Network` or
    `TN_Ansatz`, none of which change the real *quantum-circuit*
    resource estimate (`TN_Layers_Network` runs classically, not on the
    QPU -- see `data/benchmarks/ibm_tn-vqe_qesem/README.md`). So transpile calls are cached per
    (ansatz, qubits, reps, electrons, shots) key, which collapses every
    row onto a much smaller number of distinct circuits.
    """
    cache: dict[tuple[str, int, int, int, int], CircuitResourceEstimate] = {}
    estimates = []
    for row in _load_csv_cases():
        ansatz = row["Ansatz"]
        num_qubits = int(row["N_Qubit"])
        reps = int(row["Ansatz_Reps"])
        num_electrons = int(row["Active_Electrons"])
        shots = int(row["Shots"])

        key = (ansatz, num_qubits, reps, num_electrons, shots)
        if key not in cache:
            spec = circuit_spec(ansatz, num_qubits, reps=reps, num_electrons=num_electrons)
            label = f"{ansatz}, {num_qubits}q, {reps} reps"
            cache[key] = estimate_circuit_resources(
                spec, backend_name=_BACKEND_NAME, backend=_calibration(),
                shots=shots,
                optimization_level=_OPTIMIZATION_LEVEL, label=label,
            )
        # One separate circuit submission per optimizer iteration, each
        # paying its own per-sub-job overhead -- not one estimate x N.
        estimates.extend([cache[key]] * int(row["Iterations"]))
    print(f"  ({len(cache)} distinct circuits really transpiled; "
          f"the rest reused from cache)")
    return estimates


def _print_plan_breakdown(total_seconds: float, rates: IBMPricingRates) -> None:
    from qpubench.schemas.mirrors.ibm_cost_estimator import estimate_all_plans

    for plan, breakdown in estimate_all_plans(total_seconds, rates).items():
        cost = f"${breakdown.cost_usd:,.2f}" if breakdown.cost_usd is not None else "n/a"
        print(f"  {plan.value:16s} {cost:>14s}   {breakdown.notes[0] if breakdown.notes else ''}")


def main() -> None:
    print(f"Shots and iterations both come from each row's own columns "
          f"(1 iteration = 1 circuit submission).\nAnsatz is not assumed "
          f"either: each row's own Ansatz/Ansatz_Reps is built and "
          f"transpiled, at optimization_level={_OPTIMIZATION_LEVEL}.\n")

    print("=== Minimal possible benchmark study (H2/sto-3g/JW, 1 circuit) ===")
    minimal = estimate_minimal_open_plan_study()
    print(f"  {minimal.num_qubits} qubits, depth={minimal.depth}, "
          f"{minimal.two_qubit_gate_count} 2Q gates, "
          f"estimated QPU time = {minimal.estimated_qpu_time_s:.3f}s")
    _print_plan_breakdown(minimal.estimated_qpu_time_s, IBMPricingRates.default())

    print("\n=== Full benchmark study (all populated CSV rows, "
          "each at its own Iterations) ===")
    full_estimates = estimate_full_csv_study()
    agg = aggregate_benchmark_cost(full_estimates)
    print(f"  {len(full_estimates)} circuit submissions, "
          f"{agg.total_shots:,} total shots, "
          f"{agg.total_qpu_seconds:,.1f}s ({agg.total_qpu_minutes:,.1f} min) total QPU time")
    _print_plan_breakdown(agg.total_qpu_seconds, IBMPricingRates.default())


if __name__ == "__main__":
    main()
