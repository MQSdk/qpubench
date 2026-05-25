from __future__ import annotations

import pydantic

from .photonic import (
    HOMResult,
    IndistinguishabilityPurificationResult,
    PhotonicAnalogSimResult,
    PhotonicSimulationResult,
    PhotonicSensitivityAnalysis,
    PhotonicVQEResult,
)
from .gbs import (
    GBSCliqueFindingResult,
    GBSSamplingResult,
    VibronicSpectrumResult,
    TDMGBSResult,
)
from .primitives import CircuitFormat, FidelityMetric, JobStatus, QPUModality
from .qdk_chemistry import QPEResult, QChemPipelineSpec
from .qse import KQDPipelineSpec
from .qesem import QESEMJobRecord
from .qcschema import QCSchemaRecord
from .neutral_atom import AHSTaskResult
from .slowquant import SlowQuantRecord


class TranspileLayout(pydantic.BaseModel):
    """Qubit permutation produced by gate-based transpilation.

    Mirrors Qiskit C QkTranspileLayout (three uint32_t[] arrays).
    Index = virtual qubit index; value = physical qubit index.

    initial_layout    placement stage mapping
    final_layout      combined initial + SWAP-routing permutation
    output_permutation SWAP-induced rearrangement only
    """
    num_virtual:          int
    num_physical:         int
    initial_layout:       list[int]        # len = num_virtual
    final_layout:         list[int]        # len = num_virtual
    output_permutation:   list[int] = []   # len = num_physical; empty if no SWAPs

    @pydantic.model_validator(mode="after")
    def _check_lengths(self) -> TranspileLayout:
        if len(self.initial_layout) != self.num_virtual:
            raise ValueError(
                f"initial_layout length {len(self.initial_layout)} "
                f"!= num_virtual {self.num_virtual}"
            )
        if len(self.final_layout) != self.num_virtual:
            raise ValueError(
                f"final_layout length {len(self.final_layout)} "
                f"!= num_virtual {self.num_virtual}"
            )
        return self


class AdaptIteration(pydantic.BaseModel):
    """Metrics for one ADAPT-VQE macro-iteration.

    Captured from QForte ADAPTVQE attributes after each operator addition:
      _energies[i]                → energy
      _grad_norms[i]              → grad_norm
      _n_cnot_lst[i]              → n_cnot
      _n_classical_params_lst[i]  → n_classical_params
      len(_tops) at iteration i   → n_operators
    """
    iteration:          int
    energy:             float
    grad_norm:          float
    n_operators:        int    # operators in ansatz at this iteration
    n_cnot:             int
    n_classical_params: int
    n_pauli_measures:   int = 0


class ExpectationResult(pydantic.BaseModel):
    """Expectation value of one observable.

    observable_index references CircuitSpec.observables[i].
    raw_values holds per-noise-factor values when ZNE is used.
    std_error is the statistical standard error from shot noise.
    """
    observable_index: int
    value:       float
    std_error:   float
    num_shots:   int | None  = None
    raw_values:  list[float] = []     # per ZNE noise factor, pre-extrapolation


class FidelityResult(pydantic.BaseModel):
    """State or process fidelity between the executed and a reference state.

    Qrack:     metric=UNITARY,      fidelity from GetUnitaryFidelity()
    MBQC-FPGA: metric=FUBINI_STUDY, fidelity = 1 - qsl::fubiniStudy(result, ref)
    """
    fidelity:        float
    metric:          FidelityMetric = FidelityMetric.UNITARY
    reference_label: str | None     = None


class ShotResult(pydantic.BaseModel):
    """Raw shot-level sampling outcomes.

    counts keys are MSB-first bitstrings (Qiskit convention).
    For Qrack MeasureShots integer outcomes are converted by the adapter.

    memory holds per-shot bitstrings when ExecutionOptions.memory=True.
    """
    num_qubits: int
    num_shots:  int
    counts:     dict[str, int]    # bitstring -> count
    memory:     list[str]         = []   # per-shot bitstrings if memory=True

    def probabilities(self) -> dict[str, float]:
        total = sum(self.counts.values()) or 1
        return {k: v / total for k, v in self.counts.items()}

    def most_probable(self) -> str:
        return max(self.counts, key=self.counts.__getitem__)

    def marginal(self, qubits: list[int]) -> dict[str, int]:
        """Marginalise counts over a subset of qubits (by index, MSB=0)."""
        n = self.num_qubits
        result: dict[str, int] = {}
        for bitstring, count in self.counts.items():
            key = "".join(bitstring[n - 1 - q] for q in sorted(qubits, reverse=True))
            result[key] = result.get(key, 0) + count
        return result


