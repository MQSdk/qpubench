"""IBM Quantum Runtime backend adapter.

Install: pip install 'qpubench[qiskit]'

Supports:
  - Qiskit Runtime EstimatorV2  -> expectation_values
      PUB format: (circuit, observables, parameter_values?, precision?)
      observables: SparsePauliOp list; precision replaces fixed shot count.
  - Qiskit Runtime SamplerV2    -> shots / BitArray
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
  - ExecutionSpans: timing metadata per PUB attached to IBMRuntimeRecord
      (populated when the real cloud service returns them; absent in
      local/fake-backend testing — degrades to an empty list rather than
      raising, confirmed empirically against qiskit-ibm-runtime 0.47).

IBM Advantage Tracker:
  Attach a QuantumAdvantageRecord to BenchmarkRecord.advantage to register
  results against the Quantum Advantage Tracker community database.

CUDA-Q compatibility:
  The runner's BackendAdapter protocol is backend-agnostic — a CUDA-Q adapter
  implementing validate() + run() integrates without changes. Key CUDA-Q
  primitives: cudaq.observe() = EstimatorV2, cudaq.sample() = SamplerV2.
  BackendSpec.cudaq(target=...) is available for CUDA-Q targets
  ("nvidia", "qpp-cpu", "tensornet", etc.).

Credentials: never passed to this adapter as a literal string. The API token
is read at call time from the environment variable named by ``token_ref``
(default ``IBM_QUANTUM_TOKEN``); channel and instance likewise default to
``IBM_QUANTUM_CHANNEL`` / ``IBM_QUANTUM_INSTANCE``. Populate them from a
``.env`` file — see ``.env.example`` and the credentials section of the root
README. ``BackendSpec.auth`` records only these *variable names*, so a stored
BenchmarkRecord never contains a secret.

Implementation notes verified against the installed qiskit-ibm-runtime
(0.47.0) using qiskit_ibm_runtime.fake_provider local backends (no cloud
account needed to confirm correctness):
  - Real IBM backends require ISA-matched circuits: submitting an
    untranspiled circuit raises (confirmed: "Circuits that do not match
    the target hardware definition are no longer supported..."). run()
    therefore always transpiles internally before submission — it does
    not rely on the caller having called transpile() first.
  - EstimatorOptions/SamplerOptions no longer expose shots under
    `.execution.shots` (that field only has init_qubits/rep_delay in this
    version) — shots are set via `EstimatorOptions.default_precision`
    (Estimator; converted from options.shots as 1/sqrt(shots)) and
    `SamplerOptions.default_shots` (Sampler), confirmed by introspecting
    the installed Options dataclasses directly.
  - Observables must be re-mapped through the transpiled layout via
    `SparsePauliOp.apply_layout(tqc.layout)` before being passed to
    EstimatorV2 — otherwise the Pauli positions no longer match the
    physical qubits the transpiler moved them to.
  - Sampler measurements are added only on the final physical qubits
    corresponding to our own circuit.num_qubits (via
    `tqc.layout.final_index_layout()`), not the whole backend width —
    avoids wasting classical-register space (and, for local/fake-backend
    testing, avoids a full-width statevector simulation of an unrelated
    ~100+ idle ancilla qubits).
"""

from __future__ import annotations

import os
from contextlib import nullcontext
from typing import Any

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.mirrors.ibm_runtime_v2 import (
    IBMBitArrayMeta,
    IBMEstimatorPUB,
    IBMExecutionMode,
    IBMExecutionSpan,
    IBMPrimitiveType,
    IBMRuntimeRecord,
    IBMSamplerPUB,
)
from ..schemas.primitives import (
    CircuitFormat,
    ComputingModel,
    ErrorMitigationStrategy,
    JobStatus,
)
from ..schemas.result import (
    ExpectationResult,
    QuantumResult,
    ShotResult,
    TranspileLayout,
)
from ._qiskit_common import load_qiskit_circuit

_MITIGATION_TO_RESILIENCE = {
    ErrorMitigationStrategy.NONE: 0,
    ErrorMitigationStrategy.TREX: 1,
    ErrorMitigationStrategy.ZNE: 2,
    ErrorMitigationStrategy.PEC: 3,
}


def _env_or(value: str | None, env_var: str, fallback: str | None) -> str:
    """Resolve a setting from the argument, then the environment, then a fallback.

    A ``fallback`` of ``None`` means the setting is account-specific and has no
    sensible built-in value, so a missing environment variable is an error
    rather than a silent guess.
    """
    if value is not None:
        return value
    from_env = os.environ.get(env_var)
    if from_env:
        return from_env
    if fallback is None:
        raise ValueError(
            f"No value for {env_var}. Set it in your .env / environment "
            f"(see .env.example), or pass it to the adapter explicitly."
        )
    return fallback


