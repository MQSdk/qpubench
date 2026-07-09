"""Package-agnostic ADAPT-VQE control flow.

Pure Python + qpubench schemas + scipy (a lightweight classical-optimizer
dependency, not a quantum SDK) — no vendor SDK required. Implements the
adaptive derivative-assembled ansatz-growth loop (Grimsley et al., Nat.
Commun. 10, 3007 (2019)) against the fermionic singles+doubles pool in
pool.py and the circuit synthesis in circuit_synthesis.py, delegating every
energy evaluation to any qpubench BackendAdapter — exactly the same
"any operator-pool-growing algorithm can use any backend" pattern QForte's
own ExternalEvalAlgorithmAdapter established (integrations/qforte/), just
without requiring QForte itself.

Gate selection (which pool operator to add next) is delegated to a
`GateSelector` (gate_selector.py) — `FastGateSelector` (default, gradient
screen via central finite differences) or `BruteForceGateSelector` (full
re-optimization per candidate) — closing qrunch's "Create a FAST/Brute
Force Gate Selector" guides as swappable, reusable components rather than
control flow baked into this engine's main loop.

Gradient screening (FastGateSelector) uses central finite differences
rather than an analytic commutator, trading some measurement efficiency
for reusing the already-verified circuit-exponential construction directly
(see circuit_synthesis.py) instead of adding a second from-scratch
Pauli-algebra implementation (commutator expansion) with its own
correctness risk. AdaptVQEConfig.use_analytic_gradient is honored by other
adapters (QForte has real analytic gradients); this reference engine
always uses finite differences and documents that limitation rather than
claiming a capability it doesn't have.
"""
from __future__ import annotations

from typing import Any

from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import AdaptVQEConfig, ExecutionOptions
from qpubench.schemas.observable import SparsePauliObservable
from qpubench.schemas.primitives import CircuitFormat
from qpubench.schemas.record import VQAConfig
from qpubench.schemas.result import AdaptIteration, ExpectationResult, JobStatus, QuantumResult

from .circuit_synthesis import operator_trotter_step_qasm3
from .gate_selector import FastGateSelector, GateSelector
from .pool import PoolOperator, generate_singles_doubles_pool


