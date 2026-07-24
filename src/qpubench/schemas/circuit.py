from __future__ import annotations

from typing import Any

import pydantic

from .observable import SparsePauliObservable
from .primitives import CircuitFormat, ComputingModel, QubitModality


class ParameterBinding(pydantic.BaseModel):
    """One bound value for a named circuit parameter.

    Used for parametric circuits (VQE ansätze, QAOA).  A CircuitSpec may
    carry parameter names without bindings (abstract template) or with
    bindings (ready to execute).
    """
    name:  str
    value: float


class CircuitSpec(pydantic.BaseModel):
    """Modality-agnostic circuit specification.

    Gate-based (QASM2 / QASM3)
    --------------------------
    Populate serialized and format.  OpenQASM 3.0 is the preferred format for
    new circuits — use CircuitFormat.QASM3 and set serialized to the full
    OpenQASM 3.0 source string, or call CircuitSpec.from_openqasm3().
    For parametric circuits (VQE): set parameters and parameter_bindings.
    gate_counts can be populated after transpilation for record-keeping.

    Cebule SDK (QASM_GEN output)
    ----------------------------
    QASM_GEN produces multiple circuits (one per Pauli grouping); wrap each
    element of circuit_files as a CircuitSpec with format=QASM2 and attach
    the shared postprocessing_instructions via the observables field.

    MBQC
    ----
    Populate measurement_pattern. serialized is optional (JSON archive copy).

    Vendor-neutral extension fields
    -------------------------------
    measurement_pattern and photonic_circuit are stored as plain dicts so the
    core stays free of vendor schema imports.  Pass any Pydantic model (it is
    dumped automatically) and rehydrate with the vendor schema of your choice:

        from qpubench.schemas.johnrscott_mbqc_fpga import MBQCPattern
        spec = CircuitSpec(..., measurement_pattern=pattern)      # model or dict
        pattern = MBQCPattern.model_validate(spec.measurement_pattern)

        from qpubench.schemas.mqsdk_photoq import PhotonicCircuitSpec
        photonic = PhotonicCircuitSpec.model_validate(spec.photonic_circuit)
    """
    computing_model:     ComputingModel          = ComputingModel.GATE_BASED
    qubit_modality:      QubitModality | None    = None
    num_qubits:          int
    num_classical_bits:  int | None              = None
    format:              CircuitFormat           = CircuitFormat.QASM2
    serialized:          str | None              = None
    observables:         list[SparsePauliObservable] = []
    precision:           float                   = 0.01
    parameters:          list[str]               = []
    parameter_bindings:  list[ParameterBinding]  = []
    gate_counts:         dict[str, int]          = {}
    measurement_pattern: dict[str, Any] | None   = None  # e.g. johnrscott_mbqc_fpga.MBQCPattern dump
    photonic_circuit:    dict[str, Any] | None   = None  # e.g. mqsdk_photoq.PhotonicCircuitSpec dump

    @pydantic.field_validator("measurement_pattern", "photonic_circuit", mode="before")
    @classmethod
    def _dump_vendor_models(cls, v: Any) -> Any:
        # Accept any vendor Pydantic model directly; store its dict dump so
        # the core schema stays vendor-neutral and JSON-serialisable.
        return v.model_dump() if isinstance(v, pydantic.BaseModel) else v

    @pydantic.model_validator(mode="after")
    def _check_consistency(self) -> CircuitSpec:
        if self.computing_model == ComputingModel.MBQC:
            if self.measurement_pattern is None and self.serialized is None:
                raise ValueError(
                    "MBQC CircuitSpec requires measurement_pattern or serialized"
                )
        if (
            self.computing_model == ComputingModel.FUSION_BASED
            or self.qubit_modality == QubitModality.PHOTONIC
        ):
            if self.photonic_circuit is None and self.serialized is None:
                raise ValueError(
                    "Photonic CircuitSpec requires photonic_circuit or serialized"
                )
        for pb in self.parameter_bindings:
            if pb.name not in self.parameters:
                raise ValueError(
                    f"parameter_binding {pb.name!r} not declared in parameters list"
                )
        return self

    # ------------------------------------------------------------------
    # OpenQASM 3.0 helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_openqasm3(
        cls,
        source: str,
        *,
        num_qubits: int,
        **kwargs: Any,
    ) -> CircuitSpec:
        """Construct a CircuitSpec from an OpenQASM 3.0 source string."""
        return cls(
            num_qubits=num_qubits,
            format=CircuitFormat.QASM3,
            serialized=source,
            **kwargs,
        )

    @property
    def openqasm3(self) -> str | None:
        """Return the OpenQASM 3.0 source string, or None if format is not QASM3."""
        return self.serialized if self.format == CircuitFormat.QASM3 else None

    @property
    def openqasm2(self) -> str | None:
        """Return the OpenQASM 2.0 source string, or None if format is not QASM2."""
        return self.serialized if self.format == CircuitFormat.QASM2 else None

    # ------------------------------------------------------------------

    def is_parametric(self) -> bool:
        return bool(self.parameters)

    def is_bound(self) -> bool:
        return bool(self.parameters) and len(self.parameter_bindings) == len(self.parameters)

    def bind(self, values: dict[str, float]) -> CircuitSpec:
        """Return a copy with parameter bindings applied."""
        bindings = [ParameterBinding(name=k, value=v) for k, v in values.items()]
        return self.model_copy(update={"parameter_bindings": bindings})

    @property
    def total_gates(self) -> int | None:
        """Total gate count summed over gate_counts, or None if not populated.

        Note: this is a gate count, not a circuit depth — for wide circuits
        with parallel gates the true depth is much smaller.
        """
        if not self.gate_counts:
            return None
        return sum(self.gate_counts.values())
