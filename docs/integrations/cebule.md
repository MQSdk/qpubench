# Cebule SDK integration

[Cebule SDK](https://docs.mqs.dk/sections/section_014_quantum_computing/) (MQS) provides four cloud quantum-chemistry task types. qpubench models each task's input and output as typed Pydantic schemas in `src/qpubench/schemas/cebule.py`.

---

## Task types

| `CebuleTaskType` | What it does |
|---|---|
| `MOL_MAP` | Map a molecular geometry to a qubit Hamiltonian via constraint-based encoding |
| `QASM_GEN` | Generate OpenQASM 2.0 measurement circuits for a Hamiltonian |
| `TN_QC_OPT` | Tensor-network + quantum circuit hybrid VQE optimisation |
| `COVO` | Correlation-optimised virtual orbital pre-processing |

---

## Session pattern

```python
import mqsdk, os

session = mqsdk.Cebule(os.environ["EMAIL"], os.environ["PASSWORD"])
task    = session.cebule.create_task(title, TaskType.MOL_MAP, input_data)
```

Set credentials in `.env` and reference them via `BackendSpec.cebule()`:

```python
from qpubench.schemas import BackendSpec
backend = BackendSpec.cebule(email_ref="EMAIL", password_ref="PASSWORD")
```

---

## MOL_MAP

Maps a molecular geometry to a qubit Hamiltonian with constraint-based encoding.

```python
from qpubench.schemas import MolMapInput, MolMapResult, MolecularGeometry

inp = MolMapInput(molecule=MolecularGeometry(
    geometry=[0.0, 0.0, 0.0, 0.0, 0.0, 0.7414],   # flat Å (x0,y0,z0,x1,y1,z1)
    symbols=["H", "H"],
    basis="sto3g",
))

# After calling session.cebule.create_task(…):
result = MolMapResult(
    mapped_hamiltonian=[[…]],
    hf_state=[1, 1, 0, 0],
    mapping_matrix=[[…]],
    num_qubits=4,
)
```

---

## QASM_GEN

Generates OpenQASM 2.0 circuits for Hamiltonian measurement, one circuit per Pauli grouping.

```python
from qpubench.schemas import QASMGenInput, QASMGenResult

inp = QASMGenInput(operator=[[…]], include_state_circuit=True)

result = QASMGenResult(
    circuit_files=["OPENQASM 2.0; …", "OPENQASM 2.0; …"],
    postprocessing_instructions=[[1.0, -0.5], [-0.5, 1.0]],
)

# Convert each circuit to a CircuitSpec (QASM2)
specs = result.to_circuit_specs(num_qubits=4)

# Or wrap caller-supplied QASM3 transpilations
qasm3_specs = result.to_openqasm3_circuit_specs(num_qubits=4, qasm3_sources=[…])
```

---

## TN_QC_OPT

Hybrid tensor-network + quantum circuit VQE.

```python
from qpubench.schemas import TNQCOptInput, TNQCOptResult, SparsePauliObservable

inp = TNQCOptInput(
    h_coeff_values=[0.5, -0.3, 0.1],
    h_operators=["Z0", "X0 Z1", "Y1"],
    n_iterations=100,
    n_layers_network=3,
    n_layers_circuit=3,
    opt_method="BFGS",
    backend="lightning.qubit",
)

result = TNQCOptResult(
    vqe_energy=-1.136,
    phi=[0.1, -0.2, 0.3],       # optimised circuit parameters U(φ)
    theta=[0.5, -0.1, 0.2],     # optimised TN parameters U(θ)
    h_tn_opt_qubit=[0.5, -0.3, 0.1],
    qubit_operators=["Z0", "X0 Z1", "Y1"],
)

# Convert to SparsePauliObservable
obs = result.to_sparse_pauli_observable(num_qubits=2)
```

Wire `AlgorithmSpec` fields to the TN_QC_OPT parameters:

```python
from qpubench.schemas import AlgorithmSpec

spec = AlgorithmSpec(
    name="TN_QC_OPT",
    optimizer="BFGS",
    opt_maxiter=100,
    n_layers_network=3,
    n_layers_circuit=3,
)
```

---

## COVO

Correlation-optimised virtual orbitals for plane-wave periodic systems.

```python
from qpubench.schemas import COVOInput, COVOResult

inp = COVOInput(
    geometry=[0.0, 0.0, 0.0, 0.0, 0.0, 1.23],
    symbols=["B", "H"],
    cell_size=10.0,
    cutoff=200.0,
    n_virtual_orbitals=4,
)

result = COVOResult(
    one_electron_integrals=[[…]],
    two_electron_integrals=[[[[…]]]],
    hf_energy=-24.6,
    fci_energy=-24.7757,
    vqe_energy=-24.75,
    hamiltonian=[[…]],
)

print(f"Correlation energy: {result.correlation_energy:.4f} Ha")
print(f"VQE error vs FCI:   {result.vqe_error:.4f} Ha")
```

Record `fci_energy` in `VQAConfig`:

```python
from qpubench.schemas import VQAConfig

vqa = VQAConfig(
    problem_type="chemistry",
    molecule="BH",
    hf_energy=-24.6,
    fci_energy=-24.7757,      # from COVOResult
    final_eigenvalue=-24.75,
)
```

---

## `MolecularGeometry` vs `XenakisMolecule`

Both represent molecular geometries but use different coordinate layouts:

| Type | Coordinates | Usage |
|---|---|---|
| `MolecularGeometry` | Flat list: `[x0, y0, z0, x1, y1, z1, …]` | Cebule MOL_MAP, COVO |
| `XenakisMolecule` | List of tuples: `[(x0, y0, z0), (x1, y1, z1), …]` | Xenakis YAML config |

Convert between them:

```python
# XenakisMolecule → MolecularGeometry
from qpubench.schemas import MolecularGeometry, XenakisMolecule

xmol = XenakisMolecule(name="H2", symbols=["H","H"],
                        coordinates_angstrom=[(0,0,0), (0,0,0.7414)])
geom = MolecularGeometry(
    geometry=xmol.flat_coordinates(),
    symbols=xmol.symbols,
    basis=xmol.basis,
    multiplicity=xmol.multiplicity,
    charge=xmol.charge,
)
```

---

## OpenQASM 3.0 and QASM_GEN output

Cebule's `QASM_GEN` task outputs OpenQASM **2.0** strings. To use them with QASM3-aware backends, transpile each circuit and wrap with `CircuitSpec.from_openqasm3()`:

```python
from qpubench.schemas import CircuitSpec

# After transpiling QASM2 → QASM3 with your preferred tool
qasm3_source = transpile_to_qasm3(result.circuit_files[0])
spec = CircuitSpec.from_openqasm3(qasm3_source, num_qubits=4)

# Check
assert spec.openqasm3 is not None
assert spec.format.value == "qasm3"
```

The `QASMGenResult.to_openqasm3_circuit_specs(num_qubits, qasm3_sources)` helper wraps this in bulk.