def _extract_execution_spans(result: object) -> list[IBMExecutionSpan]:
    spans: list[IBMExecutionSpan] = []
    for span in getattr(result, "execution_spans", []) or []:
        start = getattr(span, "start", None)
        stop = getattr(span, "stop", None)
        spans.append(IBMExecutionSpan(
            start_iso=start.isoformat() if start else None,
            stop_iso=stop.isoformat() if stop else None,
            duration_s=(stop - start).total_seconds() if start and stop else None,
            pub_indices=list(getattr(span, "pub_slices", None) or getattr(span, "pub_indices", []) or []),
        ))
    return spans


class IBMAdapter:
    """IBM Quantum Runtime adapter using Qiskit Runtime V2 primitives.

    Parameters
    ----------
    backend_name:
        IBM backend name, e.g. ``"ibm_brisbane"``, ``"ibm_torino"``.
    channel:
        ``"ibm_quantum_platform"`` or ``"ibm_cloud"``. Left unset, it is read
        from ``$IBM_QUANTUM_CHANNEL``, falling back to
        ``"ibm_quantum_platform"`` — the only value the current SDK accepts
        for the public platform, so the fallback names a fact about the API
        rather than a choice about your account. The legacy ``"ibm_quantum"``
        (IQP) channel is gone — confirmed against the installed
        qiskit-ibm-runtime (0.47.x): ``QiskitRuntimeService`` raises
        ``ValueError`` for it now.
    instance:
        Hub/group/project string, e.g. ``"ibm-q/open/main"``, or a Cloud
        Resource Name (CRN) under the newer channel. Account-specific, so
        there is no built-in default: left unset it is read from
        ``$IBM_QUANTUM_INSTANCE``, and it is an error for that to be missing.
    token_ref:
        *Name of the environment variable* holding the API token — not the
        token. Defaults to ``"IBM_QUANTUM_TOKEN"``. There is deliberately no
        way to pass the token itself as an argument; see the credentials
        section of the root README.
    execution_mode:
        ``SESSION`` — exclusive QPU hold; use for VQE / adaptive algorithms.
        ``BATCH``   — parallel independent jobs (sweeps, hyperparameter search).
        ``SINGLE``  — single job without session/batch context (default).

    All three settings have a matching entry in ``.env.example``. Nothing in
    this class stores a credential; the token is read from the environment at
    the moment a service connection is opened.
    """

    def __init__(
        self,
        backend_name: str,
        *,
        channel: str | None = None,
        instance: str | None = None,
        token_ref: str = "IBM_QUANTUM_TOKEN",
        execution_mode: IBMExecutionMode = IBMExecutionMode.SINGLE,
    ) -> None:
        """Configure the adapter; no network call and no credential read yet."""
        self._backend_name = backend_name
        self._channel = _env_or(channel, "IBM_QUANTUM_CHANNEL", "ibm_quantum_platform")
        self._instance = _env_or(instance, "IBM_QUANTUM_INSTANCE", None)
        self._token_ref = token_ref
        self._execution_mode = execution_mode
        self._spec = BackendSpec.ibm(
            backend_name,
            channel=self._channel,
            instance=self._instance,
            token_ref=token_ref,
        )

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append(f"IBMAdapter expects GATE_BASED; got {circuit.computing_model}")
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3, CircuitFormat.JSON):
            warnings.append(f"IBMAdapter supports QASM2/3/JSON circuits; got {circuit.format}")
        if circuit.is_parametric() and not circuit.is_bound():
            warnings.append("Circuit has unbound parameters")
        return warnings

    # ------------------------------------------------------------------

    def _get_backend(self) -> Any:
        """Open a credentialed service connection and return the live backend.

        The token is read from the environment here, at the point of use, so
        it is never held on the adapter or serialised into a BenchmarkRecord.
        """
        from qiskit_ibm_runtime import QiskitRuntimeService

        token = os.environ.get(self._token_ref)
        if not token:
            raise RuntimeError(
                f"No IBM Quantum token found in ${self._token_ref}. Set it in "
                "your .env / environment (see .env.example), or point the "
                "adapter at a different variable with "
                f'IBMAdapter(..., token_ref="MY_VAR").'
            )
        service = QiskitRuntimeService(
            channel=self._channel,
            token=token,
            instance=self._instance,
        )
        return service.backend(self._backend_name)

    def get_live_backend(self) -> Any:
        """Public wrapper around `_get_backend()` — real, credentialed
        `BackendV2` for this adapter's `backend_name`/`channel`/`instance`.
        Used by `backends.ibm_cost_estimator` to estimate resources against
        live calibration data instead of the offline `FakeBackend` default.
        """
        return self._get_backend()

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def transpile(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[CircuitSpec, TranspileLayout | None]:
        """Pre-transpile against the live IBM backend topology."""
        from qiskit import qasm3
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

        backend = self._get_backend()
        qc = load_qiskit_circuit(circuit)
        pm = generate_preset_pass_manager(
            optimization_level=options.optimization_level,
            backend=backend,
            seed_transpiler=options.seed,
            layout_method=options.transpiler.layout_method,
            routing_method=options.transpiler.routing_method,
        )
        tqc = pm.run(qc)

        final_positions = tqc.layout.final_index_layout() if tqc.layout else list(range(circuit.num_qubits))
        transpile_layout = TranspileLayout(
            num_virtual=circuit.num_qubits,
            num_physical=backend.num_qubits,
            initial_layout=list(range(circuit.num_qubits)),
            final_layout=list(final_positions),
        )
        transpiled = circuit.model_copy(update={
            "serialized": qasm3.dumps(tqc),
            "format": CircuitFormat.QASM3,
            "gate_counts": dict(tqc.count_ops()),
        })
        return transpiled, transpile_layout

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Submit to IBM Quantum Runtime V2 and await results.

        Always transpiles internally first (see module docstring) — real
        IBM backends reject non-ISA circuits.
        """
        from qiskit.circuit import ClassicalRegister
        from qiskit.quantum_info import SparsePauliOp
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
        from qiskit_ibm_runtime import Batch, Session
        from qiskit_ibm_runtime import EstimatorV2 as Estimator
        from qiskit_ibm_runtime import SamplerV2 as Sampler
        from qiskit_ibm_runtime.options import EstimatorOptions, SamplerOptions

        backend = self._get_backend()
        resilience_level = _MITIGATION_TO_RESILIENCE.get(options.error_mitigation, 0)

        qc = load_qiskit_circuit(circuit)
        pm = generate_preset_pass_manager(
            optimization_level=options.optimization_level,
            backend=backend,
            seed_transpiler=options.seed,
        )
        tqc = pm.run(qc)

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
                if options.shots:
                    est_opts.default_precision = 1.0 / (options.shots ** 0.5)
                estimator = Estimator(mode=mode, options=est_opts)

                obs_list = [
                    SparsePauliOp.from_list(o.to_qiskit_pauli_list(circuit.num_qubits)).apply_layout(tqc.layout)
                    for o in circuit.observables
                ]
                pubs = [(tqc, obs) for obs in obs_list]
                job = estimator.run(pubs)
                res = job.result()

                evs = [
                    ExpectationResult(
                        observable_index=i,
                        value=float(res[i].data.evs),
                        std_error=float(res[i].data.stds),
                        num_shots=options.shots,
                    )
                    for i in range(len(circuit.observables))
                ]

                ibm_record = IBMRuntimeRecord(
                    job_id=job.job_id(),
                    execution_mode=self._execution_mode,
                    primitive_type=IBMPrimitiveType.ESTIMATOR,
                    backend_name=self._backend_name,
                    resilience_level=resilience_level,
                    shots=options.shots,
                    execution_spans=_extract_execution_spans(res),
                    estimator_pub=IBMEstimatorPUB(
                        observable_labels=[str(o) for o in obs_list],
                    ),
                )
                return QuantumResult(
                    computing_model=ComputingModel.GATE_BASED,
                    expectation_values=evs,
                    status=JobStatus.SUCCEEDED,
                    job_id=job.job_id(),
                    vendor_results={"ibm_runtime_record": ibm_record},
                )

            # ---- SamplerV2 path ----
            samp_opts = SamplerOptions()
            shots = options.require_shots("IBMAdapter (SamplerV2)")
            samp_opts.default_shots = shots
            if options.rep_delay_s is not None:
                samp_opts.execution.rep_delay = options.rep_delay_s
            sampler = Sampler(mode=mode, options=samp_opts)

            final_positions = tqc.layout.final_index_layout() if tqc.layout else list(range(circuit.num_qubits))
            tqc_meas = tqc.copy()
            tqc_meas.add_register(ClassicalRegister(circuit.num_qubits, "meas"))
            tqc_meas.measure(list(final_positions), list(range(circuit.num_qubits)))

            job = sampler.run([tqc_meas])
            res = job.result()

            bit_array = res[0].data.meas
            counts = dict(bit_array.get_counts())
            memory = list(bit_array.get_bitstrings()) if options.memory else []

            ibm_record = IBMRuntimeRecord(
                job_id=job.job_id(),
                execution_mode=self._execution_mode,
                primitive_type=IBMPrimitiveType.SAMPLER,
                backend_name=self._backend_name,
                resilience_level=resilience_level,
                shots=shots,
                execution_spans=_extract_execution_spans(res),
                sampler_pub=IBMSamplerPUB(shots=shots),
                bit_array_meta=IBMBitArrayMeta(
                    shape=list(bit_array.shape),
                    num_bits=bit_array.num_bits,
                ),
            )
            return QuantumResult(
                computing_model=ComputingModel.GATE_BASED,
                shots=ShotResult(
                    num_qubits=circuit.num_qubits,
                    num_shots=shots,
                    counts=counts,
                    memory=memory,
                ),
                status=JobStatus.SUCCEEDED,
                job_id=job.job_id(),
                vendor_results={"ibm_runtime_record": ibm_record},
            )
