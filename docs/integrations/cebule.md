# Cebule SDK integration

[Cebule SDK](https://docs.mqs.dk/sections/section_014_quantum_computing/) (MQS) provides cloud quantum-chemistry and materials-property task types. qpubench models each task's input and output as typed Pydantic schemas in `src/qpubench/schemas/mirrors/mqsdk_cebule.py`.

**Revised 2026-07-08.** This module was checked directly against the real
SDK source, [gitlab.com/mqsdk/python-sdk](https://gitlab.com/mqsdk/python-sdk),
specifically `mqsdk/core/cebule.py`'s `TaskType` enum, `mqsdk/utils/tasks.py`'s
helper functions, and the `notebooks/` examples, and turned up a real gap:
`MOL_MAP`/`QASM_GEN` (below) do not appear in that `TaskType` enum, while
fifteen other task types the SDK does expose (solvation, ab initio MD,
geometry optimization, group-contribution/GNN property prediction) weren't
modeled at all. Both are now fixed; see "Task types" below for what's
confirmed vs. kept-with-caveat, and the new sections for each task family.

---

## Task types

`CebuleTaskEnvelope` (`max_processors`, `connected_task_id`,
`connected_model_id`, `connected_dataset_id`,
`notification_minutes_threshold`) is common to every task below,
confirmed directly against `MQSCebule.create_task()`'s signature. Tasks
chain into a DAG via `connected_task_id` (e.g. `GEOMETRY_OPT` →
`COSMO` → `SIGMA` → `SOLUBILITY`).

| `CebuleTaskType` | What it does | Confirmed against |
|---|---|---|
| `COSMO` | Continuum solvation (dielectric constant + VDW radii) | `mqsdk/utils/tasks.py`, `notebooks/2_COSMO_task_Cebule.ipynb` |
| `SIGMA` | COSMO-SAC/-RS sigma profile, chained from a `COSMO` task | `mqsdk/utils/tasks.py` |
| `SOLUBILITY` | Solubility from one or more `SIGMA` results | `mqsdk/utils/tasks.py` |
| `BORN_OPPENHEIMER_MD` | Ab initio MD, Quantum-ESPRESSO-backed (periodic-capable) | `notebooks/3_BOMD_task_Cebule.ipynb` |
| `CAR_PARRINELLO_MD` | Ab initio MD, Quantum-ESPRESSO-backed (periodic-capable) | `notebooks/4_CPMD_task_Cebule.ipynb` |
| `FORCE_FIELD_MD` | Classical MD of a molecule (or polymer) in a solvent box | `scripts/md.py` |
| `GEOMETRY_OPT` | Force-field + semi-empirical geometry optimisation | `scripts/geometry.py` |
| `PERIODIC_GEOMETRY_OPT` | Geometry optimisation under periodic boundary conditions | Enum only; no usage example found, fields inferred |
| `GROUP_CONTRIBUTION` | Group-contribution property estimation, batchable over mixtures | `scripts/group_contribution.py` |
| `ATOM_ORDER` | Canonical atom ordering for a SMILES (+ optional geometry) | `mqsdk/utils/tasks.py` |
| `ACTIVITY_COEFFICIENT` | n/a | Enum only; no usage example found, not modeled beyond the envelope |
| `GNN_DATASET_CREATE`/`_EXTEND`/`_GET`/`_DELETE`, `GNN_TRAIN`, `GNN_PREDICT` | Property-prediction GNN dataset/model lifecycle | `notebooks/6_GNN_task_HLGap_GeometryOpt.ipynb` |
| `TN_QC_OPT` | Tensor-network + quantum circuit hybrid VQE optimisation | Confirmed in `TaskType` enum |
| `COVO` | Correlation-optimised virtual orbital pre-processing | Confirmed in `TaskType` enum |
| `MOL_MAP` *(unconfirmed)* | Map a molecular geometry to a qubit Hamiltonian via constraint-based encoding | Not found in `TaskType` enum; kept, see caveat above |
| `QASM_GEN` *(unconfirmed)* | Generate OpenQASM 2.0 measurement circuits for a Hamiltonian | Not found in `TaskType` enum; kept, see caveat above |

---

## Session pattern

```python
import mqsdk, os

session = mqsdk.Cebule(os.environ["EMAIL"], os.environ["PASSWORD"])

# Most tasks: kwargs become the task's JSON input.
task = session.cebule.create_task(
    "H2O geometry opt", TaskType.GEOMETRY_OPT,
    smiles_list=["O"], force_field="mmff94", optimization_method="gfn2_xtb",
)

# BORN_OPPENHEIMER_MD / CAR_PARRINELLO_MD only: input= is a raw Quantum
# ESPRESSO input file (create_task allows input= OR **kwargs, not both).
task = session.cebule.create_task(
    "QE BOMD run", TaskType.BORN_OPPENHEIMER_MD, input=qe_input_text,
)

# Chain a follow-up task via connected_task_id:
cosmo_task = session.cebule.create_task(
    "COSMO opt", TaskType.COSMO,
    connected_task_id=task.id, method="dft", basis="6-31g**", dielec=78.0,
)
```

Set credentials in `.env` and reference them via `BackendSpec.cebule()`:

```python
from qpubench.schemas import BackendSpec
backend = BackendSpec.cebule(email_ref="EMAIL", password_ref="PASSWORD")
```

---

## MOL_MAP *(unconfirmed against current SDK source)*

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

## QASM_GEN *(unconfirmed against current SDK source; fully documented on docs.mqs.dk)*

The measurement method: evaluates the expectation value of a mapped
Hamiltonian via a circuit-generation scheme that groups terms by
computational basis state pairs rather than per-Pauli-string
decomposition; generates OpenQASM 2.0 circuits, one per basis-state
grouping. Explicitly documented as compatible with the output of either
`MOL_MAP` or `TN_QC_OPT` (see below, since it's also usable *inside*
`TN_QC_OPT` directly via `measurement_method="grouped"`).

`include_state_circuit` defaults to `False` (corrected 2026-07-09 against
the current docs.mqs.dk table).

```python
from qpubench.schemas import QASMGenInput, QASMGenResult

inp = QASMGenInput(operator=[[…]], include_state_circuit=True)   # override the False default explicitly

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

Hybrid tensor-network + quantum circuit VQE. `opt_method` defaults to
`"COBYLA"` (corrected 2026-07-09; was `"BFGS"` in an earlier revision of
this doc). `measurement_method` (`"pauli"` default, or `"grouped"`,
QASM_GEN's own basis-state-pair grouping used internally) and
`optimization_mode` (`"both"` default, jointly optimize θ/φ; `"circuit"`
freezes θ for plain VQE over φ; `"network"` freezes φ for a classical-only
θ search) were added 2026-07-09, confirmed real against the current
docs.mqs.dk table.

```python
from qpubench.schemas import TNQCOptInput, TNQCOptResult, SparsePauliObservable

inp = TNQCOptInput(
    h_coeff_values=[0.5, -0.3, 0.1],
    h_operators=["Z0", "X0 Z1", "Y1"],
    n_iterations=100,
    n_layers_network=3,
    n_layers_circuit=3,
    opt_method="COBYLA",
    backend="lightning.qubit",
    measurement_method="grouped",   # or "pauli"
    optimization_mode="both",        # or "circuit" / "network"
)

result = TNQCOptResult(
    vqe_energy=-1.136,
    phi=[0.1, -0.2, 0.3],       # optimised circuit parameters U(φ)
    theta=[0.5, -0.1, 0.2],     # optimised TN parameters U(θ)
    h_tn_opt_qubit=[0.5, -0.3, 0.1],
    qubit_operators=["Z0", "X0 Z1", "Y1"],
    function_calls=42,
    cost_history=[-0.9, -1.05, -1.136],
)

# Convert to SparsePauliObservable
obs = result.to_sparse_pauli_observable(num_qubits=2)
```

Wire `AlgorithmSpec` fields to the TN_QC_OPT parameters:

```python
from qpubench.schemas import AlgorithmSpec

spec = AlgorithmSpec(
    name="TN_QC_OPT",
    optimizer="COBYLA",
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

Record `fci_energy` in `VQAResult` (computed outputs):

```python
from qpubench.schemas import VQAConfig, VQAResult

vqa = VQAConfig(problem_type="chemistry", molecule="BH")
vqa_result = VQAResult(
    hf_energy=-24.6,
    fci_energy=-24.7757,      # from COVOResult
    final_eigenvalue=-24.75,
)
```

---

## Solvation: `COSMO` → `SIGMA` → `SOLUBILITY`

A real, chained pipeline confirmed against `mqsdk/utils/tasks.py`. `COSMO`
computes continuum-solvation energetics for one molecule; `SIGMA` derives a
screening-charge-density profile from a completed `COSMO` task; `SOLUBILITY`
combines `SIGMA` profiles for a solute + solvent mixture into a solubility
estimate. This is Cebule's route to a solvent model (see
`examples/guides/create_solvent_model.py` for the PySCF route).

```python
from qpubench.schemas import CosmoInput, CosmoMethod, SigmaInput, SolubilityInput

# Step 1: COSMO on the (already geometry-optimized) solute, chained via
# connected_task_id to a prior GEOMETRY_OPT task's ID.
cosmo = CosmoInput(
    connected_task_id="geometry-opt-task-id",
    basis="6-31g**",
    optimize=True,
    dielec=78.0,       # water
)

# Step 2: sigma profile from the COSMO result.
sigma = SigmaInput(connected_task_id="cosmo-task-id", cosmo_method=CosmoMethod.COSMO_SAC)

# Step 3: solubility from solute + solvent sigma profiles.
solubility = SolubilityInput(
    connected_task_id=["sigma-solute-id", "sigma-solvent-id"],
    temperature=298.15,
    melting_point=350.0,
    enthalpy_melting=20.0,
    sol_init=0.1,
    solv_composition=[1.0],
    change_heat_capacity_melting=5.0,   # required for cosmo-sac
)
```

---

## Geometry: `GEOMETRY_OPT` / `PERIODIC_GEOMETRY_OPT`

```python
from qpubench.schemas import GeometryOptInput, GeometryOptForceField, GeometryOptMethod

geo = GeometryOptInput(
    smiles_list=["O"],
    force_field=GeometryOptForceField.MMFF94,       # or GHEMICAL
    optimization_method=GeometryOptMethod.GFN2_XTB,  # or G_XTB, AM1, UMA
)
```

`PeriodicGeometryOptInput` is the periodic-cell counterpart, confirmed to
exist in the SDK's `TaskType` enum, but no usage example was found during
this check, so its fields (`cell_lengths`, `cell_angles`, plus the same
`force_field`/`optimization_method` choice) are inferred by analogy rather
than confirmed. Verify against the live SDK before relying on exact names.

---

## Ab initio MD: `BORN_OPPENHEIMER_MD` / `CAR_PARRINELLO_MD`

Both wrap Quantum ESPRESSO directly; the payload is a **raw QE input file**
(`&control`/`&system`/`&electrons` or `&ions` namelists), not kwargs. The
confirmed example notebooks use a periodic 8-water cell (`ibrav`/`celldm`
lattice parameters), i.e. genuine periodic plane-wave DFT, a plane-wave
alternative for periodic-system chemistry (e.g. the carbon-capture
tutorial's framework, `examples/tutorials/carbon_capture_periodic_dft.py`).

```python
from qpubench.schemas import AbInitioMDInput, AbInitioMDMethod

bomd = AbInitioMDInput(
    method=AbInitioMDMethod.BORN_OPPENHEIMER,
    qe_input=open("h2o-periodic.in").read(),   # real QE input file text
)
```

Result is raw QE stdout text (`AbInitioMDResult.stdout`), not structured
JSON; parse energies/forces yourself.

## Classical MD: `FORCE_FIELD_MD`

```python
from qpubench.schemas import ForceFieldMDInput

md = ForceFieldMDInput(
    smiles_primary="CCO",              # or a list of SMILES for a polymer chain
    copies_primary=1,
    smiles_list_secondary=["O"],
    copies_list_secondary=[500],
    temperature=298.15,
    box_length_nm=4.0,
    time_fs=10_000.0,
)
```

---

## Materials properties: `GROUP_CONTRIBUTION` / `ATOM_ORDER` / `ACTIVITY_COEFFICIENT`

```python
from qpubench.schemas import GroupContributionInput, AtomOrderInput

# Batchable over multiple mixtures; each inner list is one mixture's SMILES.
gc = GroupContributionInput(smiles_list=[["CCO", "O"], ["CCC", "O"]], gc_type="unifac")

atom_order = AtomOrderInput(smiles="CCO")   # or smiles=[...] + geometry=[...] for a polymer
```

`ActivityCoefficientInput` exists (confirmed in the `TaskType` enum) but no
usage example was found; it currently carries no task-specific fields
beyond the common envelope.

---

## Property-prediction GNN: dataset + model lifecycle

```python
from qpubench.schemas import (
    GNNDatasetCreateInput, GNNDatasetExtendInput, GNNMoleculeChunk,
    GNNTrainInput, GNNPredictInput,
)

create = GNNDatasetCreateInput(
    dataset_name="hlgap_dataset", includes_target_val=True,
    target_property="homo_lumo_gap",
)
extend = GNNDatasetExtendInput(
    connected_dataset_id="dataset-id",
    molecule_chunk=GNNMoleculeChunk(
        smiles=["CCO"], coords=[[0.0, 0.0, 0.0, 1.5, 0.0, 0.0]], target_val=[3.2],
    ),
)
train = GNNTrainInput(
    connected_dataset_id="dataset-id", model_name="hlgap_model",
    hyperparameters={"epochs": 75},
)
predict = GNNPredictInput(connected_dataset_id="pred-dataset-id", connected_model_id="model-id")
```

`GNNTrainResult`/`GNNPredictResult` model the fields the SDK's own example
notebook names (a mean-absolute-error training metric; predictions the
notebook calls "effective hamiltonians") without over-specifying a payload
shape that wasn't directly confirmed.

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
