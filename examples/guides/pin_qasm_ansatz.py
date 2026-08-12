"""Pin the exact circuit each TN-VQE benchmark row runs, as committed QASM.

Requires: pip install 'qpubench[qiskit]'

Why pin it at all
-----------------
Until cebule-tn_vqe commit a760489, four of the five paths to an
expectation value disagreed with Qiskit's `q[i] = Hamiltonian index i`
convention, and with each other: on `default.qubit` at identical
parameters the two quantum modes gave 0.14497300 where the classical mode
gave 0.42729423 — the latter matching a hand-built expectation value. All
five now agree, pinned upstream by `test_qasm_uses_qiskit_qubit_ordering`
against a hand-built value rather than against another code path.

That is what makes a single pinned QASM string give the *same* energy on
both platforms and both measurement methods, which is the precondition
for the cross-backend comparison this benchmark is built to make. Before
that commit it did not hold, so pinning would have pinned an ambiguity.

Why files rather than a CSV column
----------------------------------
A multi-line QASM program does not belong in a CSV cell. The matrix
records the path and a SHA-256 prefix instead, so a silently edited
circuit is detectable — the hash in the CSV stops matching the file.
`build_benchmark_matrix.py` fills both cells for any row whose circuit
file exists here, and leaves them blank otherwise, so running this script
is optional and the matrix is generatable without Qiskit.

One interaction worth knowing: supplying `qasm_ansatz` to TN_QC_OPT
changes `n_layers_circuit`'s effective default from 3 to 1 (the circuit
is fully specified by the QASM, so the task stops building reps of its
own). Pass it explicitly whenever you pin a circuit.

Run:
    PYTHONPATH=src python examples/guides/pin_qasm_ansatz.py
"""
from __future__ import annotations

import csv
import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _ansatz_builders import build_ansatz

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CSV_PATH = (
    _REPO_ROOT / "data" / "benchmarks" / "ibm_tn-vqe_qesem"
    / "stage1_screening_matrix.csv"
)
_QASM_DIR = _REPO_ROOT / "data" / "qasm"


def tn_circuit_shapes(rows: list[dict[str, str]]) -> set[tuple[str, int, int]]:
    """The distinct (ansatz, qubits, reps) a TN-VQE row actually executes.

    Rows in `optimization_mode="network"` run no circuit at all, so they
    have nothing to pin.
    """
    return {
        (row["Ansatz"], int(row["N_Qubit"]), int(row["Ansatz_Reps"]))
        for row in rows
        if row["Method"] == "TN-VQE" and row["Optimization_Mode"] != "network"
    }


def write_pinned_qasm(ansatz: str, num_qubits: int, reps: int) -> tuple[pathlib.Path, str]:
    """Write one circuit as OpenQASM 3.0, parameters left free; return
    (path, sha256 prefix).

    The circuit is dumped *unbound*. OpenQASM 3's `input` declarations
    carry the free parameters through the file, so what is pinned is the
    structure, the qubit ordering and the parameterisation together, and
    the consumer derives `phi_shape` from the loaded circuit's
    `num_parameters`.

    Binding them away is not a neutral simplification: TN-VQE takes its
    phi count from the QASM, so a circuit dumped at zero loads as
    `num_parameters == 0` and the row silently optimises theta alone
    against a frozen |0...0>, with no exception raised. That is what
    `test_pinned_qasm_carries_the_parameters_the_matrix_claims` guards.
    """
    from qiskit import qasm3

    circuit = build_ansatz(ansatz, num_qubits, reps=reps)

    path = _QASM_DIR / f"{ansatz}_{num_qubits}q_{reps}r.qasm"
    # UTF-8 explicitly, not the locale default: an unbound n_local dump
    # names its parameters `input float[64] _{θ}_0_;`, so these files are
    # no longer pure ASCII and must not depend on the writer's locale.
    path.write_text(qasm3.dumps(circuit) + "\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> None:
    _QASM_DIR.mkdir(parents=True, exist_ok=True)
    with _CSV_PATH.open() as f:
        rows = list(csv.DictReader(f))

    shapes = sorted(tn_circuit_shapes(rows))
    if not shapes:
        raise SystemExit(f"no circuit-running TN-VQE rows found in {_CSV_PATH.name}")

    print(f"Pinning {len(shapes)} distinct TN-VQE circuits from {_CSV_PATH.name}:")
    for ansatz, num_qubits, reps in shapes:
        path, digest = write_pinned_qasm(ansatz, num_qubits, reps)
        print(f"  {path.relative_to(_REPO_ROOT)}  sha256:{digest}")

    print(
        "\nRe-run build_benchmark_matrix.py to fill Qasm_Ansatz_File / "
        "Qasm_Ansatz_SHA256 from these."
    )


if __name__ == "__main__":
    main()
