"""Q-CTRL Fire Opal schemas.

Fire Opal is a closed-box error suppression service that applies
noise-robust compilation (pulse-level optimisation + DD) transparently
before submitting to IBM Quantum hardware (fire-opal package).
"""

from __future__ import annotations

import pydantic


class FireOpalConfig(pydantic.BaseModel):
    """Configuration for a Q-CTRL Fire Opal execution.

    Fire Opal is a closed-box error suppression service that applies
    noise-robust compilation (pulse-level optimisation + DD) transparently
    before submitting to IBM Quantum hardware.

    Python API:
      fo.execute(circuits, shot_count, credentials, backend_name)
      fo.iterate(circuits, parameter_values, ...)  # PQC / VQE loops

    circuit_format   "qasm3" (default) or "qiskit" (QuantumCircuit object).
    parameter_names  non-empty for PQC / iterative VQE runs via fo.iterate().
    """

    backend_name: str
    shot_count: int = 1024
    circuit_format: str = "qasm3"  # "qasm3" | "qiskit"
    parameter_names: list[str] = []
    fire_opal_version: str | None = None


class FireOpalResult(pydantic.BaseModel):
    """Result from a Q-CTRL Fire Opal execution.

    mitigated_counts   Noise-suppressed bitstring counts (Fire Opal output).
    raw_counts         Counts with Fire Opal suppression disabled (baseline).
    suppression_ratio  |mitigated − ideal| / |raw − ideal|; < 1 = improvement.
    """

    mitigated_counts: dict[str, int] = {}
    raw_counts: dict[str, int] = {}
    suppression_ratio: float | None = None
    job_id: str | None = None
    backend_name: str | None = None
