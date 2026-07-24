"""ADAPT-VQE runners — two variants:

AdaptVQERunner
    Uses QForteAlgorithmAdapter (QForte's own internal C++ statevector).
    Post-hoc iteration callbacks from stored history.

ExternalEvalAdaptVQERunner
    Uses ExternalEvalAlgorithmAdapter, which overrides energy_feval() so
    every energy evaluation is forwarded to a registered qpubench backend.
    Enables ADAPT-VQE on Aer, Qrack GPU, IBM hardware, or any BackendAdapter.
"""
from __future__ import annotations

from collections.abc import Callable

from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import AdaptVQERunConfig, AlgorithmSpec, ExecutionOptions
from qpubench.schemas.primitives import AlgorithmFamily
from qpubench.schemas.record import BenchmarkRecord
from qpubench.schemas.result import AdaptIteration
from qpubench import BenchmarkRunner



# ---------------------------------------------------------------------------
# Callback type aliases
# ---------------------------------------------------------------------------

IterationCallback = Callable[[AdaptIteration], None]
RecordCallback    = Callable[[BenchmarkRecord], None]


# ---------------------------------------------------------------------------
# AdaptVQERunner
# ---------------------------------------------------------------------------

class AdaptVQERunner:
    """Convenience wrapper for running and comparing ADAPT-VQE variants.

    Parameters
    ----------
    runner:
        A BenchmarkRunner with a QForteAlgorithmAdapter registered.
    backend_name:
        The name the adapter was registered under (default "qforte").
    on_iteration:
        Called for each historical ADAPT macro-iteration after the run.
        Signature: (AdaptIteration) -> None
    on_record:
        Called with the completed BenchmarkRecord after each run.
        Signature: (BenchmarkRecord) -> None
    """

    def __init__(
        self,
        runner: BenchmarkRunner,
        backend_name: str                 = "qforte",
        on_iteration: IterationCallback | None = None,
        on_record:    RecordCallback | None    = None,
    ) -> None:
        self._runner       = runner
        self._backend_name = backend_name
        self._on_iteration = on_iteration
        self._on_record    = on_record

    # ------------------------------------------------------------------
    # Single run
    # ------------------------------------------------------------------

    def run(
        self,
        molecule: CircuitSpec,
        alg_spec: AlgorithmSpec,
        adapt_vqe_run_config: AdaptVQERunConfig | None = None,
        *,
        tags:   list[str] | None = None,
        run_id: str | None       = None,
        notes:  str              = "",
    ) -> BenchmarkRecord:
        """Run one ADAPT-VQE configuration and return the BenchmarkRecord."""
        record = self._runner.run(
            molecule,
            self._backend_name,
            ExecutionOptions(algorithm_spec=alg_spec, adapt_vqe_run_config=adapt_vqe_run_config),
            tags=tags or ["adapt-vqe"],
            run_id=run_id,
            notes=notes,
        )

        if self._on_iteration and record.result.adapt_history:
            for it in record.result.adapt_history:
                self._on_iteration(it)

        if self._on_record:
            self._on_record(record)

        return record

    # ------------------------------------------------------------------
    # Comparison sweeps
    # ------------------------------------------------------------------

    def compare_optimizers(
        self,
        molecule: CircuitSpec,
        pool_type: str          = "SD",
        optimizers: list[str]   | None = None,
        *,
        gradient_threshold: float = 1.0e-4,
        energy_threshold:   float = 1.0e-5,
        max_macro_iterations: int = 20,
        run_id: str | None  = None,
        tags:   list[str] | None = None,
    ) -> list[BenchmarkRecord]:
        """Run ADAPT-VQE with several optimizers on the same molecule.

        Returns one record per optimizer, ordered as given.
        """
        _optimizers = optimizers or ["BFGS", "jacobi"]
        alg_spec = AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE)
        configs = [
            AdaptVQERunConfig(
                pool_type=pool_type,
                optimizer=opt,
                gradient_threshold=gradient_threshold,
                energy_threshold=energy_threshold,
                max_macro_iterations=max_macro_iterations,
            )
            for opt in _optimizers
        ]
        return [
            self.run(
                molecule, alg_spec, cfg,
                run_id=run_id or f"compare_optimizers_{pool_type}",
                tags=tags or ["adapt-vqe", "optimizer-comparison"],
            )
            for cfg in configs
        ]

    def compare_pool_types(
        self,
        molecule:   CircuitSpec,
        pool_types: list[str]   | None = None,
        optimizer:  str                = "BFGS",
        *,
        gradient_threshold:   float = 1.0e-4,
        energy_threshold:     float = 1.0e-5,
        max_macro_iterations: int   = 20,
        run_id: str | None   = None,
        tags:   list[str] | None = None,
    ) -> list[BenchmarkRecord]:
        """Run ADAPT-VQE with several operator pool types on the same molecule."""
        _pool_types = pool_types or ["SD", "GSD"]
        alg_spec = AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE)
        configs = [
            AdaptVQERunConfig(
                pool_type=pt,
                optimizer=optimizer,
                gradient_threshold=gradient_threshold,
                energy_threshold=energy_threshold,
                max_macro_iterations=max_macro_iterations,
            )
            for pt in _pool_types
        ]
        return [
            self.run(
                molecule, alg_spec, cfg,
                run_id=run_id or f"compare_pools_{optimizer}",
                tags=tags or ["adapt-vqe", "pool-comparison"],
            )
            for cfg in configs
        ]

    def compare_algorithms(
        self,
        molecule:   CircuitSpec,
        alg_names:  list[str]  | None = None,
        pool_type:  str               = "SD",
        optimizer:  str               = "BFGS",
        *,
        run_id: str | None  = None,
        tags:   list[str] | None = None,
    ) -> list[BenchmarkRecord]:
        """Compare ADAPT-VQE against UCCNVQE (and optionally UCCNPQE/SPQE)."""
        _names = alg_names or ["UCCNVQE", "ADAPTVQE"]
        cfg = AdaptVQERunConfig(pool_type=pool_type, optimizer=optimizer)
        alg_specs = [
            AlgorithmSpec(
                name=name,
                family=AlgorithmFamily.ADAPT_VQE if name == "ADAPTVQE" else AlgorithmFamily.UCC_VQE,
            )
            for name in _names
        ]
        return [
            self.run(
                molecule, spec, cfg,
                run_id=run_id or f"compare_algorithms_{pool_type}",
                tags=tags or ["vqe", "algorithm-comparison"],
            )
            for spec in alg_specs
        ]

    # ------------------------------------------------------------------
    # Analysis helpers
    # ------------------------------------------------------------------

    @staticmethod
    def convergence_table(records: list[BenchmarkRecord]) -> list[dict]:
        """Extract a flat list of dicts suitable for pandas DataFrame construction.

        Each row is one (record × ADAPT-iteration).  For non-ADAPT algorithms
        each VQE optimizer iteration is returned from convergence_values.
        """
        rows: list[dict] = []
        for rec in records:
            alg  = rec.vqa.algorithm if rec.vqa else "?"
            opt  = rec.options.adapt_vqe_run_config.optimizer if rec.options.adapt_vqe_run_config else "?"
            pool = rec.options.adapt_vqe_run_config.pool_type if rec.options.adapt_vqe_run_config else "?"

            if rec.result.adapt_history:
                for it in rec.result.adapt_history:
                    rows.append({
                        "experiment_id": rec.experiment_id,
                        "run_id":        rec.run_id,
                        "algorithm":     alg,
                        "optimizer":     opt,
                        "pool_type":     pool,
                        "iteration":     it.iteration,
                        "energy":        it.energy,
                        "grad_norm":     it.grad_norm,
                        "n_operators":   it.n_operators,
                        "n_cnot":        it.n_cnot,
                        "n_params":      it.n_classical_params,
                    })
            else:
                for i, e in enumerate(rec.vqa_result.convergence_values if rec.vqa_result else []):
                    rows.append({
                        "experiment_id": rec.experiment_id,
                        "run_id":        rec.run_id,
                        "algorithm":     alg,
                        "optimizer":     opt,
                        "pool_type":     pool,
                        "iteration":     i,
                        "energy":        e,
                        "grad_norm":     None,
                        "n_operators":   None,
                        "n_cnot":        rec.vqa_result.n_cnot if rec.vqa_result else None,
                        "n_params":      rec.vqa_result.num_parameters if rec.vqa_result else None,
                    })
        return rows

    @staticmethod
    def summary_table(records: list[BenchmarkRecord]) -> list[dict]:
        """One row per record: final energy, error, chemical accuracy, and circuit metrics."""
        rows = []
        for rec in records:
            ev  = rec.result.expectation_values
            rows.append({
                "experiment_id":  rec.experiment_id,
                "algorithm":      rec.vqa.algorithm if rec.vqa else "?",
                "optimizer":      (rec.options.adapt_vqe_run_config.optimizer
                                   if rec.options.adapt_vqe_run_config else "?"),
                "pool_type":      (rec.options.adapt_vqe_run_config.pool_type
                                   if rec.options.adapt_vqe_run_config else "?"),
                "final_energy":   ev[0].value if ev else None,
                "energy_error":   rec.vqa_result.energy_error if rec.vqa_result else None,
                "chem_accuracy":  rec.vqa_result.chemical_accuracy if rec.vqa_result else None,
                "n_cnot":         rec.vqa_result.n_cnot if rec.vqa_result else None,
                "n_params":       rec.vqa_result.num_parameters if rec.vqa_result else None,
                "n_pauli_meas":   rec.vqa_result.n_pauli_trm_measures if rec.vqa_result else None,
                "adapt_iters":    len(rec.result.adapt_history) if rec.result.adapt_history else None,
                "total_time_s":   rec.result.total_time_s,
                "status":         rec.result.status.value,
            })
        return rows


