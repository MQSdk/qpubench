"""Template: BackendAdapter for a gate-based backend or simulator.

Use this when your backend/simulator accepts a circuit and returns
measurement results.  Copy this file into your project and fill every TODO.

Backends that fit this pattern
-------------------------------
  Gate-based simulators   (Aer, Qrack, custom statevector)
  Gate-based QPU hardware (IBM, IQM, Qibo, any cloud provider)
  MBQC-FPGA               (set circuit.computing_model = ComputingModel.MBQC)

Backends that do NOT fit — use AlgorithmAdapterTemplate instead
---------------------------------------------------------------
  Algorithm libraries that generate their own circuits from a problem spec
  (QForte, PySCF+OpenFermion, ADAPT-VQE implementations, etc.)
"""
from __future__ import annotations

from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.primitives import ComputingModel, JobStatus
from qpubench.schemas.result import (
    ExpectationResult,
    QuantumResult,
    ShotResult,
)


class MyBackendAdapter:
    """Replace 'MyBackend' with your backend's name throughout."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        # TODO: add constructor parameters your backend needs
        # e.g. device_name: str, token: str, num_qubits: int
    ) -> None:
        # TODO: store credentials / connection details
        # TODO: build self._spec using BackendSpec
        self._spec = BackendSpec(
            name="my_backend",           # TODO: your backend's canonical name
            provider="my_provider",      # TODO: provider string
            simulator=True,              # TODO: True if simulator, False if hardware
            computing_model=ComputingModel.GATE_BASED,
            num_qubits=None,             # TODO: max qubits if fixed
            native_gates=[],             # TODO: list of supported gate names
        )

    # ------------------------------------------------------------------
    # Protocol (these three methods are what qpubench calls)
    # ------------------------------------------------------------------

    @property
    def spec(self) -> BackendSpec:
        return self._spec

    def validate(self, circuit: CircuitSpec) -> list[str]:
        """Return a list of warning strings; raise ValueError for hard errors.

        Check whatever matters for your backend:
          - qubit count vs circuit.num_qubits
          - supported circuit formats
          - parametric circuits need all parameters bound
          - modality compatibility
        """
        warnings: list[str] = []

        # TODO: add your validation logic
        # Example:
        # if circuit.num_qubits > self._max_qubits:
        #     warnings.append(f"Circuit needs {circuit.num_qubits} qubits, "
        #                     f"backend supports {self._max_qubits}")
        # if circuit.is_parametric() and not circuit.is_bound():
        #     warnings.append("Circuit has unbound parameters")

        return warnings

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Execute the circuit and return a QuantumResult.

        The runner measures total wall time automatically; set qpu_time_s
        from your backend's own timing if you have it.

        Two paths depending on whether observables are set:

        Estimator path  (circuit.observables is non-empty)
            Run the circuit and measure ⟨O⟩ for each observable.
            Return QuantumResult with expectation_values populated.

        Sampler path  (circuit.observables is empty)
            Run the circuit options.shots times.
            Return QuantumResult with shots populated.
        """
        try:
            if circuit.observables:
                return self._run_estimator(circuit, options)
            else:
                return self._run_sampler(circuit, options)
        except Exception as exc:
            return QuantumResult(
                computing_model=circuit.computing_model,
            qubit_modality=circuit.qubit_modality,
                status=JobStatus.FAILED,
                error_message=str(exc),
            )

    # ------------------------------------------------------------------
    # Internal helpers — implement these
    # ------------------------------------------------------------------

    def _run_estimator(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Measure expectation values for all circuit.observables."""

        # TODO: step 1 — load / compile the circuit
        # e.g. qc = load_qasm(circuit.serialized)

        # TODO: step 2 — convert observables to your backend's format
        # Each observable is a SparsePauliObservable; use:
        #   qubits, paulis = obs.to_qrack_flat_arrays()   ← for Qrack
        #   qubits, terms  = obs.to_qiskit_c_arrays()     ← for Qiskit C API
        # Or build whatever your backend needs.

        # TODO: step 3 — run and collect energies
        # raw_energies = [my_backend.expectation(qc, obs) for obs in circuit.observables]

        # TODO: step 4 — build result
        evs = [
            ExpectationResult(
                observable_index=i,
                value=0.0,          # TODO: replace with raw_energies[i]
                std_error=0.0,      # TODO: shot-based std error if applicable
                num_shots=options.shots,
            )
            for i in range(len(circuit.observables))
        ]
        return QuantumResult(
            computing_model=circuit.computing_model,
            qubit_modality=circuit.qubit_modality,
            expectation_values=evs,
            status=JobStatus.SUCCEEDED,
            qpu_time_s=None,        # TODO: fill from backend timing
        )

    def _run_sampler(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Collect shot-level bitstring counts."""

        shots = options.shots or 1024

        # TODO: step 1 — load / compile the circuit
        # TODO: step 2 — run for `shots` shots
        # TODO: step 3 — collect counts as dict[bitstring, int]
        counts: dict[str, int] = {}   # TODO: replace with real counts

        return QuantumResult(
            computing_model=circuit.computing_model,
            qubit_modality=circuit.qubit_modality,
            shots=ShotResult(
                num_qubits=circuit.num_qubits,
                num_shots=shots,
                counts=counts,
                memory=[],          # TODO: per-shot list if options.memory=True
            ),
            status=JobStatus.SUCCEEDED,
            qpu_time_s=None,
        )
