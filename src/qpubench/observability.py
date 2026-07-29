"""Structured logging subsystem for BenchmarkRunner.

``BenchmarkRunner.add_hook()`` fires one callback per completed
``BenchmarkRecord``. That is enough to build structured logging on top of,
but by itself it is just a callback — no levels, no handlers, no
formatters. ``BenchmarkLogger`` is that missing subsystem, built entirely on
the existing hook mechanism (the runner needs no changes):

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

# Ordered by layer, not alphabetically: BenchmarkRecord is the higher-level
# type this module exists to log; JobStatus is a primitive it happens to need
# in order to pick a logging level. isort is told to leave the block alone.
# isort: off
from .schemas.record import BenchmarkRecord
from .schemas.primitives import JobStatus
# isort: on


class JSONFormatter(logging.Formatter):
    """Formats a BenchmarkLogger record as one structured JSON line.

    Looks for a ``record_payload`` dict attached via ``extra=`` (how
    ``BenchmarkLogger`` emits records); falls back to the standard
    ``logging.Formatter`` behavior for any other log record sharing the
    same handler.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render one log record as a JSON line, or defer to the base class.

        ``super().format(record)`` calls ``logging.Formatter.format`` — the
        implementation this class overrides. Deferring to it (rather than
        reimplementing it) is what lets an unrelated library share this
        handler and still get normal, human-readable log lines. See
        ``docs/developer_guide.md`` for the general pattern.
        """
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
        """Emit one completed BenchmarkRecord as a structured log entry.

        Both identifiers are logged because they answer different questions:
        ``experiment_id`` is this single execution's auto-generated UUID and
        is the key ``ResultStore.load()`` looks records up by, so a log line
        can be traced back to the stored record. ``run_id`` is the
        caller-supplied label shared by every record in one sweep, so a log
        line can be traced back to the campaign that produced it.
        """
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
