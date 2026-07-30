"""Template: AlgorithmAdapter for an algorithm library.

Use this when your library generates its own circuit from a problem spec
(molecule, Hamiltonian, graph) and manages the execution loop itself.

Libraries that fit this pattern
--------------------------------
  QForte        (UCCNVQE, ADAPT-VQE, UCCNPQE, SPQE)
  OpenFermion   (VQE variants, CISD)
  PySCF-based   (FCI, CCSD used as ground truth)
  QAOA solvers  (built-in graph problem + optimizer loop)

How it differs from BackendAdapter
------------------------------------
  BackendAdapter:   qpubench provides the circuit, library executes it.
  AlgorithmAdapter: library generates AND executes the circuit internally;
                    qpubench only records the result.

If you also want the library to use a qpubench backend for energy
evaluation (rather than its own internal simulator), see the
EnergyEvaluatorHook pattern in integrations/qforte/energy_hook.py.
"""
from __future__ import annotations

# qpubench imports — the ONLY coupling point to qpubench
from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.primitives import CircuitFormat, ComputingModel, JobStatus
from qpubench.schemas.record import VQAConfig, VQAResult
from qpubench.schemas.result import (
    ExpectationResult,
    QuantumResult,
)

# Your library import — the ONLY coupling point to the external library
# import my_algorithm_library as mylib   # TODO: uncomment and rename


class MyAlgorithmAdapter:
    """Replace 'MyAlgorithm' with your library's name throughout."""

    def __init__(
        self,
        # TODO: add constructor parameters your library needs
        # e.g. default_algorithm: str = "VQE"
    ) -> None:
        # TODO: initialise library-specific state here
        pass

    # ------------------------------------------------------------------
    # Protocol (these three methods are what BenchmarkRunner calls)
    # ------------------------------------------------------------------

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(
            name="my_algorithm_library",   # TODO
            provider="my_library",         # TODO
            simulator=True,
            computing_model=ComputingModel.GATE_BASED,
        )

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        """Return validation warnings for the problem specification.

        CircuitSpec.format should be MOLECULE_JSON for chemistry problems,
        or another format appropriate to your problem type.
        Call circuit.serialized to get the problem definition.
        """
        warnings: list[str] = []
        if circuit.format != CircuitFormat.MOLECULE_JSON:
            warnings.append(
                f"Expected MOLECULE_JSON problem spec, got {circuit.format.value!r}"
            )
        if not circuit.serialized:
            warnings.append("CircuitSpec.serialized is empty.")
        return warnings

    def run_algorithm(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[QuantumResult, VQAConfig, VQAResult]:
        """Run the algorithm and return (quantum result, VQA metadata).

        Steps:
          1. Parse circuit.serialized to get the problem definition.
          2. Read options.algorithm_spec for algorithm name + hyperparameters.
          3. Run the algorithm (this may take seconds to minutes).
          4. Extract results from the algorithm object.
          5. Return a QuantumResult, a VQAConfig (inputs) and a
             VQAResult (computed outputs).
        """
        # TODO: step 1 — parse problem spec
        # problem = load_problem(circuit.serialized)

        # TODO: step 2 — read algorithm config
        # AlgorithmSpec carries name + AlgorithmFamily; hyperparameters live
        # in a family-specific config (e.g. options.adapt_vqe_run_config for
        # AlgorithmFamily.ADAPT_VQE) or in AlgorithmSpec.extra_params.
        alg_spec = options.algorithm_spec
        # name       = alg_spec.name if alg_spec else "MY_DEFAULT_ALG"
        # optimizer  = options.adapt_vqe_run_config.optimizer if options.adapt_vqe_run_config else "BFGS"

        # TODO: step 3 — run algorithm
        # alg = mylib.MyAlgorithm(problem)
        # alg.run(optimizer=optimizer, ...)

        # TODO: step 4 — extract results
        # final_energy = alg.get_energy()
        # n_qubits     = alg.n_qubits
        final_energy = 0.0    # placeholder

        result = QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=[
                ExpectationResult(
                    observable_index=0,
                    value=final_energy,
                    std_error=0.0,
                )
            ],
            # TODO: populate adapt_history for ADAPT-type algorithms:
            # adapt_history=[
            #     AdaptIteration(
            #         iteration=i,
            #         energy=energies[i],
            #         grad_norm=grad_norms[i],
            #         n_operators=i + 1,
            #         n_cnot=cnot_counts[i],
            #         n_classical_params=i + 1,
            #     )
            #     for i in range(n_iters)
            # ],
            status=JobStatus.SUCCEEDED,
        )

        vqa = VQAConfig(
            problem_type="chemistry",      # TODO: or "optimization", "ml"
            # molecule=...,               # TODO: molecule name if applicable
            algorithm=alg_spec.name if alg_spec else None,
            optimizer=options.adapt_vqe_run_config.optimizer if options.adapt_vqe_run_config else None,
        )
        vqa_result = VQAResult(
            final_eigenvalue=final_energy,
            ground_truth=None,             # TODO: computed FCI reference if available
        )

        return result, vqa, vqa_result
