# Photonic integration

qpubench models linear-optics photonic chips and Fusion-Based QC (FBQC) in `src/qpubench/schemas/mqsdk_photoq.py` (the LOQC/FBQC section). This is **permanent-based simulation** using Fock states — distinct from the Gaussian-state / hafnian-based GBS section of the same module.

Computing model: `ComputingModel.GATE_BASED` (MZI chips, boson sampling — LOQC circuits) and `ComputingModel.FUSION_BASED` (FBQC with resource states + fusion gates). Qubit modality: `QubitModality.PHOTONIC` in both cases.

> The `mqsdk_photoq` module also covers Gaussian Boson Sampling, the pseudo-PNRD click-counting simulation methods, and the ORCA PT Series / DTU QCloud / Xanadu Aurora backends — see [gbs.md](gbs.md).

---

## Photonic circuit simulation

```python
from qpubench.schemas.mqsdk_photoq import (
    BeamsplitterSpec, MZISpec, PhaseShifterSpec,
    FockState, PhotonicCircuitSpec, PhotonicSimulationResult,
    PICPlatform, PhotonicChipArchitecture,
)
from qpubench.schemas.backend import BackendSpec

# Build a 4-mode linear-optics circuit
bs = BeamsplitterSpec(mode_a=0, mode_b=1, theta=0.7854, phi=0.0)   # 50:50
mzi = MZISpec(mode_a=2, mode_b=3, phi_inner=1.5708, phi_outer=0.0)
ps  = PhaseShifterSpec(mode=1, phi=3.14159)

circuit = PhotonicCircuitSpec(
    num_modes=4,
    beamsplitters=[bs],
    mzis=[mzi],
    phase_shifters=[ps],
    input_state=FockState(mode_occupations=[1, 0, 1, 0]),
)

# Simulation result
result = PhotonicSimulationResult(
    num_modes=4,
    output_state_amplitudes=[],    # filled by simulator
    sampling_time_s=0.012,
)

# Backend
backend = BackendSpec.photochipsim(num_modes=4)
```

---

## Single-photon sources

```python
from qpubench.schemas.mqsdk_photoq import SinglePhotonSourceSpec, PhotonSourceType

source = SinglePhotonSourceSpec(
    platform=PhotonSourceType.QUANTUM_DOT,
    indistinguishability=0.98,
    brightness=0.85,
    g2=0.002,
    wavelength_nm=925.0,
    repetition_rate_mhz=76.0,
)
```

---

## Hong-Ou-Mandel interference

```python
from qpubench.schemas.mqsdk_photoq import (
    HOMSpec, HOMResult, BeamsplitterSpec, SinglePhotonSourceSpec,
)

hom_spec = HOMSpec(
    source_a=source,
    source_b=source,
    beamsplitter=BeamsplitterSpec(mode_a=0, mode_b=1, theta=0.7854, phi=0.0),
    delay_ps=0.0,
)

hom_result = HOMResult(
    coincidence_rate=0.012,
    visibility=0.984,
    dip_depth=0.968,
    integration_time_s=60.0,
)
```

Store in `QuantumResult.hom_result`.

---

## Photon indistinguishability purification

```python
from qpubench.schemas.mqsdk_photoq import (
    IndistinguishabilityPurificationSpec,
    IndistinguishabilityPurificationResult,
)

spec = IndistinguishabilityPurificationSpec(
    input_sources=[source, source],
    purification_rounds=2,
    target_indistinguishability=0.999,
)

result = IndistinguishabilityPurificationResult(
    achieved_indistinguishability=0.997,
    loss_db=3.2,
    success_probability=0.125,
)
```

Store in `QuantumResult.indist_purification`.

---

## Photonic VQE

Variational optimization over a photonic linear-optics ansatz:

```python
from qpubench.schemas.mqsdk_photoq import PhotonicVQEConfig, PhotonicVQEStep, PhotonicVQEResult

config = PhotonicVQEConfig(
    num_modes=6,
    num_photons=3,
    max_iterations=200,
    optimizer="COBYLA",
    target_unitary_real=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],  # flattened 3×3
    target_unitary_imag=[0.0] * 9,
)

step = PhotonicVQEStep(iteration=0, energy=-1.23, parameters=[0.1, 0.5, -0.3])

vqe_result = PhotonicVQEResult(
    config=config,
    steps=[step],
    final_energy=-2.87,
    converged=True,
    final_parameters=[0.785, 1.571, -0.523, 0.314],
    num_iterations=47,
)
```

Store in `QuantumResult.photonic_vqe`.

---

## Sobol sensitivity analysis

```python
from qpubench.schemas.mqsdk_photoq import PhotonicSensitivityAnalysis, SobolParameterResult

analysis = PhotonicSensitivityAnalysis(
    num_modes=6,
    num_samples=1024,
    parameters=["theta_0", "phi_0", "theta_1", "phi_1"],
    sobol_results=[
        SobolParameterResult(parameter_name="theta_0", S1=0.42, ST=0.61),
        SobolParameterResult(parameter_name="phi_0",   S1=0.08, ST=0.15),
    ],
    total_variance=0.023,
)
```

Store in `QuantumResult.photonic_sensitivity`.

---

## FBQC (Fusion-Based QC)

```python
from qpubench.schemas.mqsdk_photoq import (
    ResourceStateSpec, ResourceStateType,
    FusionGateSpec, FusionType, FBQCRunConfig,
)

resource_state = ResourceStateSpec(
    state_type=ResourceStateType.LINEAR_4_PHOTON,
    num_photons=4,
)

fusion = FusionGateSpec(
    mode_a=1, mode_b=2,
    fusion_type=FusionType.TYPE_II,
    success_probability=0.5,
)

fbqc_config = FBQCRunConfig(
    resource_state=resource_state,
    logical_qubits=4,
    num_rounds=10,
    fusion_network=[fusion],
)
```

---

## Photonic analog Hamiltonian simulation

Simulates tight-binding propagation on a photonic waveguide array:

```python
from qpubench.schemas.mqsdk_photoq import (
    PhotonicAnalogHamiltonian, PhotonicAnalogSimConfig, PhotonicAnalogSimResult,
    FockState,
)

H = PhotonicAnalogHamiltonian(
    num_modes=4,
    coupling_matrix=[-1.0, 0.0, 0.0, -1.0, 0.0, -1.0, 0.0, 0.0,   # flattened 4×4
                      0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, -1.0],
    on_site_energies=[0.0, 0.0, 0.0, 0.0],
)

sim_config = PhotonicAnalogSimConfig(
    hamiltonian=H,
    evolution_time=1.5708,
    num_modes=4,
    initial_fock_state=FockState(mode_occupations=[1, 0, 0, 0]),
)

sim_result = PhotonicAnalogSimResult(
    config=sim_config,
    site_populations=[0.25, 0.25, 0.25, 0.25],
    energy_expectation=-1.0,
    evolution_time=1.5708,
)
```

Store in `QuantumResult.photonic_analog_sim`.

---

## Backends

```python
from qpubench.schemas.backend import BackendSpec

BackendSpec.photochipsim(num_modes=6)              # permanent-based, thewalrus
BackendSpec.strawberry_fields("fock", 6, cutoff_dim=5)
BackendSpec.perceval("SLOS", num_modes=6)          # Quandela SLOS / MPS / Naive
BackendSpec.photonic_chip_hardware("chip_001", "silicon_nitride", num_modes=8)
```
