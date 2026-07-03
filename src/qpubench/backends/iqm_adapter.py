"""IQM hardware backend adapter.

Install:
  pip install iqm-client            # core client + REST API
  pip install qiskit-iqm            # Qiskit provider (qiskit_on_iqm)
  pip install cirq-iqm              # Cirq provider (optional)

Hardware topology:
  IQM uses a **Star architecture** (e.g. IQM Garnet 20Q, IQM Sirius 24Q):
  all qubits connect via a shared computational resonator (COMPR1), giving
  effective all-to-all connectivity without SWAP routing.

Native gate set:
  PRX(θ, φ)  — parametric rotation:
               exp(-i π θ (X cos(2πφ) + Y sin(2πφ)))
               angles in **fractions of turns** (not radians!):
               θ = 0.5 → π rotation, φ = 0.25 → Y basis
  CZ         — controlled-Z (symmetric, no arguments)
  MOVE       — population exchange qubit ↔ computational resonator
               (Star topology only; not a standard unitary on qubits)

IQM Resonance cloud:
  Endpoint: https://cocos.resonance.meetiqm.com/v1
  Auth:     bearer token set via IQM_TOKEN env var or passed to IQMProvider.
  Known devices: garnet (20Q), deneb (6Q), sirius (24Q Star).

qiskit-iqm usage:
  from qiskit_on_iqm import IQMProvider
  provider  = IQMProvider(url, token=os.environ["IQM_TOKEN"])
  backend   = provider.get_backend()
  pm = generate_preset_pass_manager(optimization_level=3, backend=backend)

Calibration data (via IQMClient.get_dynamic_quantum_architecture()):
  T1 ~28 µs, T2* ~17 µs, T2 echo ~28 µs
  PRX fidelity ~99.79%, CZ fidelity ~98.42% (device-dependent)

Credentials: set via BackendSpec.auth or environment variable —
  IQM_TOKEN   (bearer token from IQM Resonance dashboard)
"""

from __future__ import annotations

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.primitives import (
    CircuitFormat,
    QPUModality,
)
from ..schemas.result import (
    QuantumResult,
    TranspileLayout,
)


