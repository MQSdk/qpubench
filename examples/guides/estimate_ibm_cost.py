"""Resource + cost estimator walkthrough: what would
data/IBM_VQE_Test_Benchmark.csv (1,218 rows: JW/mol_map baselines plus a
full Cebule TN-VQE `tn_qc_opt`/`tn_qc_opt+mol_map` sweep) actually cost to
run on real IBM Quantum hardware, under each of the four access plans?

Requires: pip install 'qpubench[qiskit]'

Two things this script deliberately keeps separate:

1. **Real, verified**: per-circuit resource estimation
   (`backends.ibm_cost_estimator.estimate_circuit_resources`) — real ALAP-
   scheduled transpilation against a real IBM calibration snapshot
   (`FakeBrisbane`, no credentials needed) plus IBM's own documented usage
   formula. Circuit depth/gate counts/duration are real Qiskit output, not
   guessed.
2. **Illustrative, clearly-labeled assumptions**: the benchmark CSV's
   sweep columns (`Ansatz`, `Optimizer`, `Shots`, ...) are still blank
   (see `data/README.md` — that's an open question back to whoever is
   designing the study, not something this script should silently
   invent). To show a concrete number anyway, this script assumes a
   hardware-efficient `EfficientSU2` ansatz (1 repetition) and a fixed
   shot count/iteration count, both printed prominently and easy to
   change at the top of `main()` — swap in the real ansatz/shot choices
   once they're decided.

Run:
    python examples/guides/estimate_ibm_cost.py
"""
from __future__ import annotations

import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

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
_ASSUMED_ANSATZ_REPS = 1
_ASSUMED_VQE_ITERATIONS = 30   # one circuit submission per optimizer iteration


def _ansatz_circuit_spec(num_qubits: int, *, reps: int = _ASSUMED_ANSATZ_REPS):
    from qiskit import qasm3
    from qiskit.circuit.library import efficient_su2

    from qpubench.schemas.circuit import CircuitSpec
    from qpubench.schemas.primitives import CircuitFormat

    qc = efficient_su2(num_qubits, reps=reps)
    bound = qc.assign_parameters([0.0] * qc.num_parameters)
    bound.measure_all()
    return CircuitSpec(num_qubits=num_qubits, format=CircuitFormat.QASM3, serialized=qasm3.dumps(bound))


def _load_csv_cases() -> list[dict[str, str]]:
    with _CSV_PATH.open() as f:
        return [row for row in csv.DictReader(f) if row["N_Qubit"]]


def estimate_minimal_open_plan_study() -> CircuitResourceEstimate:
    """The smallest real case in the CSV (H2/sto-3g/JW, 4 qubits) — "the
    minimal possible benchmark study" the Open Plan's free quota is sized
    for."""
    spec = _ansatz_circuit_spec(4)
    return estimate_circuit_resources(
        spec, backend_name=_BACKEND_NAME, shots=_ASSUMED_SHOTS_PER_CIRCUIT,
        label="H2/sto-3g/JW (minimal case)",
    )


def estimate_full_csv_study() -> list[CircuitResourceEstimate]:
    """One resource estimate per CSV row with a real N_Qubit value,
    assuming `_ASSUMED_VQE_ITERATIONS` optimizer iterations each submit
    one circuit (illustrative -- see module docstring).

    The CSV now has 1,218 rows (`JW`/`mol_map` plus a full `tn_qc_opt`/
    `tn_qc_opt+mol_map` sweep) -- most differ only in `TN_Layers_Network`,
    `Rotation_Type`, or whether `mol_map` was used, none of which change
    the real *quantum-circuit* resource estimate (`TN_Layers_Network` runs
    classically, not on the QPU -- see `data/README.md`). Real transpile
    calls are cached per (num_qubits, ansatz reps) pair -- for `tn_qc_opt`
    rows, reps = `TN_Layers_Circuit` (the one TN-VQE knob that actually
    changes the real submitted circuit depth); for plain `JW`/`mol_map`
    rows, reps = the illustrative `_ASSUMED_ANSATZ_REPS`.
    """
    cache: dict[tuple[int, int], CircuitResourceEstimate] = {}
    estimates = []
    for row in _load_csv_cases():
        num_qubits = int(row["N_Qubit"])
        is_tn_vqe = row["Mapper"].startswith("tn_qc_opt")
        reps = int(row["TN_Layers_Circuit"]) if is_tn_vqe and row["TN_Layers_Circuit"] else _ASSUMED_ANSATZ_REPS

        key = (num_qubits, reps)
        if key not in cache:
            spec = _ansatz_circuit_spec(num_qubits, reps=reps)
            label = f"{num_qubits}q, {reps} ansatz reps"
            cache[key] = estimate_circuit_resources(
                spec, backend_name=_BACKEND_NAME, shots=_ASSUMED_SHOTS_PER_CIRCUIT, label=label,
            )
        # _ASSUMED_VQE_ITERATIONS separate circuit submissions per CSV row,
        # each paying its own per-sub-job overhead -- not just one estimate x N.
        estimates.extend([cache[key]] * _ASSUMED_VQE_ITERATIONS)
    print(f"  ({len(cache)} distinct (qubits, ansatz reps) pairs really transpiled; "
          f"the rest reused from cache)")
    return estimates


def _print_plan_breakdown(total_seconds: float, rates: IBMPricingRates) -> None:
    from qpubench.schemas.mirrors.ibm_cost_estimator import estimate_all_plans

    for plan, breakdown in estimate_all_plans(total_seconds, rates).items():
        cost = f"${breakdown.cost_usd:,.2f}" if breakdown.cost_usd is not None else "n/a"
        print(f"  {plan.value:16s} {cost:>14s}   {breakdown.notes[0] if breakdown.notes else ''}")


def main() -> None:
    print(f"Assumptions: {_ASSUMED_SHOTS_PER_CIRCUIT} shots/circuit, "
          f"EfficientSU2 reps={_ASSUMED_ANSATZ_REPS}, "
          f"{_ASSUMED_VQE_ITERATIONS} VQE iterations/case (each = 1 circuit submission).\n")

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
