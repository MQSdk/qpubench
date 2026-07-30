"""Mitiq zero-noise extrapolation (ZNE) error-mitigation adapter.

Install: pip install 'qpubench[mitiq]'   (mitiq + ply — see note below)

Wraps any inner `BackendAdapter` with Mitiq's real ZNE
(`mitiq.zne.inference` factories): fold gates to scale up circuit noise,
execute each noise-scaled circuit through the wrapped adapter, and
extrapolate back to the zero-noise limit.

Verified in this repo's own sandbox: wrapping a depolarizing-noise Aer
simulator (2% single-qubit / 5% two-qubit error on H/CX) recovers
`<ZZ> = 0.993` for a Bell state via ZNE, against the raw noisy estimate's
`0.950` and a noiseless-exact `1.0` — real bias reduction, not a stub.

Gotcha found while verifying: `mitiq.zne.execute_with_zne`/`Factory.run()`
convert Qiskit circuits through Cirq internally to do gate folding.
`cirq-core` ships as a real dependency of `mitiq`, but Cirq's own QASM
import path needs the `ply` parser-generator package, which neither
`mitiq` nor `cirq-core` declares as a dependency — a bare `pip install
mitiq` fails with `ModuleNotFoundError: No module named 'ply'` the first
time a Qiskit circuit is folded, hence `ply` is listed explicitly here.

Only `MitiqNoiseScalingMethod.FOLD_GLOBAL` and `.FOLD_GATES_RANDOM` map to
a real Mitiq function in the installed mitiq 1.x — `.FOLD_GATES_FROM_LEFT`
/`.FOLD_GATES_FROM_RIGHT`/`.PULSE_STRETCH` aren't implemented there and
raise `NotImplementedError` rather than silently substituting a different
scaling method.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.mirrors.unitaryfund_mitiq import (
    MitiqNoiseScalingMethod,
    MitiqZNEConfig,
    MitiqZNEFactory,
)
from ..schemas.primitives import JobStatus
from ..schemas.result import ExpectationResult, QuantumResult
from ._qiskit_common import load_qiskit_circuit as _load_qiskit_circuit

if TYPE_CHECKING:
    from .base import BackendAdapter

_SCALE_NOISE_FN_NAMES: dict[MitiqNoiseScalingMethod, str] = {
    MitiqNoiseScalingMethod.FOLD_GLOBAL: "fold_global",
    MitiqNoiseScalingMethod.FOLD_GATES_RANDOM: "fold_gates_at_random",
}


class MitiqZNEAdapter:
    """Wraps a `BackendAdapter` with Mitiq zero-noise extrapolation.

    Only meaningful for the estimator path (`circuit.observables` set) —
    ZNE extrapolates an expectation value, not raw shot counts, so the
    sampler path (no observables) delegates straight to `inner.run()`.
    """

    def __init__(self, inner: BackendAdapter, config: MitiqZNEConfig | None = None) -> None:
        self._inner = inner
        self._config = config or MitiqZNEConfig()

    @property
    def spec(self) -> BackendSpec:
        return self._inner.spec

    @property
    def inner(self) -> BackendAdapter:
        return self._inner

    def validate(self, circuit: CircuitSpec) -> list[str]:
        return self._inner.validate(circuit)

    def _factory(self) -> Any:
        from mitiq.zne import inference

        scale_factors = self._config.scale_factors
        if self._config.factory == MitiqZNEFactory.LINEAR:
            return inference.LinearFactory(scale_factors)
        if self._config.factory == MitiqZNEFactory.RICHARDSON:
            return inference.RichardsonFactory(scale_factors)
        if self._config.factory == MitiqZNEFactory.POLY2:
            return inference.PolyFactory(scale_factors, order=2)
        if self._config.factory == MitiqZNEFactory.EXP:
            return inference.ExpFactory(scale_factors)
        raise ValueError(f"Unknown MitiqZNEFactory {self._config.factory!r}")

    def _scale_noise_fn(self) -> Any:
        from mitiq.zne import scaling

        fn_name = _SCALE_NOISE_FN_NAMES.get(self._config.scaling_method)
        if fn_name is None:
            raise NotImplementedError(
                f"MitiqNoiseScalingMethod.{self._config.scaling_method.name} isn't "
                "implemented in mitiq 1.x — only FOLD_GLOBAL and FOLD_GATES_RANDOM "
                "are wired here"
            )
        return getattr(scaling, fn_name)

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        if not circuit.observables:
            # ZNE mitigates an expectation value; raw sampling has none to
            # extrapolate, so pass the circuit straight through unmitigated.
            return self._inner.run(circuit, options)

        qc = _load_qiskit_circuit(circuit)
        scale_noise = self._scale_noise_fn()

        evs: list[ExpectationResult] = []
        for index, observable in enumerate(circuit.observables):
            # No return-type annotation on purpose: Mitiq's Executor reads
            # the executor's *live* return annotation to decide how to parse
            # results. Under this module's `from __future__ import
            # annotations`, `-> float` becomes the string "float" instead of
            # the `float` type, and Mitiq fails with "Could not parse
            # executed results from executor with type float" — confirmed
            # in this repo's own sandbox. Leaving it unannotated lets Mitiq
            # infer the type from the actual returned value instead.
            def executor(scaled_qc):  # type: ignore[no-untyped-def]
                from qiskit import qasm3

                scaled_circuit = circuit.model_copy(
                    update={
                        "serialized": qasm3.dumps(scaled_qc),
                        "format": circuit.format,
                        "observables": [observable],
                    }
                )
                result = self._inner.run(scaled_circuit, options)
                assert result.expectation_values is not None
                return result.expectation_values[0].value

            factory = self._factory()
            factory.run(
                qc,
                executor,
                scale_noise=scale_noise,
                num_to_average=self._config.num_to_average,
            )
            extrapolated_value = float(factory.reduce())
            try:
                # Undefined (raises) whenever the fit has zero residual
                # degrees of freedom — e.g. RichardsonFactory (the config
                # default) interpolates exactly through every point, so
                # there's no residual to estimate a covariance from.
                extrapolation_error = float(factory.get_zero_noise_limit_error())
            except ValueError:
                extrapolation_error = 0.0
            evs.append(
                ExpectationResult(
                    observable_index=index,
                    value=extrapolated_value,
                    std_error=extrapolation_error,
                    num_shots=options.shots,
                    raw_values=[float(v) for v in factory.get_expectation_values()],
                )
            )

        return QuantumResult(
            computing_model=circuit.computing_model,
            expectation_values=evs,
            status=JobStatus.SUCCEEDED,
        )
