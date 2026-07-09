# QCSchema / QCElemental / PennyLane integration

qpubench harmonizes its quantum chemistry schemas with three interoperable standards in `src/qpubench/schemas/molssi_qcschema.py`.

| Standard | URL | Role |
|---|---|---|
| **QCSchema** | [github.com/MolSSI/QCSchema](https://github.com/MolSSI/QCSchema) | JSON schema standard for quantum chemistry I/O |
| **QCElemental** | [github.com/MolSSI/QCElemental](https://github.com/MolSSI/QCElemental) | Python reference implementation (`qcelemental.models`) |
| **PennyLane qchem** | [pennylane.ai/datasets/collection/qchem](https://pennylane.ai/datasets/collection/qchem) | Molecular Hamiltonians, energies, wavefunctions for benchmark molecules |

The schema bridges three use cases:
1. **Classical reference data** — attach FCI/CCSD(T) energies from QCElemental results to a `QuantumResult` for QPU error benchmarking
2. **Problem specification** — describe the molecular system in QCSchema-standard format for adapter interoperability
3. **PennyLane dataset lookup** — reference a specific PennyLane qchem dataset entry (molecule, basis, bond length) and its precomputed energies

---

## Quick start

```python
from qpubench.schemas.molssi_qcschema import (
    QCMolecule, QCModel, QCDriver,
    QCAtomicInput, QCAtomicResult, QCAtomicResultProperties,
    QCEnergyComponents, QCWavefunctionData,
    PennyLaneMolDataset, QCSchemaRecord,
)
from qpubench.schemas.result import QuantumResult
from qpubench.schemas.primitives import ComputingModel

# Classical FCI reference for H2
mol = QCMolecule(
    symbols=["H", "H"],
    geometry=[0.0, 0.0, -0.7005, 0.0, 0.0, 0.7005],   # Bohr
    name="H2",
)

fci_result = QCAtomicResult(
    molecule=mol,
    driver=QCDriver.ENERGY,
    model=QCModel(method="fci", basis="sto-3g"),
    return_result=-1.1516,
    properties=QCAtomicResultProperties(
        return_energy=-1.1516,
        energy_components=QCEnergyComponents(
            nuclear_repulsion_energy=0.7137,
            fci_total_energy=-1.1516,
        ),
    ),
)

# Attach to a QuantumResult as the reference
result = QuantumResult(
    computing_model=ComputingModel.GATE_BASED,
    qcschema_record=QCSchemaRecord(atomic_result=fci_result),
)
print(result.qcschema_record.reference_energy)   # -1.1516
```

---

## Molecule format

`QCMolecule` follows QCSchema v2 conventions:
- `symbols` — list of element symbols (title case: `"H"`, `"O"`, `"N"`)
- `geometry` — flat list of 3×nat Cartesian coordinates **in Bohr** (x₀,y₀,z₀, x₁,y₁,z₁, …)
- `molecular_charge` — net charge (default 0.0)
- `molecular_multiplicity` — 2S+1 (default 1 = singlet)

This differs from `MoleculeStructureSpec` in `microsoft_qdk.py`, which uses Angström coordinates and a list of `AtomSpec` objects. Both formats coexist — use `QCMolecule` for QCSchema interoperability.

```python
# Water — geometry in Bohr
water = QCMolecule(
    symbols=["O", "H", "H"],
    geometry=[
        0.0000,  0.0000,  0.1173,   # O
        0.0000,  0.7572, -0.4692,   # H
        0.0000, -0.7572, -0.4692,   # H
    ],
    name="H2O",
    connectivity=[(0, 1, 1.0), (0, 2, 1.0)],
)
print(water.formula)    # "H2O"
print(water.num_atoms)  # 3
```

### Fragments and ghost atoms

```python
# Dimer with two fragments
dimer = QCMolecule(
    symbols=["H", "H", "H", "H"],
    geometry=[0.0, 0.0, -2.0,  0.0, 0.0, -0.7,   # fragment 1
              0.0, 0.0,  0.7,  0.0, 0.0,  2.0],   # fragment 2
    fragments=[[0, 1], [2, 3]],
    fragment_charges=[0.0, 0.0],
    fragment_multiplicities=[1, 1],
)
```

---

## Method and basis

```python
from qpubench.schemas.molssi_qcschema import QCModel, QCDriver

# Hartree-Fock with STO-3G
model_hf = QCModel(method="hf", basis="sto-3g")

# CCSD(T) with cc-pVDZ
model_ccsd = QCModel(method="ccsd(t)", basis="cc-pvdz")

# DFT with def2-SVP
model_dft = QCModel(method="b3lyp", basis="def2-svp")

# Driver types
assert QCDriver.ENERGY.value == "energy"
assert QCDriver.GRADIENT.value == "gradient"
```

---

## Atomic computation input / result

```python
from qpubench.schemas.molssi_qcschema import QCAtomicInput, QCAtomicResult, QCProvenance

# Computation specification
inp = QCAtomicInput(
    molecule=mol,
    driver=QCDriver.ENERGY,
    model=QCModel(method="ccsd", basis="cc-pvdz"),
    keywords={"freeze_core": True},
    id="job-001",
)

# Result (after running through, e.g., Psi4 or PySCF)
result = QCAtomicResult(
    molecule=mol,
    driver=QCDriver.ENERGY,
    model=QCModel(method="ccsd", basis="cc-pvdz"),
    return_result=-1.1373,
    properties=QCAtomicResultProperties(
        return_energy=-1.1373,
        energy_components=QCEnergyComponents(
            nuclear_repulsion_energy=0.7137,
            scf_one_electron_energy=-3.5692,
            ccsd_correlation_energy=-0.0200,
            ccsd_total_energy=-1.1373,
        ),
        scf_dipole_moment=[0.0, 0.0, 0.0],
    ),
    success=True,
    provenance=QCProvenance(creator="psi4", version="1.9"),
)
```

### Gradient computation

```python
result_grad = QCAtomicResult(
    molecule=mol,
    driver=QCDriver.GRADIENT,
    model=QCModel(method="hf", basis="sto-3g"),
    return_result=[0.0, 0.0, -0.0521, 0.0, 0.0, 0.0521],   # 3*nat flat gradient
    properties=QCAtomicResultProperties(return_energy=-1.1175),
    success=True,
)
```

---

## Wavefunction data

`QCWavefunctionData` stores SCF orbital coefficients, density matrices, Fock matrices, and overlap integrals as flat (JSON-safe) float lists. This is the primary input for QPU state preparation.

```python
from qpubench.schemas.molssi_qcschema import QCWavefunctionData

# H2 / STO-3G: 2 AOs, 2 MOs
wfn = QCWavefunctionData(
    basis_name="sto-3g",
    nao=2,
    nmo=2,
    # Occupied (σ) and virtual (σ*) MOs — column-major (nao × nmo flat)
    scf_orbitals_a=[0.5489, 0.5489, 0.5489, -0.5489],
    scf_eigenvalues_a=[-0.5783, 0.6695],   # orbital energies (Hartree)
    scf_occupations_a=[2.0, 0.0],
    # Overlap matrix (nao × nao flat)
    overlap_matrix=[1.0, 0.6593, 0.6593, 1.0],
)
```

---

## Geometry optimization

```python
from qpubench.schemas.molssi_qcschema import (
    QCOptimizationInput, QCOptimizationResult,
)

opt_inp = QCOptimizationInput(
    input_specification=QCAtomicInput(
        molecule=mol,
        driver=QCDriver.GRADIENT,
        model=QCModel(method="hf", basis="sto-3g"),
    ),
    initial_molecule=mol,
    keywords={"max_steps": 20, "g_convergence": "gau_tight"},
)

opt_result = QCOptimizationResult(
    input_specification=opt_inp.input_specification,
    initial_molecule=opt_inp.initial_molecule,
    final_molecule=QCMolecule(
        symbols=["H", "H"],
        geometry=[0.0, 0.0, -0.7005, 0.0, 0.0, 0.7005],
    ),
    energies=[-1.1163, -1.1171, -1.1173, -1.1175],
    success=True,
)

print(opt_result.num_steps)         # 4
print(opt_result.converged_energy)  # -1.1175
```

---

## PennyLane qchem datasets

`PennyLaneMolDataset` captures identification metadata and precomputed energies from the PennyLane qchem dataset collection. The actual HDF5 tensors (two-electron integrals, MOs) are loaded by `pennylane.data` at runtime; qpubench stores the metadata needed for benchmarking.

```python
from qpubench.schemas.molssi_qcschema import PennyLaneMolDataset

# H2 at equilibrium geometry, STO-3G basis
h2 = PennyLaneMolDataset(
    molname="H2",
    basis="STO-3G",
    bondlength=0.742,
    hf_energy=-1.1175,
    fci_energy=-1.1516,
    num_electrons=2,
    num_qubits=4,
    pauli_terms=15,
    dataset_tag="H2_STO-3G_0.742",
)
print(h2.correlation_energy)   # ≈ -0.0341 (FCI − HF)

# LiH — larger basis
lih = PennyLaneMolDataset(
    molname="LiH",
    basis="STO-3G",
    bondlength=1.5474,
    hf_energy=-7.8633,
    fci_energy=-7.8824,
    num_electrons=4,
    num_qubits=12,
    pauli_terms=631,
)
```

### Common benchmark molecules (STO-3G)

| Molecule | Electrons | Qubits (JW) | Pauli terms |
|---|---|---|---|
| H₂ | 2 | 4 | ~15 |
| LiH | 4 | 12 | ~631 |
| H₂O | 10 | 14 | ~1086 |
| BeH₂ | 6 | 14 | ~666 |
| N₂ | 14 | 20 | ~2951 |

---

## QCSchemaRecord — reference energy bridge

`QCSchemaRecord` is the top-level container that attaches to `QuantumResult.qcschema_record`. Its `reference_energy` property returns the best available classical reference regardless of which sub-record is populated.

```python
from qpubench.schemas.molssi_qcschema import QCSchemaRecord

# From an AtomicResult
rec1 = QCSchemaRecord(atomic_result=fci_result)
print(rec1.reference_energy)   # from atomic_result.properties.return_energy

# From an OptimizationResult
rec2 = QCSchemaRecord(optimization_result=opt_result)
print(rec2.reference_energy)   # from optimization_result.converged_energy

# From a PennyLane dataset
rec3 = QCSchemaRecord(pennylane_dataset=h2)
print(rec3.reference_energy)   # from pennylane_dataset.fci_energy

# Attach to QuantumResult
result = QuantumResult(
    computing_model=ComputingModel.GATE_BASED,
    qcschema_record=rec1,
)
```

---

## Interoperability with qdk_chemistry

`molssi_qcschema.py` and `microsoft_qdk.py` are complementary:

| Aspect | `microsoft_qdk.py` | `molssi_qcschema.py` |
|---|---|---|
| Molecule format | `MoleculeStructureSpec` (Å, per-atom objects) | `QCMolecule` (Bohr, flat arrays) |
| SCF result | `SCFResult` (QDK-specific fields) | `QCAtomicResultProperties` (QCSchema standard) |
| Wavefunction | — | `QCWavefunctionData` (orbital coefs, density) |
| Pipeline | `QChemPipelineSpec` (full SCF→QPE) | `QCAtomicResult` / `QCOptimizationResult` |
| Model Hamiltonians | `ModelHamiltonianSpec` (Ising, Hubbard, …) | — |
| Qubit Hamiltonian | `QubitHamiltonianSpec` | — (use `gsopt` or `qdk_chemistry`) |
| Interop target | Microsoft QDK, QuNorth | MolSSI QCSchema, PennyLane, Psi4, PySCF |
