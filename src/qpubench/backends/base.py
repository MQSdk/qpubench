"""Backend adapter protocols.

BackendAdapter        — minimal 3-method interface for backends that execute a
                        pre-written circuit (gate-based simulators, QPUs, MBQC FPGA).

TranspilableBackend   — optional extension for backends that expose transpilation
                        as a separate step (Qiskit, Qrack circuit API).

AlgorithmAdapter      — second-class protocol for algorithm libraries (QForte,
                        OpenFermion-based stacks) that generate circuits internally
                        and drive their own execution loop.  The fundamental design
                        gap in a circuit-centric framework: these libraries do not
                        accept a pre-written circuit; they generate one from a
                        problem specification (molecule, Hamiltonian).

Gap analysis
------------
BackendAdapter assumes:  qpubench provides circuit → backend executes it.
AlgorithmAdapter assumes: library generates circuit from problem spec → executes on
                          its own simulator → qpubench records results.

ErrorMitigationAdapter wraps a BackendAdapter with pre/post error mitigation or
suppression (Q-CTRL Fire Opal, Mitiq, Haiqu Rivet, etc.).  It satisfies the
BackendAdapter protocol so BenchmarkRunner requires no changes — register it
directly and it dispatches normally through the circuit-driven path.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas.backend import BackendSpec
from ..schemas.circuit import CircuitSpec
from ..schemas.execution import ExecutionOptions
from ..schemas.record import VQAConfig
from ..schemas.result import QuantumResult, TranspileLayout


@runtime_checkable
class BackendAdapter(Protocol):
    @property
    def spec(self) -> BackendSpec:
        """Static hardware / simulator description."""
        ...

    def validate(self, circuit: CircuitSpec) -> list[str]:
        """Return validation warnings; raise ValueError for hard errors.

        Check: qubit count, supported gate set, circuit format,
        modality compatibility, parameter bindings completeness.
        """
        ...

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult:
        """Transpile (if needed), execute, and return a QuantumResult.

        Contract:
          - Populate result.qpu_time_s from backend timing when available.
          - Populate result.transpile_layout if transpilation occurred.
          - Return status=FAILED with error_message on recoverable errors.
          - Raise only on unrecoverable programmer errors (bad types, etc.).
        """
        ...


@runtime_checkable
class TranspilableBackend(Protocol):
    """Extension for backends that expose transpilation as a separate step."""

    def transpile(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[CircuitSpec, TranspileLayout | None]:
        """Return the transpiled circuit and qubit layout.

        The returned CircuitSpec should have:
          - serialized updated to the native-gate QASM/QGC
          - gate_counts populated from the transpiled circuit
          - parameter_bindings preserved (re-binding still works)
        """
        ...


@runtime_checkable
class AlgorithmAdapter(Protocol):
    """Protocol for algorithm libraries that manage their own execution loop.

    These libraries (QForte, PySCF+OpenFermion stacks, etc.) accept a
    problem specification (molecule Hamiltonian), generate a circuit
    internally, execute on their own simulator, and return a result.

    The CircuitSpec passed to run_algorithm() uses format=MOLECULE_JSON
    with serialized holding either a JSON molecule dict or a file path.
    The algorithm to run is specified in options.algorithm_spec.

    Returns both a QuantumResult (for the result store) and a VQAConfig
    (chemistry metadata), since algorithm libraries produce both.
    """

    @property
    def spec(self) -> BackendSpec: ...

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        """Validate the problem specification; return warnings."""
        ...

    def run_algorithm(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[QuantumResult, VQAConfig]:
        """Run the algorithm and return (result, vqa_metadata).

        The algorithm is determined by options.algorithm_spec.name.
        """
        ...


@runtime_checkable
class ErrorMitigationAdapter(Protocol):
    """Protocol for adapters that wrap error mitigation around a BackendAdapter.

    Satisfies BackendAdapter (same spec/validate/run interface) so it can be
    registered with BenchmarkRunner directly — no runner changes needed.
    Internally the adapter holds a reference to an inner BackendAdapter and
    intercepts run() to apply pre/post processing (noise scaling, compilation,
    randomised compiling, readout correction, etc.).

    Implementations: FireOpalAdapter, MitiqAdapter, HaiquAdapter.

    The inner BackendAdapter is not registered with the runner separately;
    it is composed inside the ErrorMitigationAdapter at construction time.
    """

    @property
    def spec(self) -> BackendSpec: ...

    def validate(self, circuit: CircuitSpec) -> list[str]: ...

    def run(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> QuantumResult: ...

    @property
    def inner(self) -> BackendAdapter:
        """The wrapped BackendAdapter that performs raw circuit execution."""
        ...
