# GBS (Gaussian Boson Sampling) integration

qpubench models Gaussian Boson Sampling in `src/qpubench/schemas/mirrors/mqsdk_photoq.py` (the GBS section). This covers the Gaussian-state / hafnian-based formalism — **distinct from the LOQC section of the same module**, which uses the permanent-based / Fock-state formalism for linear-optics chips.

| | LOQC (permanent) | GBS (hafnian) |
|---|---|---|
| State representation | Fock states | Covariance matrix (Gaussian states) |
| Amplitude formula | Permanent | Hafnian |
| Hardware | MZI chips, boson samplers | Xanadu X8, Borealis TDM |
| Typical gate | BeamsplitterSpec / MZISpec | SqueezingGateSpec / S2GateSpec |

Computing model: `ComputingModel.GBS`. Qubit modality: `QubitModality.PHOTONIC`

---

## Direct GBS sampling

```python
from qpubench.schemas.mirrors.mqsdk_photoq import (
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

Store results in `QuantumResult.vendor_results["gbs_sampling"]`.

---

## Hafnian computation

```python
from qpubench.schemas.mirrors.mqsdk_photoq import (
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
from qpubench.schemas.mirrors.mqsdk_photoq import (
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

## Borealis TDM GBS

Xanadu Borealis uses a time-domain multiplexed (TDM) architecture with three fibre-loop delays [1, 6, 36] to realise 216 effective modes:

```python
from qpubench.schemas.mirrors.mqsdk_photoq import (
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
from qpubench.schemas.mirrors.mqsdk_photoq import ClusterStateSpec, GaussianStateType
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

## Pseudo-PNRD (click-counting) detectors & the four simulation methods

The photoq paper *"Classical simulation of Gaussian boson sampling with click-counting detectors"* studies GBS devices read out by **pseudo photon-number-resolving detectors** (pPNRD): a mode is demultiplexed across `N` on/off (click) detectors, and the detector reports the number `k ∈ {0, …, N}` of branches that clicked. This is the `GBSMeasurementType.PSEUDO_PNR` detector model.

```python
from qpubench.schemas.mirrors.mqsdk_photoq import (
    PseudoPNRDSpec, SimulationMethod, ClickPatternProbabilityResult,
    KensingtonianResult, MethodComparison, MPSSimulationConfig,
)
from qpubench.schemas.primitives import ComplexNumber

# One mode demultiplexed across N=4 on/off detectors.
det = PseudoPNRDSpec(num_branches=4, multiplexing="spatial")
det.collision_error(2)   # 0.4 — P(two of 2 photons share one of 4 branches)

# The full click-pattern distribution P(k), computed by method i.
dist = ClickPatternProbabilityResult(
    num_modes=2,
    num_branches=4,
    method=SimulationMethod.KENSINGTONIAN_FORMULA,
    click_patterns=[[0, 0], [1, 0], [0, 1], [1, 1]],
    probabilities=[0.61, 0.14, 0.14, 0.11],
    total_probability=1.0,
    computation_time_s=0.002,
)

# Method i also exposes the raw matrix-function value per pattern.
ken = KensingtonianResult(
    click_pattern=[1, 1], num_branches=4,
    value=ComplexNumber(re=0.11, im=0.0), probability=0.11,
)
```

The `SimulationMethod` enum names the paper's four methods (and one variant):

| `SimulationMethod` | Paper | Idea | photoq code |
|---|---|---|---|
| `KENSINGTONIAN_FORMULA` | i | Kensingtonian matrix function — the click-counting analogue of the hafnian (Eq. 26, arXiv:2305.00853) | `methods/kenform/` |
| `HAFNIAN_MODIFIED` | ii | Fock/hafnian probabilities modified by the pPNRD model `P_{k,n}(N)` | `methods/kenhaf/` |
| `TENSOR_NETWORK_MPS` | iii | Matrix-product-state simulation with a truncation-fidelity cutoff `f_t` | `methods/mps/`, `mps_fast/` |
| `BRUTE_FORCE_POVM` | iv | Explicit POVM trace (demultiplex + vacuum projection); `THERMAL_POVM` is the thermal-Gaussian variant | `methods/utility/ppnrd.py` |

Store a distribution in `QuantumResult.vendor_results["click_pattern_probability"]`.

### Method comparison

The paper's Figs. 5–11 compare the methods on one circuit (timing, TVD, KL, fidelity vs a reference method):

```python
mc = MethodComparison(
    num_modes=4, num_branches=4,
    reference_method=SimulationMethod.BRUTE_FORCE_POVM,
    methods=[SimulationMethod.KENSINGTONIAN_FORMULA, SimulationMethod.TENSOR_NETWORK_MPS],
    computation_time_s={"kensingtonian_formula": 0.01, "tensor_network_mps": 1.2},
    total_variation_distance={"tensor_network_mps": 3e-4},
    fidelity={"tensor_network_mps": 0.9997},
    mps_truncation_fidelity=0.999, mps_bond_dimension=100,
    circuit_label="clements_4mode",
)
```

The MPS parameters double as the DTU QCloud `tn-sampling` job knobs (see below):

```python
mps = MPSSimulationConfig(
    num_modes=8, physical_dimension=8, bond_dimension=100,
    truncation_fidelity=0.999, num_branches=4,
)
```

Store a comparison in `QuantumResult.vendor_results["method_comparison"]`.

---

## ORCA PT Series (time-bin interferometer)

ORCA's PT-1/PT-2 are **time-bin interferometers**: one physical beamsplitter plus one or more fibre delay loops, applied across `num_modes` time bins. Each loop couples every adjacent pair of bins, so a loop needs `num_modes - 1` beamsplitter angles.

```python
from qpubench.schemas.mirrors.mqsdk_photoq import (
    TimeBinInterferometerSpec, PTSeriesSamplingConfig,
    PTSeriesSamplingResult, PTSeriesInputType,
)
from qpubench.schemas.backend import BackendSpec

tbi = TimeBinInterferometerSpec(
    num_modes=8, num_loops=1,
    input_type=PTSeriesInputType.GBS,     # or FOCK / DISTINGUISHABLE (classical control)
    squeezing=[0.5] * 8,
    beamsplitter_angles=[0.4] * 7,        # length num_loops * (num_modes - 1)
)
tbi.num_angles_expected                   # 7

cfg = PTSeriesSamplingConfig(interferometer=tbi, num_samples=1000, device="PT-2")
res = PTSeriesSamplingResult(
    config=cfg, samples=[[0, 1, 0, 2, 1, 0, 0, 1]], mean_photon_number=1.2,
)

backend = BackendSpec.orca_pt_series(num_modes=8, num_loops=1, device="PT-2")
```

Store in `QuantumResult.vendor_results["pt_series_sampling"]`.

---

## DTU QCloud (REST API v1)

`qcloud.dtu.dk` exposes a Bearer-token REST API with two GBS job types: `tn-covariance` (build a covariance matrix server-side) and `tn-sampling` (tensor-network GBS sampling — the successor of the DASQ Kensingtonian sampler, aligned with the paper's MPS method).

```python
from qpubench.schemas.mirrors.mqsdk_photoq import (
    QCloudJobType, QCloudJobSpec, QCloudJobResult,
    TNCovarianceParams, TNSamplingParams,
)
from qpubench.schemas.backend import BackendSpec

cov = TNCovarianceParams(nmodes=64, r_db=8.0, loss=0.5, basis="pi4")
cov_job = QCloudJobSpec(
    job_type=QCloudJobType.TN_COVARIANCE, params=cov.model_dump(), worker="catlab",
)

tn = TNSamplingParams(cov_matrix=[1.0, 0.0, 0.0, 1.0], d=8, chi=100, dd=1, N=10_000, n=1)
sampling_job = QCloudJobSpec(
    job_type=QCloudJobType.TN_SAMPLING, params=tn.model_dump(), worker="tn-sampling",
)

result = QCloudJobResult(spec=sampling_job, status="succeeded", samples=[[0, 1, 2]])

backend = BackendSpec.dtu_qcloud(job_type="tn-sampling")
```

Store in `QuantumResult.vendor_results["qcloud_job"]`.

---

## Xanadu Aurora dataset

Aurora is the modular photonic quantum computer of *"Scaling and networking a modular photonic quantum computer"* (Nature 638, 2025): 35 chips, 84 squeezers, 36 PNRDs, 12 qubit modes per clock cycle. It is a published **dataset** (public S3 bucket `xanadu-aurora-data`), not a programmable device — two experiment sets: cluster-state acquisition and the decoder demo.

```python
from qpubench.schemas.mirrors.mqsdk_photoq import AuroraDatasetSpec, AuroraExperiment
from qpubench.schemas.backend import BackendSpec

spec = AuroraDatasetSpec(
    experiment=AuroraExperiment.DECODER_DEMO,
    condition="signal",            # signal | random | vacuum (decoder demo)
    batch_index=3,
    s3_key="decoder_demo/signal/batch_3/quadratures.npy",
)

backend = BackendSpec.xanadu_aurora(experiment="decoder_demo")
```

---

## Backends

```python
from qpubench.schemas.backend import BackendSpec

BackendSpec.strawberry_fields_gaussian(num_modes=8)   # local Gaussian simulator
BackendSpec.xanadu_x8(num_modes=8)                    # Xanadu X8 hardware (PNR)
BackendSpec.xanadu_borealis(via_braket=False)         # native SF RemoteEngine
BackendSpec.xanadu_borealis(via_braket=True)          # via AWS Braket BraketEngine
BackendSpec.orca_pt_series(num_modes=8, device="PT-2")  # ORCA PT Series TBI (simulated/hardware)
BackendSpec.dtu_qcloud(job_type="tn-sampling")        # DTU QCloud REST API v1
BackendSpec.xanadu_aurora(experiment="cluster_state") # Xanadu Aurora dataset
```
