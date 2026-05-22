"""Type conversion utilities: QForte ↔ qpubench schemas.

Neither qpubench nor qforte import from each other.
This module is the only place that knows about both.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import AlgorithmSpec, ExecutionOptions
from qpubench.schemas.observable import PauliTerm, SparsePauliObservable
from qpubench.schemas.primitives import CircuitFormat, ComplexNumber, PauliLabel
from qpubench.schemas.record import VQAConfig
from qpubench.schemas.result import AdaptIteration, ExpectationResult, QuantumResult
from qpubench.schemas.primitives import JobStatus, QPUModality


# ---------------------------------------------------------------------------
# Molecule spec helpers
# ---------------------------------------------------------------------------

def molecule_spec_from_file(
    json_path: str | Path,
    *,
    num_qubits: int = 0,
) -> CircuitSpec:
    """Build a CircuitSpec from a QForte external molecule JSON file.

    num_qubits can be left as 0 when unknown before building the system.
    QForteAlgorithmAdapter will fill it in after calling system_factory().
    """
    return CircuitSpec(
        num_qubits=num_qubits,
        format=CircuitFormat.MOLECULE_JSON,
        serialized=str(Path(json_path).resolve()),
    )


def molecule_spec_from_geometry(
    geometry: list[tuple[str, tuple[float, float, float]]],
    basis: str = "sto-6g",
    *,
    multiplicity: int = 1,
    charge: int = 0,
    symmetry: str = "c1",
    run_fci: int = 1,
    num_frozen_docc: int = 0,
    num_frozen_uocc: int = 0,
) -> CircuitSpec:
    """Build a CircuitSpec for an on-the-fly Psi4 build.

    Requires Psi4 to be installed.

    Example:
        spec = molecule_spec_from_geometry(
            [("H", (0, 0, 0)), ("H", (0, 0, 0.735))],
            basis="sto-6g",
        )
    """
    payload = {
        "build_type":       "psi4",
        "mol_geometry":     [[sym, list(xyz)] for sym, xyz in geometry],
        "basis":            basis,
        "multiplicity":     multiplicity,
        "charge":           charge,
        "symmetry":         symmetry,
        "run_fci":          run_fci,
        "num_frozen_docc":  num_frozen_docc,
        "num_frozen_uocc":  num_frozen_uocc,
    }
    return CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized=json.dumps(payload),
    )


# ---------------------------------------------------------------------------
# QForte QuantumOperator → SparsePauliObservable
# ---------------------------------------------------------------------------

_QFORTE_GATE_TO_PAULI = {"X": PauliLabel.X, "Y": PauliLabel.Y, "Z": PauliLabel.Z}


def qforte_op_to_sparse_pauli(
    qb_ham: Any,
    num_qubits: int,
) -> SparsePauliObservable:
    """Convert a QForte QuantumOperator to a qpubench SparsePauliObservable.

    QForte stores the qubit Hamiltonian as a list of (coeff, QuantumCircuit)
    pairs where each circuit is a Pauli string (X/Y/Z single-qubit gates).

    Falls back to an empty observable if the conversion fails — callers
    should check len(observable.terms) > 0 before using it.
    """
    terms: list[PauliTerm] = []
    try:
        for coeff, pauli_circ in qb_ham.terms():
            qubit_indices: list[int] = []
            pauli_ops: list[PauliLabel] = []
            for gate in pauli_circ.gates():
                label = _QFORTE_GATE_TO_PAULI.get(gate.gate_id())
                if label is not None:
                    qubit_indices.append(gate.target())
                    pauli_ops.append(label)
            if qubit_indices:
                terms.append(PauliTerm(
                    qubit_indices=tuple(qubit_indices),
                    pauli_ops=tuple(pauli_ops),
                    coefficient=ComplexNumber(re=float(coeff.real), im=float(coeff.imag)),
                ))
    except Exception:
        pass
    return SparsePauliObservable(num_qubits=num_qubits, terms=terms)


# ---------------------------------------------------------------------------
# QForte algorithm state → qpubench result schemas
# ---------------------------------------------------------------------------

def extract_adapt_history(alg: Any) -> list[AdaptIteration]:
    """Reconstruct per-macro-iteration metrics from a completed ADAPTVQE object."""
    energies   = list(getattr(alg, "_energies", []))
    grad_norms = list(getattr(alg, "_grad_norms", []))
    cnot_lst   = list(getattr(alg, "_n_cnot_lst", []))
    param_lst  = list(getattr(alg, "_n_classical_params_lst", []))
    pauli_lst  = list(getattr(alg, "_n_pauli_trm_measures_lst", []))
    n = len(energies)
    return [
        AdaptIteration(
            iteration=i,
            energy=energies[i],
            grad_norm=grad_norms[i] if i < len(grad_norms) else 0.0,
            n_operators=i + 1,
            n_cnot=cnot_lst[i] if i < len(cnot_lst) else 0,
            n_classical_params=param_lst[i] if i < len(param_lst) else 0,
            n_pauli_measures=pauli_lst[i] if i < len(pauli_lst) else 0,
        )
        for i in range(n)
    ]


def extract_quantum_result(alg: Any, alg_spec: AlgorithmSpec) -> QuantumResult:
    """Build a QuantumResult from any completed QForte algorithm object."""
    energy   = float(alg.get_gs_energy())
    n_cnot   = int(getattr(alg, "_n_cnot", 0))
    n_params = int(getattr(alg, "_n_classical_params", 0))
    n_pauli  = int(getattr(alg, "_n_pauli_trm_measures", 0))
    converged = bool(getattr(alg, "_converged", True))

    adapt_history: list[AdaptIteration] | None = None
    if alg_spec.name.upper() == "ADAPTVQE":
        adapt_history = extract_adapt_history(alg)

    transpiled_circuit: str | None = None
    try:
        u = getattr(alg, "_Umaxdepth", None)
        if u is not None:
            transpiled_circuit = str(u)
    except Exception:
        pass

    return QuantumResult(
        modality=QPUModality.GATE_BASED,
        expectation_values=[
            ExpectationResult(observable_index=0, value=energy, std_error=0.0)
        ],
        adapt_history=adapt_history,
        transpiled_circuit=transpiled_circuit,
        status=JobStatus.SUCCEEDED,
        metadata={
            "n_cnot":               n_cnot,
            "n_classical_params":   n_params,
            "n_pauli_trm_measures": n_pauli,
            "converged":            converged,
        },
    )


def extract_vqa_config(alg: Any, mol: Any, alg_spec: AlgorithmSpec) -> VQAConfig:
    """Build a VQAConfig from a completed QForte algorithm + molecule."""
    hf_energy  = float(getattr(alg, "_hf_energy", getattr(mol, "hf_energy", 0.0)))
    fci_energy = float(getattr(mol, "fci_energy", 0.0))
    energy_hist = list(getattr(alg, "_energies", []))
    adapts_reached = (
        alg_spec.name.upper() == "ADAPTVQE"
        and not bool(getattr(alg, "_converged", True))
    )
    return VQAConfig(
        problem_type="chemistry",
        hf_energy=hf_energy,
        algorithm=alg_spec.name,
        pool_type=alg_spec.pool_type,
        optimizer=alg_spec.optimizer,
        num_parameters=int(getattr(alg, "_n_classical_params", 0)),
        n_cnot=int(getattr(alg, "_n_cnot", 0)),
        n_pauli_trm_measures=int(getattr(alg, "_n_pauli_trm_measures", 0)),
        convergence_values=energy_hist,
        adapt_maxiter_reached=adapts_reached,
        final_eigenvalue=float(alg.get_gs_energy()),
        ground_truth=fci_energy if fci_energy != 0.0 else None,
    )
