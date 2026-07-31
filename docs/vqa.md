# Variational quantum algorithms (VQE, ADAPT-VQE, QAOA)

Variational quantum algorithms (VQAs) find the lowest eigenvalue of a Hamiltonian by preparing a parametrized quantum state (an *ansatz*), measuring its energy, and letting a classical optimizer adjust the parameters to drive that energy down. This page covers the ways VQAs run in qpubench: plain VQE as a loop over ordinary circuit runs (any registered backend, your optimizer), QAOA as the same kind of loop applied to a combinatorial cost Hamiltonian, and self-driving implementations like ADAPT-VQE behind a package-agnostic contract, so you can swap the underlying engine (QForte, a from-scratch Qiskit-convention engine, or a QDK/Azure-flavored one) without changing your run configuration.

## The family

| Algorithm | `AlgorithmFamily` | Ansatz | What varies |
|---|---|---|---|
| **VQE** | `VQE` (UCC-type ansätze and the ExcitationSolve optimizer are choices *under* it; a hand-rolled circuit-loop run needs no tag) | Fixed, chosen up front (e.g. UCCSD) | Only the parameters are optimized |
| **QAOA** | `QAOA` | Fixed: p alternating cost/mixer layers | Only the 2·p angles (γ, β) are optimized, over a combinatorial cost Hamiltonian |
| **ADAPT-VQE** | `ADAPT_VQE` | Grown one operator at a time | The ansatz *structure* adapts to the problem, then parameters are optimized |
| UCC-PQE / SPQE | `UCC_PQE` / `SPQE` | Fixed / adaptive | Projective (residual) equations instead of energy minimization |

The distinction that matters for benchmarking: in plain VQE the ansatz circuit is fixed before the run, whereas ADAPT-VQE **builds its own circuit** as it goes, adding whichever pool operator has the largest energy gradient each macro-iteration until that gradient falls below a threshold. The two therefore take different execution paths through qpubench:

- **Plain VQE is not an adapter of any kind.** It is a classical optimization loop that *uses* a `BackendAdapter`: each energy evaluation binds the current parameters into the ansatz and runs it as an ordinary circuit. The backend, simulator or hardware, is whatever adapter you registered; the optimizer and the loop live in your code (see the next section).
- **ADAPT-VQE implementations are `AlgorithmAdapter`s**: the library receives a problem specification (a molecule), generates circuits internally, and drives its own loop; qpubench records the outcome.

See [Backends & adapters](backends.md) for the two protocols. `AlgorithmFamily` tags exist for the library-driven algorithms so that runs of "the same algorithm" from different libraries can be compared, including `VQE` for a library-driven fixed-ansatz VQE such as QForte's `UCCNVQE` (there UCC is the *ansatz* choice, not a family of its own). A plain, hand-rolled VQE loop needs no family tag, since it is fully described by its circuit, observable, and `VQAConfig` metadata, though you may set `family=VQE` on it if you want it to group with library-driven VQE runs in the store.

## Running plain VQE

A VQE run needs four ingredients, and qpubench keeps them separate:

1. **A parametrized ansatz, with its Hamiltonian**: a `CircuitSpec` with named `parameters` and the Hamiltonian attached as `observables`. The two are conceptually distinct (the ansatz prepares the state; the Hamiltonian is the observable whose energy you measure), but they travel together on one `CircuitSpec`. Keep this *unbound*: it is the reusable master copy.
2. **A backend**: any registered `BackendAdapter` (Aer, PennyLane Lightning, IBM hardware, …). This is where "which machine runs it" is decided.
3. **An initial guess**: a plain vector of starting parameter values, separate from the circuit.
4. **A classical optimizer**: e.g. `scipy.optimize.minimize`. qpubench deliberately does not bundle one; the loop is a few lines and any optimizer works.

Each energy evaluation binds the current parameters into a *copy* of the ansatz (`.bind()` never mutates the master) and runs it; every evaluation is persisted as a full `BenchmarkRecord`, so the stored history *is* the convergence trace:

