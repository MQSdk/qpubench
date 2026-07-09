"""QMatter schemas.

QMatter compresses quantum simulation problems (chemistry, materials) to
their 'essential core', reducing qubit and gate requirements for
life-sciences / drug-discovery workloads.
"""

from __future__ import annotations

import pydantic


class QMatterConfig(pydantic.BaseModel):
    """QMatter quantum problem compression configuration.

    QMatter compresses quantum simulation problems (chemistry, materials)
    to their 'essential core', reducing qubit and gate requirements for
    life-sciences / drug-discovery workloads.

    target_domain   "chemistry" | "materials" | "drug_discovery" | "finance"
    """

    compression_method: str = "active_space"  # "active_space" | "qmatter_compress"
    target_domain: str = "chemistry"
    qmatter_version: str | None = None


class QMatterCompressionResult(pydantic.BaseModel):
    """Result from a QMatter problem compression run."""

    qubits_before: int | None = None
    qubits_after: int | None = None
    gates_before: int | None = None
    gates_after: int | None = None
    compression_ratio: float | None = None  # qubits_after / qubits_before
