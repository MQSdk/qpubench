"""IBM Quantum Runtime backend adapter.

Install: pip install 'qpubench[qiskit]'

Supports:
  - Qiskit Runtime EstimatorV2  → expectation_values
      PUB format: (circuit, observables, parameter_values?, precision?)
      observables: SparsePauliOp list; precision replaces fixed shot count.
  - Qiskit Runtime SamplerV2    → shots / BitArray
      PUB format: (circuit, parameter_values?, shots?)
      Result: BitArray with shape (num_shots,) or (num_params, num_shots).
      Adapter converts to ShotResult via BitArray.get_counts().
  - IBM resilience levels:
      0 = raw
      1 = TREX (twirled readout error extinction)
      2 = ZNE  (zero-noise extrapolation)
      3 = PEC  (probabilistic error cancellation)
  - Execution modes (IBMExecutionMode):
      SESSION — exclusive QPU hold; lowest latency; use for VQE / adaptive loops
      BATCH   — jobs queued independently; parallel workloads / sweeps
      SINGLE  — one-shot job outside any session/batch context (default)
  - Dynamic circuits (mid-circuit measurement) when backend supports them
  - ExecutionSpans: timing metadata per PUB attached to IBMRuntimeRecord

IBM Advantage Tracker:
  Attach a QuantumAdvantageRecord to BenchmarkRecord.advantage to register
  results against the Quantum Advantage Tracker community database.

CUDA-Q compatibility:
  The runner's BackendAdapter protocol is backend-agnostic — a CUDA-Q adapter
  implementing validate() + run() integrates without changes.  Key CUDA-Q
  primitives: cudaq.observe() ≈ EstimatorV2, cudaq.sample() ≈ SamplerV2.
  BackendSpec.cudaq(target=...) is available for CUDA-Q targets
  ("nvidia", "qpp-cpu", "tensornet", etc.).

Credentials: set via BackendSpec.auth or environment variables —
  IBM_QUANTUM_TOKEN, IBM_QUANTUM_INSTANCE, IBM_QUANTUM_CHANNEL
"""

from __future__ import annotations

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.error_mitigation import (
    IBMExecutionMode,
)
from ..schemas.execution import ExecutionOptions
from ..schemas.primitives import (
    CircuitFormat,
    ErrorMitigationStrategy,
    QPUModality,
)
from ..schemas.result import (
    QuantumResult,
    TranspileLayout,
)

_MITIGATION_TO_RESILIENCE = {
    ErrorMitigationStrategy.NONE: 0,
    ErrorMitigationStrategy.TREX: 1,
    ErrorMitigationStrategy.ZNE: 2,
    ErrorMitigationStrategy.PEC: 3,
}


