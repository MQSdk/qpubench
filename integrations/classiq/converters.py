"""Type conversion utilities: Classiq SDK <-> qpubench schemas.

Neither qpubench nor classiq import from each other.
This module is the only place that knows about both.
"""
from __future__ import annotations

import json
from typing import Any

from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.classiq import (
    ClassiqChemistryModel,
    ClassiqCombinatorialOptimizationSpec,
    ClassiqConstraints,
    ClassiqExecutionResult,
    ClassiqPreferences,
    ClassiqSynthesisResult,
)
from qpubench.schemas.primitives import CircuitFormat


# ---------------------------------------------------------------------------
# Problem-spec builders: qmod_source + build metadata -> CircuitSpec(QMOD)
#
# qmod_source is the serialized model text produced by the Classiq SDK's own
# `classiq.create_model(main)` — building `main` (the @qfunc-decorated
# functional model) is inherently application- and version-specific and is
# left to caller code, exactly as QForte's molecule build spec is left to
# caller code in integrations/qforte/converters.py.
# ---------------------------------------------------------------------------

def problem_spec_from_qmod(
    qmod_source: str,
    *,
    constraints: ClassiqConstraints | None = None,
    preferences: ClassiqPreferences | None = None,
    num_shots: int = 1000,
    kind: str = "generic",
    chemistry_model: ClassiqChemistryModel | None = None,
    combinatorial_spec: ClassiqCombinatorialOptimizationSpec | None = None,
) -> CircuitSpec:
    """Build a CircuitSpec(format=QMOD) wrapping a Classiq build request.

    kind + chemistry_model / combinatorial_spec are metadata only (used to
    populate VQAConfig after the run); the actual synthesis input is
    qmod_source.
    """
    payload: dict[str, Any] = {
        "qmod_source": qmod_source,
        "constraints": (constraints or ClassiqConstraints()).model_dump(),
        "preferences": (preferences or ClassiqPreferences()).model_dump(mode="json"),
        "num_shots": num_shots,
        "kind": kind,
    }
    if chemistry_model is not None:
        payload["chemistry_model"] = chemistry_model.model_dump()
    if combinatorial_spec is not None:
        payload["combinatorial_spec"] = combinatorial_spec.model_dump()
    return CircuitSpec(
        num_qubits=0,   # unknown until synthesize() reports width
        format=CircuitFormat.QMOD,
        serialized=json.dumps(payload),
    )


def problem_spec_from_chemistry_model(
    model: ClassiqChemistryModel,
    qmod_source: str,
    *,
    constraints: ClassiqConstraints | None = None,
    preferences: ClassiqPreferences | None = None,
    num_shots: int = 1000,
) -> CircuitSpec:
    return problem_spec_from_qmod(
        qmod_source,
        constraints=constraints,
        preferences=preferences,
        num_shots=num_shots,
        kind="chemistry",
        chemistry_model=model,
    )


def problem_spec_from_combinatorial_spec(
    spec: ClassiqCombinatorialOptimizationSpec,
    qmod_source: str,
    *,
    constraints: ClassiqConstraints | None = None,
    preferences: ClassiqPreferences | None = None,
    num_shots: int = 1000,
) -> CircuitSpec:
    return problem_spec_from_qmod(
        qmod_source,
        constraints=constraints,
        preferences=preferences,
        num_shots=num_shots,
        kind="combinatorial_optimization",
        combinatorial_spec=spec,
    )


# ---------------------------------------------------------------------------
# Classiq SDK objects -> qpubench schemas
#
# Attribute access is defensive (best-effort, several candidate paths tried
# in order) because QuantumProgram / ExecutionJob's attribute surface has
# changed across Classiq SDK releases. Run `dir(quantum_program)` /
# `dir(job_result)` on your installed version if a field always comes back
# None and adjust the candidate paths below.
# ---------------------------------------------------------------------------

def _first_attr(obj: Any, *paths: str) -> Any:
    for path in paths:
        cur = obj
        try:
            for attr in path.split("."):
                cur = getattr(cur, attr)
            if cur is not None:
                return cur
        except AttributeError:
            continue
    return None


def synthesis_result_from_quantum_program(quantum_program: Any) -> ClassiqSynthesisResult:
    """Best-effort extraction of a ClassiqSynthesisResult from a QuantumProgram."""
    gate_count = _first_attr(
        quantum_program, "transpiled_circuit.count_ops", "gate_count",
    )
    return ClassiqSynthesisResult(
        program_id=_first_attr(quantum_program, "id", "program_id"),
        qasm3=_first_attr(quantum_program, "qasm", "transpiled_circuit.qasm"),
        width=_first_attr(quantum_program, "data.width", "width"),
        depth=_first_attr(quantum_program, "transpiled_circuit.depth", "depth"),
        gate_count=dict(gate_count) if gate_count else {},
        cx_count=_first_attr(quantum_program, "transpiled_circuit.cx_count", "cx_count"),
    )


def execution_result_from_job(job_result: Any) -> ClassiqExecutionResult:
    """Best-effort extraction of a ClassiqExecutionResult from execute(...).result()."""
    counts = _first_attr(job_result, "value.counts", "counts")
    job_id = _first_attr(job_result, "job_id", "id")
    return ClassiqExecutionResult(
        job_id=job_id,
        counts=dict(counts) if counts else {},
    )
