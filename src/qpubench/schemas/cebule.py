"""Cebule SDK (MQS) task input/output schemas.

Maps the four Cebule task types to typed Pydantic models that slot cleanly
into qpubench CircuitSpec / QuantumResult / VQAConfig records.

Task types
----------
MOL_MAP    molecular geometry → qubit Hamiltonian (constraint-based encoding)
QASM_GEN   Hamiltonian → OpenQASM measurement circuits + post-processing table
TN_QC_OPT  tensor-network + quantum circuit hybrid VQE optimisation
COVO       correlation-optimised virtual orbital pre-processing

SDK session pattern
-------------------
    import mqsdk, os
    session = mqsdk.Cebule(os.environ['EMAIL'], os.environ['PASSWORD'])
    task = session.cebule.create_task(title, TaskType.*, input_data)
"""
from __future__ import annotations

from typing import Any

import pydantic

from .circuit import CircuitSpec
from .primitives import CebuleTaskType, CircuitFormat
from .observable import SparsePauliObservable


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

class MolecularGeometry(pydantic.BaseModel):
    """Cartesian molecular geometry shared by MOL_MAP and COVO inputs.

    geometry is a flat 1-D list of Cartesian coordinates in Angstroms,
    ordered as (x0, y0, z0, x1, y1, z1, ...).
    """
    geometry:     list[float]
    symbols:      list[str]
    basis:        str = "sto3g"
    multiplicity: int = 1
    charge:       int = 0

    @pydantic.model_validator(mode="after")
    def _check_geometry(self) -> MolecularGeometry:
        if len(self.geometry) != 3 * len(self.symbols):
            raise ValueError(
                f"geometry length {len(self.geometry)} must be 3 × "
                f"len(symbols) = {3 * len(self.symbols)}"
            )
        return self


# ---------------------------------------------------------------------------
# MOL_MAP
# ---------------------------------------------------------------------------

class MolMapInput(pydantic.BaseModel):
    """Input for the Cebule MOL_MAP task."""
    task_type: CebuleTaskType = CebuleTaskType.MOL_MAP
    molecule:  MolecularGeometry


class MolMapResult(pydantic.BaseModel):
    """Output of the Cebule MOL_MAP task.

    mapped_hamiltonian  sparse matrix (2-D) of the qubit Hamiltonian after
                        constraint-based encoding; rows/cols = qubit basis states
    hf_state            Hartree-Fock ground state in the mapped qubit basis
    mapping_matrix      bijective mapping operator D (2-D)
    num_qubits          qubit count after encoding (< 2N for constraint encoding)
    """
    mapped_hamiltonian: list[list[float]]
    hf_state:           list[int]
    mapping_matrix:     list[list[float]]
    num_qubits:         int | None = None

    def to_sparse_pauli_observable(
        self,
        num_qubits: int,
        operators: list[str],
        coefficients: list[float],
    ) -> SparsePauliObservable:
        """Convert qubit operator strings + coefficients to a SparsePauliObservable.

        operators and coefficients come from a follow-up TN_QC_OPT result
        (qubit_operators / h_tn_opt_qubit).
        """
        return SparsePauliObservable.from_cebule_operators(
            operators, coefficients, num_qubits
        )


# ---------------------------------------------------------------------------
# QASM_GEN
# ---------------------------------------------------------------------------

class QASMGenInput(pydantic.BaseModel):
    """Input for the Cebule QASM_GEN task.

    operator is a Hermitian sparse matrix (2-D list) whose expectation value
    is to be measured.  Either state_vector or state_circuit (OpenQASM string)
    may be supplied for state preparation; both are optional.
    """
    task_type:             CebuleTaskType = CebuleTaskType.QASM_GEN
    operator:              list[list[float]]
    state_vector:          list[float] | None = None
    state_circuit:         str | None         = None
    include_state_circuit: bool               = True


class QASMGenResult(pydantic.BaseModel):
    """Output of the Cebule QASM_GEN task.

    circuit_files             one OpenQASM 2.0 string per Pauli grouping
    postprocessing_instructions  2-D table: each row encodes how to combine
                              measurement outcomes for that circuit into the
                              final expectation value (sign/coefficient data)
    state_circuit             state preparation sub-circuit (OpenQASM 2.0)
    """
    circuit_files:               list[str]
    postprocessing_instructions: list[list[float]]
    state_circuit:               str | None = None

    def to_circuit_specs(self, num_qubits: int) -> list[CircuitSpec]:
        """Wrap each circuit_file as a CircuitSpec with format=QASM2."""
        return [
            CircuitSpec(
                num_qubits=num_qubits,
                format=CircuitFormat.QASM2,
                serialized=src,
            )
            for src in self.circuit_files
        ]

    def to_openqasm3_circuit_specs(
        self,
        num_qubits: int,
        qasm3_sources: list[str],
    ) -> list[CircuitSpec]:
        """Wrap caller-supplied OpenQASM 3.0 transpilations of each circuit.

        Use this when a downstream transpiler (e.g. Qiskit) has converted the
        QASM_GEN output circuits to OpenQASM 3.0 format.
        """
        if len(qasm3_sources) != len(self.circuit_files):
            raise ValueError(
                f"qasm3_sources length {len(qasm3_sources)} != "
                f"circuit_files length {len(self.circuit_files)}"
            )
        return [
            CircuitSpec.from_openqasm3(src, num_qubits=num_qubits)
            for src in qasm3_sources
        ]


