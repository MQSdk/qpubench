from __future__ import annotations

from typing import Any

import pydantic

from .primitives import ErrorMitigationStrategy


class ZNEConfig(pydantic.BaseModel):
    """Zero-noise extrapolation parameters.

    Mirrors VQEBench ZneOptions and IBM Qiskit Runtime resilience_level=2.
    extrapolator: "linear", "poly2", "richardson"
    """
    noise_factors: tuple[float, ...] = (1.0, 3.0, 5.0)
    extrapolator:  str               = "linear"


class TranspilerConfig(pydantic.BaseModel):
    """Gate-based transpiler options.

    Mirrors Qiskit C QkTranspileOptions {optimization_level, seed,
    approximation_degree} plus Qiskit Python routing/layout selectors.
    """
    layout_method:        str | None  = None    # "trivial", "dense", "sabre"
    routing_method:       str | None  = None    # "sabre", "lookahead", "stochastic"
    approximation_degree: float       = 1.0     # synthesis precision [0, 1]; Qiskit C
    basis_gates:          list[str]   = []      # override backend native gates
    initial_layout:       list[int]   = []      # manual virtual→physical mapping


class AlgorithmSpec(pydantic.BaseModel):
    """Specification for an algorithm-driven VQE run.

    Used by algorithm-library adapters (e.g. QForteAdapter, Cebule SDK) that
    generate their own circuits internally rather than accepting a pre-written
    circuit.

    QForte VQE variants:
      UCCNVQE    — disentangled UCC VQE (fixed operator pool)
      ADAPTVQE   — adaptive derivative-assembled pseudo-Trotterised VQE
      UCCNPQE    — UCC projective quantum eigensolver
      SPQE       — selected projective quantum eigensolver

    Cebule SDK task types (see CebuleTaskType):
      TN_QC_OPT  — tensor-network + quantum circuit hybrid VQE
      COVO       — correlation-optimised virtual orbital pre-processing
      MOL_MAP    — molecular Hamiltonian → qubit mapping
      QASM_GEN   — OpenQASM measurement circuit generation

    pool_type options: "SD", "GSD", "SDTQ", "sa_SD", "custom"
    optimizer options: "BFGS", "jacobi", "nelder-mead", "L-BFGS-B", "COBYLA"
    """
    name:               str               # "UCCNVQE", "ADAPTVQE", "TN_QC_OPT", ...
    pool_type:          str          = "SD"
    optimizer:          str          = "BFGS"
    use_analytic_grad:  bool         = True
    opt_thresh:         float        = 1.0e-5
    opt_ftol:           float        = 1.0e-5
    opt_maxiter:        int          = 200
    noise_factor:       float        = 0.0    # UCCNVQE: artificial noise
    avqe_thresh:        float        = 1.0e-2 # ADAPTVQE: gradient norm threshold
    adapt_maxiter:      int          = 20     # ADAPTVQE: macro-iteration limit
    compact_excitations: bool        = False
    qubit_excitations:  bool         = False
    diis_max_dim:       int          = 0      # 0 = disabled
    # ExcitationSolve fields (dlr-wf/ExcitationSolve)
    num_samples:        int          = 5      # energy probe points per parameter sweep (≥5)
    # Evolutionary / GA fields (Xenakis family)
    param_restarts:     int          = 1      # random restarts for local parameter search
    local_opt_steps:    int          = 0      # coordinate-descent steps per restart
    # TN_QC_OPT (Cebule) fields
    n_layers_network:   int | None   = None   # classical tensor network depth
    n_layers_circuit:   int | None   = None   # quantum circuit layer count
    three_para_tn:      bool         = True   # rotation parameterisation mode
    qasm_ansatz:        str | None   = None   # pre-defined parametric QASM ansatz
    theta_init:         list[float]  = []     # TN parameter initialisation
    phi_init:           list[float]  = []     # circuit parameter initialisation
    extra_params:       dict[str, Any] = {}   # algorithm-specific escape hatch


class ExecutionOptions(pydantic.BaseModel):
    """Execution parameters shared across all modalities.

    Gate-based fields
    -----------------
    shots              None = statevector (exact); int = shot-based sampling
    optimization_level transpiler tier 0–3 (Qiskit / Qrack convention)
    error_mitigation   post-execution mitigation strategy
    zne_config         required when error_mitigation = ZNE
    memory             return per-shot bitstrings alongside aggregate counts
    rep_delay_s        time between shots (thermal relaxation, hardware only)
    init_qubits        reset to |0⟩ before each shot (default True)
    transpiler         routing / layout / synthesis options

    Algorithm-driven fields (QForte and similar libraries)
    -------------------------------------------------------
    algorithm_spec     which algorithm to run and its hyperparameters

    MBQC fields
    -----------
    cluster_depth         number of measurement rounds (D)
    adaptive_corrections  whether byproduct corrections are applied
    """
    shots:                int | None              = None
    optimization_level:   int                     = 1
    error_mitigation:     ErrorMitigationStrategy = ErrorMitigationStrategy.NONE
    zne_config:           ZNEConfig | None        = None
    seed:                 int | None              = None
    timeout_s:            float | None            = None
    memory:               bool                    = False
    rep_delay_s:          float | None            = None
    init_qubits:          bool                    = True
    transpiler:           TranspilerConfig        = pydantic.Field(
        default_factory=TranspilerConfig
    )
    algorithm_spec:       AlgorithmSpec | None    = None
    cluster_depth:        int | None              = None
    adaptive_corrections: bool                    = True

    @pydantic.model_validator(mode="after")
    def _zne_default_config(self) -> ExecutionOptions:
        if (
            self.error_mitigation == ErrorMitigationStrategy.ZNE
            and self.zne_config is None
        ):
            self.zne_config = ZNEConfig()
        return self