# ---------------------------------------------------------------------------
# ExternalEvalAdaptVQERunner
# ---------------------------------------------------------------------------

class ExternalEvalAdaptVQERunner:
    """Run ADAPT-VQE (or any QForte algorithm) with a qpubench backend as the
    energy oracle.

    Wraps ExternalEvalAlgorithmAdapter, which subclasses QForte's algorithm
    class and overrides energy_feval() so every energy evaluation is
    forwarded to the registered qpubench backend.

    Parameters
    ----------
    runner:
        A BenchmarkRunner with an ExternalEvalAlgorithmAdapter registered.
    backend_name:
        The name the adapter was registered under.
    on_iteration:
        Called for each historical ADAPT macro-iteration after run completes.
    on_record:
        Called with the completed BenchmarkRecord after each run.

    Example
    -------
        from qpubench import BenchmarkRunner, ExecutionOptions, AlgorithmSpec
        from qpubench import StubGateAdapter
        from qpubench_qforte import ExternalEvalAlgorithmAdapter
        from qpubench_qforte.adapt_vqe import ExternalEvalAdaptVQERunner
        from qpubench_qforte.converters import molecule_spec_from_file

        runner = BenchmarkRunner()
        stub   = StubGateAdapter(seed=0)
        runner.register(
            ExternalEvalAlgorithmAdapter(energy_backend=stub),
            name="qforte+stub",
        )
        ext_runner = ExternalEvalAdaptVQERunner(runner, "qforte+stub")
        mol    = molecule_spec_from_file("He-ccpvdz.json")
        record = ext_runner.run(mol, AlgorithmSpec(name="ADAPTVQE"))
    """

    def __init__(
        self,
        runner: BenchmarkRunner,
        backend_name: str,
        on_iteration: IterationCallback | None = None,
        on_record:    RecordCallback    | None = None,
    ) -> None:
        self._runner       = runner
        self._backend_name = backend_name
        self._on_iteration = on_iteration
        self._on_record    = on_record

    def run(
        self,
        molecule: CircuitSpec,
        alg_spec: AlgorithmSpec,
        adapt_vqe_run_config: AdaptVQERunConfig | None = None,
        *,
        tags:   list[str] | None = None,
        run_id: str | None       = None,
        notes:  str              = "",
    ) -> BenchmarkRecord:
        record = self._runner.run(
            molecule,
            self._backend_name,
            ExecutionOptions(algorithm_spec=alg_spec, adapt_vqe_run_config=adapt_vqe_run_config),
            tags=tags or ["adapt-vqe", "external-eval"],
            run_id=run_id,
            notes=notes,
        )
        if self._on_iteration and record.result.adapt_history:
            for it in record.result.adapt_history:
                self._on_iteration(it)
        if self._on_record:
            self._on_record(record)
        return record

    def compare_backends(
        self,
        molecule: CircuitSpec,
        alg_spec: AlgorithmSpec,
        backend_names: list[str],
        adapt_vqe_run_config: AdaptVQERunConfig | None = None,
        *,
        run_id: str | None = None,
        tags: list[str] | None = None,
    ) -> list[BenchmarkRecord]:
        """Run the same ADAPT-VQE configuration on multiple energy backends."""
        pool_type = adapt_vqe_run_config.pool_type if adapt_vqe_run_config else "default"
        records = []
        for name in backend_names:
            rec = self._runner.run(
                molecule,
                name,
                ExecutionOptions(algorithm_spec=alg_spec, adapt_vqe_run_config=adapt_vqe_run_config),
                run_id=run_id or f"compare_backends_{pool_type}",
                tags=tags or ["adapt-vqe", "backend-comparison"],
            )
            if self._on_record:
                self._on_record(rec)
            records.append(rec)
        return records
