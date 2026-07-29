"""Quantum Advantage Tracker schemas.

Cross-cutting experiment metadata for the Quantum Advantage Tracker
(https://github.com/quantum-advantage-tracker/quantum-advantage-tracker.github.io),
a community-governed registry co-initiated by IBM, Flatiron Institute,
BlueQubit and Algorithmiq.

Filed under ``catalogs/`` rather than ``mirrors/`` because there is no single
vendor SDK behind it: it is a registry several organisations publish into. The
module is named for what it catalogues, not by the ``<org>_<package>``
convention the mirrors use — that convention degenerates for a GitHub Pages
registry whose organisation and project share a name (it would read
``quantum_advantage_tracker_quantum_advantage_tracker``). See
docs/developer_guide.md.
"""

from __future__ import annotations

import enum

import pydantic


class AdvantageExperimentType(str, enum.Enum):
    OBSERVABLE_ESTIMATION = "observable_estimation"  # Loschmidt echo, Ising magnetization, OTOC
    VARIATIONAL = "variational"  # VQE, QAOA objective
    CLASSICALLY_VERIFIABLE = "classically_verifiable"  # peaked circuits, boson sampling variants


class ClassicalComparisonMethod(str, enum.Enum):
    TENSOR_NETWORK = "tensor_network"  # MPS, DMRG, iTEBD
    EXACT = "exact"  # full statevector simulation
    MONTE_CARLO = "monte_carlo"  # QMC, MCMC
    PERTURBATION = "perturbation"  # perturbative expansion
    CLASSICAL_EM = "classical_em"  # classical-only error mitigation baseline
    NONE = "none"  # no classical baseline available


class QuantumAdvantageRecord(pydantic.BaseModel):
    """Experiment metadata compatible with the Quantum Advantage Tracker.

    The Quantum Advantage Tracker (quantum-advantage-tracker.github.io) is a
    community-governed registry of experiments claiming or supporting quantum
    advantage, co-initiated by IBM, Flatiron Institute, BlueQubit, and
    Algorithmiq.

    Three experiment categories (AdvantageExperimentType):
      OBSERVABLE_ESTIMATION   — Loschmidt echo, Ising magnetization, OTOC
      VARIATIONAL             — VQE energy, QAOA approximation ratio
      CLASSICALLY_VERIFIABLE  — peaked circuits, boson sampling variants

    Fields mirror the tracker's GitHub issue submission template.

    coupling_params   problem-specific parameters, e.g. {"b": 1.0, "delta": 0.5}
                      for an Ising model with longitudinal field b and anisotropy δ.
    floquet_layers    number of Floquet / Trotter evolution layers.
    verified          True if the quantum advantage claim has been independently
                      verified by a third party.
    submission_url    GitHub issue URL or permalink on the tracker site.
    """

    experiment_type: AdvantageExperimentType
    circuit_name: str | None = None
    num_qubits: int | None = None
    backend_name: str | None = None
    floquet_layers: int | None = None
    circuit_depth: int | None = None
    observable_value: float | None = None
    observable_error_bound: float | None = None
    classical_method: ClassicalComparisonMethod = ClassicalComparisonMethod.NONE
    classical_time_s: float | None = None
    coupling_params: dict[str, float] = {}
    verified: bool = False
    submission_url: str | None = None
    publication_doi: str | None = None
    notes: str = ""
