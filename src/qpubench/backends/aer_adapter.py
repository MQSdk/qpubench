"""Qiskit Aer backend adapter.

Install: pip install 'qpubench[qiskit]'

Supports:
  - Statevector simulation   (shots=None)
  - Shot-based QASM          (shots=N)
  - Per-shot memory          (options.memory=True → ShotResult.memory)
  - Estimator path           (circuit.observables populated)
  - Sampler path             (circuit.observables empty)
  - ZNE via prototype-zne    (options.error_mitigation=ZNE)
  - Noise model injection    (pass via auth["noise_model_json"])
"""
from __future__ import annotations

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions, TranspilerConfig
from ..schemas.primitives import CircuitFormat, ErrorMitigationStrategy, FidelityMetric, JobStatus, QPUModality
from ..schemas.result import (
    ExpectationResult,
    FidelityResult,
    QuantumResult,
    ShotResult,
    TranspileLayout,
)


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
        if circuit.modality != QPUModality.GATE_BASED:
            warnings.append(
                f"AerAdapter expects GATE_BASED; got {circuit.modality}"
            )
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3, CircuitFormat.JSON):
            warnings.append(
                f"AerAdapter supports QASM2/3 or JSON; got {circuit.format}"
            )
        if circuit.is_parametric() and not circuit.is_bound():
            warnings.append("Circuit has unbound parameters; bind before running")
        return warnings

    def transpile(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[CircuitSpec, TranspileLayout | None]:
        """Transpile to Aer's native gate set via Qiskit transpiler.

        TODO: fill in with real implementation —

            from qiskit import transpile as qk_transpile
            from qiskit import QuantumCircuit
            from qiskit_aer import AerSimulator

            qc      = QuantumCircuit.from_qasm_str(circuit.serialized)
            backend = AerSimulator()
            tqc     = qk_transpile(
                qc,
                backend=backend,
                optimization_level=options.optimization_level,
                layout_method=options.transpiler.layout_method,
                routing_method=options.transpiler.routing_method,
                seed_transpiler=options.seed,
            )
            layout = tqc.layout
            init_l = list(layout.initial_layout.get_physical_bits().values())
            # Build TranspileLayout and update gate_counts from tqc.count_ops()
        """
        raise NotImplementedError(
            "AerAdapter.transpile: see TODO in aer_adapter.py"
        )

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Execute circuit on Aer simulator.

        TODO: fill in with real implementation —

        Estimator path (circuit.observables populated):
            from qiskit_aer.primitives import Estimator
            estimator = Estimator()
            estimator.set_options(
                shots=options.shots,
                seed_simulator=options.seed,
            )
            qc  = QuantumCircuit.from_qasm_str(circuit.serialized)
            obs = [SparsePauliOp(...) for o in circuit.observables]   # convert
            job = estimator.run([(qc, obs[i]) for i in range(len(obs))])
            result = job.result()
            evs = [
                ExpectationResult(
                    observable_index=i,
                    value=float(result[i].data.evs),
                    std_error=float(result[i].data.stds),
                    num_shots=options.shots,
                )
                for i in range(len(obs))
            ]
            return QuantumResult(
                modality=QPUModality.GATE_BASED,
                expectation_values=evs,
                status=JobStatus.SUCCEEDED,
            )

        Sampler path (circuit.observables empty):
            from qiskit_aer.primitives import Sampler
            sampler = Sampler()
            sampler.set_options(shots=options.shots, seed_simulator=options.seed, memory=options.memory)
            job    = sampler.run([qc])
            result = job.result()
            counts = dict(result[0].data.meas.get_counts())
            memory = result[0].data.meas.get_memory() if options.memory else []
            return QuantumResult(
                modality=QPUModality.GATE_BASED,
                shots=ShotResult(
                    num_qubits=circuit.num_qubits,
                    num_shots=options.shots or sum(counts.values()),
                    counts=counts,
                    memory=memory,
                ),
                status=JobStatus.SUCCEEDED,
            )
        """
        raise NotImplementedError(
            "AerAdapter.run: see TODO in aer_adapter.py"
        )
