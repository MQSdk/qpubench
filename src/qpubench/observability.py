"""Structured logging subsystem for BenchmarkRunner.

Closes qrunch's "Using the Logger" guide gap: ``BenchmarkRunner.add_hook()``
fires one callback per completed ``BenchmarkRecord`` — enough to build real
structured logging on top of, but by itself just one hook, not "levels,
handlers, formatters" the way qrunch's guide documents. ``BenchmarkLogger``
is that subsystem, built directly on top of the existing hook mechanism (no
runner changes needed):

  - levels      SUCCEEDED -> INFO, FAILED -> ERROR (status-based, real
                ``logging`` levels, not a single flat log line).
  - handlers    any ``logging.Handler`` — ``StreamHandler`` (default),
                ``FileHandler``, ``RotatingFileHandler``, etc.
  - formatters  ``JSONFormatter`` (structured, machine-parseable) by
                default; swap for any ``logging.Formatter``.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .schemas.primitives import JobStatus
from .schemas.record import BenchmarkRecord


class JSONFormatter(logging.Formatter):
    """Formats a BenchmarkLogger record as one structured JSON line.

    Looks for a ``record_payload`` dict attached via ``extra=`` (how
    ``BenchmarkLogger`` emits records); falls back to the standard
    ``logging.Formatter`` behavior for any other log record sharing the
    same handler.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "record_payload", None)
        if payload is None:
            return super().format(record)
        return json.dumps(payload)


class BenchmarkLogger:
    """Structured logging on top of ``BenchmarkRunner.add_hook()``.

    Parameters
    ----------
    name:
        Logger name (default ``"qpubench.benchmark"``).
    handler:
        ``logging.Handler`` to attach; defaults to a ``StreamHandler`` with
        ``JSONFormatter``. Pass e.g. ``logging.FileHandler("results.log")``
        or ``logging.handlers.RotatingFileHandler(...)`` for a different
        real handler.
    level:
        Minimum level the underlying logger emits (default ``INFO``).
    """

    def __init__(
        self,
        name: str = "qpubench.benchmark",
        *,
        handler: logging.Handler | None = None,
        level: int = logging.INFO,
    ) -> None:
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        if handler is None:
            handler = logging.StreamHandler()
            handler.setFormatter(JSONFormatter())
        self.logger.addHandler(handler)

    def attach(self, runner: Any) -> None:
        """Wire this logger into a ``BenchmarkRunner`` via ``add_hook()``."""
        runner.add_hook(self._on_record)

    def _on_record(self, record: BenchmarkRecord) -> None:
        payload = {
            "experiment_id": record.experiment_id,
            "backend": record.backend.name,
            "status": record.result.status.value,
            "elapsed_s": record.result.total_time_s,
            "num_qubits": record.num_qubits,
            "run_id": record.run_id,
        }
        level = logging.ERROR if record.result.status == JobStatus.FAILED else logging.INFO
        self.logger.log(level, payload, extra={"record_payload": payload})


__all__ = ["BenchmarkLogger", "JSONFormatter"]
