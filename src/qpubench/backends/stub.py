"""Stub backends for testing and examples.

These adapters return synthetic results without touching any real hardware.
Use them to verify your runner / store pipeline before wiring up a real backend.

There are two of them rather than one because the two paradigms this framework
spans produce structurally different results, and a single gate-based stub
would only exercise half the record format. ``StubGateAdapter`` fills
``QuantumResult.expectation_values``; ``StubMBQCAdapter`` fills
``mbqc_rounds``, ``fidelity`` and ``shots``, and is the only adapter in the
package that exercises the measurement-pattern input path, the per-round
byproduct-operator bookkeeping, and the reversed MBQC bit order (bit 0 = Z,
bit 1 = X) documented in ``schemas/mirrors/johnrscott_mbqc_fpga.py``. MBQC hardware is
an FPGA on someone's bench, not a pip-installable simulator, so without this
stub none of that would be reachable in CI or in an example.
"""
from __future__ import annotations

import random

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.primitives import ComputingModel, FidelityMetric, JobStatus
from ..schemas.result import (
    ExpectationResult,
    FidelityResult,
    MBQCRoundResult,
    QuantumResult,
    ShotResult,
)


class StubGateAdapter:
    """Returns a random expectation value for every observable in the circuit."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._spec = BackendSpec.aer_statevector()

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append(
                f"StubGateAdapter expects GATE_BASED; got {circuit.computing_model}"
            )
        return warnings

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        ev = [
            ExpectationResult(
                observable_index=i,
                value=self._rng.uniform(-1.0, 0.0),
                std_error=self._rng.uniform(0.0, 0.05),
                num_shots=options.shots,
            )
            for i in range(len(circuit.observables))
        ]
        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=ev or None,
            status=JobStatus.SUCCEEDED,
            qpu_time_s=self._rng.uniform(0.1, 2.0),
        )


class StubMBQCAdapter:
    """Returns random MBQC outcomes with a synthetic Fubini-Study fidelity."""

    def __init__(self, seed: int | None = None, fidelity: float = 0.95) -> None:
        self._rng = random.Random(seed)
        self._fidelity = fidelity

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(
            name="stub_mbqc",
            provider="mbqc",
            computing_model=ComputingModel.MBQC,
        )

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.MBQC:
            warnings.append(
                f"StubMBQCAdapter expects MBQC; got {circuit.computing_model}"
            )
        return warnings

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Replay the measurement pattern with random outcomes.

        The core stores the pattern as a vendor-neutral dict, so the typed
        schema is rehydrated here in the adapter layer — that is what keeps
        ``schemas/circuit.py`` free of any MBQC-specific import.
        """
        if circuit.measurement_pattern is None:
            return QuantumResult(
                computing_model=ComputingModel.MBQC,
                status=JobStatus.FAILED,
                error_message="No measurement_pattern in CircuitSpec",
            )
        from ..schemas.mirrors.johnrscott_mbqc_fpga import MBQCPattern

        pattern = MBQCPattern.model_validate(circuit.measurement_pattern)

        N = pattern.num_logical_qubits
        D = pattern.num_rounds
        rounds = [
            MBQCRoundResult(
                round_index=d,
                outcomes=[self._rng.randint(0, 1) for _ in range(N)],
                byproduct_z=self._rng.randint(0, (1 << N) - 1),
                byproduct_x=self._rng.randint(0, (1 << N) - 1),
                settings_used=[self._rng.randint(0, 1) for _ in range(N)],
            )
            for d in range(D)
        ]

        final_outcomes = rounds[-1].outcomes
        corrected = [
            final_outcomes[q] ^ ((rounds[-1].byproduct_x >> q) & 1)
            for q in range(N)
        ]
        bitstring = "".join(str(corrected[q]) for q in reversed(range(N)))
        num_shots = options.shots if options.shots is not None else 1

        return QuantumResult(
            computing_model=ComputingModel.MBQC,
            mbqc_rounds=rounds,
            fidelity=FidelityResult(
                fidelity=self._fidelity + self._rng.gauss(0, 0.01),
                metric=FidelityMetric.FUBINI_STUDY,
            ),
            shots=ShotResult(
                num_qubits=N,
                num_shots=num_shots,
                counts={bitstring: num_shots},
            ),
            status=JobStatus.SUCCEEDED,
            qpu_time_s=self._rng.uniform(0.001, 0.01),
        )
