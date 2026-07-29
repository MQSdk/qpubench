"""qoqo_qasm — qoqo ⇄ OpenQASM translation and its dialects (HQS).

A thin package with one disproportionately useful idea: **"OpenQASM 3.0" is
not one format**.  ``roqoqo_qasm::QasmVersion`` is a version *and* a dialect,
and the same qoqo circuit emits materially different text under each:

    2.0 Vanilla   standard OpenQASM 2.0, with gate definitions emitted
    2.0 Qulacs    OpenQASM 2.0 without gate definitions (Qulacs supplies its own)
    3.0 Vanilla   standard OpenQASM 3.0, PRAGMA operations dropped
    3.0 Roqoqo    OpenQASM 3.0 plus roqoqo's own pragma syntax
    3.0 Braket    OpenQASM 3.0 plus AWS Braket's pragma syntax

Why this matters to qpubench
----------------------------
``primitives.CircuitFormat`` has ``QASM2`` and ``QASM3`` and stops there, so
two records can both claim ``format=QASM3`` while one is portable and the
other only loads under Braket.  ``QasmDialect`` below names the difference,
and ``QoqoQasmConfig.circuit_format`` maps back onto the core enum so nothing
is lost in the other direction.

The second idea worth mirroring is honesty about coverage: qoqo_qasm refuses
to translate a circuit containing an operation with no QASM equivalent rather
than silently dropping it.  ``QoqoQasmTranslationResult`` records what was
translated and what was refused, so a benchmark that ran on a *subset* of its
intended circuit is visible as such.

Register naming
---------------
roqoqo addresses qubits in one flat ``usize`` space with no declared
registers; OpenQASM requires an explicitly named register.  The translation
therefore invents one, ``q`` by default — a detail that becomes load-bearing
the moment two translated circuits are concatenated.

References
----------
qoqo_qasm   https://github.com/HQSquantumsimulations/qoqo_qasm
roqoqo-qasm https://docs.rs/roqoqo-qasm/
"""
from __future__ import annotations

import enum

import pydantic

from ..primitives import CircuitFormat

DEFAULT_QUBIT_REGISTER_NAME = "q"


class QasmDialect(str, enum.Enum):
    """OpenQASM version *and* dialect, as ``QasmVersion::from_str`` parses it.

    The values are the exact strings qoqo_qasm's ``Backend`` accepts, so a
    stored config can be handed back to it verbatim.  ``"2.0"`` and ``"3.0"``
    are also accepted upstream as aliases for the Vanilla dialects; this enum
    uses the explicit forms so a record never leaves the dialect implicit.
    """
    V2_VANILLA = "2.0Vanilla"
    V2_QULACS  = "2.0Qulacs"
    V3_VANILLA = "3.0Vanilla"
    V3_ROQOQO  = "3.0Roqoqo"
    V3_BRAKET  = "3.0Braket"

    @property
    def circuit_format(self) -> CircuitFormat:
        """The core ``CircuitFormat`` this dialect serialises to."""
        return CircuitFormat.QASM2 if self.value.startswith("2.0") else CircuitFormat.QASM3

    @property
    def is_portable(self) -> bool:
        """True for dialects a standards-conforming QASM parser accepts.

        The Qulacs dialect omits gate definitions and the Roqoqo/Braket
        dialects add non-standard pragmas, so only the Vanilla dialects
        survive a round trip through an unrelated toolchain.
        """
        return self in (QasmDialect.V2_VANILLA, QasmDialect.V3_VANILLA)

    @property
    def supports_pragmas(self) -> bool:
        """True when PRAGMA operations survive translation.

        Vanilla dialects drop them — which means noise PRAGMAs
        (``PragmaDamping`` and friends) silently leave the circuit, turning a
        noisy program into a noiseless one.
        """
        return self in (QasmDialect.V3_ROQOQO, QasmDialect.V3_BRAKET)


class QoqoQasmConfig(pydantic.BaseModel):
    """qoqo_qasm ``Backend`` construction arguments.

    qubit_register_name  the QASM register name roqoqo's flat qubit space is
                         written into; upstream default ``"q"``
    dialect              which QASM version and dialect to emit
    """
    qubit_register_name: str         = DEFAULT_QUBIT_REGISTER_NAME
    dialect:             QasmDialect = QasmDialect.V2_VANILLA

    @property
    def circuit_format(self) -> CircuitFormat:
        return self.dialect.circuit_format

    @property
    def version_string(self) -> str:
        """The string to pass to ``Backend(qubit_register_name, qasm_version)``."""
        return self.dialect.value


class QoqoQasmTranslationResult(pydantic.BaseModel):
    """Outcome of translating one qoqo circuit to QASM.

    qasm              the emitted source, or None when translation failed
    untranslated_ops  hqslang names of operations with no QASM equivalent.
                      Non-empty means the translation was *refused*, not
                      partially applied: qoqo_qasm raises
                      ``OperationNotInBackend`` rather than emitting an
                      incomplete circuit.
    dropped_pragmas   PRAGMA names removed because the target dialect does
                      not carry pragmas.  Unlike ``untranslated_ops`` this is
                      not an error — but a dropped noise pragma changes what
                      the circuit means, so it belongs in the record.
    """
    config:           QoqoQasmConfig
    qasm:             str | None = None
    untranslated_ops: list[str]  = []
    dropped_pragmas:  list[str]  = []

    @property
    def succeeded(self) -> bool:
        return self.qasm is not None and not self.untranslated_ops

    @property
    def is_faithful(self) -> bool:
        """True when the QASM means the same thing as the source circuit.

        A successful translation that dropped noise pragmas is *not*
        faithful: it produces a valid circuit describing a different
        experiment.
        """
        return self.succeeded and not self.dropped_pragmas

    @pydantic.model_validator(mode="after")
    def _check_dropped_pragmas(self) -> QoqoQasmTranslationResult:
        if self.dropped_pragmas and self.config.dialect.supports_pragmas:
            raise ValueError(
                f"dialect {self.config.dialect.value} carries pragmas, so "
                f"dropped_pragmas {self.dropped_pragmas} should be empty"
            )
        return self