```python
import numpy as np
from scipy.optimize import minimize
from qpubench import BenchmarkRunner, VQAConfig
from qpubench.backends import AerAdapter        # pip install "qpubench[qiskit]"

runner = BenchmarkRunner()
runner.register(AerAdapter(), name="aer")       # 2. the backend: swap for hardware here

# 1. ansatz: unbound CircuitSpec with parameters=["theta_0", ...] and the
#    Hamiltonian attached as ansatz.observables

def energy(theta: np.ndarray) -> float:
    bound = ansatz.bind({name: float(v) for name, v in zip(ansatz.parameters, theta)})
    # VQAConfig only *labels* this run for the record; it records what was
    # run (problem, molecule, ansatz/optimizer names) so records are
    # filterable later. It sets no execution parameters: the actual values
    # are the bound `theta` above, not anything here.
    record = runner.run(bound, "aer",
        vqa=VQAConfig(problem_type="chemistry", molecule="H2", basis="sto-3g",
                      ansatz="my_ansatz", optimizer="BFGS"))
    return record.result.expectation_values[0].value

x0 = np.zeros(len(ansatz.parameters))           # 3. initial guess: data, not circuit
res = minimize(energy, x0, method="BFGS")       # 4. the optimizer
```

Two conventions to note. First, the input to a VQE workflow is the *parametrized* circuit plus a separate initial guess; you never store parameter values in your master ansatz; binding happens per evaluation, and the bound copy inside each `BenchmarkRecord` is what makes that record exactly reproducible later. Second, changing where the energies are evaluated (statevector simulator, shot-based sampling, real hardware) means re-registering a different adapter and changing the backend name in `runner.run()`; nothing about the ansatz, guess, or optimizer changes.

