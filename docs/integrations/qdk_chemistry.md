# QDK Chemistry integration

qpubench models the Microsoft QDK quantum chemistry pipeline in `src/qpubench/schemas/qdk_chemistry.py`. The schemas cover the full pipeline from molecular structure through SCF, active-space selection, Hamiltonian construction, qubit encoding, state preparation, QPE/IQPE phase estimation, and Azure Quantum resource estimation.

Modality: `QPUModality.QPE`

---

## Pipeline overview

```
MoleculeStructureSpec
  └─ SCFRunConfig → SCFResult
       └─ OrbitalLocalizationConfig → OrbitalLocalizationResult
            └─ ActiveSpaceSelectionConfig → ActiveSpaceSelectionResult
                 └─ SCIWavefunctionSpec   (optional MACIS/ASCI multi-configuration)
                      └─ FermionicHamiltonianSpec
                           └─ QubitHamiltonianSpec
                                └─ StatePrepConfig → StatePrepCircuitResult
                                     └─ QPEConfig → QPEResult
                                          └─ ResourceEstimatorConfig → ResourceEstimationResult
```

All stages are captured in `QChemPipelineSpec` stored in `QuantumResult.qchem_pipeline`.

---

## Molecular structure and SCF

```python
from qpubench.schemas.qdk_chemistry import (
    AtomSpec, MoleculeStructureSpec, CoordinateUnit,
    SCFRunConfig, SCFResult, SCFMethod,
)

# H2 at equilibrium
mol = MoleculeStructureSpec(
    atoms=[
        AtomSpec(symbol="H", x=0.0, y=0.0, z=0.0),
        AtomSpec(symbol="H", x=0.0, y=0.0, z=0.7414),
    ],
    charge=0,
    spin_multiplicity=1,
    units=CoordinateUnit.ANGSTROM,
    name="H2",
)

scf_config = SCFRunConfig(
    method=SCFMethod.RHF,
    basis="sto-3g",
    convergence_threshold=1e-9,
    max_iterations=200,
)

scf_result = SCFResult(
    hf_energy=-1.1175,
    num_electrons=2,
    num_alpha=1,
    num_beta=1,
    num_orbitals=2,
    orbital_energies=[-0.5785, 0.6709],
    converged=True,
    num_iterations=8,
)
```

---

## Orbital localization and active space

```python
from qpubench.schemas.qdk_chemistry import (
    OrbitalLocalizationConfig, OrbitalLocalizationResult, OrbitalLocalizerType,
    OrbitalEntanglementEntropies,
    ActiveSpaceSelectionConfig, ActiveSpaceSelectionResult, ActiveSpaceSelectorType,
)

loc_config = OrbitalLocalizationConfig(
    localizer_type=OrbitalLocalizerType.MP2_NO,
    num_orbitals=4,
)

entropies = OrbitalEntanglementEntropies(
    num_orbitals=4,
    s1_entropies=[0.01, 0.62, 0.61, 0.02],        # single-orbital entanglement
    mutual_information=[0.0, 0.0, 0.0, 0.0,        # flattened 4×4; I(i,j)
                        0.0, 0.0, 0.98, 0.0,
                        0.0, 0.98, 0.0, 0.0,
                        0.0, 0.0, 0.0, 0.0],
)

loc_result = OrbitalLocalizationResult(
    localizer_type=OrbitalLocalizerType.MP2_NO,
    entropies=entropies,
    selected_orbital_indices=[1, 2],
)

as_config = ActiveSpaceSelectionConfig(
    selector_type=ActiveSpaceSelectorType.MP2_NO,
    num_active_electrons=2,
    num_active_orbitals=2,
)

as_result = ActiveSpaceSelectionResult(
    selector_type=ActiveSpaceSelectorType.MP2_NO,
    active_electrons=2,
    active_orbitals=2,
    orbital_indices=[1, 2],
    frozen_core_energy=-1.1175,
)
```

---

## Fermionic and qubit Hamiltonians

```python
from qpubench.schemas.qdk_chemistry import (
    FermionicHamiltonianSpec, QubitHamiltonianSpec,
    PauliStringTerm, QubitEncodingType,
)

h_fermionic = FermionicHamiltonianSpec(
    num_orbitals=2,
    num_electrons=2,
    core_energy=-1.1175,
    one_body_integrals=[-0.5785, 0.0, 0.0, 0.6709],   # flattened 2×2
    two_body_integrals=[0.674, 0.0, 0.0, 0.674,        # flattened 2×2×2×2
                        0.0, 0.181, 0.181, 0.0, ...],
    schatten_norm=1.432,                                 # ‖H‖₁ for QPE timing
)

h_qubit = QubitHamiltonianSpec(
    encoding=QubitEncodingType.JORDAN_WIGNER,
    num_qubits=4,
    num_pauli_terms=15,
    pauli_terms=[
        PauliStringTerm(pauli_string="IIII", coefficient=-0.0988),
        PauliStringTerm(pauli_string="IIIZ",  coefficient=-0.2159),
        # ...
    ],
)
```

---

## QPE / IQPE

