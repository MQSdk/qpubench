"""Qibo backend adapter — local simulator, Qibolab hardware, or Qibo cloud.

Install: pip install 'qpubench[qibo]'   (qibo + qibo-cloud-backends)

Qibo is a full-stack quantum computing framework. This one adapter covers its
three execution surfaces, selected by ``execution``:

  execution="local"    local simulator — ``qibo.set_backend("numpy")`` (also
                       "qibojit", "tensorflow", "pytorch"). No credentials.
  execution="qibolab"  self-hosted QPU — ``qibo.set_backend("qibolab",
                       platform=...)``. Qibolab compiles the circuit to pulse
                       sequences and drives the lab's control electronics.
                       See https://qibo.science/qibolab/stable/.
  execution="cloud"    remote QPU via qibo-cloud-backends —
                       ``qibo.set_backend("qibo-cloud-backends",
                       client=..., token=..., platform=...)``. ``client`` is
                       "qibo-client" (TII cloud) or "qiskit-client" (IBM
                       servers). See
                       https://qibo.science/qibo-cloud-backends/stable/.

Circuit loading
---------------
Qibo's ``Circuit.from_qasm`` parses OpenQASM 2.0. QASM2 CircuitSpecs are fed
in directly (no Qiskit needed); QASM3 CircuitSpecs are converted to QASM2
first via the shared ``load_qiskit_circuit`` helper + ``qiskit.qasm2.dumps``
(the same Qiskit path every other adapter already uses).

Bit ordering
------------
Qibo is **big-endian** (qubit 0 is the leftmost bit of a measurement
bitstring); qpubench's ``ShotResult`` uses the Qiskit **little-endian**
convention (qubit 0 rightmost). Confirmed empirically against qibo 0.2.23:
an X on qubit 0 of a 2-qubit register yields qibo "10" vs Qiskit "01". This
adapter therefore reverses every count/memory bitstring so stored results
match the rest of the framework.

Estimator path
--------------
Like the IQM and Quantinuum adapters, the Estimator path is intentionally not
implemented: real Qibo hardware (Qibolab / cloud) returns measurement samples,
not expectation values. Use the Sampler path and reconstruct expectation
values classically from counts.

Verified for real (no credentials) against qibo 0.2.23: the local-simulator
Sampler path is fully executed end-to-end (QASM load, measurement injection,
frequency + per-shot sample parsing, endianness fix) on the ``numpy`` backend.
Only the Qibolab / cloud backends need a real lab or account.

Credentials
-----------
  QIBO_CLIENT_TOKEN  qibo-client (TII cloud) access token
  IBMQ_TOKEN         qiskit-client (IBM servers) access token
The env-var name is taken from ``BackendSpec.auth["token_ref"]``.
"""

from __future__ import annotations

from typing import Any

import os

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.primitives import (
    CircuitFormat,
    ComputingModel,
    JobStatus,
    QubitModality,
)
from ..schemas.result import (
    QuantumResult,
    ShotResult,
)
from ._qiskit_common import load_qiskit_circuit


class QiboAdapter:
    """Qibo adapter (local simulator, Qibolab hardware, or Qibo cloud).

    Parameters
    ----------
    platform:
        For ``execution="local"``: the Qibo simulation engine ("numpy",
        "qibojit", ...). For "qibolab": the Qibolab Platform name. For
        "cloud": the remote device id ("sim", "ibm_kyiv", ...).
    execution:
        ``"local"`` (default), ``"qibolab"``, or ``"cloud"``.
    client:
        Cloud client — ``"qibo-client"`` (TII) or ``"qiskit-client"`` (IBM).
        Only used when ``execution="cloud"``.
    token_ref:
        Env-var name holding the cloud access token.
    num_qubits:
        Expected qubit count; used for the spec only.
    qubit_modality:
        QPU modality for hardware backends (default SUPERCONDUCTING).
    """

    def __init__(
        self,
        platform: str = "numpy",
        *,
        execution: str = "local",
        client: str = "qibo-client",
        token_ref: str = "",
        num_qubits: int | None = None,
        qubit_modality: QubitModality | None = None,
    ) -> None:
        self._execution = execution
        self._platform  = platform
        self._client    = client
        self._token_ref = token_ref

        if execution == "local":
            self._spec = BackendSpec.qibo_simulator(platform, num_qubits=num_qubits)
        elif execution == "qibolab":
            self._spec = BackendSpec.qibolab(
                platform,
                num_qubits=num_qubits,
                qubit_modality=qubit_modality or QubitModality.SUPERCONDUCTING,
            )
        elif execution == "cloud":
            self._spec = BackendSpec.qibo_cloud(
                platform,
                client=client,
                token_ref=token_ref,
                num_qubits=num_qubits,
                qubit_modality=qubit_modality or QubitModality.SUPERCONDUCTING,
            )
        else:
            raise ValueError(
                f"QiboAdapter: execution must be 'local', 'qibolab', or 'cloud'; "
                f"got {execution!r}"
            )

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append(
                f"QiboAdapter expects GATE_BASED; got {circuit.computing_model}"
            )
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3):
            warnings.append(
                f"QiboAdapter accepts QASM2/3 circuits; got {circuit.format}"
            )
        if circuit.is_parametric() and not circuit.is_bound():
            warnings.append("Circuit has unbound parameters")
        return warnings

    # ------------------------------------------------------------------

    def _activate_backend(self) -> None:
        """Select the global Qibo backend for this adapter's execution mode."""
        import qibo

        if self._execution == "local":
            qibo.set_backend(self._platform)
        elif self._execution == "qibolab":
            qibo.set_backend("qibolab", platform=self._platform)
        else:  # cloud
            token = os.environ.get(self._token_ref, "") if self._token_ref else ""
            qibo.set_backend(
                "qibo-cloud-backends",
                client=self._client,
                token=token,
                platform=self._platform,
            )

    def _load_qibo_circuit(self, circuit: CircuitSpec) -> Any:
        from qibo import Circuit

        if circuit.format == CircuitFormat.QASM2:
            return Circuit.from_qasm(circuit.serialized or "")
        # QASM3 (or anything Qiskit can load) -> QASM2 for Qibo's parser.
        from qiskit import qasm2

        return Circuit.from_qasm(qasm2.dumps(load_qiskit_circuit(circuit)))

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Execute on the selected Qibo backend and return raw counts."""
        if circuit.observables:
            raise NotImplementedError(
                "QiboAdapter: Estimator path not available — Qibo hardware "
                "(Qibolab / cloud) returns measurement samples, not expectation "
                "values (confirmed against qibo 0.2.23); use the Sampler path "
                "and compute observables classically from counts."
            )

        from qibo import gates

        self._activate_backend()
        qc = self._load_qibo_circuit(circuit)
        if not qc.measurements:
            qc.add(gates.M(*range(qc.nqubits)))

        shots = options.require_shots("QiboAdapter")
        result = qc(nshots=shots)

        # Qibo is big-endian (qubit 0 leftmost); reverse to the Qiskit
        # little-endian convention ShotResult documents.
        counts = {
            str(bitstring)[::-1]: int(n)
            for bitstring, n in result.frequencies(binary=True).items()
        }
        memory: list[str] = []
        if options.memory:
            memory = [
                "".join(str(int(b)) for b in row)[::-1]
                for row in result.samples(binary=True)
            ]

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
