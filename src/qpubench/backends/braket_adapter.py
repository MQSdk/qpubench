"""AWS Braket generic gate-based backend adapter.

Install: pip install 'qpubench[braket]'   (amazon-braket-sdk + qiskit-braket-provider)

Covers Rigetti / IonQ / OQC QPUs and Braket's own SV1/DM1/TN1 simulators —
any device reachable through `braket.aws.AwsDevice` (or `braket.devices.LocalSimulator`
for local testing). This is the *generic* gate-based Braket path; two other
places in the schema layer already talk to Braket for their own specialized
IR and are not superseded by this adapter:
  - `BackendSpec.xanadu_borealis(via_braket=True)` — GBS (Xanadu Borealis)
  - `BackendSpec.aquila()`                          — neutral-atom AHS (QuEra)

Implementation note — why qiskit-braket-provider
--------------------------------------------------
Braket's own OpenQASM3 interpreter does not ship a `stdgates.inc` (an
`include "stdgates.inc";` line fails with
``FileNotFoundError: stdgates.inc`` — confirmed empirically against
amazon-braket-sdk 1.x) and uses different native gate names than Qiskit's
stdgates (`cnot`, not `cx` — also confirmed empirically). Rather than
hand-translating gate names out of our QASM2/QASM3 text, this adapter goes
through `qiskit_braket_provider`, AWS's own official Qiskit<->Braket bridge:
`BraketLocalBackend`/`BraketAwsBackend` are real `qiskit.providers.BackendV2`
instances, so `generate_preset_pass_manager()` and the `BraketSampler`/
`BraketEstimator` PUB-based primitives work exactly like
`aer_adapter.py`/`ibm_adapter.py` — same CircuitSpec -> QuantumCircuit
loading helper, same SparsePauliOp conversion.

Verified for real in a sandbox with no AWS account/credentials via
`BraketLocalBackend` (wraps `braket.devices.LocalSimulator`): sampler
counts and estimator expectation values both confirmed correct on a Bell
circuit.

Key Braket-specific gotchas
----------------------------
  - Every AWS-hosted task (simulator or QPU) requires an S3 output location.
    Passed as the `s3_destination_folder=(bucket, prefix)` constructor
    option on `BraketSampler`/`BraketEstimator` (verified via
    `BraketSampler.__init__`'s `**options` -> forwarded verbatim to
    `AwsDevice.run(program_set, **options)`), resolved from
    `BackendSpec.auth["s3_bucket_ref"]` (an env-var *name*, not the literal
    bucket — same convention as `ibm_adapter.py`'s `token_ref`).
  - `BraketLocalBackend` needs no S3 config and no AWS account at all —
    the local/simulator-arn branch below skips it entirely.
  - Implements the optional `TranspilableBackend` protocol (`.transpile()`),
    same as `ibm_adapter.py`/`iqm_adapter.py`.
"""
from __future__ import annotations

import os
from typing import Any

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.primitives import (
    CircuitFormat,
    ComputingModel,
    JobStatus,
)
from ..schemas.result import (
    ExpectationResult,
    QuantumResult,
    ShotResult,
    TranspileLayout,
)
from ._qiskit_common import load_qiskit_circuit

_LOCAL_ARNS = frozenset({"local", "arn:aws:braket:::device/quantum-simulator/amazon/sv1:local"})


class BraketAdapter:
    """AWS Braket adapter (via qiskit-braket-provider).

    Parameters
    ----------
    device_arn:
        Full Braket device ARN — see BackendSpec.braket() docstring for
        examples. Defaults to the SV1 managed simulator. Pass ``"local"``
        to run against ``BraketLocalBackend`` (no AWS account needed).
    s3_bucket_ref:
        Env-var name holding the S3 bucket Braket writes task results to.
        Ignored for the local backend.
    s3_prefix:
        Key prefix under the bucket for this backend's results.
    """

    def __init__(
        self,
        device_arn: str = "arn:aws:braket:::device/quantum-simulator/amazon/sv1",
        *,
        s3_bucket_ref: str = "",
        s3_prefix: str = "braket-results",
    ) -> None:
        self._device_arn    = device_arn
        self._s3_bucket_ref = s3_bucket_ref
        self._s3_prefix      = s3_prefix
        self._spec = BackendSpec.braket(
            device_arn,
            s3_bucket_ref=s3_bucket_ref,
            s3_prefix=s3_prefix,
        )

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append(
                f"BraketAdapter expects GATE_BASED; got {circuit.computing_model}"
            )
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3):
            warnings.append(
                f"BraketAdapter supports QASM2/3 circuits; got {circuit.format}"
            )
        return warnings

    # ------------------------------------------------------------------

    def _backend(self) -> Any:
        from qiskit_braket_provider import BraketAwsBackend, BraketLocalBackend

        if self._device_arn in _LOCAL_ARNS:
            return BraketLocalBackend()
        return BraketAwsBackend(arn=self._device_arn)

    def _s3_options(self) -> dict[str, object]:
        if not self._s3_bucket_ref:
            return {}
        bucket = os.environ.get(self._s3_bucket_ref, "")
        return {"s3_destination_folder": (bucket, self._s3_prefix)}

    def transpile(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[CircuitSpec, TranspileLayout | None]:
        """Pre-compile against the target device's native gate set."""
        from qiskit import qasm3
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

        qc = load_qiskit_circuit(circuit)
        backend = self._backend()
        pm = generate_preset_pass_manager(
            optimization_level=options.optimization_level,
            backend=backend,
            seed_transpiler=options.seed,
        )
        tqc = pm.run(qc)

        layout = TranspileLayout(
            num_virtual=circuit.num_qubits,
            num_physical=backend.num_qubits,
            initial_layout=list(range(circuit.num_qubits)),
            final_layout=list(range(circuit.num_qubits)),
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
        """Execute on an AWS Braket device (or BraketLocalBackend)."""
        from qiskit.quantum_info import SparsePauliOp
        from qiskit_braket_provider import BraketEstimator, BraketSampler

        qc = load_qiskit_circuit(circuit)
        backend = self._backend()
        s3_options = self._s3_options()

        if circuit.observables:
            # ---- Estimator path ----
            estimator = BraketEstimator(backend, **s3_options)
            obs_list = [
                SparsePauliOp.from_list(o.to_qiskit_pauli_list(circuit.num_qubits))
                for o in circuit.observables
            ]
            pubs = [(qc, obs) for obs in obs_list]
            precision = (1.0 / (options.shots ** 0.5)) if options.shots else None
            job = estimator.run(pubs, precision=precision) if precision else estimator.run(pubs)
            result = job.result()

            evs = [
                ExpectationResult(
                    observable_index=i,
                    value=float(result[i].data.evs),
                    std_error=float(result[i].metadata.get("target_precision", 0.0)),
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
        qc_meas = qc.copy()
        if not qc_meas.cregs:
            qc_meas.measure_all()
        sampler = BraketSampler(backend, **s3_options)
        shots = options.require_shots("BraketAdapter")
        job = sampler.run([qc_meas], shots=shots)
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
