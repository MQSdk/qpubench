# GBS (Gaussian Boson Sampling) integration

qpubench models Gaussian Boson Sampling in `src/qpubench/schemas/gbs.py`. This covers the Gaussian-state / hafnian-based formalism — **distinct from `photonic.py`** which uses the permanent-based / Fock-state formalism for linear-optics chips.

| | `photonic.py` | `gbs.py` |
|---|---|---|
| State representation | Fock states | Covariance matrix (Gaussian states) |
| Amplitude formula | Permanent | Hafnian |
| Hardware | MZI chips, boson samplers | Xanadu X8, Borealis TDM |
| Typical gate | BeamsplitterSpec / MZISpec | SqueezingGateSpec / S2GateSpec |

Modality: `QPUModality.GBS`

---

## Direct GBS sampling

```python
from qpubench.schemas.gbs import (
    SqueezingGateSpec, S2GateSpec, RotationGateSpec,
    InterferometerSpec, GBSProgramSpec, GBSMeasurementType,
    GBSSamplingConfig, GBSSamplingResult, GBSSample,
)
from qpubench.schemas.backend import BackendSpec

# 4-mode GBS program
prog = GBSProgramSpec(
    num_modes=4,
    squeezing_params=[
        SqueezingGateSpec(mode_index=0, r=0.8, phi=0.0),
        SqueezingGateSpec(mode_index=1, r=0.8, phi=0.0),
        SqueezingGateSpec(mode_index=2, r=0.8, phi=0.0),
        SqueezingGateSpec(mode_index=3, r=0.8, phi=0.0),
    ],
    interferometer=InterferometerSpec(
        mode_indices=[0, 1, 2, 3],
        unitary_real=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],  # 4×4 identity
        unitary_imag=[0.0] * 16,
        source="random_haar",
    ),
    measurement_type=GBSMeasurementType.FOCK,
)

config = GBSSamplingConfig(
    program=prog,
    num_samples=1000,
    backend_type="gaussian_simulator",
)

sample = GBSSample(photon_numbers=[2, 0, 1, 1])
print(sample.total_photons)   # 4
print(sample.num_clicks)      # 3

backend = BackendSpec.strawberry_fields_gaussian(num_modes=4)
```

Store results in `QuantumResult.gbs_sampling`.

---

## Hafnian computation

```python
from qpubench.schemas.gbs import (
    GaussianStateSpec, HafnianMatrixSpec,
    HafnianComputationSpec, HafnianResult,
    QuadratureOrdering,
)
from qpubench.schemas.primitives import ComplexNumber

# Covariance matrix (XP_BLOCKS ordering: [x1,x2,...,p1,p2,...])
state = GaussianStateSpec(
    num_modes=2,
    mean_vector=[0.0, 0.0, 0.0, 0.0],
    covariance_matrix=[1.5, 0.0, 0.0, 0.0,    # flattened 4×4
                       0.0, 1.5, 0.0, 0.0,
                       0.0, 0.0, 0.5, 0.0,
                       0.0, 0.0, 0.0, 0.5],
    quadrature_ordering=QuadratureOrdering.XP_BLOCKS,
)

haf_spec = HafnianComputationSpec(
    B_real=[0.0, 0.6, 0.6, 0.0],   # 2×2 flattened
    B_imag=[0.0, 0.0, 0.0, 0.0],
    output_pattern=[1, 1],           # detect 1 photon in each mode
)

haf_result = HafnianResult(
    hafnian=ComplexNumber(re=0.6, im=0.0),
    probability=0.0947,
    method="thewalrus",
)
```

---

## Graph-based GBS (clique finding)

Encode a graph adjacency matrix into a GBS device via Takagi decomposition, then use the photon-number samples to find dense subgraphs (cliques).

```python
from qpubench.schemas.gbs import (
    GBSGraphConfig, GraphScalingMethod,
    TakagiDecompositionSpec, GBSCliqueFindingResult,
)

config = GBSGraphConfig(
    adjacency_matrix=[0.0, 1.0, 1.0, 0.0,   # 4-node graph, flattened
                      1.0, 0.0, 1.0, 1.0,
                      1.0, 1.0, 0.0, 1.0,
                      0.0, 1.0, 1.0, 0.0],
    num_nodes=4,
    num_photons=2,
    num_samples=10_000,
    scaling_method=GraphScalingMethod.DIVIDE_BY_MAX,
)

takagi = TakagiDecompositionSpec(
    num_modes=4,
    singular_values=[0.95, 0.87, 0.44, 0.12],
    unitary_real=[1, 0, 0, 0, 0, 1, 0, 0,   # 4×4 Takagi unitary
                  0, 0, 1, 0, 0, 0, 0, 1],
    unitary_imag=[0.0] * 16,
)

result = GBSCliqueFindingResult(
    config=config,
    takagi=takagi,
    num_samples_completed=10_000,
    shrunk_cliques=[[0, 1, 2], [1, 2, 3]],
    searched_cliques=[[0, 1, 2], [0, 2, 3], [1, 2, 3]],
    mean_density=0.82,
    mean_clique_size=3.0,
    max_clique_size=3,
    min_clique_size=3,
)
```

