"""Guide: QAOA for MaxCut — the third VQA algorithm alongside VQE and ADAPT-VQE.

Where vanilla VQE minimizes a molecular energy and ADAPT-VQE grows its own
ansatz, the Quantum Approximate Optimization Algorithm (QAOA) attacks a
*combinatorial* problem: it prepares a fixed-structure ansatz of p alternating
cost/mixer layers and optimizes the 2*p angles (gamma, beta) to minimize the
cost Hamiltonian's expectation value. Here the problem is MaxCut on a small
graph — partition the vertices into two sets so as many edges as possible are
cut.

Like vanilla VQE (and unlike ADAPT-VQE), QAOA needs no `AlgorithmAdapter`: it
is a classical optimization loop that evaluates energies through any registered
`BackendAdapter`. The run is *named* by a `VQAConfig`
(`problem_type="optimization"`, `algorithm="QAOA"`) and *configured* by a
`QAOARunConfig` (p, mixer, optimizer, ...) — the same two-object split
ADAPT-VQE uses (see docs/algorithm_spec.md).

Nothing here is a stub: `ToyStatevectorAdapter` is a genuine exact statevector
simulator, and the MaxCut answer is cross-checked against brute force.

Requires: pip install 'qpubench[adapt_vqe]'   (numpy + scipy)

Run:
    python examples/guides/qaoa_maxcut.py
"""
from __future__ import annotations

import itertools
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import numpy as np
from scipy.optimize import minimize

from qpubench import BenchmarkRunner, ExecutionOptions, QAOARunConfig, VQAConfig
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.observable import PauliTerm, SparsePauliObservable
from qpubench.schemas.primitives import ComplexNumber, PauliLabel

from examples.common.toy_hamiltonians import exact_ground_state_energy
from examples.common.toy_statevector_backend import ToyStatevectorAdapter

# A small non-bipartite graph: the 5-cycle C5. MaxCut = 4 (one edge must stay
# uncut in any 2-colouring of an odd cycle), so the optimum is non-trivial.
NUM_VERTICES = 5
EDGES: list[tuple[int, int]] = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)]


def maxcut_cost_observable() -> SparsePauliObservable:
    """Cost Hamiltonian H_C = sum_{(i,j) in E} Z_i Z_j.

    A cut edge contributes <Z_i Z_j> = -1, an uncut edge +1, so *minimizing*
    <H_C> maximizes the number of cut edges. The additive/scaling constant in
    the textbook 0.5*(1 - Z_iZ_j) form is dropped: it shifts the objective but
    not its argmin.
    """
    terms = [
        PauliTerm(
            qubit_indices=(i, j),
            pauli_ops=(PauliLabel.Z, PauliLabel.Z),
            coefficient=ComplexNumber(re=1.0),
        )
        for (i, j) in EDGES
    ]
    return SparsePauliObservable(num_qubits=NUM_VERTICES, terms=terms)


def qaoa_maxcut_qasm(gammas: np.ndarray, betas: np.ndarray) -> str:
    """OpenQASM 3.0 for a p-layer QAOA MaxCut ansatz with numeric angles bound.

    Emits only the gate vocabulary ToyStatevectorAdapter understands
    (`h`, `cx`, `rz`, `rx`) — no comment lines, angles as plain decimals. The
    cost layer exp(-i*gamma*Z_iZ_j) uses the standard CX-RZ(2*gamma)-CX
    decomposition; the transverse-field mixer exp(-i*beta*X_k) is RX(2*beta).
    """
    lines = ["OPENQASM 3.0;", f"qubit[{NUM_VERTICES}] q;"]
    # Initial state |+>^n
    lines += [f"h q[{k}];" for k in range(NUM_VERTICES)]
    for gamma, beta in zip(gammas, betas):
        for i, j in EDGES:                              # cost layer
            lines.append(f"cx q[{i}], q[{j}];")
            lines.append(f"rz({2 * gamma:.10f}) q[{j}];")
            lines.append(f"cx q[{i}], q[{j}];")
        for k in range(NUM_VERTICES):                  # transverse-field mixer
            lines.append(f"rx({2 * beta:.10f}) q[{k}];")
    return "\n".join(lines)


