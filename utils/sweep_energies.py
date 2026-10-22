"""Exact energy after every optimizer iteration of each collected run.

Requires: pip install 'qpubench[qiskit]', and tn-vqe (cebule-tn_vqe)
importable for TN-VQE rows.

A run's final point under shot noise lands wherever its last iteration
left it, a few tenths of a mHa from the optimum it is wandering around,
so a single final state cannot separate rows closer than that. This
records the noiseless energy at the end of every iteration, so the plots
can average over the last few instead.

For each record it takes the parameters at each iteration boundary
(`sweep_params`, fetched from Cebule by `task_id` for records collected
before the runner kept them), binds phi to the pinned circuit, and takes
the statevector expectation value against H, or on a TN-VQE row against
U(theta)^dag H U(theta), built by tn-vqe's own orbital rotation from the
row's real task input. The result is stored on the record as
`sweep_energies`. Records that already carry it are left alone. The
results file is copied to `<name>.pre_sweep_energies` before it is
rewritten.

Run:
    PYTHONPATH=src python utils/sweep_energies.py [--campaign NAME] [--csv PATH]
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _campaign
import _campaign_runner as runner
from _statevector_energy import REPO, cebule_operator


def _transform(row: dict[str, str], campaign):
    """theta -> (labels, coefficients) of U(theta)^dag H U(theta), as tn-vqe
    computes it for this row's task input (Givens networks only)."""
    from tn_vqe.construct_hamiltonian import infer_h_type
    from tn_vqe.parsers import parse_input_TNQCOpt
    from tn_vqe.pipeline import _mapped_hamiltonian, _orbital_pauli_terms

    payload = runner.task_payload(runner.build_input(row, campaign))
    parsed = parse_input_TNQCOpt(payload)
    coefficients, operators, tn_ansatz = parsed[0], parsed[1], parsed[5]
    mapping_matrix, mapped_hamiltonian = parsed[15], parsed[16]
    mapped = _mapped_hamiltonian(mapping_matrix, coefficients, operators, mapped_hamiltonian)
    terms = _orbital_pauli_terms(tn_ansatz, coefficients, operators,
                                 infer_h_type(operators), int(row["N_Qubit"]), mapped=mapped)
    if terms is None:
        raise ValueError(f"case {row['Case_ID']}: no orbital-rotation route for {tn_ansatz}")

    def hamiltonian(theta):
        labels, coeffs = terms(theta)
        return ([" ".join(f"{p}{q}" for p, q in term) for term in labels], list(coeffs))

    return hamiltonian


def sweep_energies(record: dict, row: dict[str, str], campaign) -> list[float]:
    import numpy as np
    from qiskit import qasm3
    from qiskit.quantum_info import SparsePauliOp, Statevector

    circuit = qasm3.loads((REPO / row["Qasm_Ansatz_File"]).read_text(encoding="utf-8"))
    n_phi = circuit.num_parameters
    if row["Method"] == "TN-VQE":
        transform = _transform(row, campaign)
    else:
        coefficients, operators, _ = runner.hamiltonian(row, campaign)
        fixed = SparsePauliOp(operators, coefficients)

    energies = []
    for params in record["sweep_params"]:
        state = Statevector(circuit.assign_parameters(params[:n_phi]))
        if row["Method"] == "TN-VQE":
            labels, coeffs = transform(np.asarray(params[n_phi:], dtype=float))
            op = cebule_operator(labels, coeffs, circuit.num_qubits)
        else:
            op = fixed
        energies.append(float(state.expectation_value(op).real))
    return energies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    _campaign.add_argument(parser)
    parser.add_argument("--csv", type=pathlib.Path, default=None,
                        help="the matrix whose results to fill (default: the campaign's CSV)")
    args = parser.parse_args()
    campaign = _campaign.load(args.campaign)
    csv_path = args.csv or campaign.CSV
    path = campaign.RESULTS_DIR / f"{csv_path.stem}.ndjson"

    with csv_path.open() as f:
        rows = {r["Case_ID"]: r for r in csv.DictReader(f)}
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    todo = [r for r in records if "sweep_energies" not in r
            and rows.get(str(r["Case_ID"]), {}).get("Method") in ("VQE", "TN-VQE")]
    print(f"{len(todo)} of {len(records)} records lack sweep_energies")
    if not todo:
        return

    session = None
    for record in todo:
        case = str(record["Case_ID"])
        if not record.get("sweep_params"):
            session = session or runner.open_session()
            payload = session.cebule.get_result(record["task_id"], runner.RESULT_TYPE)
            record["sweep_params"] = runner.sweep_params(
                payload.get("param_history"), payload.get("iteration_boundaries"))
        if not record["sweep_params"]:
            print(f"  case {case}: no iteration history")
            continue
        record["sweep_energies"] = sweep_energies(record, rows[case], campaign)
        print(f"  case {case}: {len(record['sweep_energies'])} iterations")

    shutil.copy2(path, path.with_name(path.name + ".pre_sweep_energies"))
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    print(f"rewrote {path}")


if __name__ == "__main__":
    main()
