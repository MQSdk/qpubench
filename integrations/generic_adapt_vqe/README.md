# Generic ADAPT-VQE engine

Package-agnostic `AlgorithmFamily.ADAPT_VQE` implementation — pure Python +
[scipy](https://scipy.org/) for the classical optimizer, no vendor quantum
SDK. Delegates every energy evaluation to any qpubench `BackendAdapter`, the
same pattern `integrations/qforte/ExternalEvalAlgorithmAdapter` established
for QForte, generalized so QForte itself isn't required.

> **See [docs/vqa.md](../../docs/vqa.md) for the overall VQA picture** — how
> VQE and ADAPT-VQE relate and the package-agnostic `AdaptVQERunConfig`
> contract this engine consumes. This README covers the engine internals.

Used by `integrations/ibm_qiskit_adapt_vqe/` and
`integrations/microsoft_qdk_adapt_vqe/`, which are thin wrappers over this
engine differing only in `BackendSpec` naming/defaults.

## Files

| File | Purpose |
|------|---------|
| `pool.py` | Fermionic singles+doubles excitation pool, Jordan-Wigner mapped to `SparsePauliObservable` |
| `circuit_synthesis.py` | Pauli-string exponential `exp(-i·angle·P)` → OpenQASM 3.0 |
| `engine.py` | `GenericAdaptVQEEngine` — ansatz growth loop, gradient screening, optimizer |

## Correctness

Nothing here is taken on faith. `pool.py`'s Jordan-Wigner formulas and
`circuit_synthesis.py`'s gate sequence are both independently verified
against dense-matrix ground truth (creation/annihilation operator
construction; `scipy.linalg.expm`) in `tests/test_generic_adapt_vqe.py` —
run it with `pip install 'qpubench[adapt_vqe]'`.

## Design choices worth knowing

- **Gradient screening uses central finite differences**, not an analytic
  commutator. This reuses the already-verified circuit-exponential
  construction directly instead of adding a second from-scratch Pauli-algebra
  routine (commutator expansion) with its own correctness risk. Use
  `shots=None` (statevector) in `energy_options` — shot noise makes finite
  differences unreliable at small epsilon.
- **Spin-orbital convention**: qubit index == spin-orbital index; occupied =
  `[0, num_electrons)`, virtual = `[num_electrons, num_qubits)`. Map your own
  orbital ordering (interleaved alpha/beta, blocked, etc.) onto this before
  calling in.
- **Not molecular electronic structure**: this engine takes an
  already-built qubit Hamiltonian (`SparsePauliObservable`). Build it with
  whichever chemistry pipeline you like (e.g. `schemas/microsoft_qdk.py`'s
  `QChemPipelineSpec`) before handing it to `GenericAdaptVQEEngine` or the
  two adapters built on it.

## Quick start

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