```python
from qpubench.schemas.qdk_chemistry import (
    QPEConfig, QPEResult, QPEMethod,
    TimeEvolutionConfig, TimeEvolutionBuilderType,
    StatePrepConfig, StatePrepCircuitResult, StatePrepMethod,
)
import math

# State preparation
state_config = StatePrepConfig(
    method=StatePrepMethod.SPARSE_ISOMETRY_GF2X,
    num_determinants=4,
    target_fidelity=0.999,
)

state_result = StatePrepCircuitResult(
    method=StatePrepMethod.SPARSE_ISOMETRY_GF2X,
    circuit_qasm="OPENQASM 2.0; ...",
    num_cnots=12,
    circuit_depth=18,
    achieved_fidelity=0.9998,
)

# IQPE: 1 ancilla, sequential measurements
iqpe_config = QPEConfig(
    method=QPEMethod.ITERATIVE,
    evolution_time=math.pi / 1.432,   # T = π / ‖H‖₁
    num_bits=12,
    shots_per_bit=10,
    time_evolution=TimeEvolutionConfig(
        builder_type=TimeEvolutionBuilderType.SUZUKI_TROTTER,
        trotter_order=2,
        num_steps=6,
    ),
)

iqpe_result = QPEResult(
    raw_energy=-1.1373,
    bitstring_msb_first="110010011101",
    alias_branches=[-1.1373, -0.8821],
    error_mha=0.15,
    quantization_limit_mha=0.12,
    num_bits_used=12,
    evolution_time=math.pi / 1.432,
)
```

---

## Resource estimation (Azure Quantum)

```python
from qpubench.schemas.qdk_chemistry import (
    ResourceEstimatorConfig, ResourceEstimationResult,
    ErrorBudgetPartition, QubitParamsType, QECScheme,
)

estimator_config = ResourceEstimatorConfig(
    qubit_params=QubitParamsType.GATE_NS_E4,
    qec_scheme=QECScheme.SURFACE_CODE,
    error_budget=ErrorBudgetPartition(
        logical_error=0.001,
        rotation_synthesis=0.0005,
        t_state_distillation=0.0005,
    ),
)

est_result = ResourceEstimationResult(
    num_physical_qubits=2847,
    runtime_s=0.043,
    t_gate_count=58_420,
    logical_qubits=38,
    code_distance=15,
    num_t_factories=4,
)
```

---

## Model Hamiltonians

Use model Hamiltonians instead of a molecular structure for condensed-matter benchmarks:

```python
from qpubench.schemas.qdk_chemistry import (
    ModelHamiltonianSpec, ModelHamiltonianType,
    LatticeGraphSpec, LatticeTopology,
    IsingParams, HeisenbergParams, HubbardParams,
)

# Transverse-field Ising chain
ising = ModelHamiltonianSpec(
    hamiltonian_type=ModelHamiltonianType.ISING,
    lattice=LatticeGraphSpec(topology=LatticeTopology.CHAIN, num_sites=10),
    ising=IsingParams(J=1.0, h=0.5),
)

# Heisenberg XXX ring
heisenberg = ModelHamiltonianSpec(
    hamiltonian_type=ModelHamiltonianType.HEISENBERG,
    lattice=LatticeGraphSpec(topology=LatticeTopology.RING, num_sites=8),
    heisenberg=HeisenbergParams(Jx=1.0, Jy=1.0, Jz=1.0, h=0.0),
)

# Hubbard chain
hubbard = ModelHamiltonianSpec(
    hamiltonian_type=ModelHamiltonianType.HUBBARD,
    lattice=LatticeGraphSpec(topology=LatticeTopology.CHAIN, num_sites=6),
    hubbard=HubbardParams(t=1.0, U=4.0),
)
```

Only one parameter block (`ising`, `heisenberg`, `hubbard`, `huckel`, `ppp`) may be non-`None`; the validator enforces this.

---

## Full pipeline record

```python
from qpubench.schemas.qdk_chemistry import QChemPipelineSpec
from qpubench.schemas.result import QuantumResult
from qpubench.schemas.primitives import QPUModality

pipeline = QChemPipelineSpec(
    molecule=mol,
    scf_config=scf_config,
    scf_result=scf_result,
    active_space_result=as_result,
    fermionic_hamiltonian=h_fermionic,
    qubit_hamiltonian=h_qubit,
    state_prep_config=state_config,
    state_prep_result=state_result,
    qpe_config=iqpe_config,
    qpe_result=iqpe_result,
    resource_estimator_config=estimator_config,
    resource_estimation_result=est_result,
)

result = QuantumResult(
    modality=QPUModality.QPE,
    qpe_result=iqpe_result,
    qchem_pipeline=pipeline,
)
```

---

## Backends

```python
from qpubench.schemas.backend import BackendSpec

BackendSpec.qdk_chemistry_simulator("qdk_sparse_state_simulator", num_qubits=20)
BackendSpec.azure_quantum("microsoft.estimator",
                          resource_id_ref="AZURE_RESOURCE_ID",
                          location_ref="AZURE_LOCATION")
BackendSpec.azure_quantum("quantinuum.hqs-lt-s1")   # Quantinuum H1 hardware
```
