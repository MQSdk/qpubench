from __future__ import annotations

import datetime
import uuid
from typing import Any

import pydantic

from .backend import BackendSpec
from .circuit import CircuitSpec
from .advantage import QuantumAdvantageRecord
from .execution import ExecutionOptions
from .result import QuantumResult

SCHEMA_VERSION = "3.0.0"

def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class VQAConfig(pydantic.BaseModel):
    """VQE / VQA experiment *inputs* — what the user chose to run.

    Computed outputs (final energies, convergence history, final-ansatz
    statistics) live in VQAResult: they are produced by the run, never
    supplied by the user.

    Chemistry fields
    ----------------
    molecule, basis, num_electrons, num_alpha, num_beta

    Algorithm fields
    ----------------
    algorithm:  "UCCNVQE" | "ADAPTVQE" | "UCCNPQE" | "SPQE" | "VQE"
                | "TN_QC_OPT" | "COVO" | "MOL_MAP" | "QASM_GEN" | ...
    pool_type:  operator pool for UCC variants ("SD", "GSD", "SDTQ", "sa_SD")
    optimizer:  classical optimizer name
    mapper:     "Parity" | "JordanWigner" | "BravyiKitaev" | "MQS"
    ansatz:     "EfficientSU2" | "TwoLocal" | "UCCSD" | ...

    Cebule TN_QC_OPT fields
    -----------------------
    n_layers_network:  classical tensor network depth U(θ)
    n_layers_circuit:  quantum circuit layer count U(φ)

    Cross-record links
    ------------------
    ga_run_id / genome_hash        Xenakis GA search provenance
    classiq_synthesis_id           links to ClassiqSynthesisResult.program_id

    Vendor extension point
    ----------------------
    vendor_data:  vendor/tool-specific metadata with no shared cross-vendor
                  meaning, keyed by vendor (e.g. vendor_data={"cebule": {...}}).
                  New vendor-only fields go here instead of growing this model.
    """
    # Forbid unknown fields so pre-3.0 callers passing computed values
    # (final_eigenvalue, ground_truth, ...) fail loudly instead of silently
    # dropping data — those fields now live in VQAResult.
    model_config = pydantic.ConfigDict(extra="forbid")

    problem_type:             str                   # "chemistry", "optimization", "ml"
    molecule:                 str | None            = None
    basis:                    str | None            = None
    num_electrons:            int | None            = None
    num_alpha:                int | None            = None   # spin-up electrons
    num_beta:                 int | None            = None   # spin-down electrons
    algorithm:                str | None            = None
    pool_type:                str | None            = None
    mapper:                   str | None            = None   # "Parity"|"JW"|"BK"|"MQS"
    ansatz:                   str | None            = None
    optimizer:                str | None            = None
    n_layers_network:         int | None            = None   # Cebule TN depth
    n_layers_circuit:         int | None            = None   # Cebule circuit layers
    # Active-space fields (GSOpt / ExcitationSolve / any active-space VQE)
    active_electrons:         int | None            = None   # electrons in active space
    active_orbitals:          int | None            = None   # orbitals in active space
    # Cross-record links
    ga_run_id:                str | None            = None   # links to GARunResult.run_id
    genome_hash:              str | None            = None   # stable hash of evolved genome
    classiq_synthesis_id:     str | None            = None   # links to ClassiqSynthesisResult.program_id
    # Extension point for vendor/tool-specific metadata that has no shared
    # cross-vendor meaning.  New vendor-only fields go here (keyed by vendor,
    # e.g. vendor_data={"cebule": {...}}) instead of growing this model.
    vendor_data:              dict[str, Any]        = {}


class VQAResult(pydantic.BaseModel):
    """Computed outputs of a VQE / VQA run — produced, never user-supplied.

    Algorithm adapters and integration converters populate this from the
    actual run; the circuit-driven runner derives final_eigenvalue from
    QuantumResult.expectation_values when no VQAResult is supplied.

    Energies
    --------
    final_eigenvalue:  converged variational energy
    ground_truth:      computed exact reference (FCI / exact diagonalisation)
    hf_energy:         Hartree-Fock reference energy
    fci_energy:        Full CI energy (used as ground-truth fallback)

    Final-ansatz statistics
    -----------------------
    num_parameters, n_cnot, n_pauli_trm_measures, nfev

    Convergence
    -----------
    convergence_values:     energy per optimizer iteration
    convergence_parameters: parameter vector per iteration
    adapt_maxiter_reached:  True if ADAPT-VQE hit adapt_maxiter without converging

    Evolutionary search
    -------------------
    best_complexity:  Xenakis ad-hoc complexity score of the best genome
    """
    model_config = pydantic.ConfigDict(extra="forbid")

    final_eigenvalue:         float | None          = None
    ground_truth:             float | None          = None
    hf_energy:                float | None          = None   # Hartree-Fock reference
    fci_energy:               float | None          = None   # Full CI energy
    num_parameters:           int | None            = None   # parameters in final ansatz
    n_cnot:                   int | None            = None   # CNOT count in final circuit
    n_pauli_trm_measures:     int | None            = None   # total Pauli measurements
    nfev:                     int | None            = None   # total function evaluations
    convergence_values:       list[float]           = []
    convergence_parameters:   list[list[float]]     = []
    adapt_maxiter_reached:    bool                  = False
    best_complexity:          float | None          = None   # Xenakis complexity score

    @property
    def reference_energy(self) -> float | None:
        """ground_truth if set, else fci_energy."""
        return self.ground_truth if self.ground_truth is not None else self.fci_energy

    @property
    def energy_error(self) -> float | None:
        ref = self.reference_energy
        if self.final_eigenvalue is None or ref is None:
            return None
        return abs(self.final_eigenvalue - ref)

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

    vqa:           VQAConfig | None             = None   # experiment inputs
    vqa_result:    VQAResult | None             = None   # computed outputs
    num_qubits:    int
    circuit_depth: int | None                   = None
    ga_run_id:     str | None                   = None   # links this record to a GARunResult
    advantage:     QuantumAdvantageRecord | None = None   # Quantum Advantage Tracker metadata
    tags:          list[str]                    = []
    notes:         str                          = ""

    @classmethod
    def from_vqe(
        cls,
        *,
        circuit: CircuitSpec,
        backend: BackendSpec,
        options: ExecutionOptions,
        result: QuantumResult,
        vqa: VQAConfig,
        vqa_result: VQAResult | None = None,
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
            vqa_result=vqa_result,
            num_qubits=circuit.num_qubits,
            circuit_depth=circuit_depth,
            tags=tags or ["vqe"],
            run_id=run_id,
        )
