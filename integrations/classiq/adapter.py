"""Classiq algorithm adapter — implements qpubench's AlgorithmAdapter protocol.

Two-stage pipeline, both stages through the Classiq cloud SDK:
  1. synthesize   functional model (Qmod) + constraints/preferences -> circuit
  2. execute      circuit -> counts

Separation contract
--------------------
qpubench does not import classiq.
classiq is not imported anywhere outside this integrations/classiq/ directory.

Version note
-------------
The core synthesis primitives used here (create_model / set_constraints /
set_preferences / synthesize / execute, and the Constraints / Preferences
classes) have been Classiq's stable top-level entry points since early
releases. Their exact keyword-argument names can still drift between SDK
versions — ClassiqConstraints / ClassiqPreferences (classiq.py) are
documented as a provider-neutral simplification, not a guaranteed byte-exact
mirror. If `cq.Constraints(**...)` raises a TypeError on your installed
version, check the field names Classiq actually expects and adjust the
model_dump() call below.

Building the @qfunc functional model itself (the chemistry ansatz, the QAOA
mixer/cost layers, ...) is inherently application- and SDK-version-specific
and is left to caller code — see converters.problem_spec_from_qmod(). This
mirrors integrations/qforte/adapter.py, where building the QForte molecular
`System` is similarly left to caller-supplied build specs.
"""
from __future__ import annotations

import json
import time
from typing import Any

from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.classiq_classiq import ClassiqConstraints, ClassiqPreferences
from qpubench.schemas.primitives import CircuitFormat, ComputingModel, JobStatus
from qpubench.schemas.record import VQAConfig
from qpubench.schemas.result import QuantumResult

from .converters import execution_result_from_job, synthesis_result_from_quantum_program


def _require_classiq() -> Any:
    try:
        import classiq
        return classiq
    except ImportError as exc:
        raise ImportError(
            "classiq is not installed.\n"
            "  pip install classiq\n"
            "  classiq login   # device-code auth against the Classiq cloud\n"
            "  or: https://docs.classiq.io/latest/getting-started/installation/"
        ) from exc


class ClassiqAlgorithmAdapter:
    """Implements qpubench's AlgorithmAdapter protocol for Classiq.

    Consumes a CircuitSpec(format=QMOD) built by
    converters.problem_spec_from_qmod() / problem_spec_from_chemistry_model()
    / problem_spec_from_combinatorial_spec(), synthesizes a circuit under the
    embedded ClassiqConstraints/ClassiqPreferences, executes it through
    Classiq's own execute(), and returns (QuantumResult, VQAConfig).

    Usage
    -----
        from qpubench import BenchmarkRunner, NDJSONStore, ExecutionOptions
        from classiq_adapter.adapter import ClassiqAlgorithmAdapter
        from classiq_adapter.converters import problem_spec_from_qmod

        runner = BenchmarkRunner(store=NDJSONStore("results.ndjson"))
        runner.register(ClassiqAlgorithmAdapter(), name="classiq")

        spec = problem_spec_from_qmod(my_qmod_source)
        record = runner.run(spec, "classiq", ExecutionOptions())
    """

    def __init__(self, default_num_shots: int = 1000) -> None:
        self._default_num_shots = default_num_shots

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(
            name="classiq_simulator",
            provider="classiq",
            simulator=True,
            computing_model=ComputingModel.GATE_BASED,
        )

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.format != CircuitFormat.QMOD:
            warnings.append(
                f"ClassiqAlgorithmAdapter expects format=QMOD; got {circuit.format.value!r}"
            )
        if not circuit.serialized:
            warnings.append("CircuitSpec.serialized is empty.")
        else:
            try:
                payload = json.loads(circuit.serialized)
            except json.JSONDecodeError:
                warnings.append("CircuitSpec.serialized is not valid JSON.")
            else:
                if not payload.get("qmod_source"):
                    warnings.append("Problem spec is missing 'qmod_source'.")
        return warnings

    def run_algorithm(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[QuantumResult, VQAConfig]:
        cq = _require_classiq()
        payload = json.loads(circuit.serialized or "{}")

        qmod_source  = payload["qmod_source"]
        constraints  = ClassiqConstraints.model_validate(payload.get("constraints", {}))
        preferences  = ClassiqPreferences.model_validate(payload.get("preferences", {}))
        num_shots    = options.shots or payload.get("num_shots") or self._default_num_shots
        kind         = payload.get("kind", "generic")

        t0 = time.monotonic()
        model = cq.set_constraints(
            qmod_source, cq.Constraints(**constraints.model_dump(exclude_none=True)),
        )
        model = cq.set_preferences(
            model, cq.Preferences(**preferences.model_dump(exclude_none=True)),
        )
        quantum_program = cq.synthesize(model)
        synthesis_duration_s = time.monotonic() - t0

        synthesis = synthesis_result_from_quantum_program(quantum_program)
        synthesis.synthesis_duration_s = synthesis_duration_s

        job = cq.execute(quantum_program)
        job_result = job.result()
        exec_result = execution_result_from_job(job_result)

        result = QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            transpiled_circuit=synthesis.qasm3,
            transpiled_circuit_format=CircuitFormat.QASM3 if synthesis.qasm3 else None,
            status=JobStatus.SUCCEEDED,
            job_id=exec_result.job_id,
            metadata={
                "classiq_synthesis_id": synthesis.program_id,
                "classiq_width": synthesis.width,
                "classiq_depth": synthesis.depth,
                "counts": exec_result.counts,
                "num_shots": num_shots,
            },
        )

        vqa = VQAConfig(
            problem_type="chemistry" if kind == "chemistry" else "optimization",
            algorithm=f"classiq_{kind}",
            classiq_synthesis_id=synthesis.program_id,
            n_cnot=synthesis.cx_count,
        )
        return result, vqa