# ---------------------------------------------------------------------------
# TN_QC_OPT
# ---------------------------------------------------------------------------

class TNQCOptInput(pydantic.BaseModel):
    """Input for the Cebule TN_QC_OPT task.

    h_operators accepts three operator formats (as in the SDK):
      Fermionic:    ((site, bool), ...)
      Qubit tuple:  ((qubit, 'X'|'Y'|'Z'), ...)
      Qubit string: "X0 Y1 Z3"

    Store the raw SDK value here; use SparsePauliObservable.from_cebule_operators()
    on the TNQCOptResult output for a typed representation.
    """
    task_type:        CebuleTaskType  = CebuleTaskType.TN_QC_OPT
    h_coeff_values:   list[float]
    h_operators:      list[Any]
    n_iterations:     int
    n_layers_network: int
    qasm_ansatz:      str | None     = None
    n_layers_circuit: int            = 3
    three_para_tn:    bool           = True
    theta_init:       list[float]    = []
    phi_init:         list[float]    = []
    conv_tol:         float | None   = None
    opt_method:       str            = "BFGS"
    backend:          str            = "lightning.qubit"   # or "qiskit.aer"


class TNQCOptResult(pydantic.BaseModel):
    """Output of the Cebule TN_QC_OPT task.

    qubit_operators uses space-separated PauliLabel+index tokens ("X0 Y1 Z3").
    Use SparsePauliObservable.from_cebule_operators(qubit_operators,
    h_tn_opt_qubit, num_qubits) to get a typed observable.
    """
    vqe_energy:      float
    phi:             list[float]   # optimised circuit parameters U(φ)
    theta:           list[float]   # optimised TN parameters U(θ)
    h_tn_opt_qubit:  list[float]   # optimised Hamiltonian coefficients
    qubit_operators: list[str]     # "X0 Y1 Z3" format, parallel to h_tn_opt_qubit

    def to_sparse_pauli_observable(self, num_qubits: int) -> SparsePauliObservable:
        return SparsePauliObservable.from_cebule_operators(
            self.qubit_operators, self.h_tn_opt_qubit, num_qubits
        )


# ---------------------------------------------------------------------------
# COVO
# ---------------------------------------------------------------------------

class COVOInput(pydantic.BaseModel):
    """Input for the Cebule COVO task (plane-wave periodic systems)."""
    task_type:          CebuleTaskType = CebuleTaskType.COVO
    geometry:           list[float]    # Cartesian coordinates in Angstroms (flat)
    symbols:            list[str]
    cell_size:          float          # simulation box side length (Å)
    periodic:           bool           = False
    cutoff:             float          # plane-wave energy cutoff (Hartree)
    n_virtual_orbitals: int
    charge:             int            = 0
    multiplicity:       int            = 1
    tolerance:          float          = 1.0e-6   # SCF convergence threshold

    @pydantic.model_validator(mode="after")
    def _check_geometry(self) -> COVOInput:
        if len(self.geometry) != 3 * len(self.symbols):
            raise ValueError(
                f"geometry length {len(self.geometry)} must be 3 × "
                f"len(symbols) = {3 * len(self.symbols)}"
            )
        return self


class COVOResult(pydantic.BaseModel):
    """Output of the Cebule COVO task.

    one_electron_integrals  N×N kinetic + nuclear attraction matrix
    two_electron_integrals  N⁴ electron repulsion tensor (N×N×N×N)
    hf_energy               Hartree-Fock energy (Hartree)
    fci_energy              Full CI energy (Hartree); reference for VQE error
    vqe_energy              VQE-optimised energy (Hartree)
    hamiltonian             full electronic Hamiltonian matrix (2-D)
    """
    one_electron_integrals: list[list[float]]
    two_electron_integrals: list[list[list[list[float]]]]
    hf_energy:              float
    fci_energy:             float
    vqe_energy:             float
    hamiltonian:            list[list[float]]

    @property
    def correlation_energy(self) -> float:
        """FCI correlation energy relative to Hartree-Fock."""
        return self.fci_energy - self.hf_energy

    @property
    def vqe_error(self) -> float:
        """VQE error vs FCI ground truth (absolute value)."""
        return abs(self.vqe_energy - self.fci_energy)


__all__ = [
    "COVOInput",
    "COVOResult",
    "MolMapInput",
    "MolMapResult",
    "MolecularGeometry",
    "QASMGenInput",
    "QASMGenResult",
    "TNQCOptInput",
    "TNQCOptResult",
]
