# Variational quantum algorithms (VQE, ADAPT-VQE)

Variational quantum algorithms (VQAs) find the lowest eigenvalue of a Hamiltonian by preparing a parametrized quantum state (an *ansatz*), measuring its energy, and letting a classical optimizer adjust the parameters to drive that energy down. VQE and ADAPT-VQE are two members of this family, and qpubench models both under one package-agnostic contract so you can swap the underlying engine — QForte, a from-scratch Qiskit-convention engine, or a QDK/Azure-flavored one — without changing your run configuration.

## The family

| Algorithm | `AlgorithmFamily` | Ansatz | What varies |
|---|---|---|---|
| **VQE** (incl. UCC-VQE) | `UCC_VQE` | Fixed, chosen up front (e.g. UCCSD) | Only the parameters are optimized |
| **ADAPT-VQE** | `ADAPT_VQE` | Grown one operator at a time | The ansatz *structure* adapts to the problem, then parameters are optimized |
| UCC-PQE / SPQE | `UCC_PQE` / `SPQE` | Fixed / adaptive | Projective (residual) equations instead of energy minimization |

The distinction that matters for benchmarking: in plain VQE the circuit is fixed before the run, whereas ADAPT-VQE **builds its own circuit** as it goes, adding whichever pool operator has the largest energy gradient each macro-iteration until that gradient falls below a threshold. That is why VQE fits qpubench's `BackendAdapter` protocol (you hand it a circuit) while ADAPT-VQE fits the `AlgorithmAdapter` protocol (the library generates circuits from a problem spec and drives its own loop). See [Backends & adapters](backends.md) for the two protocols.

## The package-agnostic contract

An ADAPT-VQE run is described by two objects, neither tied to any vendor SDK:

- **`AlgorithmSpec`** carries identity only: `name` + `AlgorithmFamily.ADAPT_VQE`.
- **`AdaptVQEConfig`** (in `schemas/execution.py`) carries the hyperparameters every implementation accepts:

| Field | Meaning | Default |
|---|---|---|
| `pool_type` | Operator pool: `"SD"`, `"GSD"`, `"SDTQ"`, `"sa_SD"` | `"SD"` |
| `optimizer` | Classical optimizer name (each adapter maps it onto its own set) | `"BFGS"` |
| `gradient_threshold` | Ansatz-growth stop: ‖gradient‖ below this ends growth | `1e-2` |
| `energy_threshold` | Micro-optimizer (parameter-fit) convergence | `1e-5` |
| `max_macro_iterations` | Ansatz-growth steps / depth cap | `20` |
| `max_micro_iterations` | Optimizer steps per macro-iteration | `200` |
| `use_analytic_gradient` | Analytic gradient vs. finite differences | `True` |

Because the config is package-agnostic, the *same* `AdaptVQEConfig` runs against any registered ADAPT-VQE adapter — register a different one under a different name and compare the resulting `BenchmarkRecord`s directly:

```python
from qpubench import (
    AdaptVQEConfig, AlgorithmFamily, AlgorithmSpec, BenchmarkRunner, ExecutionOptions,
)
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.primitives import CircuitFormat

# The "circuit" is a problem description: a molecule file, not gates
mol = CircuitSpec(num_qubits=0, format=CircuitFormat.MOLECULE_JSON,
                  serialized="/path/to/He-ccpvdz.json")

options = ExecutionOptions(
    algorithm_spec=AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
    adapt_vqe_config=AdaptVQEConfig(pool_type="SD", optimizer="BFGS",
                                    gradient_threshold=1e-4, max_macro_iterations=20),
)

runner = BenchmarkRunner()
# register QForteAlgorithmAdapter from integrations/qforte/ ...
record = runner.run(mol, "qforte", options)
# ... or the exact same options against a different implementation:
# register IBMQiskitAdaptVQEAdapter from integrations/ibm_qiskit_adapt_vqe/
record = runner.run(mol, "ibm_qiskit_adapt_vqe", options)
```

Here `ExecutionOptions` is built explicitly because the run needs more than a shot count — which algorithm to run and its hyperparameters. The result comes back in the same `BenchmarkRecord` format as any single-circuit run, and its `record.vqa` (a `VQAConfig`) carries the derived chemistry metrics (`energy_error`, `chemical_accuracy`) when you supply `final_eigenvalue` and `ground_truth`.

## The three interchangeable ADAPT-VQE engines

`AlgorithmFamily.ADAPT_VQE` has three implementations that share the package-agnostic config. Pick by what you have installed and where you want energies evaluated:

