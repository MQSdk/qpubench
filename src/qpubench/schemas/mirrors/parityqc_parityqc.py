"""ParityQC schemas.

ParityOS (Parity Twine compiler) maps QUBO/HCBO optimisation problems to
parity-encoded circuits on a square lattice.
"""

from __future__ import annotations

import enum

import pydantic


class ParityQCProblemEncoding(str, enum.Enum):
    QUBO = "qubo"  # Quadratic Unconstrained Binary Optimisation
    HCBO = "hcbo"  # Higher-order Constrained Binary Optimisation
    ISING = "ising"  # Ising Hamiltonian (J/h form)


class ParityQCConfig(pydantic.BaseModel):
    """ParityQC parity encoding compilation configuration.

    ParityOS (Parity Twine compiler) maps QUBO/HCBO optimisation problems
    to parity-encoded circuits on a square lattice, reducing 2-qubit gate
    count and depth compared to standard compilation.

    lattice_rows × lattice_cols   parity lattice dimensions; product ≥ n_variables.
    parity_version                ParityOS version label, e.g. "v2.3".
    """

    problem_encoding: ParityQCProblemEncoding = ParityQCProblemEncoding.QUBO
    n_variables: int | None = None
    lattice_rows: int | None = None
    lattice_cols: int | None = None
    parity_version: str | None = None


class ParityQCResult(pydantic.BaseModel):
    """Result from a ParityQC parity-encoding compilation pass."""

    gate_count_native: int | None = None  # gates in parity-compiled output
    gate_count_direct: int | None = None  # gates without parity (baseline)
    depth_native: int | None = None
    depth_direct: int | None = None
    two_qubit_reduction_pct: float | None = None  # % reduction in 2Q gate count
