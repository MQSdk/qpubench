# SlowQuant integration

qpubench models the full [SlowQuant](https://github.com/erikkjellgren/SlowQuant) quantum chemistry workflow in `src/qpubench/schemas/erikkjellgren_slowquant.py`.

| Component | Details |
|---|---|
| **Library** | [SlowQuant](https://github.com/erikkjellgren/SlowQuant) ([docs](https://slowquant.readthedocs.io/en/latest/)) |
| **Computing model** | `ComputingModel.GATE_BASED` |
| **Result field** | `QuantumResult.slowquant_record` |
| **Quantum backend** | Qiskit circuit compilation (any gate-based provider) |

SlowQuant specializes in **unitary parameterized wave functions** — UCC, factorized UCC, and truncated UPS — where the same parameter vector describes both the classical statevector and the compiled Qiskit quantum circuit. This makes it directly suitable for hybrid QPU workflows where the optimizer runs classically and only the energy evaluation is sent to hardware.

---

## Quick start

```python
from qpubench.schemas.erikkjellgren_slowquant import (
    UCCAnsatzType, UCCExcitationLevel, UCCOptimizationMethod,
    UCCActiveSpaceConfig, UCCWavefunctionConfig,
    UCCSCFResult, UCCOptimizationResult,
    SlowQuantRecord,
)
from qpubench.schemas.result import QuantumResult
from qpubench.schemas.primitives import ComputingModel

# H2 / STO-3G  —  2 electrons in 2 orbitals
active_space = UCCActiveSpaceConfig(
    num_active_electrons=2,
    num_active_orbitals=2,
    num_total_electrons=2,
    num_total_orbitals=2,
)

wf_config = UCCWavefunctionConfig(
    ansatz=UCCAnsatzType.UCC,
    excitations=UCCExcitationLevel.SD,
    active_space=active_space,
)
print(wf_config.num_qubits)   # 4  (= 2 × 2 orbitals)

scf = UCCSCFResult(
    hf_energy=-1.1175,
    converged=True,
    mo_energies=[-0.5755, 0.6697],
    homo_index=0,
)
print(scf.homo_lumo_gap)   # 1.2452

opt = UCCOptimizationResult(
    method=UCCOptimizationMethod.ONE_STEP,
    num_iterations=12,
    converged=True,
    final_energy=-1.1372,
    theta=[0.1142],
)

record = SlowQuantRecord(
    molecule_name="H2",
    basis_set="STO-3G",
    scf_result=scf,
    wavefunction_config=wf_config,
    optimization_result=opt,
)
print(record.correlation_energy)   # -0.0197 Hartree
print(record.num_qubits)           # 4

result = QuantumResult(
    computing_model=ComputingModel.GATE_BASED,
    slowquant_record=record,
)
```

---

## Active space configuration

`UCCActiveSpaceConfig` maps directly to SlowQuant's `cas=[n_active_elec, n_active_orb]` argument and the `include_active_kappa` orbital optimization flag.

```python
from qpubench.schemas.erikkjellgren_slowquant import UCCActiveSpaceConfig

# Full-valence active space for LiH
active = UCCActiveSpaceConfig(
    num_active_electrons=2,
    num_active_orbitals=5,
    num_total_electrons=4,
    num_total_orbitals=11,
    frozen_core_orbitals=1,        # Li 1s frozen
    frozen_virtual_orbitals=5,     # high-energy virtuals frozen
    include_orbital_optimization=True,   # optimize MOs alongside θ
)
print(active.num_qubits)   # 10  (= 2 × 5 orbitals)
```

### SlowQuant `cas` → qpubench mapping

| SlowQuant | qpubench |
|---|---|
| `cas[0]` (num active electrons) | `UCCActiveSpaceConfig.num_active_electrons` |
| `cas[1]` (num active orbitals) | `UCCActiveSpaceConfig.num_active_orbitals` |
| `include_active_kappa=True` | `UCCActiveSpaceConfig.include_orbital_optimization=True` |
| `num_inactive_orbs` | `UCCActiveSpaceConfig.frozen_core_orbitals` |
| `num_virtual_orbs` | `UCCActiveSpaceConfig.frozen_virtual_orbitals` |

---

## Ansatz types

| `UCCAnsatzType` | SlowQuant class | Description |
|---|---|---|
| `ucc` | `WaveFunctionUCC` | Standard unitary coupled cluster |
| `fucc` | `WaveFunctionUCC` (factorized) | Product of individual excitation unitaries |
| `tups` | `WaveFunctionUPS` | Truncated Unitary Product State — hardware-efficient |
| `qnp` | `WaveFunctionUPS` (QNP) | Qubit Number Parity — preserves qubit parity |
| `saups` | `WaveFunctionUPS` (state-averaged) | Simultaneous ground + excited state optimization |

```python
from qpubench.schemas.erikkjellgren_slowquant import UCCAnsatzType, UCCExcitationLevel, UCCWavefunctionConfig

# Hardware-efficient tUPS ansatz with active orbital rotation
wf = UCCWavefunctionConfig(
    ansatz=UCCAnsatzType.TUPS,
    excitations=UCCExcitationLevel.SD,
    active_space=active,
    spin_adapted=True,           # reduce parameter count
)
```

### Parameter compatibility

A key SlowQuant feature: **the θ vector is parameter-compatible** between the classical statevector optimizer and the compiled Qiskit quantum circuit. The `UCCOptimizationResult.theta` values can be loaded directly into a Qiskit `ParameterVector` without any re-encoding.

---

## SCF → UCC workflow

```python
from qpubench.schemas.erikkjellgren_slowquant import (
    UCCIntegralData, UCCSCFResult,
    UCCOptimizationResult, UCCOptimizationMethod,
    UCCIterationRecord, UCCRDMData,
)

# 1. Molecular integrals (AO basis)
integrals = UCCIntegralData(
    basis_set="cc-pVDZ",
    num_basis_functions=14,
    h_ao=[...],      # 14×14 = 196 floats, row-major
    overlap_ao=[...],  # 196 floats
    # g_ao omitted — 14⁴ = 38416 entries; only include for small systems
)

# 2. HF SCF
scf = UCCSCFResult(
    hf_energy=-7.8632,
    nuclear_repulsion=0.9924,
    num_iterations=8,
    converged=True,
    mo_energies=[-2.452, -0.298, -0.215, 0.030, 0.130, ...],
    orbital_occupations=[2.0, 2.0, 0.0, 0.0, ...],
    homo_index=1,
)
print(scf.homo_lumo_gap)   # 0.245 Hartree

# 3. UCC optimization — with per-iteration history
opt = UCCOptimizationResult(
    method=UCCOptimizationMethod.TWO_STEP,
    num_iterations=25,
    converged=True,
    final_energy=-7.8820,
    theta=[0.0412, -0.1083, 0.0213, ...],
    kappa=[0.0021, -0.0034, ...],   # orbital rotation params (two-step)
    gradient_norm_final=3.2e-7,
    iteration_history=[
        UCCIterationRecord(iteration=1, energy=-7.8701, gradient_norm=0.0312),
        UCCIterationRecord(iteration=2, energy=-7.8789, gradient_norm=0.0088),
        # ...
    ],
)
print(opt.num_theta_params)   # varies with active space and excitation level
print(opt.num_kappa_params)   # > 0 only for two_step

# 4. Reduced density matrices
rdm = UCCRDMData(
    num_active_orbitals=5,
    rdm1=[...],    # 5² = 25 floats
    rdm2=[...],    # 5⁴ = 625 floats
)
```

---

## Linear response theory

SlowQuant computes excitation energies and transition properties via linear response theory at four levels. The excitation level string controls how many excitation operators enter the response matrix.

```python
from qpubench.schemas.erikkjellgren_slowquant import (
    UCCLinearResponseType, UCCLinearResponseResult, UCCExcitedStateResult,
    UCCExcitationLevel,
)

# Self-consistent linear response at SDTQ level
lr = UCCLinearResponseResult(
    response_type=UCCLinearResponseType.SELF_CONSISTENT,
    excitation_level=UCCExcitationLevel.SDTQ,
    num_states_computed=5,
    excited_states=[
        UCCExcitedStateResult(
            state_index=1,
            excitation_energy_au=0.2879,
            # excitation_energy_ev auto-filled: 0.2879 × 27.2114 = 7.836 eV
            transition_dipole=[0.0, 0.0, 0.7423],   # [µx, µy, µz] a.u.
            oscillator_strength=0.1321,
        ),
        UCCExcitedStateResult(
            state_index=2,
            excitation_energy_au=0.3412,
            # excitation_energy_ev auto-filled: 9.285 eV
        ),
    ],
)

print(lr.excitation_energies_ev)    # [7.836, 9.285, ...]
print(lr.oscillator_strengths)      # [0.1321, None, ...]
```

### Linear response levels

| `UCCLinearResponseType` | SlowQuant method | Description |
|---|---|---|
| `naive` | `get_linear_response_matrix_naive` | No orbital response |
| `projected` | `get_linear_response_matrix_projected` | Projected orbital response |
| `self_consistent` | `get_linear_response_matrix_sc` | Fully self-consistent (most accurate) |
| `state_transfer` | `get_linear_response_matrix_st` | State-transfer formulation |

---

## Quantum circuit metadata

```python
from qpubench.schemas.erikkjellgren_slowquant import (
    UCCCircuitSpec, UCCMeasurementConfig, UCCAnsatzType, UCCExcitationLevel,
)

# UCC-SD circuit compiled at Qiskit optimization level 3
circuit_spec = UCCCircuitSpec(
    ansatz_type=UCCAnsatzType.UCC,
    excitation_level=UCCExcitationLevel.SD,
    num_qubits=4,
    num_parameters=1,       # one θ amplitude for H2 UCC-SD
    gate_depth=32,
    cx_count=12,
    single_qubit_gates=28,
    qubit_encoding="jordan_wigner",
)

# Measurement grouping (clique cover of commuting Pauli strings)
meas_config = UCCMeasurementConfig(
    num_cliques=6,               # 6 commuting groups for H2 Hamiltonian
    postselection_enabled=True,  # reject bitstrings violating ⟨N⟩ = 2
    shots_per_evaluation=8192,
    num_pauli_strings=15,
    error_mitigation="measurement_correction",
)
```

### Clique-based measurement grouping

SlowQuant groups the qubit Hamiltonian Pauli strings by **qubit-wise commutativity** so that each clique can be measured simultaneously. The number of measurement circuits equals `num_cliques` (much smaller than `num_pauli_strings` for typical active spaces). Post-selection then removes bitstrings that violate particle-number conservation, reducing shot noise.

---

## SlowQuant → qpubench field mapping

| SlowQuant Python object | qpubench type | Field |
|---|---|---|
| `WaveFunctionUCC(cas=[ne,no], excitations="SD")` | `UCCWavefunctionConfig` | `ansatz`, `excitations`, `active_space` |
| `wf.energy` | `UCCOptimizationResult.final_energy` | Energy in Hartree |
| `wf.theta` | `UCCOptimizationResult.theta` | Circuit amplitude params |
| `wf.kappa` | `UCCOptimizationResult.kappa` | Orbital rotation params |
| `IntegralTransforms.Hamiltonian_energy` | `UCCSCFResult.hf_energy` | HF reference energy |
| `MolecularSystem.nuclear_repulsion_energy` | `UCCSCFResult.nuclear_repulsion` | Nuclear repulsion |
| `MolecularSystem.mo_energies` | `UCCSCFResult.mo_energies` | Orbital eigenvalues |
| `LinearResponseUCC.get_excitation_energies()` | `UCCLinearResponseResult.excited_states[i].excitation_energy_au` | Excitation energies |
| `LinearResponseUCC.get_oscillator_strength()` | `UCCExcitedStateResult.oscillator_strength` | Oscillator strengths |
| `LinearResponseUCC.get_transition_dipole()` | `UCCExcitedStateResult.transition_dipole` | Transition dipoles |
| `rdm1_active` | `UCCRDMData.rdm1` | 1-RDM in active MO basis |
| `rdm2_active` | `UCCRDMData.rdm2` | 2-RDM in active MO basis |
| `QuantumInterface.circuit` | `UCCCircuitSpec` | Compiled Qiskit circuit metadata |
| `QuantumInterface.num_cliques` | `UCCMeasurementConfig.num_cliques` | Commuting measurement groups |
| `QuantumInterface.do_postselection` | `UCCMeasurementConfig.postselection_enabled` | Post-selection filter |

---

## Complete H2 example

```python
from qpubench.schemas.erikkjellgren_slowquant import (
    UCCAnsatzType, UCCExcitationLevel, UCCOptimizationMethod,
    UCCActiveSpaceConfig, UCCWavefunctionConfig,
    UCCSCFResult, UCCOptimizationResult,
    UCCExcitedStateResult, UCCLinearResponseResult, UCCLinearResponseType,
    UCCCircuitSpec, UCCMeasurementConfig,
    SlowQuantRecord,
)
from qpubench.schemas.result import QuantumResult
from qpubench.schemas.primitives import ComputingModel
from qpubench import BenchmarkRunner, NDJSONStore, ExecutionOptions
import pathlib

# --- Active space + wavefunction ---
active = UCCActiveSpaceConfig(num_active_electrons=2, num_active_orbitals=2)
wf_config = UCCWavefunctionConfig(
    ansatz=UCCAnsatzType.UCC,
    excitations=UCCExcitationLevel.SD,
    active_space=active,
)

# --- SCF ---
scf = UCCSCFResult(
    hf_energy=-1.1175, converged=True,
    mo_energies=[-0.5755, 0.6697], homo_index=0,
)

# --- Optimization ---
opt = UCCOptimizationResult(
    method=UCCOptimizationMethod.ONE_STEP,
    num_iterations=12, converged=True,
    final_energy=-1.1372, theta=[0.1142],
)

# --- Linear response (excitation energies) ---
lr = UCCLinearResponseResult(
    response_type=UCCLinearResponseType.SELF_CONSISTENT,
    excitation_level=UCCExcitationLevel.SD,
    num_states_computed=3,
    excited_states=[
        UCCExcitedStateResult(state_index=1, excitation_energy_au=0.4847),
        # excitation_energy_ev auto-filled: 13.19 eV
    ],
)

# --- Circuit metadata ---
circ = UCCCircuitSpec(
    ansatz_type=UCCAnsatzType.UCC, excitation_level=UCCExcitationLevel.SD,
    num_qubits=4, num_parameters=1, gate_depth=32, cx_count=12,
)
meas = UCCMeasurementConfig(
    num_cliques=6, postselection_enabled=True,
    shots_per_evaluation=8192, num_pauli_strings=15,
)

# --- Assemble ---
sq_record = SlowQuantRecord(
    molecule_name="H2", basis_set="STO-3G",
    scf_result=scf, wavefunction_config=wf_config,
    optimization_result=opt, linear_response=lr,
    circuit_spec=circ, measurement_config=meas,
)
print(f"Correlation energy: {sq_record.correlation_energy:.4f} Ha")
print(f"1st excitation:     {sq_record.linear_response.excited_states[0].excitation_energy_ev:.3f} eV")
print(f"Qubits:             {sq_record.num_qubits}")

# --- Store via BenchmarkRunner ---
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.primitives import CircuitFormat

mol = CircuitSpec(num_qubits=4, format=CircuitFormat.QASM2,
                  serialized="OPENQASM 2.0; ...")

runner = BenchmarkRunner(
    store=NDJSONStore(pathlib.Path("results/h2_ucc.ndjson"))
)
# Register a SlowQuant adapter from integrations/slowquant/ (not bundled)
# runner.register(SlowQuantAdapter(), name="slowquant")
# record = runner.run(mol, "slowquant", ExecutionOptions(shots=8192))
```
