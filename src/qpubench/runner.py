from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .backends.base import AlgorithmAdapter, BackendAdapter
from .schemas.circuit import CircuitSpec
from .schemas.execution import ExecutionOptions
from .schemas.primitives import JobStatus
from .schemas.record import BenchmarkRecord, VQAConfig
from .schemas.result import QuantumResult

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Orchestrates benchmark execution across registered backends.

    Supports two adapter protocols:

    BackendAdapter    — circuit-driven: qpubench provides the circuit, the
                        backend executes it.  Used for simulators (Aer, Qrack),
                        IBM Quantum Runtime, IQM, MBQC-FPGA.

    AlgorithmAdapter  — algorithm-driven: the library generates the circuit
                        from a problem spec and drives its own execution loop.
                        Used for QForte (UCCNVQE, ADAPT-VQE), OpenFermion stacks.
                        Detected automatically via isinstance() check.

    Usage pattern:
        runner = BenchmarkRunner(store=NDJSONStore(Path("results.ndjson")))
        runner.register(StubGateAdapter(), name="stub")
        record = runner.run(circuit, "stub", options)
        # Algorithm adapters (QForte etc.) are registered the same way;
        # the runner dispatches to run_algorithm() automatically.

    Hooks receive every completed BenchmarkRecord before persistence.
    """

    def __init__(self, store: Any | None = None) -> None:
        self._backends: dict[str, Any] = {}
        self._store = store
        self._hooks: list[Callable[[BenchmarkRecord], None]] = []

    def register(
        self,
        adapter: Any,
        *,
        name: str | None = None,
    ) -> None:
        key = name or adapter.spec.name
        self._backends[key] = adapter
        logger.debug("Registered adapter %r", key)

    def add_hook(self, fn: Callable[[BenchmarkRecord], None]) -> None:
        self._hooks.append(fn)

    def list_backends(self) -> list[str]:
        return list(self._backends)

    # ------------------------------------------------------------------
    # Single execution
    # ------------------------------------------------------------------

    def run(
        self,
        circuit: CircuitSpec,
        backend_name: str,
        options: ExecutionOptions,
        *,
        vqa: VQAConfig | None   = None,
        tags: list[str] | None  = None,
        run_id: str | None      = None,
        notes: str              = "",
    ) -> BenchmarkRecord:
        adapter = self._backends[backend_name]

        # --- Algorithm-driven path (QForte, etc.) ---
        if isinstance(adapter, AlgorithmAdapter):
            warnings = adapter.validate_problem(circuit)
            for w in warnings:
                logger.warning("[%s] %s", backend_name, w)

            t0 = time.perf_counter()
            try:
                result, extracted_vqa = adapter.run_algorithm(circuit, options)
            except Exception as exc:
                logger.exception("AlgorithmAdapter %r raised", backend_name)
                result = QuantumResult(
                    modality=circuit.modality,
                    status=JobStatus.FAILED,
                    error_message=str(exc),
                )
                extracted_vqa = vqa or VQAConfig(problem_type="unknown")
            elapsed = time.perf_counter() - t0

            # Caller-supplied vqa overrides extracted metadata if provided
            merged_vqa: VQAConfig | None = vqa if vqa is not None else extracted_vqa

        # --- Circuit-driven path (Aer, IBM, Qrack, MBQC, stubs) ---
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
                    modality=circuit.modality,
                    status=JobStatus.FAILED,
                    error_message=str(exc),
                )
            elapsed = time.perf_counter() - t0
            merged_vqa = vqa

        if result.total_time_s is None:
            result = result.model_copy(update={"total_time_s": round(elapsed, 6)})

        record = BenchmarkRecord(
            circuit=circuit,
            backend=adapter.spec,
            options=options,
            result=result,
            vqa=merged_vqa,
            num_qubits=circuit.num_qubits,
            run_id=run_id,
            tags=tags or [],
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

    # ------------------------------------------------------------------
    # Parameter sweep
    # ------------------------------------------------------------------

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