class IQMAdapter:
    """IQM hardware adapter using qiskit-iqm (IQMProvider / IQMBackend).

    Parameters
    ----------
    device_name:
        IQM device identifier, e.g. ``"garnet"``, ``"deneb"``, ``"sirius"``.
    url:
        IQM Resonance endpoint URL.
        Default: ``"https://cocos.resonance.meetiqm.com/v1"``.
    token:
        Bearer token for IQM Resonance.
        Falls back to ``IQM_TOKEN`` environment variable.
    num_qubits:
        Expected qubit count; used for validation only.
    """

    _RESONANCE_URL = "https://cocos.resonance.meetiqm.com/v1"

    def __init__(
        self,
        device_name: str,
        *,
        url: str = _RESONANCE_URL,
        token: str | None = None,
        num_qubits: int | None = None,
    ) -> None:
        self._device_name = device_name
        self._url = url
        self._token = token
        self._spec = BackendSpec.iqm_resonance(
            device_name, num_qubits=num_qubits, api_token_ref=token or ""
        )

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.modality != QPUModality.GATE_BASED:
            warnings.append(f"IQMAdapter expects GATE_BASED; got {circuit.modality}")
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3):
            warnings.append(
                f"IQMAdapter accepts QASM2/3 circuits (transpiled internally); got {circuit.format}"
            )
        if circuit.is_parametric() and not circuit.is_bound():
            warnings.append("Circuit has unbound parameters")
        return warnings

    def transpile(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[CircuitSpec, TranspileLayout | None]:
        """Transpile to IQM native gates via qiskit-iqm.

        TODO: fill in with real implementation —

            import os
            from qiskit import QuantumCircuit
            from qiskit_on_iqm import IQMProvider
            from qiskit.transpiler.preset_passmanagers import (
                generate_preset_pass_manager,
            )

            provider = IQMProvider(
                self._url,
                token=self._token or os.environ["IQM_TOKEN"],
            )
            backend = provider.get_backend()

            qc  = QuantumCircuit.from_qasm_str(circuit.serialized)
            pm  = generate_preset_pass_manager(
                optimization_level=options.optimization_level,
                backend=backend,
                seed_transpiler=options.seed,
            )
            tqc = pm.run(qc)

            # Star topology: IQMNaiveResonatorMoving pass may insert MOVE gates.
            # The coupling map uses qubit↔resonator edges, not qubit↔qubit.
            # Physical qubit names are e.g. "QB1" … "QB20" + "COMPR1".

            layout = tqc.layout
            # extract initial / final virtual→physical mapping
            transpile_layout = TranspileLayout(
                num_virtual=circuit.num_qubits,
                num_physical=backend.num_qubits,
                initial_layout=list(range(circuit.num_qubits)),
                final_layout=list(range(circuit.num_qubits)),
            )
            transpiled = circuit.model_copy(update={
                "serialized": tqc.qasm(),
                "gate_counts": dict(tqc.count_ops()),
                "format": "qasm3",
            })
            return transpiled, transpile_layout
        """
        raise NotImplementedError("IQMAdapter.transpile: see TODO in iqm_adapter.py")

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Transpile and submit to IQM Resonance via qiskit-iqm.

        TODO: fill in with real implementation —

            import os
            from qiskit import QuantumCircuit
            from qiskit_on_iqm import IQMProvider
            from qiskit.transpiler.preset_passmanagers import (
                generate_preset_pass_manager,
            )

            provider = IQMProvider(
                self._url,
                token=self._token or os.environ["IQM_TOKEN"],
            )
            backend = provider.get_backend()

            qc  = QuantumCircuit.from_qasm_str(circuit.serialized)
            pm  = generate_preset_pass_manager(
                optimization_level=options.optimization_level,
                backend=backend,
                seed_transpiler=options.seed,
            )
            tqc = pm.run(qc)

            shots = options.shots or 1024

            # --- Estimator path (observables present) ---
            if circuit.observables:
                from qiskit_ibm_runtime import EstimatorV2 as Estimator
                # IQM does not yet expose an IBM-style EstimatorV2.
                # Use the Qiskit Statevector backend as a local stand-in for
                # now; replace with IQM's native expectation-value estimation
                # when available in qiskit-iqm.
                raise NotImplementedError(
                    "IQMAdapter: Estimator path not yet available via qiskit-iqm; "
                    "use the Sampler path and compute observables classically."
                )

            # --- Sampler path (bitstring counts) ---
            job    = backend.run(tqc, shots=shots, rep_delay=options.rep_delay_s)
            result = job.result()
            counts = dict(result.get_counts())
            memory = result.get_memory() if options.memory else []

            return QuantumResult(
                modality=QPUModality.GATE_BASED,
                shots=ShotResult(
                    num_qubits=circuit.num_qubits,
                    num_shots=shots,
                    counts=counts,
                    memory=memory,
                ),
                status=JobStatus.SUCCEEDED,
                job_id=job.job_id(),
                qpu_time_s=result.time_taken,
            )
        """
        raise NotImplementedError("IQMAdapter.run: see TODO in iqm_adapter.py")

    # ------------------------------------------------------------------
    # Calibration helper
    # ------------------------------------------------------------------

    @staticmethod
    def fetch_calibration(device_name: str, url: str, token: str) -> dict[str, object]:
        """Fetch per-qubit and per-gate calibration data from IQM Client.

        TODO: fill in with real implementation —

            import os
            from iqm.iqm_client import IQMClient

            client = IQMClient(url, token=token)
            arch   = client.get_dynamic_quantum_architecture()

            # arch.components is a dict of component_name → ComponentInfo
            # Each ComponentInfo carries calibration_sets with T1, T2*, T2 echo,
            # PRX fidelity, CZ fidelity, MOVE fidelity (Star topology).
            #
            # Typical values (device-dependent):
            #   T1      ~28 µs
            #   T2*     ~17 µs
            #   T2 echo ~28 µs
            #   PRX     ~99.79 % fidelity
            #   CZ      ~98.42 % fidelity

            calibration: dict[str, object] = {}
            for comp_name, comp_info in arch.components.items():
                calibration[comp_name] = {
                    "t1_s":  comp_info.t1_s,
                    "t2_s":  comp_info.t2_s,
                    "t2e_s": comp_info.t2e_s,
                }
            for op_name, op_calib in arch.operations.items():
                for loci, props in op_calib.items():
                    calibration[f"{op_name}_{loci}"] = {
                        "fidelity": props.fidelity,
                        "duration_s": props.duration_s,
                    }
            return calibration
        """
        raise NotImplementedError("IQMAdapter.fetch_calibration: see TODO in iqm_adapter.py")
