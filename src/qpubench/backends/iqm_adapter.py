"""IQM hardware backend adapter.

Install: pip install 'qpubench[iqm]'   (iqm-client[qiskit])

Hardware topology:
  IQM uses a **Star architecture** (e.g. IQM Garnet 20Q, IQM Sirius 24Q):
  all qubits connect via a shared computational resonator (COMPR1), giving
  effective all-to-all connectivity without SWAP routing.

Native gate set:
  r(theta, phi)  — parametric rotation (PRX under a different Qiskit
               instruction name; confirmed on the real transpiled output
               below): exp(-i pi theta (X cos(2*pi*phi) + Y sin(2*pi*phi)))
  cz         — controlled-Z (symmetric, no arguments)
  MOVE       — population exchange qubit <-> computational resonator
               (Star topology only; not a standard unitary on qubits)

IQM Resonance cloud:
  Endpoint: https://cocos.resonance.meetiqm.com/v1
  Auth:     bearer token set via IQM_TOKEN env var or passed to IQMProvider.
  Known devices: garnet (20Q), deneb (6Q), sirius (24Q Star).

Import path change (verified empirically)
------------------------------------------
The standalone ``qiskit-iqm``/``qiskit_on_iqm`` packages are obsolete —
importing ``qiskit_iqm`` now raises
``RuntimeError: The qiskit-iqm package is obsolete ... use iqm-client[qiskit]
instead``. The real, current package is ``iqm-client[qiskit]`` (>=22.10),
which bundles the same functionality under the ``iqm.qiskit_iqm`` /
``iqm.iqm_client`` namespace — confirmed by installing both in an isolated
sandbox venv and inspecting ``IQMProvider``/``IQMClient`` directly.

qiskit-iqm usage:
  from iqm.qiskit_iqm import IQMProvider
  provider = IQMProvider(url, token=os.environ["IQM_TOKEN"])
  backend  = provider.get_backend(device_name)
  pm = generate_preset_pass_manager(optimization_level=3, backend=backend)

Verified for real (no live IQM server) via ``iqm.qiskit_iqm.fake_backends``
(``IQMFakeAdonis`` etc. — bundled local BackendV2 instances): transpile +
Sampler-path run both confirmed correct on a Bell circuit, including the
real native gate names above and Star-topology final qubit layout.

Calibration data (via IQMClient.get_calibration_set()):
  Confirmed against iqm-client 34.0.4: CalibrationSet.observations is a
  list of ObservationLite(dut_field, value, unit, uncertainty, ...) — the
  real source of per-qubit/per-gate T1/T2/fidelity numbers (not
  DynamicQuantumArchitecture.components/operations, which only names
  qubits/gates, not their calibrated values).

Credentials: set via BackendSpec.auth or environment variable —
  IQM_TOKEN   (bearer token from IQM Resonance dashboard)
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
)
from ..schemas.result import (
    QuantumResult,
    ShotResult,
    TranspileLayout,
)
from ._qiskit_common import load_qiskit_circuit


class IQMAdapter:
    """IQM hardware adapter using iqm-client's Qiskit bridge (IQMProvider / IQMBackend).

    Parameters
    ----------
    device_name:
        IQM device identifier, e.g. ``"garnet"``, ``"deneb"``, ``"sirius"``.
    url:
        IQM Resonance endpoint URL.
        Default: ``"https://cocos.resonance.meetiqm.com/v1"``.
    token_ref:
        *Name of the environment variable* holding the IQM Resonance bearer
        token — not the token itself. Defaults to ``"IQM_TOKEN"``. There is
        deliberately no way to pass the token as a literal argument; see the
        credentials section of the root README.
    num_qubits:
        Expected qubit count; used for validation only.
    """

    _RESONANCE_URL = "https://cocos.resonance.meetiqm.com/v1"

    def __init__(
        self,
        device_name: str,
        *,
        url: str | None = None,
        token_ref: str = "IQM_TOKEN",
        num_qubits: int | None = None,
    ) -> None:
        """Configure the adapter; no network call and no credential read yet."""
        self._device_name = device_name
        self._url = url if url is not None else os.environ.get("IQM_SERVER_URL", self._RESONANCE_URL)
        self._token_ref = token_ref
        self._spec = BackendSpec.iqm_resonance(
            device_name, num_qubits=num_qubits, api_token_ref=token_ref
        )

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append(f"IQMAdapter expects GATE_BASED; got {circuit.computing_model}")
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3):
            warnings.append(
                f"IQMAdapter accepts QASM2/3 circuits (transpiled internally); got {circuit.format}"
            )
        if circuit.is_parametric() and not circuit.is_bound():
            warnings.append("Circuit has unbound parameters")
        return warnings

    # ------------------------------------------------------------------

    def _get_backend(self) -> Any:
        """Open a credentialed provider and return the live backend.

        The token is read from the environment here, at the point of use, so
        it is never held on the adapter or serialised into a BenchmarkRecord.
        """
        from iqm.qiskit_iqm import IQMProvider  # type: ignore[attr-defined]

        token = os.environ.get(self._token_ref)
        if not token:
            raise RuntimeError(
                f"No IQM token found in ${self._token_ref}. Set it in your "
                ".env / environment (see .env.example), or point the adapter "
                'at a different variable with IQMAdapter(..., token_ref="MY_VAR").'
            )
        provider = IQMProvider(self._url, token=token)
        return provider.get_backend(self._device_name)

    def _transpile_qc(self, circuit: CircuitSpec, options: ExecutionOptions, backend: Any) -> Any:
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

        qc = load_qiskit_circuit(circuit)
        pm = generate_preset_pass_manager(
            optimization_level=options.optimization_level,
            backend=backend,
            seed_transpiler=options.seed,
        )
        return pm.run(qc)

    def transpile(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[CircuitSpec, TranspileLayout | None]:
        """Transpile to IQM native gates (r/cz, Star-topology MOVE) via iqm-client."""
        from qiskit import qasm3

        backend = self._get_backend()
        tqc = self._transpile_qc(circuit, options, backend)

        final_positions = tqc.layout.final_index_layout() if tqc.layout else list(range(circuit.num_qubits))
        transpile_layout = TranspileLayout(
            num_virtual=circuit.num_qubits,
            num_physical=backend.num_qubits,
            initial_layout=list(range(circuit.num_qubits)),
            final_layout=list(final_positions),
        )
        transpiled = circuit.model_copy(update={
            "serialized": qasm3.dumps(tqc),
            "gate_counts": dict(tqc.count_ops()),
            "format": CircuitFormat.QASM3,
        })
        return transpiled, transpile_layout

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Transpile and submit to IQM Resonance via iqm-client's Qiskit bridge."""
        if circuit.observables:
            raise NotImplementedError(
                "IQMAdapter: Estimator path not available — iqm-client's qiskit "
                "bridge (iqm.qiskit_iqm, confirmed against 34.0.4) exposes no "
                "EstimatorV2-equivalent; use the Sampler path and compute "
                "observables classically from counts."
            )

        backend = self._get_backend()
        tqc = self._transpile_qc(circuit, options, backend)
        if not tqc.cregs:
            tqc.measure_all()

        shots = options.require_shots("IQMAdapter")
        job = backend.run(tqc, shots=shots, memory=options.memory)
        result = job.result()
        counts = dict(result.get_counts())
        # Per-shot memory: supported by real IQM hardware backends, not by
        # the bundled fake/local backends (confirmed: IQMFakeAdonis.run()
        # ignores memory=True and get_memory() raises).
        memory = result.get_memory() if options.memory else []

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
            qpu_time_s=getattr(result, "time_taken", None),
        )

    # ------------------------------------------------------------------
    # Calibration helper
    # ------------------------------------------------------------------

    @staticmethod
    def fetch_calibration(
        device_name: str, url: str, *, token_ref: str = "IQM_TOKEN"
    ) -> dict[str, object]:
        """Fetch per-qubit and per-gate calibration data from IQM Client.

        ``token_ref`` names the environment variable holding the bearer token;
        the token itself is never taken as an argument.

        Typical values (device-dependent):
          T1      ~28 us
          T2*     ~17 us
          T2 echo ~28 us
          PRX     ~99.79 % fidelity
          CZ      ~98.42 % fidelity
        """
        from iqm.iqm_client import IQMClient

        token = os.environ.get(token_ref)
        if not token:
            raise RuntimeError(
                f"No IQM token found in ${token_ref}. Set it in your .env / "
                "environment (see .env.example)."
            )
        client = IQMClient(url, token=token)
        calibration_set = client.get_calibration_set()

        calibration: dict[str, object] = {}
        for obs in calibration_set.observations:
            calibration[obs.dut_field] = {
                "value": obs.value,
                "unit": obs.unit,
                "uncertainty": obs.uncertainty,
            }
        return calibration
