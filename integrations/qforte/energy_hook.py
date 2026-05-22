"""EnergyEvaluatorHook — redirect QForte's energy_feval to a qpubench backend.

Architecture
------------
QForte's classical optimizer (scipy.minimize) calls energy_feval(params) → float.
This module:
  1. Subclasses the QForte algorithm class and overrides energy_feval.
  2. Inside energy_feval, builds the current parametrised circuit via
     build_Uvqc(), converts it to QASM2, runs it on the qpubench backend,
     and returns ⟨H⟩.
  3. Falls back to QForte's own Computer if the backend call fails.

This makes QForte's ADAPT-VQE (or UCCNVQE) run its ansatz on any
qpubench-compatible backend — Aer statevector, Qrack GPU, IBM hardware.

Separation contract
-------------------
qpubench does not import qforte.
qforte does not import qpubench.
This file imports from both; it lives only in qpubench-qforte.
"""
from __future__ import annotations

import warnings
from typing import Any

from qpubench.backends.base import BackendAdapter
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.observable import SparsePauliObservable

from .circuit_utils import qforte_circuit_to_qasm2


class EnergyEvaluatorHook:
    """Wraps a qpubench BackendAdapter for use as QForte's energy oracle.

    Parameters
    ----------
    backend:
        Any object implementing qpubench's BackendAdapter protocol.
        Statevector backends (shots=None) are most accurate; shot-based
        backends introduce sampling noise proportional to 1/√shots.
    hamiltonian:
        Qubit Hamiltonian as SparsePauliObservable.
        Build from alg._qb_ham with qforte_op_to_sparse_pauli().
    n_qubits:
        Total qubit count (int(alg._nqb)).
    ref:
        HF reference bitstring (list(alg._ref)).
    options:
        ExecutionOptions forwarded to backend.run().
        Default: statevector (shots=None), no mitigation.
    """

    def __init__(
        self,
        backend: Any,
        hamiltonian: SparsePauliObservable,
        n_qubits: int,
        ref: list[int],
        options: ExecutionOptions | None = None,
    ) -> None:
        self._backend    = backend
        self._ham        = hamiltonian
        self._n_qubits   = n_qubits
        self._ref        = ref
        self._options    = options or ExecutionOptions()
        self._call_count = 0
        self._energies:  list[float] = []

    # ------------------------------------------------------------------

    def evaluate(self, qf_circuit: Any) -> float:
        """Convert circuit → QASM2 → backend.run() → ⟨H⟩."""
        self._call_count += 1
        qasm = qforte_circuit_to_qasm2(qf_circuit, self._n_qubits, self._ref)
        circuit_spec = CircuitSpec(
            num_qubits=self._n_qubits,
            serialized=qasm,
            observables=[self._ham],
        )
        result = self._backend.run(circuit_spec, self._options)
        if not result.expectation_values:
            raise RuntimeError(
                f"Backend {self._backend.spec.name!r} returned no expectation values. "
                "Make sure the backend supports the Estimator path (circuit.observables populated)."
            )
        energy = float(result.expectation_values[0].value)
        self._energies.append(energy)
        return energy

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def energy_history(self) -> list[float]:
        """All energies returned to the optimizer, in evaluation order."""
        return list(self._energies)


# ---------------------------------------------------------------------------
# Dynamic subclass factory
# ---------------------------------------------------------------------------

def make_hooked_class(base_class: Any, hook: EnergyEvaluatorHook) -> Any:
    """Return a subclass of base_class whose energy_feval calls the hook.

    The resulting class is a drop-in replacement: construct it the same way,
    run it the same way.  Every energy evaluation goes through the hook;
    the gradient is still computed by QForte (via measure_gradient, which
    calls energy_feval internally — so the hook covers gradients too).

    Falls back to QForte's internal evaluation if the hook raises an error.

    Example
    -------
        HookedAdaptVQE = make_hooked_class(qforte.ADAPTVQE, hook)
        alg = HookedAdaptVQE(mol, print_summary_file=False)
        alg.run(pool_type="SD", optimizer="BFGS", ...)
    """

    class _HookedAlgorithm(base_class):  # type: ignore[valid-type]
        _qpubench_hook: EnergyEvaluatorHook = hook

        def energy_feval(self, params: list[float]) -> float:
            self._tamps = list(params)
            try:
                circuit = self.build_Uvqc()
                return self._qpubench_hook.evaluate(circuit)
            except Exception as exc:
                warnings.warn(
                    f"qpubench energy hook raised {type(exc).__name__}: {exc!s}. "
                    "Falling back to QForte's internal energy evaluation.",
                    stacklevel=2,
                )
                return super().energy_feval(params)

    _HookedAlgorithm.__name__    = f"Hooked{base_class.__name__}"
    _HookedAlgorithm.__qualname__ = f"Hooked{base_class.__qualname__}"
    return _HookedAlgorithm