class GenericAdaptVQEEngine:
    """Runs ADAPT-VQE against any qpubench BackendAdapter as the energy oracle.

    Parameters
    ----------
    hamiltonian     qubit Hamiltonian to minimize (SparsePauliObservable).
    num_qubits      circuit width.
    num_electrons   occupied spin-orbitals in the HF reference (see
                    pool.generate_singles_doubles_pool for the convention).
    energy_backend  any qpubench BackendAdapter; circuit.observables=[H]
                    Estimator-path calls return the trial energy.
    config          package-agnostic ADAPT-VQE hyperparameters.
    energy_options  ExecutionOptions forwarded to energy_backend.run();
                    shots=None (statevector) recommended for a clean
                    gradient screen — shot noise makes finite differences
                    unreliable at small epsilon.
    gate_selector   which pool operator to add each macro-iteration —
                    defaults to `FastGateSelector()` (gradient screen,
                    the engine's original behavior, unchanged). Pass
                    `BruteForceGateSelector()` for qrunch's exact-but-
                    expensive alternative (gate_selector.py).
    """

    def __init__(
        self,
        hamiltonian: SparsePauliObservable,
        num_qubits: int,
        num_electrons: int,
        energy_backend: Any,
        config: AdaptVQEConfig | None = None,
        energy_options: ExecutionOptions | None = None,
        gate_selector: GateSelector | None = None,
    ) -> None:
        self.hamiltonian    = hamiltonian
        self.num_qubits     = num_qubits
        self.num_electrons  = num_electrons
        self.energy_backend = energy_backend
        self.config          = config or AdaptVQEConfig()
        self.energy_options   = energy_options or ExecutionOptions()
        self.gate_selector    = gate_selector or FastGateSelector()
        self.pool: list[PoolOperator] = generate_singles_doubles_pool(num_qubits, num_electrons)

    # ------------------------------------------------------------------
    # Circuit assembly
    # ------------------------------------------------------------------

    def _ansatz_qasm3(self, selected: list[int], amplitudes: list[float]) -> str:
        lines = [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            f"qubit[{self.num_qubits}] q;",
        ]
        lines += [f"x q[{i}];" for i in range(self.num_electrons)]  # HF reference
        for idx, amp in zip(selected, amplitudes):
            for term in self.pool[idx].observable.terms:
                lines += operator_trotter_step_qasm3(term, amp)
        return "\n".join(lines)

    def circuit_spec(self, selected: list[int], amplitudes: list[float]) -> CircuitSpec:
        """Public accessor — the exact CircuitSpec used for energy evaluation."""
        return CircuitSpec(
            num_qubits=self.num_qubits,
            format=CircuitFormat.QASM3,
            serialized=self._ansatz_qasm3(selected, amplitudes),
            observables=[self.hamiltonian],
        )

    # ------------------------------------------------------------------
    # Energy evaluation (delegated to energy_backend)
    # ------------------------------------------------------------------

    def _energy(self, selected: list[int], amplitudes: list[float]) -> float:
        circuit = self.circuit_spec(selected, amplitudes)
        result  = self.energy_backend.run(circuit, self.energy_options)
        if not result.expectation_values:
            raise RuntimeError(
                f"energy_backend {self.energy_backend.spec.name!r} returned no "
                "expectation values — it must support the Estimator path "
                "(circuit.observables populated)."
            )
        return float(result.expectation_values[0].value)

    # ------------------------------------------------------------------
    # Classical optimizer
    # ------------------------------------------------------------------

    def _optimize(self, selected: list[int], amplitudes: list[float]) -> list[float]:
        from scipy.optimize import minimize

        def objective(x: Any) -> float:
            return self._energy(selected, list(x))

        res = minimize(
            objective,
            amplitudes,
            method=self.config.optimizer,
            options={"maxiter": self.config.max_micro_iterations},
            tol=self.config.energy_threshold,
        )
        return list(res.x)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> tuple[QuantumResult, VQAConfig]:
        selected: list[int]   = []
        amplitudes: list[float] = []
        adapt_history: list[AdaptIteration] = []
        converged = False

        for _ in range(self.config.max_macro_iterations):
            best_idx, score, converged = self.gate_selector.select(
                self.pool, selected, amplitudes, self._energy, self.config,
            )
            if converged or best_idx < 0:
                converged = True
                break
            selected.append(best_idx)
            amplitudes.append(0.0)
            amplitudes = self._optimize(selected, amplitudes)
            energy = self._energy(selected, amplitudes)
            circuit = self._ansatz_qasm3(selected, amplitudes)
            adapt_history.append(AdaptIteration(
                iteration=len(adapt_history),
                energy=energy,
                grad_norm=score,
                n_operators=len(selected),
                n_cnot=circuit.count("\ncx "),
                n_classical_params=len(amplitudes),
            ))

        final_energy = adapt_history[-1].energy if adapt_history else self._energy(selected, amplitudes)
        final_qasm    = self._ansatz_qasm3(selected, amplitudes)
        n_cnot        = final_qasm.count("\ncx ")

        result = QuantumResult(
            computing_model=self.energy_backend.spec.computing_model,
            expectation_values=[
                ExpectationResult(observable_index=0, value=final_energy, std_error=0.0)
            ],
            adapt_history=adapt_history or None,
            transpiled_circuit=final_qasm,
            transpiled_circuit_format=CircuitFormat.QASM3,
            status=JobStatus.SUCCEEDED,
            metadata={"converged": converged, "selected_operators": [
                self.pool[i].label for i in selected
            ]},
        )
        vqa = VQAConfig(
            problem_type="chemistry",
            algorithm="ADAPTVQE",
            pool_type=self.config.pool_type,
            optimizer=self.config.optimizer,
            num_parameters=len(amplitudes),
            n_cnot=n_cnot,
            convergence_values=[it.energy for it in adapt_history],
            adapt_maxiter_reached=not converged,
            final_eigenvalue=final_energy,
        )
        return result, vqa
