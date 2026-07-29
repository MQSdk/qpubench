from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .backends.base import AlgorithmAdapter
from .schemas.circuit import CircuitSpec
from .schemas.execution import ExecutionOptions
from .schemas.primitives import JobStatus
from .schemas.record import BenchmarkRecord, VQAConfig, VQAResult
from .schemas.result import QuantumResult

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Orchestrates benchmark execution across registered backends.

    Supports two adapter protocols:

    BackendAdapter    — circuit-driven: qpubench provides the circuit, the
                        backend executes it. Used by every simulator and
                        hardware QPU adapter.

    AlgorithmAdapter  — algorithm-driven: the library generates the circuit
                        from a problem spec and drives its own execution loop.
                        Used by algorithm libraries that will not accept a
                        pre-written circuit. Detected automatically via an
                        isinstance() check.

    The authoritative list of which concrete adapters ship in this package,
    which protocol each implements, and which are still stubs is maintained in
    ``docs/backends.md`` — deliberately not duplicated here, so the two cannot
    drift apart.

    Usage pattern:

        runner = BenchmarkRunner(store="results.ndjson")
        runner.register(name="stub", seed=42)
        record = runner.run(circuit, "stub", shots=4096)

        runner.register(AerAdapter(), name="aer")
        record = runner.run(circuit, "aer", ExecutionOptions(shots=4096, memory=True))

    Passing ``store=`` a str or Path creates an NDJSONStore. Calling
    ``register()`` with no adapter creates a StubGateAdapter; every other
    adapter — both protocols alike — is constructed by the caller and passed
    in explicitly, and the runner picks the right execution path itself.

    Hooks receive every completed BenchmarkRecord before persistence.
    """

    def __init__(self, store: Any | str | None = None) -> None:
        """Create a runner, optionally bound to a result store.

        A filesystem path (str or pathlib.Path) becomes an append-only
        NDJSONStore, so the common case needs neither an explicit store import
        nor pathlib — just ``store="results/bell.ndjson"``. Pass a
        ParquetStore / S3Store instance to use one of the other stores, or
        nothing at all to keep results in memory only.
        """
        import pathlib

        if isinstance(store, (str, pathlib.Path)):
            from .store import NDJSONStore

            store = NDJSONStore(store)
        self._backends: dict[str, Any] = {}
        self._store = store
        self._hooks: list[Callable[[BenchmarkRecord], None]] = []

    def register(
        self,
        adapter: Any | None = None,
        *,
        name: str | None = None,
        seed: int | None = None,
    ) -> None:
        """Register an adapter under ``name``.

        Called without an adapter, a ``StubGateAdapter`` (random results, no
        quantum SDK needed) is created automatically — ``runner.register(
        name="stub", seed=42)`` is shorthand for ``runner.register(
        StubGateAdapter(seed=42), name="stub")``.
        """
        if adapter is None and name is None:
            raise TypeError(
                "register() without an adapter needs a name, e.g. "
                'runner.register(name="stub", seed=42)'
            )
        if adapter is None:
            from .backends.stub import StubGateAdapter

            adapter = StubGateAdapter(seed=seed)
        elif seed is not None:
            raise TypeError(
                "seed= only applies to the auto-created stub; construct your "
                "adapter with its own seed instead, e.g. StubGateAdapter(seed=...)"
            )
        key = name if name is not None else adapter.spec.name
        self._backends[key] = adapter
        logger.debug("Registered adapter %r", key)

    def add_hook(self, fn: Callable[[BenchmarkRecord], None]) -> None:
        """Register a callback fired with every completed BenchmarkRecord.

        Hooks run after the record is built and before it is persisted, in
        registration order. A hook that raises is logged and skipped — it
        never aborts the run or prevents persistence.
        """
        self._hooks.append(fn)

    def list_backends(self) -> list[str]:
        """Return the names every adapter is currently registered under."""
        return list(self._backends)

    def run(
        self,
        circuit: CircuitSpec,
        backend_name: str,
        options: ExecutionOptions | None = None,
        *,
        shots: int | None       = None,
        vqa: VQAConfig | None   = None,
        tags: list[str] | None  = None,
        run_id: str | None      = None,
        notes: str              = "",
    ) -> BenchmarkRecord:
        """Execute ``circuit`` on the backend registered as ``backend_name``.

        For the common case only a shot count is needed — ``runner.run(
        circuit, "stub", shots=4096)`` builds ``ExecutionOptions(shots=4096)``
        for you. Pass a full ``ExecutionOptions`` instead when you need more
        (error mitigation, transpiler settings, algorithm configs, ...).

        ``vqa`` carries only the experiment *inputs* (molecule, ansatz,
        optimizer, ...).  Computed outputs are never passed in: algorithm
        adapters return a ``VQAResult``, and for circuit-driven VQA runs the
        runner derives ``VQAResult.final_eigenvalue`` from the result's
        expectation values automatically.

        Two execution paths follow, chosen by which protocol the registered
        adapter satisfies. The algorithm-driven path calls
        ``validate_problem()`` / ``run_algorithm()`` and receives the VQA
        metadata back from the adapter, with any caller-supplied ``vqa``
        taking precedence over what the adapter extracted. The circuit-driven
        path calls ``validate()`` / ``run()`` and carries the caller's ``vqa``
        through unchanged. Either way an adapter exception is caught and
        recorded as a FAILED QuantumResult rather than propagating, so one bad
        backend cannot abort a sweep.
        """
        if options is None:
            options = ExecutionOptions(shots=shots)
        elif shots is not None:
            raise TypeError(
                "pass shots= either directly or inside ExecutionOptions, not both"
            )
        try:
            adapter = self._backends[backend_name]
        except KeyError:
            registered = ", ".join(sorted(self._backends)) or "<none>"
            raise KeyError(
                f"No backend registered as {backend_name!r}. "
                f"Registered backends: {registered}"
            ) from None

        if isinstance(adapter, AlgorithmAdapter):
            warnings = adapter.validate_problem(circuit)
            for w in warnings:
                logger.warning("[%s] %s", backend_name, w)

            t0 = time.perf_counter()
            try:
                result, extracted_vqa, vqa_result = adapter.run_algorithm(
                    circuit, options
                )
            except Exception as exc:
                logger.exception("AlgorithmAdapter %r raised", backend_name)
                result = QuantumResult(
                    computing_model=circuit.computing_model,
                    qubit_modality=circuit.qubit_modality,
                    status=JobStatus.FAILED,
                    error_message=str(exc),
                )
                extracted_vqa = vqa if vqa is not None else VQAConfig(problem_type="unknown")
                vqa_result = None
            elapsed = time.perf_counter() - t0

            merged_vqa: VQAConfig | None = vqa if vqa is not None else extracted_vqa

        else:
            warnings = adapter.validate(circuit)
            for w in warnings:
                logger.warning("[%s] %s", backend_name, w)

            t0 = time.perf_counter()
            try:
                result = adapter.run(circuit, options)
            except Exception as exc:
                logger.exception("BackendAdapter %r raised", backend_name)
                result = QuantumResult(
                    computing_model=circuit.computing_model,
                    qubit_modality=circuit.qubit_modality,
                    status=JobStatus.FAILED,
                    error_message=str(exc),
                )
            elapsed = time.perf_counter() - t0
            merged_vqa = vqa
            vqa_result = None

        if merged_vqa is not None and vqa_result is None and result.expectation_values:
            vqa_result = VQAResult(
                final_eigenvalue=result.expectation_values[0].value
            )

        if result.total_time_s is None:
            result = result.model_copy(update={"total_time_s": round(elapsed, 6)})

        record = BenchmarkRecord(
            circuit=circuit,
            backend=adapter.spec,
            options=options,
            result=result,
            vqa=merged_vqa,
            vqa_result=vqa_result,
            num_qubits=circuit.num_qubits,
            run_id=run_id,
            tags=tags if tags is not None else [],
            notes=notes,
        )

        for hook in self._hooks:
            try:
                hook(record)
            except Exception:
                logger.exception("Hook %r raised", hook)

        if self._store is not None:
            self._store.save(record)

        return record

    def sweep(
        self,
        circuits: list[CircuitSpec],
        backend_names: list[str],
        options_list: list[ExecutionOptions],
        *,
        run_id: str | None     = None,
        tags: list[str] | None = None,
        progress: Callable[[int, int], None] | None = None,
        **kwargs: Any,
    ) -> list[BenchmarkRecord]:
        """Cartesian product sweep over circuits × backends × options.

        progress(current, total) is called before each run if provided.
        All runs share the same run_id so they can be grouped in the store.
        """
        combos = [
            (c, b, o)
            for c in circuits
            for b in backend_names
            for o in options_list
        ]
        total = len(combos)
        records: list[BenchmarkRecord] = []

        for i, (circuit, backend_name, options) in enumerate(combos):
            if progress is not None:
                progress(i, total)
            records.append(
                self.run(
                    circuit,
                    backend_name,
                    options,
                    run_id=run_id,
                    tags=tags,
                    **kwargs,
                )
            )

        if progress is not None:
            progress(total, total)

        return records
