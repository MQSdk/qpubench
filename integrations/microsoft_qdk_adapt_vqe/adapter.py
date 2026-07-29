"""ADAPT-VQE targeting QDK / Azure Quantum simulators and hardware.

Implements qpubench's AlgorithmAdapter protocol on top of the package-
agnostic engine in integrations/generic_adapt_vqe/ — identical pool
generation, Jordan-Wigner mapping, circuit synthesis, gradient screening,
and optimizer loop as integrations/ibm_qiskit_adapt_vqe/adapter.py. Only the
BackendSpec naming/defaults differ (QDK simulator / Azure Quantum targets
via BackendSpec.qdk_chemistry_simulator() / BackendSpec.azure_quantum(),
see src/qpubench/schemas/backend.py).

Why this exists alongside microsoft_qdk.py
--------------------------------------------
schemas/mirrors/microsoft_qdk.py models the Microsoft QDK chemistry-course pipeline
(SCF -> active-space selection -> QPE/IQPE resource estimation) — a
phase-estimation workflow, not ADAPT-VQE. This adapter is the variational
counterpart: QDK's Quantum Chemistry Library and Azure Quantum both support
UCC-style variational algorithms too, not only QPE, so AlgorithmFamily.
ADAPT_VQE is a legitimate thing to run "via microsoft_qdk" — it just isn't
the same pipeline as the QPE one already modeled. Build the qubit
Hamiltonian with microsoft_qdk.py's QChemPipelineSpec (SCF through
fermionic-to-qubit mapping) and hand it to this adapter for the
ADAPT-VQE loop instead of continuing on to QPEConfig.

Separation contract
-------------------
qpubench core never imports from any quantum SDK. This file and
generic_adapt_vqe/ import from qpubench only — pure Python (+ scipy for
the classical optimizer), no vendor SDK required at all.
"""
from __future__ import annotations

import json
from typing import Any

from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import AdaptVQERunConfig, ExecutionOptions
from qpubench.schemas.observable import SparsePauliObservable
from qpubench.schemas.primitives import CircuitFormat, ComputingModel
from qpubench.schemas.record import VQAConfig, VQAResult
from qpubench.schemas.result import QuantumResult

from ..generic_adapt_vqe.engine import GenericAdaptVQEEngine


class MicrosoftQDKAdaptVQEAdapter:
    """ADAPT-VQE for QDK / Azure Quantum simulators and hardware.

    Problem spec contract (CircuitSpec, format=MOLECULE_JSON)
    -----------------------------------------------------------
    Identical to IBMQiskitAdaptVQEAdapter — serialized is a JSON object:
        {
          "num_qubits":    4,
          "num_electrons": 2,
          "hamiltonian":   <SparsePauliObservable.model_dump()>
        }
    Build the qubit Hamiltonian with microsoft_qdk.py's chemistry pipeline
    (or any other) before handing it in — this adapter is the ADAPT-VQE
    control flow only, not electronic-structure theory.

    Parameters
    ----------
    energy_backend:
        A qpubench BackendAdapter used for energy evaluation. Defaults are
        tuned for BackendSpec.qdk_chemistry_simulator() /
        BackendSpec.azure_quantum(...) but any BackendAdapter works.
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
            name=f"microsoft_qdk_adapt_vqe+{self._energy_backend.spec.name}",
            provider="microsoft_qdk_adapt_vqe",
            simulator=self._energy_backend.spec.simulator,
            computing_model=ComputingModel.GATE_BASED,
        )

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.format != CircuitFormat.MOLECULE_JSON:
            warnings.append(
                f"MicrosoftQDKAdaptVQEAdapter expects format=MOLECULE_JSON; "
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
        config      = options.adapt_vqe_run_config or AdaptVQERunConfig()

        engine = GenericAdaptVQEEngine(
            hamiltonian=hamiltonian,
            num_qubits=spec["num_qubits"],
            num_electrons=spec["num_electrons"],
            energy_backend=self._energy_backend,
            config=config,
            energy_options=self._energy_options,
        )
        return engine.run()
