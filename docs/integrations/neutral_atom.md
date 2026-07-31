# Neutral atom / AHS integration (Bloqade · Aquila)

qpubench models neutral-atom Analog Hamiltonian Simulation (AHS) in `src/qpubench/schemas/mirrors/quera_bloqade.py`.

| Component | Details |
|---|---|
| **SDK** | [Bloqade](https://github.com/QuEraComputing/bloqade) (QuEra) |
| **Hardware** | Aquila 256-qubit Rydberg QPU via AWS Braket |
| **Computing model** | `ComputingModel.ADIABATIC` |
| **Qubit modality** | `QubitModality.NEUTRAL_ATOM` |
| **Result field** | `QuantumResult.vendor_results["ahs_result"]` |
| **Backend factories** | `BackendSpec.aquila()`, `BackendSpec.bloqade_emulator()` |

In AHS, neutral Rubidium-87 atoms are trapped at programmable 2-D positions by optical tweezers. A global laser applies a time-dependent Rabi drive (Ω, φ) and detuning (Δ), evolving the system through the Rydberg blockade Hamiltonian:

```
H(t) = Ω(t)/2 · Σᵢ (e^{iφ(t)} |gᵢ⟩⟨rᵢ| + h.c.) - Δ(t) · Σᵢ nᵢ + Σᵢ<ⱼ C₆/rᵢⱼ⁶ · nᵢnⱼ
```

Measurement collapses each atom to ground (1) or Rydberg (0) state.

---

## Quick start

```python
from qpubench.schemas.mirrors.quera_bloqade import (
    AtomicSite, AtomArrangement, LatticeGeometryType,
    AHSDrivingField, AHSTimeSeries, AHSProgramSpec,
    AHSShotResult, AHSShotStatus, AHSTaskResult,
    NeutralAtomCoupling,
)
from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.result import QuantumResult
from qpubench.schemas.primitives import ComputingModel, QubitModality

# 1-D chain of 5 atoms at 6 µm spacing
sites = [AtomicSite(x=i * 6.0, y=0.0) for i in range(5)]
arrangement = AtomArrangement(
    sites=sites,
    lattice_type=LatticeGeometryType.CHAIN,
    lattice_spacing_um=6.0,
)

# Rabi amplitude: ramp up, hold, ramp down (π-pulse shape)
rabi = AHSTimeSeries(
    times_us=[0.0, 0.1, 0.9, 1.0],
    values=[0.0, 15.7, 15.7, 0.0],     # rad/µs
)
# Detuning: linear sweep from -30 to +30 rad/µs
detuning = AHSTimeSeries(
    times_us=[0.0, 1.0],
    values=[-30.0, 30.0],              # rad/µs
)
# Phase: constant at 0
phase = AHSTimeSeries(times_us=[0.0, 1.0], values=[0.0, 0.0])

field = AHSDrivingField(
    coupling=NeutralAtomCoupling.RYDBERG,
    rabi_amplitude=rabi,
    rabi_phase=phase,
    detuning=detuning,
)

program = AHSProgramSpec(
    atom_arrangement=arrangement,
    driving_fields=[field],
    total_duration_us=1.0,
    description="Z2 antiferromagnetic order preparation",
)
print(f"Effective qubits: {program.num_qubits}")   # 5
```

---

## Atom arrangements

### Pre-defined lattices

```python
from qpubench.schemas.mirrors.quera_bloqade import AtomicSite, AtomArrangement, LatticeGeometryType

# Square lattice 4×4
sites_sq = [
    AtomicSite(x=i * 6.0, y=j * 6.0)
    for i in range(4) for j in range(4)
]
sq = AtomArrangement(
    sites=sites_sq,
    lattice_type=LatticeGeometryType.SQUARE,
    lattice_spacing_um=6.0,
)
print(sq.num_sites)           # 16
print(sq.fill_fraction)       # 1.0

# Chain with a defect (empty site)
chain_sites = [AtomicSite(x=i * 5.0, y=0.0) for i in range(6)]
chain = AtomArrangement(
    sites=chain_sites,
    filling=[1, 1, 0, 1, 1, 1],   # site 2 missing
    lattice_type=LatticeGeometryType.CHAIN,
    lattice_spacing_um=5.0,
)
print(chain.num_filled_sites)  # 5
```

### Aquila constraints

- Minimum inter-site spacing: **4.0 µm**
- Field of view: **75 µm × 76 µm**
- Maximum sites: **256**

---

## Waveforms

### AHSTimeSeries (hardware format)

```python
from qpubench.schemas.mirrors.quera_bloqade import AHSTimeSeries

# Rabi amplitude: trapezoidal π-pulse over 1 µs
rabi = AHSTimeSeries(
    times_us=[0.0, 0.3, 0.7, 1.0],
    values=[0.0, 15.7, 15.7, 0.0],   # rad/µs
)
print(rabi.duration_us)    # 1.0
print(rabi.num_points)     # 4

# Detuning ramp: -30 → +30 rad/µs over 2 µs
det = AHSTimeSeries(
    times_us=[0.0, 2.0],
    values=[-30.0, 30.0],
)
```

### AHSWaveform (Bloqade builder format)

The compact form stores segment durations + boundary values before discretization.

```python
from qpubench.schemas.mirrors.quera_bloqade import AHSWaveform, AHSWaveformType

# Piecewise linear Rabi (required for Ω on hardware)
wf_rabi = AHSWaveform(
    waveform_type=AHSWaveformType.PIECEWISE_LINEAR,
    durations_us=[0.3, 0.4, 0.3],          # 3 segments → 1.0 µs total
    values=[0.0, 15.7, 15.7, 0.0],         # 4 boundary values
)
print(wf_rabi.total_duration_us)   # 1.0

# Piecewise constant phase (required for φ on hardware)
wf_phase = AHSWaveform(
    waveform_type=AHSWaveformType.PIECEWISE_CONSTANT,
    durations_us=[1.0],
    values=[0.0],
)

# Polynomial detuning: Δ(t) = -30 + 60t  (linear sweep)
wf_poly = AHSWaveform(
    waveform_type=AHSWaveformType.POLY,
    duration_us=1.0,
    values=[-30.0, 60.0],   # c₀ + c₁·t
)
```

### Aquila waveform constraints

| Field | Allowed shape | Range |
|---|---|---|
| Rabi amplitude Ω(t) | Piecewise linear | [0, 15.8] rad/µs |
| Phase φ(t) | Piecewise constant | [-99, 99] rad |
| Detuning Δ(t) | Piecewise linear | [-125, 125] rad/µs |
| Max slope dΩ/dt | n/a | 250 rad/µs² |
| Max slope dΔ/dt | n/a | 2500 rad/µs² |
| Time resolution | n/a | 0.001 µs |
| Max duration | n/a | 4.0 µs |

---

## Driving fields and programs

```python
from qpubench.schemas.mirrors.quera_bloqade import (
    AHSDrivingField, AHSProgramSpec, AHSLocalDetuning,
    NeutralAtomCoupling, SpatialModulationType,
)

# Global Rydberg drive
field = AHSDrivingField(
    coupling=NeutralAtomCoupling.RYDBERG,
    rabi_amplitude=rabi,
    rabi_phase=phase,
    detuning=detuning,
    spatial_modulation=SpatialModulationType.UNIFORM,
)

# Optional local detuning (experimental feature on Aquila)
# Effective detuning at site k: h_k × Δ_local(t)
local_det = AHSLocalDetuning(
    time_series=AHSTimeSeries(times_us=[0.0, 1.0], values=[0.0, 100.0]),
    site_coefficients=[0.0, 1.0, 0.0, 1.0, 0.0],  # alternating sites
)

program = AHSProgramSpec(
    atom_arrangement=arrangement,
    driving_fields=[field],
    local_detunings=[local_det],
    total_duration_us=1.0,
)
```

### Parametric sweeps

```python
from qpubench.schemas.mirrors.quera_bloqade import AHSBatchSpec

# Sweep detuning endpoint and Rabi max across 4 parameter sets
batch = AHSBatchSpec(
    variable_names=["detuning_end", "rabi_max"],
    parameter_values=[
        [-20.0, -10.0,   0.0,  10.0],   # detuning_end
        [ 10.0,  12.0,  14.0,  15.7],   # rabi_max
    ],
    num_shots_per_batch=100,
)
print(batch.batch_size)   # 4
```

---

## Hardware specification

```python
from qpubench.schemas.mirrors.quera_bloqade import AquilaDeviceSpec

hw = AquilaDeviceSpec()   # all Aquila defaults
print(hw.max_qubits)               # 256
print(hw.c6_rad_us_um6)            # 5420000.0  (van der Waals C₆)
print(hw.cost_per_shot_usd)        # 0.01

# Custom / future device
custom = AquilaDeviceSpec(max_qubits=512, max_pulse_duration_us=8.0)
```

---

## Results

### Shot structure

```python
from qpubench.schemas.mirrors.quera_bloqade import AHSShotResult, AHSShotStatus

shot = AHSShotResult(
    status=AHSShotStatus.SUCCESS,
    pre_sequence=[1, 1, 1, 1, 1],   # all atoms loaded
    post_sequence=[1, 0, 1, 0, 1],  # alternating Rydberg excitations (Z2 order)
)
print(shot.is_perfect_fill)   # True, usable for analysis

# Imperfect fill: site 2 missing before evolution
bad = AHSShotResult(
    status=AHSShotStatus.SUCCESS,
    pre_sequence=[1, 1, 0, 1, 1],
    post_sequence=[1, 0, 0, 0, 1],
)
print(bad.is_perfect_fill)   # False, excluded from default analysis
```

### Task result analysis

```python
from qpubench.schemas.mirrors.quera_bloqade import AHSTaskResult, AHSExecutionMetadata

task = AHSTaskResult(
    metadata=AHSExecutionMetadata(
        task_id="arn:aws:braket:us-east-1::task/abc123",
        device_id="arn:aws:braket:us-east-1::device/qpu/quera/Aquila",
        status="COMPLETED",
        cost_usd=0.10,
    ),
    num_shots_requested=10,
    shot_results=[...],   # list of AHSShotResult
)

# Analysis (perfect-fill shots only, matching Bloqade's filter_perfect_filling=True)
print(task.perfect_fill_shots)   # shots with all pre_sequence == 1 and SUCCESS
print(task.bitstrings)           # [[1,0,1,0,1], [0,1,0,1,0], ...]
print(task.counts)               # {"10101": 47, "01010": 43, ...}
print(task.rydberg_densities)    # [0.48, 0.51, 0.47, 0.52, 0.49], P(Rydberg) per site
```

### Attach to QuantumResult

```python
result = QuantumResult(
    computing_model=ComputingModel.ADIABATIC,
    qubit_modality=QubitModality.NEUTRAL_ATOM,
    vendor_results={"ahs_result": task},
)
```

---

## Backends

```python
from qpubench.schemas.backend import BackendSpec

# QuEra Aquila QPU via AWS Braket (hardware)
aquila = BackendSpec.aquila(aws_region="us-east-1")
# name="aquila", provider="quera", simulator=False

# Bloqade Python local emulator (exact statevector, no credentials)
emulator = BackendSpec.bloqade_emulator(num_qubits=12)
# name="bloqade_python", provider="bloqade", simulator=True
```

---

## Bloqade builder → qpubench mapping

Bloqade uses a fluent builder API to construct programs. The mapping to qpubench types:

| Bloqade builder call | qpubench type |
|---|---|
| `start.add_position([(x,y), ...])` | `AtomArrangement(sites=[AtomicSite(x,y), ...])` |
| `Square(n, lattice_spacing=6.0)` | `AtomArrangement(lattice_type=SQUARE, lattice_spacing_um=6.0)` |
| `.rydberg.detuning.uniform.piecewise_linear(durations, values)` | `AHSDrivingField(coupling=RYDBERG, detuning=AHSTimeSeries(...))` |
| `.rydberg.amplitude.uniform.piecewise_linear(...)` | `AHSDrivingField(rabi_amplitude=AHSTimeSeries(...))` |
| `.rydberg.phase.uniform.piecewise_constant(...)` | `AHSDrivingField(rabi_phase=AHSTimeSeries(...))` |
| `.batch_assign(var=[v1, v2, ...])` | `AHSBatchSpec(variable_names=["var"], parameter_values=[[v1, v2, ...]])` |
| `result.report.bitstrings()` | `AHSTaskResult.bitstrings` |
| `result.report.counts()` | `AHSTaskResult.counts` |
| `result.report.rydberg_densities()` | `AHSTaskResult.rydberg_densities` |
| `shot.pre_sequence` | `AHSShotResult.pre_sequence` |
| `shot.post_sequence` | `AHSShotResult.post_sequence` |