class MBQCRoundResult(pydantic.BaseModel):
    """Summary of one measurement round across all logical qubits.

    byproduct_z and byproduct_x are packed N-bit integers; bit q = qubit q.
    ops register convention: Z=bit0, X=bit1 per qubit (byproduct.vhd).
    """
    round_index:   int
    outcomes:      list[int]    # 0 or 1 per logical qubit
    byproduct_z:   int          # packed N-bit
    byproduct_x:   int          # packed N-bit
    settings_used: list[int]    # s value applied per qubit


class QuantumResult(pydantic.BaseModel):
    """Top-level execution result, modality-agnostic.

    Populate only the fields relevant to the execution.

    Gate-based typical output
    -------------------------
    expectation_values  — Estimator path (VQE, QAOA objective)
    shots               — Sampler path (raw counts ± per-shot memory)
    quasi_probabilities — PEC / TREX mitigated probabilities
    transpile_layout    — virtual → physical qubit mapping used
    transpiled_circuit  — QASM/QGC of the circuit after transpilation

    Algorithm-driven output (QForte etc.)
    -------------------------------------
    expectation_values  — final energy as observable_index=0
    adapt_history       — per-macro-iteration metrics (ADAPT-VQE only)

    MBQC output
    -----------
    mbqc_rounds         — per-round measurement and byproduct register state
    fidelity            — Fubini-Study distance from reference (sim only)
    shots               — corrected bitstring counts
    """
    modality:            QPUModality
    expectation_values:  list[ExpectationResult] | None = None
    shots:               ShotResult | None               = None
    fidelity:            FidelityResult | None           = None
    mbqc_rounds:         list[MBQCRoundResult] | None    = None
    adapt_history:       list[AdaptIteration] | None     = None
    quasi_probabilities: dict[str, float] | None         = None
    transpile_layout:          TranspileLayout | None   = None
    transpiled_circuit:        str | None               = None
    transpiled_circuit_format: CircuitFormat | None     = None
    status:                    JobStatus                = JobStatus.SUCCEEDED
    job_id:              str | None                      = None
    qpu_time_s:          float | None                    = None
    total_time_s:        float | None                    = None
    error_message:         str | None                    = None
    wall_seconds:          float | None                  = None   # actual wall time
    wall_budget_seconds:   float | None                  = None   # allowed budget (GSOpt)
    metadata:              dict                          = {}
    # Photonic-modality result fields (QPUModality.PHOTONIC_LINEAR_OPTICS / FUSION_BASED)
    photonic_simulation:        PhotonicSimulationResult | None                 = None
    photonic_vqe:               PhotonicVQEResult | None                        = None
    photonic_sensitivity:       PhotonicSensitivityAnalysis | None              = None
    hom_result:                 HOMResult | None                                = None
    indist_purification:        IndistinguishabilityPurificationResult | None   = None
    photonic_analog_sim:        PhotonicAnalogSimResult | None                  = None
    # QPE-modality result fields (QPUModality.QPE)
    qpe_result:                 QPEResult | None                                = None
    qchem_pipeline:             QChemPipelineSpec | None                        = None
    # GBS-modality result fields (QPUModality.GBS)
    gbs_sampling:               GBSSamplingResult | None                        = None
    gbs_clique_finding:         GBSCliqueFindingResult | None                   = None
    vibronic_spectrum:          VibronicSpectrumResult | None                   = None
    tdm_gbs:                    TDMGBSResult | None                             = None
    # KQD-modality result fields (QPUModality.KQD)
    kqd_pipeline:               KQDPipelineSpec | None                          = None
    # QESEM (Qedma) error suppression/mitigation result fields
    qesem_result:               QESEMJobRecord | None                           = None
    # QCSchema / QCElemental / PennyLane quantum chemistry reference record
    qcschema_record:            QCSchemaRecord | None                           = None
    # Neutral-atom (Rydberg / AHS) result fields (QPUModality.NEUTRAL_ATOM)
    ahs_result:                 AHSTaskResult | None                            = None
    # SlowQuant UCC / VQE calculation record
    slowquant_record:           SlowQuantRecord | None                          = None

    @property
    def openqasm3_transpiled(self) -> str | None:
        """Return the transpiled circuit as OpenQASM 3.0, or None."""
        if self.transpiled_circuit_format == CircuitFormat.QASM3:
            return self.transpiled_circuit
        return None
