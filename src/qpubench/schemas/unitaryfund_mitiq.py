"""Mitiq schemas.

Mitiq (Unitary Fund) is an open-source error mitigation library:
ZNE, PEC, CDR, REM, DDD.
"""

from __future__ import annotations

import enum

import pydantic


class MitiqTechnique(str, enum.Enum):
    ZNE = "zne"  # zero-noise extrapolation
    PEC = "pec"  # probabilistic error cancellation
    CDR = "cdr"  # Clifford data regression
    REM = "rem"  # readout error mitigation
    DDD = "ddd"  # dynamical decoupling (Mitiq variant)


class MitiqNoiseScalingMethod(str, enum.Enum):
    FOLD_GLOBAL = "fold_global"  # whole-circuit gate folding; simplest
    FOLD_GATES_RANDOM = "fold_gates_at_random"  # random gate-level folding
    FOLD_GATES_FROM_LEFT = "fold_gates_from_left"
    FOLD_GATES_FROM_RIGHT = "fold_gates_from_right"
    PULSE_STRETCH = "pulse_stretch"  # pulse-level noise scaling


class MitiqZNEFactory(str, enum.Enum):
    LINEAR = "linear"  # linear extrapolation; fast but biased for large noise
    RICHARDSON = "richardson"  # Richardson extrapolation; order = len(scale_factors) - 1
    POLY2 = "poly2"  # degree-2 polynomial
    EXP = "exponential"  # exponential decay model


class MitiqDDDRule(str, enum.Enum):
    XX = "xx"  # X–X pair
    XYXY = "xyxy"  # alternating X–Y–X–Y; suppresses depolarising + dephasing
    YY = "yy"  # Y–Y pair


class MitiqZNEConfig(pydantic.BaseModel):
    """Zero-noise extrapolation configuration (Mitiq).

    scale_factors    noise amplification factors applied to the circuit,
                     e.g. [1.0, 3.0, 5.0]; must all be ≥ 1.0.
    scaling_method   how noise is amplified at the gate or pulse level.
    factory          extrapolation model fit to the noise-scaled values.
    num_to_average   circuit instances averaged per scale factor.
    """

    scale_factors: list[float] = [1.0, 3.0, 5.0]
    scaling_method: MitiqNoiseScalingMethod = MitiqNoiseScalingMethod.FOLD_GLOBAL
    factory: MitiqZNEFactory = MitiqZNEFactory.RICHARDSON
    num_to_average: int = 1


class MitiqPECConfig(pydantic.BaseModel):
    """Probabilistic error cancellation configuration (Mitiq).

    num_samples    Monte Carlo samples drawn from the quasi-probability distribution.
    precision      target precision (σ); overrides num_samples if set.
    representation_labels   descriptive labels for the quasi-prob decomposition
                            of each noisy gate, e.g. "cx(0,1)".
    """

    num_samples: int = 200
    precision: float | None = None
    representation_labels: list[str] = []


class MitiqCDRConfig(pydantic.BaseModel):
    """Clifford data regression configuration (Mitiq).

    Near-Clifford training circuits are used to learn a noise model, then
    the learned correction is applied to the target (non-Clifford) circuit.

    fraction_non_clifford   fraction of non-Clifford gates left in training circuits
                            to capture near-Clifford noise behaviour.
    fit_function            regression model: "linear" | "poly2" | "nn".
    """

    num_training_circuits: int = 10
    fraction_non_clifford: float = 0.1
    fit_function: str = "linear"  # "linear" | "poly2" | "nn"


class MitiqREMConfig(pydantic.BaseModel):
    """Readout error mitigation configuration (Mitiq).

    inverse_confusion_matrix   calibrated inverse M^{-1} of the readout confusion
                               matrix M[i,j] = P(measure i | prepare j).
                               Stored as a flat row-major list of length 4^num_qubits.
    """

    num_qubits: int
    inverse_confusion_matrix: list[float] = []  # flat row-major; len = 4^num_qubits


class MitiqDDDConfig(pydantic.BaseModel):
    """Mitiq dynamical decoupling (DDD) configuration.

    rule     DD pulse sequence inserted in idle windows.
    spacing  number of identity gates between each DD gate pair; 0 = tight.
    """

    rule: MitiqDDDRule = MitiqDDDRule.XYXY
    spacing: int = 0


class MitiqConfig(pydantic.BaseModel):
    """Top-level Mitiq mitigation configuration (one technique per run).

    Populate only the config sub-model corresponding to technique.
    executor_backend   label for the underlying execution backend, e.g. "aer".
    """

    technique: MitiqTechnique
    mitiq_version: str | None = None
    executor_backend: str | None = None
    zne: MitiqZNEConfig | None = None
    pec: MitiqPECConfig | None = None
    cdr: MitiqCDRConfig | None = None
    rem: MitiqREMConfig | None = None
    ddd: MitiqDDDConfig | None = None


class MitiqResult(pydantic.BaseModel):
    """Result from a Mitiq error-mitigated execution.

    scale_values   ZNE: raw expectation values per noise scale factor
                   (pre-extrapolation); empty for non-ZNE techniques.
    """

    technique: MitiqTechnique
    mitigated_value: float
    unmitigated_value: float | None = None
    std_error: float | None = None
    num_shots_total: int | None = None
    scale_values: list[float] = []
