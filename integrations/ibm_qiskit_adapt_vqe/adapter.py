"""ADAPT-VQE via a from-scratch, Qiskit-circuit-convention implementation.

Implements qpubench's AlgorithmAdapter protocol on top of the package-
agnostic engine in integrations/generic_adapt_vqe/ — pool generation,
Jordan-Wigner mapping, circuit synthesis, gradient screening, and the
optimizer loop live there and are shared verbatim with
integrations/microsoft_qdk_adapt_vqe/. This adapter differs from that one
only in its BackendSpec naming/defaults: it demonstrates that
AlgorithmFamily.ADAPT_VQE can be satisfied by more than one package —
evangelistalab/qforte's native C++ implementation
(integrations/qforte/adapter.py), or this one, registered side by side and
driven with the same AdaptVQEConfig.

Circuit synthesis here emits standard OpenQASM 3.0 (gate names h, rx, rz,
cx) — the same convention IBMAdapter / AerAdapter already speak — so any
qpubench BackendAdapter can serve as the energy oracle without a Qiskit
installation being required for the algorithm logic itself; only the
energy_backend you register (e.g. a real Qiskit/Aer-backed AerAdapter) pulls
in the Qiskit SDK, consistent with qpubench's "SDK imports go inside the
method that uses them" rule for adapters.

Separation contract
-------------------
qpubench core never imports from any quantum SDK. This file and
generic_adapt_vqe/ import from qpubench only — they are pure Python
(+ scipy for the classical optimizer), no vendor SDK required at all.
"""
from __future__ import annotations

import json
from typing import Any

from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import AdaptVQEConfig, ExecutionOptions
from qpubench.schemas.observable import SparsePauliObservable
from qpubench.schemas.primitives import CircuitFormat, ComputingModel
from qpubench.schemas.record import VQAConfig, VQAResult
from qpubench.schemas.result import QuantumResult

from ..generic_adapt_vqe.engine import GenericAdaptVQEEngine


class IBMQiskitAdaptVQEAdapter:
    """ADAPT-VQE with Qiskit-style OpenQASM 3.0 circuits, any energy backend.

    Problem spec contract (CircuitSpec, format=MOLECULE_JSON)
    -----------------------------------------------------------
    serialized is a JSON object:
        {
          "num_qubits":    4,
          "num_electrons": 2,
          "hamiltonian":   <SparsePauliObservable.model_dump()>
        }
    Molecular electronic-structure work (SCF, active-space selection,
    fermionic-to-qubit mapping) is out of scope here — build the qubit
    Hamiltonian with whichever chemistry pipeline you like (e.g.
    microsoft_qdk.py's QChemPipelineSpec) and hand it in pre-mapped.

    Parameters
    ----------
    energy_backend:
        A qpubench BackendAdapter used for energy evaluation (Estimator
        path — circuit.observables populated). Aer, Qrack, IBM Quantum
        Runtime, or any other registered backend.
    energy_options:
        ExecutionOptions forwarded to energy_backend.run(). shots=None
        (statevector) is recommended — the gradient screen uses finite
        differences, which shot noise makes unreliable at small epsilon.
    """

    def __init__(
        self,
        energy_backend: Any,
        energy_options: ExecutionOptions | None = None,
    ) -> None:
        self._energy_backend = energy_backend
        self._energy_options = energy_options or ExecutionOptions()

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(
            name=f"ibm_qiskit_adapt_vqe+{self._energy_backend.spec.name}",
            provider="ibm_qiskit_adapt_vqe",
            simulator=self._energy_backend.spec.simulator,
            computing_model=ComputingModel.GATE_BASED,
        )

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.format != CircuitFormat.MOLECULE_JSON:
            warnings.append(
                f"IBMQiskitAdaptVQEAdapter expects format=MOLECULE_JSON; "
                f"got {circuit.format.value!r}"
            )
        if not circuit.serialized:
            warnings.append("CircuitSpec.serialized is empty.")
        return warnings

    def run_algorithm(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[QuantumResult, VQAConfig, VQAResult]:
        spec        = json.loads(circuit.serialized or "{}")
        hamiltonian = SparsePauliObservable.model_validate(spec["hamiltonian"])
        config      = options.adapt_vqe_config or AdaptVQEConfig()

        engine = GenericAdaptVQEEngine(
            hamiltonian=hamiltonian,
            num_qubits=spec["num_qubits"],
            num_electrons=spec["num_electrons"],
            energy_backend=self._energy_backend,
            config=config,
            energy_options=self._energy_options,
        )
        return engine.run()
