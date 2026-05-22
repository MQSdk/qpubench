"""IBM Quantum Runtime backend adapter.

Install: pip install 'qpubench[qiskit]'

Supports:
  - Qiskit Runtime Estimator (V2)  → expectation_values
  - Qiskit Runtime Sampler (V2)    → shots / memory
  - IBM resilience levels:
      0 = raw
      1 = TREX (twirled readout error extinction)
      2 = ZNE  (zero-noise extrapolation)
      3 = PEC  (probabilistic error cancellation)
  - Session-based execution (group related jobs)
  - Dynamic circuits (mid-circuit measurement) when backend supports them

Credentials: set via BackendSpec.auth or environment variables —
  IBM_QUANTUM_TOKEN, IBM_QUANTUM_INSTANCE, IBM_QUANTUM_CHANNEL
"""
from __future__ import annotations

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.primitives import (
    CircuitFormat,
    ErrorMitigationStrategy,
    JobStatus,
    QPUModality,
)
from ..schemas.result import (
    ExpectationResult,
    QuantumResult,
    ShotResult,
    TranspileLayout,
)

_MITIGATION_TO_RESILIENCE = {
    ErrorMitigationStrategy.NONE:  0,
    ErrorMitigationStrategy.TREX:  1,
    ErrorMitigationStrategy.ZNE:   2,
    ErrorMitigationStrategy.PEC:   3,
}


class IBMAdapter:
    """IBM Quantum Runtime adapter using Qiskit Runtime V2 primitives.

    Parameters
    ----------
    backend_name:
        IBM backend name, e.g. ``"ibm_brisbane"``.
    channel:
        ``"ibm_quantum"`` (IQP) or ``"ibm_cloud"`` (IBM Cloud).
    token:
        API token.  Falls back to ``IBM_QUANTUM_TOKEN`` env var.
    instance:
        Hub/group/project string, e.g. ``"ibm-q/open/main"``.
    use_session:
        If True, wrap execution in an IBM Runtime Session for lower
        queue latency on multi-job runs (sweeps, VQE optimisation loops).
    """

    def __init__(
        self,
        backend_name: str,
        *,
        channel:     str         = "ibm_quantum",
        token:       str | None  = None,
        instance:    str         = "ibm-q/open/main",
        use_session: bool        = False,
    ) -> None:
        self._backend_name = backend_name
        self._channel      = channel
        self._token        = token
        self._instance     = instance
        self._use_session  = use_session
        self._spec = BackendSpec.ibm(
            backend_name, channel=channel, instance=instance,
            token_ref=token or ""
        )

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.modality != QPUModality.GATE_BASED:
            warnings.append(
                f"IBMAdapter expects GATE_BASED; got {circuit.modality}"
            )
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3, CircuitFormat.JSON):
            warnings.append(
                f"IBMAdapter supports QASM2/3/JSON circuits; got {circuit.format}"
            )
        if circuit.is_parametric() and not circuit.is_bound():
            warnings.append("Circuit has unbound parameters")
        return warnings

    def transpile(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[CircuitSpec, TranspileLayout | None]:
        """Pre-transpile against the live IBM backend topology.

        TODO: fill in with real implementation —

            import os
            from qiskit_ibm_runtime import QiskitRuntimeService
            from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

            service = QiskitRuntimeService(
                channel=self._channel,
                token=self._token or os.environ["IBM_QUANTUM_TOKEN"],
                instance=self._instance,
            )
            backend = service.backend(self._backend_name)
            pm = generate_preset_pass_manager(
                optimization_level=options.optimization_level,
                backend=backend,
                seed_transpiler=options.seed,
                layout_method=options.transpiler.layout_method,
                routing_method=options.transpiler.routing_method,
            )
            qc  = QuantumCircuit.from_qasm_str(circuit.serialized)
            tqc = pm.run(qc)

            layout = tqc.layout
            init_l  = list(range(circuit.num_qubits))  # fill from layout object
            final_l = list(range(circuit.num_qubits))

            transpile_layout = TranspileLayout(
                num_virtual=circuit.num_qubits,
                num_physical=backend.num_qubits,
                initial_layout=init_l,
                final_layout=final_l,
            )
            transpiled = circuit.model_copy(update={
                "serialized": tqc.qasm(),
                "gate_counts": dict(tqc.count_ops()),
            })
            return transpiled, transpile_layout
        """
        raise NotImplementedError(
            "IBMAdapter.transpile: see TODO in ibm_adapter.py"
        )

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Submit to IBM Quantum Runtime and await results.

        TODO: fill in with real implementation —

            import os
            from qiskit import QuantumCircuit
            from qiskit_ibm_runtime import (
                QiskitRuntimeService, Session,
                EstimatorV2 as Estimator,
                SamplerV2   as Sampler,
            )
            from qiskit_ibm_runtime.options import EstimatorOptions, SamplerOptions

            service  = QiskitRuntimeService(
                channel=self._channel,
                token=self._token or os.environ["IBM_QUANTUM_TOKEN"],
                instance=self._instance,
            )
            backend  = service.backend(self._backend_name)
            resilience_level = _MITIGATION_TO_RESILIENCE.get(
                options.error_mitigation, 0
            )

            qc = QuantumCircuit.from_qasm_str(circuit.serialized)

            session_ctx = Session(backend=backend) if self._use_session else nullcontext()
            with session_ctx as session:

                if circuit.observables:
                    # --- Estimator path ---
                    est_opts = EstimatorOptions()
                    est_opts.resilience_level   = resilience_level
                    est_opts.execution.shots     = options.shots or 4096
                    est_opts.default_precision   = circuit.precision
                    estimator = Estimator(mode=session or backend, options=est_opts)

                    obs_list = [build_sparse_pauli_op(o) for o in circuit.observables]
                    pubs     = [(qc, obs) for obs in obs_list]
                    job      = estimator.run(pubs)
                    result   = job.result()
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
                        modality=QPUModality.GATE_BASED,
                        expectation_values=evs,
                        status=JobStatus.SUCCEEDED,
                        job_id=job.job_id(),
                        qpu_time_s=result.metadata.get("execution", {}).get("execution_spans", [None])[0],
                    )

                else:
                    # --- Sampler path ---
                    samp_opts = SamplerOptions()
                    samp_opts.execution.shots  = options.shots or 4096
                    samp_opts.execution.memory = options.memory
                    if options.rep_delay_s is not None:
                        samp_opts.execution.rep_delay = options.rep_delay_s
                    sampler = Sampler(mode=session or backend, options=samp_opts)

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
                        job_id=job.job_id(),
                    )
        """
        raise NotImplementedError(
            "IBMAdapter.run: see TODO in ibm_adapter.py"
        )