def initial_angles(config: QAOARunConfig) -> tuple[np.ndarray, np.ndarray]:
    """Starting (gamma, beta) per QAOARunConfig.initialization strategy."""
    p = config.reps
    if config.initialization == "zeros":
        return np.zeros(p), np.zeros(p)
    if config.initialization == "random":
        rng = np.random.default_rng(0)
        return rng.uniform(0, math.pi, p), rng.uniform(0, math.pi, p)
    # "ramp" (default): TQA-style linear schedule — gamma ramps up, beta down.
    frac = (np.arange(p) + 0.5) / p
    dt = 0.7
    return frac * dt, (1.0 - frac) * dt


def brute_force_maxcut() -> int:
    """Exact MaxCut by enumerating all 2^n bipartitions (n is tiny here)."""
    best = 0
    for assignment in itertools.product((0, 1), repeat=NUM_VERTICES):
        cut = sum(1 for i, j in EDGES if assignment[i] != assignment[j])
        best = max(best, cut)
    return best


def main() -> None:
    runner = BenchmarkRunner()
    runner.register(ToyStatevectorAdapter(), name="toy")

    cost = maxcut_cost_observable()
    config = QAOARunConfig(reps=3, mixer="x", optimizer="COBYLA",
                           max_iterations=200, initialization="ramp")

    print("Step 1 — the problem: MaxCut on C5")
    print("-" * 44)
    print(f"  {NUM_VERTICES} vertices, edges = {EDGES}")
    best_cut = brute_force_maxcut()
    # <H_C> = (#uncut - #cut); its minimum corresponds to the maximum cut.
    min_cost = exact_ground_state_energy(cost)
    print(f"  brute-force MaxCut     = {best_cut} of {len(EDGES)} edges")
    print(f"  min <H_C> (exact)      = {min_cost:.4f}")

    print("\nStep 2 — the algorithm: QAOA")
    print("-" * 44)
    print(f"  layers p               = {config.reps}")
    print(f"  mixer / optimizer      = {config.mixer} / {config.optimizer}")
    print(f"  angle init             = {config.initialization}")

    # Each energy evaluation binds the current angles into a fresh circuit and
    # runs it; every evaluation is persisted as a full BenchmarkRecord, so the
    # stored history *is* the QAOA convergence trace.
    history: list[float] = []

    def energy(params: np.ndarray) -> float:
        gammas, betas = params[: config.reps], params[config.reps :]
        circuit = CircuitSpec.from_openqasm3(
            qaoa_maxcut_qasm(gammas, betas),
            num_qubits=NUM_VERTICES,
            observables=[cost],
        )
        record = runner.run(
            circuit, "toy",
            options=ExecutionOptions(qaoa_run_config=config),   # shots=None -> exact
            vqa=VQAConfig(problem_type="optimization", algorithm="QAOA",
                          optimizer=config.optimizer),
            tags=["qaoa", "maxcut"],
        )
        value = record.result.expectation_values[0].value
        history.append(value)
        return value

    g0, b0 = initial_angles(config)
    x0 = np.concatenate([g0, b0])

    print("\nStep 3 — optimize the 2*p angles")
    print("-" * 44)
    res = minimize(energy, x0, method=config.optimizer,
                   options={"maxiter": config.max_iterations})

    print(f"  evaluations            = {len(history)}")
    print(f"  QAOA <H_C>             = {res.fun:.4f}")

    print("\nStep 4 — read off the cut")
    print("-" * 44)
    # Cut value from the objective: #cut = (#edges - <H_C>) / 2.
    qaoa_cut = (len(EDGES) - res.fun) / 2.0
    approx_ratio = qaoa_cut / best_cut
    print(f"  QAOA expected cut      = {qaoa_cut:.3f}")
    print(f"  optimal cut            = {best_cut}")
    print(f"  approximation ratio    = {approx_ratio:.3f}")
    print(f"  fraction of exact min  = {res.fun / min_cost:.3f}"
          "  (1.000 = QAOA reached the exact optimum)")

    print("\nSwap ToyStatevectorAdapter for AerAdapter (or hardware) and set "
          "shots=... in ExecutionOptions to run the same loop on real samples.")


if __name__ == "__main__":
    main()
