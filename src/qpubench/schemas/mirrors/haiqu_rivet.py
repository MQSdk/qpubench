"""Haiqu Rivet schemas.

Rivet (haiqu-ai/rivet, Apache-2.0) is a hardware-agnostic transpilation
middleware that caches and pipelines decomposition, routing, and
scheduling passes.
"""

from __future__ import annotations

from typing import Any

import pydantic


class HaiquRivetConfig(pydantic.BaseModel):
    """Haiqu Rivet transpilation middleware configuration.

    Rivet (haiqu-ai/rivet, Apache-2.0) is a hardware-agnostic transpilation
    layer that caches and pipelines decomposition, routing, and scheduling
    passes.  Supported backends: "qiskit" | "bqskit" | "pytket".

    compression_level   proprietary state-compression level (0 = off, only the
                        open-source Rivet package; >0 requires proprietary SDK).
    pass_config         JSON-serialisable dict of transpiler pass arguments.
    """

    transpiler_backend: str = "qiskit"  # "qiskit" | "bqskit" | "pytket"
    optimization_level: int = 1
    caching: bool = True
    compression_level: int = 0  # 0 = disabled (open-source Rivet)
    pass_config: dict[str, Any] = {}
    rivet_version: str | None = None


class HaiquTranspilationResult(pydantic.BaseModel):
    """Circuit-quality metrics from a Haiqu Rivet transpilation pass."""

    gate_count_before: int | None = None
    gate_count_after: int | None = None
    depth_before: int | None = None
    depth_after: int | None = None
    two_qubit_gates_before: int | None = None
    two_qubit_gates_after: int | None = None
    cache_hit: bool = False
    transpile_time_s: float | None = None
