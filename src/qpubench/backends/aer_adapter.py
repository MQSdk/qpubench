"""Qiskit Aer backend adapter.

Install: pip install 'qpubench[qiskit]'

Supports:
  - Statevector simulation   (shots=None)
  - Shot-based QASM          (shots=N)
  - Per-shot memory          (options.memory=True -> ShotResult.memory)
  - Estimator path           (circuit.observables populated)
  - Sampler path             (circuit.observables empty)
  - Noise model injection    (pass via auth["noise_model_json"])

Uses qiskit_aer.primitives.EstimatorV2/SamplerV2 — the V1 Estimator/Sampler
classes have been deprecated since Aer 0.15 (confirmed against the installed
qiskit-aer 0.17.2: constructing either raises DeprecationWarning pointing at
the V2 classes used here).
"""
from __future__ import annotations

from typing import Any

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.primitives import CircuitFormat, ComputingModel, JobStatus
from ..schemas.result import (
    ExpectationResult,
    QuantumResult,
    ShotResult,
    TranspileLayout,
)
from ._qiskit_common import load_qiskit_circuit as _load_qiskit_circuit


class AerAdapter:
    """Qiskit Aer statevector / QASM simulator adapter.

    Parameters
    ----------
    noise_model_json:
        Optional JSON string produced by ``NoiseModel.to_dict()``.
        Injected into AerSimulator when provided.
    """

    def __init__(self, noise_model_json: str | None = None) -> None:
        self._noise_model_json = noise_model_json
        self._spec = BackendSpec.aer_statevector()

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append(
                f"AerAdapter expects GATE_BASED; got {circuit.computing_model}"
            )
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3, CircuitFormat.JSON):
            warnings.append(
                f"AerAdapter supports QASM2/3 or JSON; got {circuit.format}"
            )
        if circuit.is_parametric() and not circuit.is_bound():
            warnings.append("Circuit has unbound parameters; bind before running")
        return warnings

    def _build_noise_model(self) -> Any | None:
        if not self._noise_model_json:
            return None
        import json

        from qiskit_aer.noise import NoiseModel

        return NoiseModel.from_dict(json.loads(self._noise_model_json))

    def transpile(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[CircuitSpec, TranspileLayout | None]:
        """Transpile to Aer's native gate set via the Qiskit transpiler."""
        from qiskit import transpile as qk_transpile
        from qiskit import qasm3
        from qiskit_aer import AerSimulator

        qc = _load_qiskit_circuit(circuit)
        backend = AerSimulator(noise_model=self._build_noise_model())
        tqc = qk_transpile(
            qc,
            backend=backend,
            optimization_level=options.optimization_level,
            layout_method=options.transpiler.layout_method,
            routing_method=options.transpiler.routing_method,
            seed_transpiler=options.seed,
        )

        layout = None
        if tqc.layout is not None:
            init_l = list(tqc.layout.initial_layout.get_physical_bits().keys())
            layout = TranspileLayout(
                num_virtual=circuit.num_qubits,
                num_physical=backend.num_qubits,
                initial_layout=list(range(circuit.num_qubits)),
                final_layout=init_l[: circuit.num_qubits] if init_l else list(range(circuit.num_qubits)),
            )

        transpiled = circuit.model_copy(update={
            "serialized": qasm3.dumps(tqc),
            "format": CircuitFormat.QASM3,
            "gate_counts": dict(tqc.count_ops()),
        })
        return transpiled, layout

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Execute circuit on the Aer simulator."""
        from qiskit.quantum_info import SparsePauliOp
        from qiskit_aer.primitives import EstimatorV2, SamplerV2

        qc = _load_qiskit_circuit(circuit)
        noise_model = self._build_noise_model()

        if circuit.observables:
            # ---- Estimator path ----
            estimator = EstimatorV2(
                options={
                    "backend_options": {"noise_model": noise_model} if noise_model else {},
                    "run_options": {"seed_simulator": options.seed} if options.seed is not None else {},
                }
            )
            obs_list = [
                SparsePauliOp.from_list(o.to_qiskit_pauli_list(circuit.num_qubits))
                for o in circuit.observables
            ]
            pubs = [(qc, obs) for obs in obs_list]
            precision = (1.0 / (options.shots ** 0.5)) if options.shots else None
            job = estimator.run(pubs, precision=precision)
            result = job.result()

            evs = [
                ExpectationResult(
                    observable_index=i,
                    value=float(result[i].data.evs),
                    std_error=float(result[i].data.stds),
                    num_shots=options.shots,
                )
                for i in range(len(circuit.observables))
            ]
            return QuantumResult(
                computing_model=ComputingModel.GATE_BASED,
                expectation_values=evs,
                status=JobStatus.SUCCEEDED,
            )

        # ---- Sampler path ----
        qc = qc.copy()
        if not qc.cregs:
            qc.measure_all()
        sampler = SamplerV2(
            seed=options.seed,
            options={
                "backend_options": {"noise_model": noise_model} if noise_model else {},
            },
        )
        shots = options.require_shots("AerAdapter")
        job = sampler.run([qc], shots=shots)
        result = job.result()

        pub_result = result[0]
        bit_array = next(iter(pub_result.data.values()))
        counts = dict(bit_array.get_counts())
        memory = list(bit_array.get_bitstrings()) if options.memory else []

        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            shots=ShotResult(
                num_qubits=circuit.num_qubits,
                num_shots=shots,
                counts=counts,
                memory=memory,
            ),
            status=JobStatus.SUCCEEDED,
        )
