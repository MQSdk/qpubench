"""Exact energy of a TN_QC_OPT run's final state, by statevector simulation.

Imported, not run. Requires: pip install 'qpubench[qiskit]'.

A run's reported `vqe_energy` is the lowest noisy evaluation it saw, so it
sits below the true energy of any state the run reached by a few
shot-noise widths -- enough to report energies below FCI. Re-evaluating
the final parameters without shot noise gives the energy of the state the
run actually ended in, which is what methods should be compared on.

Needs a result record carrying `phi` and `h_tn_opt_qubit` (written by
`_campaign_runner.append_record`) and the run's pinned circuit. Exact
simulation is exponential in the qubit count, so this is for the small
registers benchmark campaigns run on simulators.
"""
from __future__ import annotations

import pathlib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]


def cebule_operator(labels: list[str], coefficients: list[float], num_qubits: int):
    """A SparsePauliOp from Cebule's sparse labels ("X0 Z3", "" for identity).

    The index in a label is the Qiskit qubit index.
    """
    from qiskit.quantum_info import SparsePauliOp

    terms = []
    for label, coefficient in zip(labels, coefficients):
        tokens = label.split()
        terms.append((
            "".join(t[0] for t in tokens), [int(t[1:]) for t in tokens], coefficient,
        ))
    return SparsePauliOp.from_sparse_list(terms, num_qubits)


def exact_energy(qasm_text: str, phi: list[float], h_tn_opt_qubit: Any) -> float:
    """<psi(phi)| H |psi(phi)> for the pinned circuit, without shot noise.

    `phi` binds positionally to the loaded circuit's parameters, as tn-vqe
    binds it; `h_tn_opt_qubit` is the (labels, coefficients) pair tn-vqe
    returns, i.e. U(theta)^dag H U(theta) at the final theta.
    """
    from qiskit import qasm3
    from qiskit.quantum_info import Statevector

    circuit = qasm3.loads(qasm_text)
    labels, coefficients = h_tn_opt_qubit
    hamiltonian = cebule_operator(labels, coefficients, circuit.num_qubits)
    state = Statevector(circuit.assign_parameters(list(phi)))
    return float(state.expectation_value(hamiltonian).real)


def record_exact_energy(record: dict[str, Any], run: dict[str, str]) -> float | None:
    """Exact final energy for one result record and its matrix row, or None
    if the record predates storing the final parameters."""
    phi, hamiltonian = record.get("phi"), record.get("h_tn_opt_qubit")
    # A table that mixes old and new records fills the gaps with NaN.
    if not isinstance(phi, list) or not isinstance(hamiltonian, (list, tuple)):
        return None
    qasm_text = (REPO / run["Qasm_Ansatz_File"]).read_text(encoding="utf-8")
    return exact_energy(qasm_text, phi, hamiltonian)
