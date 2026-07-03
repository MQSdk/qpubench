from __future__ import annotations

import datetime
import uuid

import pydantic

from .backend import BackendSpec
from .circuit import CircuitSpec
from .execution import ExecutionOptions
from .result import QuantumResult

SCHEMA_VERSION = "1.11.0"

def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class VQAConfig(pydantic.BaseModel):
    """VQE / VQA-specific experiment metadata.

    Replaces the implicit 16-column DataFrame schema from VQEBench,
    extended to cover algorithm-library runs (QForte UCCNVQE, ADAPT-VQE, etc.),
    Qiskit-based workflows, and Cebule SDK tasks (TN_QC_OPT, COVO, MOL_MAP).

    Chemistry fields (always)
    -------------------------
    molecule, basis, num_electrons, num_alpha, num_beta, hf_energy, fci_energy

    Algorithm fields
    ----------------
    algorithm:      "UCCNVQE" | "ADAPTVQE" | "UCCNPQE" | "SPQE" | "VQE"
                    | "TN_QC_OPT" | "COVO" | "MOL_MAP" | "QASM_GEN" | …
    pool_type:      operator pool for UCC variants ("SD", "GSD", "SDTQ", "sa_SD")
    optimizer:      classical optimizer name
    num_parameters: number of variational parameters in final ansatz

    Qiskit / Cebule mapper
    ----------------------
    mapper:  "Parity" | "JordanWigner" | "BravyiKitaev" | "MQS"
    ansatz:  "EfficientSU2" | "TwoLocal" | "UCCSD" | …

    Cebule TN_QC_OPT fields
    -----------------------
    n_layers_network:  classical tensor network depth U(θ)
    n_layers_circuit:  quantum circuit layer count U(φ)

    Convergence
    -----------
    convergence_values:     energy per optimizer iteration
    convergence_parameters: parameter vector per iteration
    adapt_maxiter_reached:  True if ADAPT-VQE hit adapt_maxiter without converging
    """
    problem_type:             str                   # "chemistry", "optimization", "ml"
    molecule:                 str | None            = None
    basis:                    str | None            = None
    num_electrons:            int | None            = None
    num_alpha:                int | None            = None   # spin-up electrons
    num_beta:                 int | None            = None   # spin-down electrons
    hf_energy:                float | None          = None   # Hartree-Fock reference
    fci_energy:               float | None          = None   # Full CI energy (COVO output)
    algorithm:                str | None            = None
    pool_type:                str | None            = None
    mapper:                   str | None            = None   # "Parity"|"JW"|"BK"|"MQS"
    ansatz:                   str | None            = None
    optimizer:                str | None            = None
    num_parameters:           int | None            = None
    n_cnot:                   int | None            = None   # CNOT count in final circuit
    n_pauli_trm_measures:     int | None            = None   # total Pauli measurements
    n_layers_network:         int | None            = None   # Cebule TN depth
    n_layers_circuit:         int | None            = None   # Cebule circuit layers
    # Active-space fields (GSOpt / ExcitationSolve / any active-space VQE)
    active_electrons:         int | None            = None   # electrons in active space
    active_orbitals:          int | None            = None   # orbitals in active space
    nfev:                     int | None            = None   # total function evaluations
    # Evolutionary circuit search fields (Xenakis family)
    ga_run_id:                str | None            = None   # links to GARunResult.run_id
    genome_hash:              str | None            = None   # stable hash of evolved genome
    best_complexity:          float | None          = None   # Xenakis ad-hoc complexity score
    convergence_values:       list[float]           = []
    convergence_parameters:   list[list[float]]     = []
    adapt_maxiter_reached:    bool                  = False
    final_eigenvalue:         float | None          = None
    ground_truth:             float | None          = None

    @property
    def energy_error(self) -> float | None:
        if self.final_eigenvalue is None or self.ground_truth is None:
            return None
        return abs(self.final_eigenvalue - self.ground_truth)

    @property
    def chemical_accuracy(self) -> bool | None:
        err = self.energy_error
        if err is None:
            return None
        return err < 1.6e-3    # 1 mHartree threshold


class BenchmarkRecord(pydantic.BaseModel):
    """Single benchmark execution record.

    One record = one circuit/problem × one backend × one options configuration.
    Use run_id to group records belonging to the same parameter sweep.
    """
    model_config = pydantic.ConfigDict()

    schema_version: str               = SCHEMA_VERSION
    experiment_id:  str               = pydantic.Field(
        default_factory=lambda: str(uuid.uuid4())
    )
    run_id:         str | None        = None
    timestamp:      datetime.datetime = pydantic.Field(
        default_factory=_utcnow
    )

    circuit:  CircuitSpec
    backend:  BackendSpec
    options:  ExecutionOptions
    result:   QuantumResult

    vqa:           VQAConfig | None = None
    num_qubits:    int
    circuit_depth: int | None       = None
    ga_run_id:     str | None       = None   # links this record to a GARunResult
    tags:          list[str]        = []
    notes:         str              = ""

    @classmethod
    def from_vqe(
        cls,
        *,
        circuit: CircuitSpec,
        backend: BackendSpec,
        options: ExecutionOptions,
        result: QuantumResult,
        vqa: VQAConfig,
        circuit_depth: int | None = None,
        tags: list[str] | None    = None,
        run_id: str | None        = None,
    ) -> BenchmarkRecord:
        return cls(
            circuit=circuit,
            backend=backend,
            options=options,
            result=result,
            vqa=vqa,
            num_qubits=circuit.num_qubits,
            circuit_depth=circuit_depth,
            tags=tags or ["vqe"],
            run_id=run_id,
        )
