from __future__ import annotations

from typing import Any

import pydantic

from .primitives import AlgorithmFamily, ErrorMitigationStrategy


class ZNEConfig(pydantic.BaseModel):
    """Zero-noise extrapolation parameters.

    Mirrors IBM Qiskit Runtime resilience_level=2 ZNE options.
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
    """Identifies which algorithm-driven run this is.

    Used by AlgorithmAdapter implementations (QForte, Cebule SDK, Xenakis,
    ExcitationSolve, ...) that generate their own circuits internally rather
    than accepting a pre-written circuit.

    name    library-specific algorithm label, e.g. "ADAPTVQE", "UCCNVQE",
            "TN_QC_OPT" — interpreted by whichever adapter is registered.
    family  package-agnostic identity (AlgorithmFamily). Set this to compare
            runs of "the same algorithm" across different implementing
            adapters — e.g. family=ADAPT_VQE lets a caller switch between
            the evangelistalab_qforte, ibm_qiskit_adapt_vqe, and
            microsoft_qdk_adapt_vqe adapters using the same AdaptVQERunConfig.
    extra_params  escape hatch for adapter-specific kwargs not covered by a
                  typed config.

    Hyperparameters live in each algorithm's own schema module, not here:
      ADAPT_VQE (generic)    → AdaptVQERunConfig (this module)
      QForte-specific extras → evangelistalab_qforte.QForteAlgorithmConfig
      ExcitationSolve        → dlr_excitation_solve.ExcitationSolveConfig
      Xenakis GA search      → mqsdk_xenakis.GAConfig / GenomeConfig
      Cebule TN_QC_OPT       → mqsdk_cebule.TNQCOptInput
      QDK QPE/IQPE           → microsoft_qdk.QPEConfig
    """
    name:          str
    family:        AlgorithmFamily | None = None
    extra_params:  dict[str, Any]         = {}


class AdaptVQERunConfig(pydantic.BaseModel):
    """Package-agnostic ADAPT-VQE hyperparameters (AlgorithmFamily.ADAPT_VQE).

    The common contract every ADAPT-VQE implementation accepts, regardless
    of which package runs it. Each adapter translates these into its own
    call — e.g. QForteAlgorithmConfig wraps this plus QForte-only extras
    (diis_max_dim, use_cumulative_thresh, add_equiv_ops).

    pool_type              operator pool: "SD" | "GSD" | "SDTQ" | "sa_SD"
    optimizer              classical optimizer name; each adapter maps this
                            onto its own supported set (e.g. scipy method name)
    gradient_threshold      macro-iteration stop: ‖gradient‖ below this ends
                            ansatz growth (QForte: avqe_thresh)
    energy_threshold        micro-optimizer (parameter fit) convergence
                            threshold (QForte: opt_thresh)
    max_macro_iterations    operator-pool growth steps / ansatz depth cap
                            (QForte: adapt_maxiter)
    max_micro_iterations    optimizer steps per macro-iteration
                            (QForte: opt_maxiter)
    use_analytic_gradient   analytic gradient (parameter-shift / commutator)
                            vs finite-difference
    """
    pool_type:             str   = "SD"
    optimizer:             str   = "BFGS"
    gradient_threshold:    float = 1.0e-2
    energy_threshold:      float = 1.0e-5
    max_macro_iterations:  int   = 20
    max_micro_iterations:  int   = 200
    use_analytic_gradient: bool  = True


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
    algorithm_spec     which algorithm to run (name + AlgorithmFamily)
    adapt_vqe_run_config   shared hyperparameter contract for
                       AlgorithmFamily.ADAPT_VQE, package-agnostic

    MBQC fields
    -----------
    cluster_depth         number of measurement rounds (D)
    adaptive_corrections  whether byproduct corrections are applied

    Vendor mitigation options
    -------------------------
    mitigation_options    vendor-neutral dict for strategy-specific options,
                          keyed by vendor/strategy.  Pydantic models passed
                          as values are dumped automatically.  Example
                          (QESEM — see qedma_qesem.qesem_mitigation_options):

                              options = ExecutionOptions(
                                  error_mitigation=ErrorMitigationStrategy.QESEM,
                                  mitigation_options=qesem_mitigation_options(
                                      circuit_options=QESEMCircuitOptions(...),
                                      job_options=QESEMJobOptions(...),
                                  ),
                              )
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
    adapt_vqe_run_config:     AdaptVQERunConfig | None   = None
    cluster_depth:        int | None              = None
    adaptive_corrections: bool                    = True
    mitigation_options:   dict[str, Any]          = {}

    @pydantic.field_validator("mitigation_options", mode="before")
    @classmethod
    def _dump_vendor_models(cls, v: Any) -> Any:
        # Accept vendor Pydantic models as values; store dict dumps so the
        # core schema stays vendor-neutral and JSON-serialisable.
        if isinstance(v, dict):
            return {
                k: val.model_dump() if isinstance(val, pydantic.BaseModel) else val
                for k, val in v.items()
            }
        return v

    @pydantic.model_validator(mode="after")
    def _zne_default_config(self) -> ExecutionOptions:
        if (
            self.error_mitigation == ErrorMitigationStrategy.ZNE
            and self.zne_config is None
        ):
            self.zne_config = ZNEConfig()
        return self
