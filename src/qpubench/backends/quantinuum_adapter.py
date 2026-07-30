"""Quantinuum H-Series hardware backend adapter.

Install: pip install 'qpubench[quantinuum]'   (pytket-quantinuum + pytket-qiskit)

Hardware
--------
Quantinuum's H-Series are trapped-ion QPUs (QCCD architecture with ion
shuttling), giving effective **all-to-all connectivity** — no SWAP routing.
Devices (see https://docs.quantinuum.com/systems/trainings/h2/getting_started/api_options.html):

  H2-1     — 56-qubit H2 hardware
  H2-1E    — H2 emulator (physically-accurate noise model, runs in the cloud)
  H2-1SC   — H2 syntax checker (free circuit validation; returns no counts)
  H1-1 / H1-1E / H1-1SC  — 20-qubit H1 generation

Native gate set (confirmed empirically against pytket-quantinuum 0.59.1 by
compiling a Bell circuit offline — see the transpile() output):
  Rz(theta)        — virtual Z rotation
  PhasedX(a, b)    — U1q(a, b), single-qubit XY-plane rotation
  ZZPhase(t)       — RZZ(t) two-qubit entangler (ZZMax / TK2 also in the 2Q set)

Access path — why pytket, not Qiskit
------------------------------------
Unlike the IBM/IQM/Braket adapters, Quantinuum has no Qiskit ``BackendV2`` /
PUB-primitive interface. The current, official Python route is
``pytket-quantinuum``'s ``QuantinuumBackend`` (submitting through Quantinuum
Nexus), driven with pytket ``Circuit`` objects. This adapter therefore
converts the CircuitSpec's QASM into a pytket ``Circuit`` via
``pytket.extensions.qiskit.qiskit_to_tk`` (reusing the shared
``load_qiskit_circuit`` helper), compiles with the device's own
``get_compiled_circuit``, and submits via ``process_circuit`` /
``get_result``. The transpiled circuit is serialised back to OpenQASM 3.0 by
converting the compiled pytket circuit to Qiskit (``tk_to_qiskit``) and
``qasm3.dumps`` — the native ``PhasedX``/``ZZPhase`` gates are emitted as
QASM3 gate definitions, exactly like the IBM/IQM adapters do with their
native gates.

Verified for real (no live Quantinuum account) against pytket-quantinuum
0.59.1: the transpile path runs offline via ``QuantinuumBackend(...,
machine_debug=True)`` (real Quantinuum compilation to Rz/PhasedX/ZZPhase);
the full sampler plumbing (qiskit->tket conversion, process_circuit,
get_result, counts parsing) is exercised against a local pytket simulator.
Only the credential-fetching ``_get_backend()`` call needs a real account.

Estimator path
--------------
Like the IQM adapter, the Estimator path is intentionally not implemented:
Quantinuum exposes no server-side expectation-value primitive. Use the
Sampler path and reconstruct expectation values classically from counts.

Credentials
-----------
pytket-quantinuum authenticates through the Quantinuum Nexus credential
store — run ``QuantinuumBackend.login()`` (or ``qnexus.login()``) once to
cache a token. The account username/email may be supplied non-interactively
via an environment variable named by ``BackendSpec.auth["user_ref"]``.
"""

from __future__ import annotations

from collections import Counter
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
    QuantumResult,
    ShotResult,
    TranspileLayout,
)
from ._qiskit_common import load_qiskit_circuit