| Adapter | Location | Engine | Needs |
|---|---|---|---|
| `QForteAlgorithmAdapter` | `integrations/qforte/` | QForte's native C++ statevector | `pip install qforte` (C++ compiler) |
| `IBMQiskitAdaptVQEAdapter` | `integrations/ibm_qiskit_adapt_vqe/` | `integrations/generic_adapt_vqe/` — pure Python + scipy | `pip install 'qpubench[adapt_vqe]'` |
| `MicrosoftQDKAdaptVQEAdapter` | `integrations/microsoft_qdk_adapt_vqe/` | Same generic engine, QDK/Azure `BackendSpec` defaults | `pip install 'qpubench[adapt_vqe]'` |

### QForte engine

QForte's pybind11 object model (Circuit, Gate, QubitOperator, …) and its Algorithm/AnsatzAlgorithm/ADAPTVQE attribute surface are modeled as typed schemas in `schemas/evangelistalab_qforte.py` — no ad-hoc `getattr()` scraping of private attributes. `QForteAlgorithmConfig` wraps the shared `AdaptVQEConfig` plus QForte-only extras (`diis_max_dim`, `use_cumulative_thresh`, `add_equiv_ops`). The adapter also ships an `ExternalEvalAlgorithmAdapter` that routes every energy evaluation through any qpubench `BackendAdapter` (Aer, IBM, …) instead of QForte's own simulator. See `integrations/qforte/README.md` for the file-by-file layout.

### Generic engine (Qiskit / QDK adapters)

`integrations/generic_adapt_vqe/` is a package-agnostic engine — pure Python + [scipy](https://scipy.org/) for the classical optimizer, no vendor quantum SDK. It implements from scratch:

- **`pool.py`** — the fermionic singles+doubles excitation pool, Jordan-Wigner mapped to `SparsePauliObservable`.
- **`circuit_synthesis.py`** — Pauli-string exponential `exp(-i·angle·P)` synthesized to OpenQASM 3.0.
- **`engine.py`** — `GenericAdaptVQEEngine`: the ansatz-growth loop, gradient screening, and optimizer.

Every energy evaluation is delegated to whichever `BackendAdapter` you pass as the energy oracle, so the same engine drives the IBM/Qiskit and QDK/Azure adapters — they differ only in `BackendSpec` naming and defaults. Nothing here is taken on faith: `pool.py`'s Jordan-Wigner formulas and `circuit_synthesis.py`'s gate sequence are both independently verified against dense-matrix ground truth (creation/annihilation operator construction; `scipy.linalg.expm`) in `tests/test_generic_adapt_vqe.py`.

Two design choices worth knowing:

- **Gradient screening uses central finite differences**, not an analytic commutator — it reuses the already-verified circuit-exponential construction directly rather than adding a second from-scratch Pauli-algebra routine. Use `shots=None` (statevector) in the energy options; shot noise makes finite differences unreliable at small epsilon.
- **Spin-orbital convention**: qubit index == spin-orbital index; occupied = `[0, num_electrons)`, virtual = `[num_electrons, num_qubits)`. Map your own orbital ordering onto this before calling in.
- **It is not a chemistry pipeline**: the engine takes an already-built qubit Hamiltonian (`SparsePauliObservable`). Build it with whichever pipeline you like — `schemas/microsoft_qdk.py`'s `QChemPipelineSpec`, or `qpubench.hamiltonian_sources` (HamLib / PennyLane / ab initio) — before handing it over.

Direct use of the engine (bypassing the adapters):

```python
from qpubench import StubGateAdapter
from qpubench.schemas.execution import AdaptVQEConfig
from generic_adapt_vqe.engine import GenericAdaptVQEEngine

engine = GenericAdaptVQEEngine(
    hamiltonian=my_qubit_hamiltonian,   # SparsePauliObservable
    num_qubits=4,
    num_electrons=2,
    energy_backend=StubGateAdapter(seed=0),   # or a real backend
    config=AdaptVQEConfig(pool_type="SD", optimizer="BFGS"),
)
result, vqa, vqa_result = engine.run()
```

## Where to go next

- Runnable examples: `examples/guides/vqe_calculator.py` (assemble a calculator), `examples/guides/ground_state_energy_problem.py` (define the problem), `examples/demos/adapt_vqe_convergence_study.py` (sweep the gradient threshold), and `examples/qforte_vqe_benchmark.py` (three QForte methods on He/cc-pVDZ).
- Building real Hamiltonians to feed a VQA: [Examples — Real Hamiltonian sources](../examples/README.md#real-hamiltonian-sources).
- The record and metadata schemas: [`record` / `VQAConfig`](schemas.md#record), [`execution` / `AdaptVQEConfig`](schemas.md#execution).
- Writing your own algorithm adapter: [Backends & adapters](backends.md#writing-a-new-algorithmadapter) and the [integration guide](../INTEGRATION_GUIDE.md).
