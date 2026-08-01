"""Resource + cost estimator walkthrough: what would
data/IBM_VQE_Test_Benchmark.csv (294 rows, the stage-1 screening matrix)
actually cost to run on real IBM Quantum hardware, under each of the four
access plans?

Requires: pip install 'qpubench[qiskit]'

Two things this script deliberately keeps separate:

1. **Real, verified**: per-circuit resource estimation
   (`backends.ibm_cost_estimator.estimate_circuit_resources`) — real ALAP-
   scheduled transpilation against a real IBM calibration snapshot
   (`FakeBrisbane`, no credentials needed) plus IBM's own documented usage
   formula. Circuit depth/gate counts/duration are real Qiskit output, not
   guessed. The ansatz is real too: each row names its own `Ansatz` and
   `Ansatz_Reps`, and `_ansatz_builders.py` builds that circuit rather
   than substituting a hardware-efficient stand-in, which matters a lot
   (a real Trotterized UCCSD costs ~17x EfficientSU2 at 12 qubits).
2. **Illustrative, clearly-labeled assumptions**: the CSV's `Shots` and
   `Qiskit_Opt_Level` columns are still blank (see `data/README.md` —
   that's an open question back to whoever is designing the study, not
   something this script should silently invent). To show a concrete
   number anyway, this script assumes a fixed shot count and iteration
   count, both printed prominently and easy to change at the top of
   `main()`.

Run:
    python examples/guides/estimate_ibm_cost.py
"""
from __future__ import annotations

import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _ansatz_builders import circuit_spec

from qpubench.backends.ibm_cost_estimator import estimate_circuit_resources
from qpubench.schemas.mirrors.ibm_cost_estimator import (
    CircuitResourceEstimate,
    IBMPricingRates,
    aggregate_benchmark_cost,
)

_CSV_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "IBM_VQE_Test_Benchmark.csv"
_BACKEND_NAME = "ibm_brisbane"   # offline FakeBrisbane snapshot -- no credentials needed

# --- Illustrative assumptions (the CSV doesn't specify these yet) ---------
_ASSUMED_SHOTS_PER_CIRCUIT = 4096
_ASSUMED_VQE_ITERATIONS = 30   # one circuit submission per optimizer iteration


def _load_csv_cases() -> list[dict[str, str]]:
    with _CSV_PATH.open() as f:
        return [row for row in csv.DictReader(f) if row["N_Qubit"]]


def estimate_minimal_open_plan_study() -> CircuitResourceEstimate:
    """The smallest real case in the CSV (H2/sto-3g/JW, 4 qubits) — "the
    minimal possible benchmark study" the Open Plan's free quota is sized
    for."""
    spec = circuit_spec("EfficientSU2", 4, reps=1)
    return estimate_circuit_resources(
        spec, backend_name=_BACKEND_NAME, shots=_ASSUMED_SHOTS_PER_CIRCUIT,
        label="H2/sto-3g/JW EfficientSU2 (minimal case)",
    )


def estimate_full_csv_study() -> list[CircuitResourceEstimate]:
    """One resource estimate per CSV row, assuming
    `_ASSUMED_VQE_ITERATIONS` optimizer iterations each submit one
    circuit (illustrative -- see module docstring).

    Many rows differ only in `Measurement_Method`, `TN_Layers_Network` or
    `Rotation_Type`, none of which change the real *quantum-circuit*
    resource estimate (`TN_Layers_Network` runs classically, not on the
    QPU -- see `data/README.md`). So transpile calls are cached per
    (ansatz, qubits, reps, electrons) key, which collapses all 294 rows
    onto a much smaller number of distinct circuits.
    """
    cache: dict[tuple[str, int, int, int], CircuitResourceEstimate] = {}
    estimates = []
    for row in _load_csv_cases():
        ansatz = row["Ansatz"]
        num_qubits = int(row["N_Qubit"])
        reps = int(row["Ansatz_Reps"])
        num_electrons = int(row["Active_Electrons"])

        key = (ansatz, num_qubits, reps, num_electrons)
        if key not in cache:
            spec = circuit_spec(ansatz, num_qubits, reps=reps, num_electrons=num_electrons)
            label = f"{ansatz}, {num_qubits}q, {reps} reps"
            cache[key] = estimate_circuit_resources(
                spec, backend_name=_BACKEND_NAME, shots=_ASSUMED_SHOTS_PER_CIRCUIT, label=label,
            )
        # _ASSUMED_VQE_ITERATIONS separate circuit submissions per CSV row,
        # each paying its own per-sub-job overhead -- not just one estimate x N.
        estimates.extend([cache[key]] * _ASSUMED_VQE_ITERATIONS)
    print(f"  ({len(cache)} distinct circuits really transpiled; "
          f"the rest reused from cache)")
    return estimates


def _print_plan_breakdown(total_seconds: float, rates: IBMPricingRates) -> None:
    from qpubench.schemas.mirrors.ibm_cost_estimator import estimate_all_plans

    for plan, breakdown in estimate_all_plans(total_seconds, rates).items():
        cost = f"${breakdown.cost_usd:,.2f}" if breakdown.cost_usd is not None else "n/a"
        print(f"  {plan.value:16s} {cost:>14s}   {breakdown.notes[0] if breakdown.notes else ''}")


def main() -> None:
    print(f"Assumptions: {_ASSUMED_SHOTS_PER_CIRCUIT} shots/circuit, "
          f"{_ASSUMED_VQE_ITERATIONS} VQE iterations/case (each = 1 circuit "
          f"submission).\nAnsatz is not assumed: each row's own Ansatz/"
          f"Ansatz_Reps is built and transpiled.\n")

    print("=== Minimal possible benchmark study (H2/sto-3g/JW, 1 circuit) ===")
    minimal = estimate_minimal_open_plan_study()
    print(f"  {minimal.num_qubits} qubits, depth={minimal.depth}, "
          f"{minimal.two_qubit_gate_count} 2Q gates, "
          f"estimated QPU time = {minimal.estimated_qpu_time_s:.3f}s")
    _print_plan_breakdown(minimal.estimated_qpu_time_s, IBMPricingRates.default())

    print(f"\n=== Full benchmark study (all populated CSV rows x "
          f"{_ASSUMED_VQE_ITERATIONS} iterations each) ===")
    full_estimates = estimate_full_csv_study()
    agg = aggregate_benchmark_cost(full_estimates)
    print(f"  {len(full_estimates)} circuit submissions, "
          f"{agg.total_shots:,} total shots, "
          f"{agg.total_qpu_seconds:,.1f}s ({agg.total_qpu_minutes:,.1f} min) total QPU time")
    _print_plan_breakdown(agg.total_qpu_seconds, IBMPricingRates.default())


if __name__ == "__main__":
    main()