class QuantinuumAdapter:
    """Quantinuum H-Series adapter using pytket-quantinuum's QuantinuumBackend.

    Parameters
    ----------
    device_name:
        Quantinuum device identifier, e.g. ``"H2-1"`` (hardware),
        ``"H2-1E"`` (emulator), ``"H2-1SC"`` (syntax checker).
    num_qubits:
        Expected qubit count; used for validation / spec only.
    user_ref:
        Env-var name holding the Quantinuum account username/email for
        non-interactive login.
    """

    def __init__(
        self,
        device_name: str = "H2-1E",
        *,
        num_qubits: int | None = None,
        user_ref: str = "",
    ) -> None:
        self._device_name = device_name
        self._spec = BackendSpec.quantinuum(
            device_name, num_qubits=num_qubits, user_ref=user_ref
        )

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.computing_model != ComputingModel.GATE_BASED:
            warnings.append(
                f"QuantinuumAdapter expects GATE_BASED; got {circuit.computing_model}"
            )
        if circuit.format not in (CircuitFormat.QASM2, CircuitFormat.QASM3):
            warnings.append(
                f"QuantinuumAdapter accepts QASM2/3 circuits (transpiled internally); "
                f"got {circuit.format}"
            )
        if circuit.is_parametric() and not circuit.is_bound():
            warnings.append("Circuit has unbound parameters")
        return warnings

    # ------------------------------------------------------------------

    def _get_backend(self) -> Any:
        from pytket.extensions.quantinuum import QuantinuumBackend

        return QuantinuumBackend(device_name=self._device_name)

    def _load_tket(self, circuit: CircuitSpec) -> Any:
        from pytket.extensions.qiskit import qiskit_to_tk

        return qiskit_to_tk(load_qiskit_circuit(circuit))

    def _compile(self, circuit: CircuitSpec, options: ExecutionOptions, backend: Any) -> Any:
        """Compile to Quantinuum native gates at the requested optimisation level.

        ``ExecutionOptions.optimization_level`` spans Qiskit's 0-3 range, but
        pytket only defines levels 0-2. Level 3 is rejected rather than
        silently clamped to 2: quietly running a different optimisation level
        than the one a benchmark asked for would make its results
        incomparable with the same level on another backend.
        """
        if options.optimization_level > 2:
            raise ValueError(
                f"Quantinuum (pytket) supports optimisation levels 0-2; got "
                f"{options.optimization_level}. Choose a level in that range "
                "explicitly — see docs/backends.md for the per-backend ranges."
            )
        tkc = self._load_tket(circuit)
        return backend.get_compiled_circuit(
            tkc, optimisation_level=options.optimization_level
        )

    def transpile(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[CircuitSpec, TranspileLayout | None]:
        """Compile to Quantinuum native gates (Rz / PhasedX / ZZPhase)."""
        from pytket.extensions.qiskit import tk_to_qiskit
        from qiskit import qasm3

        backend = self._get_backend()
        compiled = self._compile(circuit, options, backend)

        gate_counts = {
            str(t).removeprefix("OpType."): n
            for t, n in Counter(cmd.op.type for cmd in compiled.get_commands()).items()
        }
        transpile_layout = TranspileLayout(
            num_virtual=circuit.num_qubits,
            num_physical=compiled.n_qubits,
            initial_layout=list(range(circuit.num_qubits)),
            final_layout=list(range(compiled.n_qubits)),
        )
        transpiled = circuit.model_copy(update={
            "serialized": qasm3.dumps(tk_to_qiskit(compiled)),
            "gate_counts": gate_counts,
            "format": CircuitFormat.QASM3,
        })
        return transpiled, transpile_layout

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Compile and submit to Quantinuum via pytket-quantinuum."""
        if circuit.observables:
            raise NotImplementedError(
                "QuantinuumAdapter: Estimator path not available — Quantinuum "
                "exposes no server-side expectation-value primitive (confirmed "
                "against pytket-quantinuum 0.59.1); use the Sampler path and "
                "compute observables classically from counts."
            )

        backend = self._get_backend()
        compiled = self._compile(circuit, options, backend)
        if compiled.n_bits == 0:
            compiled.measure_all()

        shots = options.require_shots("QuantinuumAdapter")
        handle = backend.process_circuit(compiled, n_shots=shots, seed=options.seed)
        result = backend.get_result(handle)

        # pytket returns counts keyed by tuples of ints (MSB-first); join to
        # the bitstrings ShotResult expects.
        counts = {
            "".join(str(b) for b in outcome): n
            for outcome, n in result.get_counts().items()
        }
        memory: list[str] = []
        if options.memory:
            memory = ["".join(str(b) for b in shot) for shot in result.get_shots()]

        return QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            shots=ShotResult(
                num_qubits=circuit.num_qubits,
                num_shots=shots,
                counts=counts,
                memory=memory,
            ),
            status=JobStatus.SUCCEEDED,
            job_id=str(handle),
        )