Store in `QuantumResult.gbs_clique_finding`.

---

## Vibronic spectra (GAMESS + Duschinsky + GBS)

Compute Frank-Condon profiles for molecular electronic transitions using GBS:

```python
from qpubench.schemas.gbs import (
    VibronicSpectrumConfig, NormalModeData, DuschinskyResult,
    VibronicGBSParams, VibronicSpectrumResult,
)

config = VibronicSpectrumConfig(
    molecule_name="water",
    ground_state_file="Ground_Water.out.txt",
    excited_state_file="Excited_Water.txt",
    temperature_K=0.0,
    num_samples=50_000,
    freq_range_cm1=(-1000.0, 8000.0),
)

ground = NormalModeData(
    num_atoms=3,
    num_modes=3,
    equilibrium_geometry=[0.0, -0.121, 0.0, 1.425, 0.962, 0.0, -1.425, 0.962, 0.0],
    normal_mode_vectors=[1.0] * 9,
    frequencies_cm1=[1595.0, 3657.0, 3756.0],
    atomic_masses_amu=[15.995, 1.008, 1.008],
)

duschinsky = DuschinskyResult(
    num_modes=3,
    rotation_matrix_Ud=[1, 0, 0, 0, 1, 0, 0, 0, 1],  # 3×3 flattened
    displacement_delta=[0.01, 0.02, 0.0],
)

gbs_params = VibronicGBSParams(
    num_modes=3,
    t=[0.1, 0.05, 0.0],
    U1_real=[1, 0, 0, 0, 1, 0, 0, 0, 1],
    U1_imag=[0.0] * 9,
    r=[0.2, 0.15, 0.05],
    U2_real=[1, 0, 0, 0, 1, 0, 0, 0, 1],
    U2_imag=[0.0] * 9,
    alpha_real=[0.0, 0.0, 0.0],
    alpha_imag=[0.0, 0.0, 0.0],
)

spectrum = VibronicSpectrumResult(
    config=config,
    ground_state_data=ground,
    duschinsky=duschinsky,
    gbs_params=gbs_params,
    sample_energies_cm1=[0.0, 1595.0, 3657.0],
    histogram_bins=[0.0, 1000.0, 2000.0, 4000.0],
    histogram_counts=[50.0, 30.0, 20.0],
)
```

Store in `QuantumResult.vibronic_spectrum`.

---

## Borealis TDM GBS

Xanadu Borealis uses a time-domain multiplexed (TDM) architecture with three fibre-loop delays [1, 6, 36] to realise 216 effective modes:

```python
from qpubench.schemas.gbs import (
    TDMDelaySpec, TDMGBSConfig, TDMGBSResult, TDMSqueezingLevel,
)

delays = TDMDelaySpec(delays=[1, 6, 36], effective_modes=216)

tdm_config = TDMGBSConfig(
    delays=delays,
    squeezing_level=TDMSqueezingLevel.HIGH,
    num_shots=50_000,
    crop=True,
    num_modes_requested=216,
    device_arn="arn:aws:braket:us-east-1::device/qpu/xanadu/Borealis",
)

tdm_result = TDMGBSResult(
    config=tdm_config,
    num_modes_effective=216,
    num_shots_completed=50_000,
    mean_photon_per_mode=1.21,
    sampling_time_s=47.3,
)
```

Store in `QuantumResult.tdm_gbs`.

```python
backend = BackendSpec.xanadu_borealis(via_braket=True)
```

---

## CV cluster states

```python
from qpubench.schemas.gbs import ClusterStateSpec, GaussianStateType
import math

cluster = ClusterStateSpec(
    state_type=GaussianStateType.CLUSTER_1D,
    num_nodes=5,
    squeezing_r=0.5,
    measurement_angles=[0.0, math.pi / 4, math.pi / 2, 0.0, math.pi / 4],
    boundary_condition="open",
)
```

---

## Backends

```python
from qpubench.schemas.backend import BackendSpec

BackendSpec.strawberry_fields_gaussian(num_modes=8)   # local simulator
BackendSpec.xanadu_x8(num_modes=8)                   # Xanadu X8 hardware (PNR)
BackendSpec.xanadu_borealis(via_braket=False)         # native SF RemoteEngine
BackendSpec.xanadu_borealis(via_braket=True)          # via AWS Braket BraketEngine
```