For building the Hamiltonian to attach as `ansatz.observables`, see [Examples: Real Hamiltonian sources](../examples/README.md#real-hamiltonian-sources). For UCC-specific VQE where a library drives the loop for you (a full chemistry stack behind it), see the SlowQuant integration (`integrations/slowquant/`, an `AlgorithmAdapter` for `AlgorithmFamily.VQE`-family runs with a UCC ansatz).

## Running QAOA

QAOA is the *same execution path as plain VQE*, a classical optimization loop over ordinary circuit runs with no `AlgorithmAdapter`, pointed at a **combinatorial** cost Hamiltonian instead of a molecular one. It takes the exact same four ingredients (ansatz, backend, initial guess, optimizer), with two specifics:

- **The ansatz is not free-form.** It is a fixed structure of `p` alternating layers: a *cost* unitary `exp(-iγ·H_C)` followed by a *mixer* unitary `exp(-iβ·H_M)`, repeated `p` times, over an initial `|+⟩^n` state. Only the `2·p` angles `(γ, β)` are optimized. For MaxCut on a graph the cost is `H_C = Σ_{(i,j)∈E} Z_iZ_j`, and *minimizing* `⟨H_C⟩` maximizes the number of cut edges.
- **`QAOARunConfig` names the knobs.** `p` (`reps`), the `mixer`, the `optimizer`, and the angle `initialization` strategy live in `QAOARunConfig` (on `ExecutionOptions.qaoa_run_config`), the package-agnostic contract, the QAOA counterpart of `AdaptVQERunConfig`. The run is *labelled* by a `VQAConfig` with `problem_type="optimization"` and `algorithm="QAOA"`. See [Algorithms & `AlgorithmSpec`](algorithm_spec.md#vqaconfig--runconfig) for why the knobs are not fields on `VQAConfig`.

```python
import numpy as np
from scipy.optimize import minimize
from qpubench import BenchmarkRunner, ExecutionOptions, QAOARunConfig, VQAConfig
from qpubench.schemas.circuit import CircuitSpec

runner = BenchmarkRunner()
runner.register(AerAdapter(), name="aer")            # or any registered backend

config = QAOARunConfig(reps=3, mixer="x", optimizer="COBYLA")   # p = 3 layers
cost   = maxcut_cost_observable(edges)               # SparsePauliObservable: Σ Z_iZ_j

def energy(params: np.ndarray) -> float:
    gammas, betas = params[:config.reps], params[config.reps:]
    circuit = CircuitSpec.from_openqasm3(              # p cost+mixer layers, angles bound
        qaoa_maxcut_qasm(edges, gammas, betas), num_qubits=n, observables=[cost])
    record = runner.run(circuit, "aer",
        options=ExecutionOptions(qaoa_run_config=config),
        vqa=VQAConfig(problem_type="optimization", algorithm="QAOA",
                      optimizer=config.optimizer))
    return record.result.expectation_values[0].value  # ⟨H_C⟩

x0  = np.zeros(2 * config.reps)                        # 2·p angles
res = minimize(energy, x0, method=config.optimizer)
best_cut = (len(edges) - res.fun) / 2                  # read the cut off the objective
```

Everything else is identical to plain VQE: each evaluation binds the current angles into a fresh circuit, runs it as an ordinary `CircuitSpec`, and is persisted as a full `BenchmarkRecord`, so the stored history *is* the QAOA convergence trace. Swapping simulator for shot-based sampling or real hardware means re-registering a different adapter and setting `shots=...`, nothing more. A complete, genuinely-executing version (graph definition, `qaoa_maxcut_qasm`, brute-force cross-check, approximation ratio) is in `examples/guides/qaoa_maxcut.py`.

## The package-agnostic ADAPT-VQE contract (library-driven runs)

An ADAPT-VQE run is described by two objects, neither tied to any vendor SDK:

- **`AlgorithmSpec`** carries identity only: `name` + `AlgorithmFamily.ADAPT_VQE`.
- **`AdaptVQERunConfig`** (in `schemas/execution.py`) carries the hyperparameters every implementation accepts:

| Field | Meaning | Default |
|---|---|---|
| `pool_type` | Operator pool: `"SD"`, `"GSD"`, `"SDTQ"`, `"sa_SD"` | `"SD"` |
| `optimizer` | Classical optimizer name (each adapter maps it onto its own set) | `"BFGS"` |
| `gradient_threshold` | Ansatz-growth stop: ‖gradient‖ below this ends growth | `1e-2` |
| `energy_threshold` | Micro-optimizer (parameter-fit) convergence | `1e-5` |
| `max_macro_iterations` | Ansatz-growth steps / depth cap | `20` |
| `max_micro_iterations` | Optimizer steps per macro-iteration | `200` |
| `use_analytic_gradient` | Analytic gradient vs. finite differences | `True` |

Because the config is package-agnostic, the *same* `AdaptVQERunConfig` runs against any registered ADAPT-VQE adapter; register a different one under a different name and compare the resulting `BenchmarkRecord`s directly:

```python
from qpubench import (
    AdaptVQERunConfig, AlgorithmFamily, AlgorithmSpec, BenchmarkRunner, ExecutionOptions,
)
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.primitives import CircuitFormat

# The "circuit" is a problem description: a molecule file, not gates
mol = CircuitSpec(num_qubits=0, format=CircuitFormat.MOLECULE_JSON,
                  serialized="/path/to/He-ccpvdz.json")

options = ExecutionOptions(
    algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
    adapt_vqe_run_config=AdaptVQERunConfig(pool_type="SD", optimizer="BFGS",
                                    gradient_threshold=1e-4, max_macro_iterations=20),
)

runner = BenchmarkRunner()
# register QForteAlgorithmAdapter from integrations/qforte/ ...
record = runner.run(mol, "qforte", options)
# ... or the exact same options against a different implementation:
# register IBMQiskitAdaptVQEAdapter from integrations/ibm_qiskit_adapt_vqe/
record = runner.run(mol, "ibm_qiskit_adapt_vqe", options)
```

Here `ExecutionOptions` is built explicitly because the run needs more than a shot count: which algorithm to run and its hyperparameters. The result comes back in the same `BenchmarkRecord` format as any single-circuit run: `record.vqa` (a `VQAConfig`) holds the experiment inputs, and `record.vqa_result` (a `VQAResult`) holds the computed outputs, including the derived chemistry metrics (`energy_error`, `chemical_accuracy`) when `final_eigenvalue` and a reference such as `ground_truth` are present.

## The three interchangeable ADAPT-VQE engines

`AlgorithmFamily.ADAPT_VQE` has three implementations that share the package-agnostic config. Pick by what you have installed and where you want energies evaluated:

| Adapter | Location | Engine | Needs |
|---|---|---|---|
| `QForteAlgorithmAdapter` | `integrations/qforte/` | QForte's native C++ statevector | `pip install qforte` (C++ compiler) |
| `IBMQiskitAdaptVQEAdapter` | `integrations/ibm_qiskit_adapt_vqe/` | `integrations/generic_adapt_vqe/`, pure Python + scipy | `pip install 'qpubench[adapt_vqe]'` |
| `MicrosoftQDKAdaptVQEAdapter` | `integrations/microsoft_qdk_adapt_vqe/` | Same generic engine, QDK/Azure `BackendSpec` defaults | `pip install 'qpubench[adapt_vqe]'` |

### QForte engine

QForte's pybind11 object model (Circuit, Gate, QubitOperator, …) and its Algorithm/AnsatzAlgorithm/ADAPTVQE attribute surface are modeled as typed schemas in `schemas/mirrors/evangelistalab_qforte.py`, with no ad-hoc `getattr()` scraping of private attributes. `QForteAlgorithmConfig` wraps the shared `AdaptVQERunConfig` plus QForte-only extras (`diis_max_dim`, `use_cumulative_thresh`, `add_equiv_ops`). The adapter also ships an `ExternalEvalAlgorithmAdapter` that routes every energy evaluation through any qpubench `BackendAdapter` (Aer, IBM, …) instead of QForte's own simulator. See `integrations/qforte/README.md` for the file-by-file layout.

### Generic engine (Qiskit / QDK adapters)

`integrations/generic_adapt_vqe/` is a package-agnostic engine: pure Python + [scipy](https://scipy.org/) for the classical optimizer, no vendor quantum SDK. It implements from scratch:

- **`pool.py`**: the fermionic singles+doubles excitation pool, Jordan-Wigner mapped to `SparsePauliObservable`.
- **`circuit_synthesis.py`**: Pauli-string exponential `exp(-i·angle·P)` synthesized to OpenQASM 3.0.
- **`engine.py`**: `GenericAdaptVQEEngine`, the ansatz-growth loop, gradient screening, and optimizer.

Every energy evaluation is delegated to whichever `BackendAdapter` you pass as the energy oracle, so the same engine drives the IBM/Qiskit and QDK/Azure adapters; they differ only in `BackendSpec` naming and defaults. Nothing here is taken on faith: `pool.py`'s Jordan-Wigner formulas and `circuit_synthesis.py`'s gate sequence are both independently verified against dense-matrix ground truth (creation/annihilation operator construction; `scipy.linalg.expm`) in `tests/test_generic_adapt_vqe.py`.

Two design choices worth knowing:

- **Gradient screening uses central finite differences**, not an analytic commutator; it reuses the already-verified circuit-exponential construction directly rather than adding a second from-scratch Pauli-algebra routine. Use `shots=None` (statevector) in the energy options; shot noise makes finite differences unreliable at small epsilon.
- **Spin-orbital convention**: qubit index == spin-orbital index; occupied = `[0, num_electrons)`, virtual = `[num_electrons, num_qubits)`. Map your own orbital ordering onto this before calling in.
- **It is not a chemistry pipeline**: the engine takes an already-built qubit Hamiltonian (`SparsePauliObservable`). Build it with whichever pipeline you like, `schemas/mirrors/microsoft_qdk.py`'s `QChemPipelineSpec` or `qpubench.hamiltonian_sources` (HamLib / PennyLane / ab initio), before handing it over.

Direct use of the engine (bypassing the adapters):

```python
from qpubench import StubGateAdapter
from qpubench.schemas.execution import AdaptVQERunConfig
from generic_adapt_vqe.engine import GenericAdaptVQEEngine

engine = GenericAdaptVQEEngine(
    hamiltonian=my_qubit_hamiltonian,   # SparsePauliObservable
    num_qubits=4,
    num_electrons=2,
    energy_backend=StubGateAdapter(seed=0),   # or a real backend
    config=AdaptVQERunConfig(pool_type="SD", optimizer="BFGS"),
)
result, vqa, vqa_result = engine.run()
```

## Where to go next

- Runnable examples: `examples/guides/qaoa_maxcut.py` (QAOA MaxCut, end to end), `examples/guides/vqe_calculator.py` (assemble a calculator), `examples/guides/ground_state_energy_problem.py` (define the problem), `examples/demos/adapt_vqe_convergence_study.py` (sweep the gradient threshold), and `examples/qforte_vqe_benchmark.py` (three QForte methods on He/cc-pVDZ).
- Building real Hamiltonians to feed a VQA: [Examples: Real Hamiltonian sources](../examples/README.md#real-hamiltonian-sources).
- The record and metadata schemas: [`record` / `VQAConfig`](schemas.md#record), [`execution` / `AdaptVQERunConfig` / `QAOARunConfig`](schemas.md#execution).
- Writing your own algorithm adapter: [Backends & adapters](backends.md#writing-a-new-algorithmadapter) and the [integrations directory](../integrations/README.md).
