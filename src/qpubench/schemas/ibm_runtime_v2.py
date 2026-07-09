"""IBM Qiskit Runtime V2 schemas.

PUB structure and BitArray result metadata for EstimatorV2/SamplerV2.
"""

from __future__ import annotations

import enum

import pydantic


class IBMExecutionMode(str, enum.Enum):
    SESSION = "session"  # exclusive QPU hold; lowest queue latency; billed by wall time
    BATCH = "batch"  # jobs queued independently; billed by cumulative QPU time
    SINGLE = "single"  # one-shot job; no session or batch context


class IBMPrimitiveType(str, enum.Enum):
    ESTIMATOR = "estimator"  # EstimatorV2 — returns expectation values ± stds
    SAMPLER = "sampler"  # SamplerV2   — returns BitArray shot data


class IBMEstimatorPUB(pydantic.BaseModel):
    """IBM EstimatorV2 Primitive Unified Bloc (PUB).

    EstimatorV2.run(pubs) where each PUB is:
      (circuit, observables, parameter_values?, precision?)

    observable_labels   SparsePauliOp Pauli string labels, e.g. ["ZZ", "IXX"].
    parameter_values    flat vector of parameter bindings (broadcast by Qiskit).
    precision           target statistical precision σ; replaces fixed shot count.
    """

    observable_labels: list[str] = []
    parameter_values: list[float] = []
    precision: float | None = None


class IBMSamplerPUB(pydantic.BaseModel):
    """IBM SamplerV2 Primitive Unified Bloc (PUB).

    SamplerV2.run(pubs) where each PUB is:
      (circuit, parameter_values?, shots?)
    """

    parameter_values: list[float] = []
    shots: int | None = None


class IBMExecutionSpan(pydantic.BaseModel):
    """One ExecutionSpan from IBM Runtime result metadata.

    IBM Runtime returns a list of SliceSpan / DoubleSliceSpan objects; each
    carries start/stop wall-clock timestamps and index slices that map the
    span to specific PUB result indices.

    start_iso / stop_iso   ISO-8601 UTC timestamps.
    pub_indices            PUB result indices covered by this span.
    """

    start_iso: str | None = None  # ISO-8601 UTC
    stop_iso: str | None = None
    duration_s: float | None = None
    pub_indices: list[int] = []


class IBMBitArrayMeta(pydantic.BaseModel):
    """Metadata describing a SamplerV2 BitArray result.

    BitArray preserves the full ND structure of a parameterized PUB:
      shape = (num_parameter_sets, num_shots_per_set)
    For a non-parametric circuit: shape = (num_shots,).

    The dense shot data is held in QuantumResult.shots (ShotResult) after
    the adapter converts BitArray to bitstring counts via .get_counts().
    """

    shape: list[int]  # ND shape, e.g. [1024] or [50, 512]
    num_bits: int
    register_name: str = "meas"


class IBMRuntimeRecord(pydantic.BaseModel):
    """IBM Quantum Runtime job metadata.

    Captures session/batch context, PUB structure, and timing spans for
    reproducible experiment annotation on QuantumResult.

    session_id   IBM Runtime Session ID; None for BATCH and SINGLE modes.
    batch_id     IBM Runtime Batch ID; None for SESSION and SINGLE modes.
    resilience_level   0 (raw) | 1 (TREX) | 2 (ZNE) | 3 (PEC) —
                       maps to ErrorMitigationStrategy values.
    """

    job_id: str | None = None
    session_id: str | None = None  # None for BATCH / SINGLE
    batch_id: str | None = None  # None for SESSION / SINGLE
    execution_mode: IBMExecutionMode = IBMExecutionMode.SINGLE
    primitive_type: IBMPrimitiveType = IBMPrimitiveType.ESTIMATOR
    backend_name: str | None = None
    resilience_level: int | None = None  # 0–3
    shots: int | None = None
    execution_spans: list[IBMExecutionSpan] = []
    estimator_pub: IBMEstimatorPUB | None = None
    sampler_pub: IBMSamplerPUB | None = None
    bit_array_meta: IBMBitArrayMeta | None = None  # populated on Sampler path