class IBMAdapter:
    """IBM Quantum Runtime adapter using Qiskit Runtime V2 primitives.

    Parameters
    ----------
    backend_name:
        IBM backend name, e.g. ``"ibm_brisbane"``, ``"ibm_torino"``.
    channel:
        ``"ibm_quantum"`` (IQP) or ``"ibm_cloud"`` (IBM Cloud).
    token:
        API token.  Falls back to ``IBM_QUANTUM_TOKEN`` env var.
    instance:
        Hub/group/project string, e.g. ``"ibm-q/open/main"``.
    execution_mode:
        ``SESSION`` — exclusive QPU hold; use for VQE / adaptive algorithms.
        ``BATCH``   — parallel independent jobs (sweeps, hyperparameter search).
        ``SINGLE``  — single job without session/batch context (default).
    """

    def __init__(
        self,
        backend_name: str,
        *,
        channel: str = "ibm_quantum",
        token: str | None = None,
        instance: str = "ibm-q/open/main",
        execution_mode: IBMExecutionMode = IBMExecutionMode.SINGLE,
    ) -> None:
        self._backend_name = backend_name
        self._channel = channel
        self._token = token
        self._instance = instance
        self._execution_mode = execution_mode
        self._spec = BackendSpec.ibm(
            backend_name, channel=channel, instance=instance, token_ref=token or ""
        )

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.modality != QPUModality.GATE_BASED:
            warnings.append(f"IBMAdapter expects GATE_BASED; got {circuit.modality}")
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3, CircuitFormat.JSON):
            warnings.append(f"IBMAdapter supports QASM2/3/JSON circuits; got {circuit.format}")
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
        raise NotImplementedError("IBMAdapter.transpile: see TODO in ibm_adapter.py")

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Submit to IBM Quantum Runtime V2 and await results.

        EstimatorV2 PUB format: (circuit, observables, parameter_values?, precision?)
        SamplerV2 PUB format:   (circuit, parameter_values?, shots?)

        ExecutionSpans in result.metadata carry per-PUB SliceSpan objects with
        .start / .stop ISO-8601 timestamps; captured in IBMRuntimeRecord.execution_spans.

        SamplerV2 returns BitArray (not counts dict).  BitArray.shape =
        (num_shots,) for a single circuit; (num_params, num_shots) for parametric.
        Convert via BitArray.get_counts() → dict[str, int].

        TODO: fill in with real implementation —

            import os
            from contextlib import nullcontext
            from qiskit import QuantumCircuit
            from qiskit_ibm_runtime import (
                QiskitRuntimeService, Session, Batch,
                EstimatorV2 as Estimator,
                SamplerV2   as Sampler,
            )
            from qiskit_ibm_runtime.options import EstimatorOptions, SamplerOptions

            service = QiskitRuntimeService(
                channel=self._channel,
                token=self._token or os.environ["IBM_QUANTUM_TOKEN"],
                instance=self._instance,
            )
            backend = service.backend(self._backend_name)
            resilience_level = _MITIGATION_TO_RESILIENCE.get(
                options.error_mitigation, 0
            )
            qc = QuantumCircuit.from_qasm_str(circuit.serialized)

            # --- Execution-mode context ---
            if self._execution_mode == IBMExecutionMode.SESSION:
                exec_ctx = Session(backend=backend)
            elif self._execution_mode == IBMExecutionMode.BATCH:
                exec_ctx = Batch(backend=backend)
            else:
                exec_ctx = nullcontext()

            with exec_ctx as ctx:
                mode = ctx if ctx is not None else backend

                if circuit.observables:
                    # ---- EstimatorV2 path ----
                    est_opts = EstimatorOptions()
                    est_opts.resilience_level = resilience_level
                    est_opts.execution.shots  = options.shots or 4096
                    estimator = Estimator(mode=mode, options=est_opts)

                    obs_list = [build_sparse_pauli_op(o) for o in circuit.observables]
                    # Each PUB: (circuit, SparsePauliOp, param_values?, precision?)
                    pubs = [(qc, obs) for obs in obs_list]
                    job  = estimator.run(pubs)
                    res  = job.result()

                    evs = [
                        ExpectationResult(
                            observable_index=i,
                            value=float(res[i].data.evs),
                            std_error=float(res[i].data.stds),
                            num_shots=options.shots,
                        )
                        for i in range(len(circuit.observables))
                    ]

                    # Capture ExecutionSpans for IBMRuntimeRecord
                    spans = _extract_execution_spans(res)
                    ibm_record = IBMRuntimeRecord(
                        job_id=job.job_id(),
                        execution_mode=self._execution_mode,
                        primitive_type=IBMPrimitiveType.ESTIMATOR,
                        backend_name=self._backend_name,
                        resilience_level=resilience_level,
                        shots=options.shots,
                        execution_spans=spans,
                        estimator_pub=IBMEstimatorPUB(
                            observable_labels=[str(o) for o in obs_list],
                        ),
                    )
                    return QuantumResult(
                        modality=QPUModality.GATE_BASED,
                        expectation_values=evs,
                        status=JobStatus.SUCCEEDED,
                        job_id=job.job_id(),
                        ibm_runtime_record=ibm_record,
                    )

                else:
                    # ---- SamplerV2 path ----
                    samp_opts = SamplerOptions()
                    samp_opts.execution.shots = options.shots or 4096
                    if options.rep_delay_s is not None:
                        samp_opts.execution.rep_delay = options.rep_delay_s
                    sampler = Sampler(mode=mode, options=samp_opts)

                    # PUB: (circuit, param_values?, shots?)
                    job = sampler.run([qc])
                    res = job.result()

                    # BitArray: shape (num_shots,) for a single non-parametric circuit.
                    # get_counts() converts to dict[str, int].
                    bit_array = res[0].data.meas
                    counts    = dict(bit_array.get_counts())
                    memory    = list(bit_array.get_memory()) if options.memory else []

                    spans = _extract_execution_spans(res)
                    ibm_record = IBMRuntimeRecord(
                        job_id=job.job_id(),
                        execution_mode=self._execution_mode,
                        primitive_type=IBMPrimitiveType.SAMPLER,
                        backend_name=self._backend_name,
                        resilience_level=resilience_level,
                        shots=options.shots,
                        execution_spans=spans,
                        sampler_pub=IBMSamplerPUB(shots=options.shots),
                        bit_array_meta=IBMBitArrayMeta(
                            shape=list(bit_array.shape),
                            num_bits=bit_array.num_bits,
                        ),
                    )
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
                        ibm_runtime_record=ibm_record,
                    )

        Helper stubs referenced above:

            def _extract_execution_spans(result) -> list[IBMExecutionSpan]:
                from ..schemas.error_mitigation import IBMExecutionSpan
                spans = []
                for span in getattr(result.metadata, "execution_spans", []):
                    spans.append(IBMExecutionSpan(
                        start_iso=span.start.isoformat() if span.start else None,
                        stop_iso=span.stop.isoformat() if span.stop else None,
                        duration_s=(span.stop - span.start).total_seconds()
                                   if span.start and span.stop else None,
                    ))
                return spans

            def build_sparse_pauli_op(obs):
                from qiskit.quantum_info import SparsePauliOp
                terms = [(
                    "".join(pt.pauli_ops[i].value for i in range(len(pt.pauli_ops))),
                    pt.coefficient.value,
                ) for pt in obs.terms]
                return SparsePauliOp.from_list(terms)
        """
        raise NotImplementedError("IBMAdapter.run: see TODO in ibm_adapter.py")
