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
      VQE (generic)          → VQERunConfig (this module)
      ADAPT_VQE (generic)    → AdaptVQERunConfig (this module)
      QAOA (generic)         → QAOARunConfig (this module)
      QForte-specific extras → evangelistalab_qforte.QForteAlgorithmConfig
      ExcitationSolve        → dlr_excitation_solve.ExcitationSolveConfig
      Xenakis GA search      → mqsdk_xenakis.GAConfig / GenomeConfig
      Cebule TN_QC_OPT       → mqsdk_cebule.TNQCOptInput
      QDK QPE/IQPE           → microsoft_qdk.QPEConfig
    """
    name:          str
    family:        AlgorithmFamily | None = None
    extra_params:  dict[str, Any]         = {}


class VQERunConfig(pydantic.BaseModel):
    """Package-agnostic fixed-ansatz VQE hyperparameters (AlgorithmFamily.VQE).

    The common contract every fixed-ansatz VQE implementation accepts,
    regardless of which package runs it.  Unlike ADAPT-VQE the ansatz
    structure is chosen up front and never grows during the run — there is
    no operator pool and no gradient-driven macro loop — so this config only
    names the ansatz, its depth, the classical optimizer, and how the
    starting parameters are produced.  Set on ExecutionOptions.vqe_run_config.

    A UCC-type ansatz (QForte's UCCNVQE) and a Fourier-series parameter fit
    (dlr_excitation_solve) are both choices *under* this family, recorded in
    `ansatz` / `optimizer` — they are not families of their own.

    ansatz                circuit family to build: "UCCSD" | "EfficientSU2" |
                           "TwoLocal" | "HEA" | ... ; each adapter maps this
                           onto its own constructor
    layers                ansatz repetition depth (Qiskit's `reps`); 1 for
                           ansätze with no repeating block
    optimizer             classical optimizer name; each adapter maps this
                           onto its own supported set (e.g. scipy method name)
    max_iterations        classical-optimizer step cap
    energy_threshold      optimizer convergence threshold on the energy
    initialization        starting-parameter strategy: "zeros" | "random" |
                           "hf" (Hartree-Fock reference) | "custom" (use
                           initial_parameters)
    initial_parameters    explicit starting vector; read when
                           initialization="custom"
    init_scale            std-dev of the random draw when
                           initialization="random"; seeded by
                           ExecutionOptions.seed, which is why this config
                           carries no seed of its own
    use_analytic_gradient analytic gradient (parameter-shift) vs
                           finite-difference

    Distinct from bestquark_gsopt.GSOptVQERunConfig, which is not a contract
    at all: that one records how one run of GSOpt's own VQE benchmark lane
    was parameterised.
    """
    ansatz:                str         = "UCCSD"
    layers:                int         = 1
    optimizer:             str         = "BFGS"
    max_iterations:        int         = 200
    energy_threshold:      float       = 1.0e-5
    initialization:        str         = "zeros"
    initial_parameters:    list[float] = []
    init_scale:            float       = 1.0e-2
    use_analytic_gradient: bool        = True


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


class QAOARunConfig(pydantic.BaseModel):
    """Package-agnostic QAOA hyperparameters (AlgorithmFamily.QAOA).

    The Quantum Approximate Optimization Algorithm prepares a fixed-structure
    ansatz built from p alternating layers of a problem (cost) unitary and a
    mixer unitary, then optimizes the 2·p angles (γ, β) classically to minimize
    ⟨cost⟩.  Unlike ADAPT-VQE the ansatz structure is fixed up front — only p,
    the mixer, and the optimizer choose it — so this config is the common
    contract every QAOA implementation accepts, regardless of which package
    (or hand-rolled loop) runs it.  Set on ExecutionOptions.qaoa_run_config.

    reps                 p — number of cost+mixer layers; ansatz has 2·p angles
    mixer                mixer Hamiltonian: "x" (transverse field, standard) |
                          "xy" (ring/parity-preserving) | "grover"
    optimizer            classical optimizer name; each adapter/loop maps this
                          onto its own supported set (e.g. scipy method name).
                          COBYLA is the usual default for shot-based QAOA.
    max_iterations       classical-optimizer step cap
    initialization       starting-angle strategy: "zeros" | "random" |
                          "ramp" (linear γ ramp-up / β ramp-down, TQA-style)
    alpha_cvar           CVaR tail fraction for the cost objective; 1.0 = plain
                          expectation value, <1.0 optimizes the best-α quantile
                          of sampled bitstrings (matches
                          classiq_classiq.ClassiqCombinatorialOptimizationSpec)
    """
    reps:            int   = 1
    mixer:           str   = "x"
    optimizer:       str   = "COBYLA"
    max_iterations:  int   = 100
    initialization:  str   = "ramp"
    alpha_cvar:      float = 1.0


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
    vqe_run_config     shared hyperparameter contract for
                       AlgorithmFamily.VQE (fixed ansatz), package-agnostic
    adapt_vqe_run_config   shared hyperparameter contract for
                       AlgorithmFamily.ADAPT_VQE, package-agnostic
    qaoa_run_config    shared hyperparameter contract for
                       AlgorithmFamily.QAOA, package-agnostic

    Set the one matching algorithm_spec.family; they are independent fields,
    not alternatives to each other, so nothing stops a caller populating
    several — only the one its family names is read.

    MBQC fields
    -----------
    cluster_depth         number of measurement rounds (D)
    adaptive_corrections  whether byproduct corrections are applied

    Distributed execution
    ---------------------
    distributed_run_config  how to spread one circuit over several QPUs —
                          partitioning across a quantum network, or gate /
                          wire cutting.  Stored as a dict so the core stays
                          free of the cross-cutting schema import; pass a
                          model and it is dumped automatically:

                              from qpubench.schemas.distributed_execution import (
                                  DistributedRunConfig,
                              )
                              options = ExecutionOptions(
                                  distributed_run_config=DistributedRunConfig(...),
                              )
                              cfg = DistributedRunConfig.model_validate(
                                  options.distributed_run_config
                              )

                          These are the *inputs* (budgets, strategy, seed).
                          The choices the tool made — which gates were cut,
                          which qubit went to which QPU — are outputs and
                          belong on CircuitSpec.distribution.

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
    vqe_run_config:       VQERunConfig | None     = None
    adapt_vqe_run_config:     AdaptVQERunConfig | None   = None
    qaoa_run_config:      QAOARunConfig | None    = None
    cluster_depth:        int | None              = None
    adaptive_corrections: bool                    = True
    mitigation_options:   dict[str, Any]          = {}
    distributed_run_config: dict[str, Any] | None = None

    def require_shots(self, backend_name: str) -> int:
        """Return ``shots``, raising if the caller never chose a value.

        ``shots=None`` means "statevector, exact" — a deliberate choice, not a
        blank to be filled in. Adapters on a sampling-only execution path
        therefore call this instead of substituting a house default: an
        implicit ``shots or 1024`` would silently turn a request for exact
        results into 1024 sampled ones, and would make two benchmarks that
        never named a shot count look comparable when they are not.
        """
        if self.shots is None:
            raise ValueError(
                f"{backend_name} needs an explicit shot count on this path: set "
                "ExecutionOptions(shots=...) (or pass shots= to runner.run). "
                "shots=None means exact statevector, which this path cannot "
                "provide."
            )
        if self.shots <= 0:
            raise ValueError(f"shots must be positive; got {self.shots}")
        return self.shots

    @pydantic.field_validator("distributed_run_config", mode="before")
    @classmethod
    def _dump_distributed_run_config(cls, v: Any) -> Any:
        # Accept distributed_execution.DistributedRunConfig directly; store its
        # dict dump so the core keeps zero cross-module schema imports.
        return v.model_dump() if isinstance(v, pydantic.BaseModel) else v

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
