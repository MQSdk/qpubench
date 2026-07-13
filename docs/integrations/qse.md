# QSE / KQD integration

qpubench models Krylov Quantum Diagonalization (KQD) and Quantum Subspace Expansion (QSE) in `src/qpubench/schemas/mqsdk_qse.py`. The schemas cover the algorithm families implemented in [MQSdk/qse](https://github.com/MQSdk/qse).

Computing model: `ComputingModel.GATE_BASED` (KQD is an algorithmic technique on top of gate-based circuits — see `KQDMethod`, not a separate paradigm)

---

## Algorithm overview

Three algorithm variants share the same pipeline structure:

| Variant | `KQDMethod` | How subspace is built |
|---|---|---|
| Standard KQD | `HADAMARD_TEST` | Modified Hadamard test measures ⟨ψ_{I,m}\|O\|ψ_{J,n}⟩ for all (ref, power) pairs |
| Sample-based KQD | `SAMPLE_BASED_SQD` | Krylov circuits measured in Fock basis; bitstrings post-selected by particle number |
| Multi-reference | `MULTI_REF_HADAMARD` / `MULTI_REF_SQD` | d_refs reference states each seed their own Krylov series |

All variants use Trotter time evolution U = e^{−iHdt} to generate the Krylov basis {U^k|Φ⟩}.

---

## Reference states

### Néel states (spin chains)

```python
from qpubench.schemas.mqsdk_qse import NeelStateSpec, KQDReferenceSpec, KQDReferenceStateType

# Two complementary Néel states for antiferromagnetic chain
ref0 = KQDReferenceSpec(
    state_type=KQDReferenceStateType.NEEL,
    bitstring="1010101010",
    neel=NeelStateSpec(num_spins=10, shift=0),
    label="neel_shift0",
)
ref1 = KQDReferenceSpec(
    state_type=KQDReferenceStateType.NEEL,
    bitstring="0101010101",
    neel=NeelStateSpec(num_spins=10, shift=1),
    label="neel_shift1",
)
```

### Slater determinants (chemistry)

```python
from qpubench.schemas.mqsdk_qse import SlaterDeterminantRef, KQDReferenceSpec, KQDReferenceStateType

# H2 in STO-3G: 2 active orbitals, 2 electrons (HF reference)
slater = SlaterDeterminantRef(
    ncas=2,         # 2 active spatial orbitals → 4 spin-orbitals
    occ_alpha=[0],  # α orbital 0 occupied
    occ_beta=[0],   # β orbital 0 occupied
)
print(slater.bitstring)      # "1010" (alpha_0=1, alpha_1=0, beta_0=1, beta_1=0)
print(slater.num_qubits)     # 4
print(slater.num_electrons)  # 2

ref_chem = KQDReferenceSpec(
    state_type=KQDReferenceStateType.SLATER_DET,
    bitstring=slater.bitstring,
    slater_det=slater,
    label="hf_reference",
)
```

---

## Time evolution

```python
from qpubench.schemas.mqsdk_qse import KQDTimeEvolutionSpec, KrylovTimeEvolutionVariant
import math

# dt = π / ‖H‖₂ (spectral norm)
dt = math.pi / 3.0

te_spec = KQDTimeEvolutionSpec(
    dt=dt,
    num_trotter_steps=6,
    variant=KrylovTimeEvolutionVariant.EFFICIENT_ALTERNATING,
)

print(te_spec.dt_circ)   # dt / 6 — Trotter step size for each sub-circuit
```

`EFFICIENT_ALTERNATING`: alternating forward/reverse Rxyz blocks (default in qse).  
`LIE_TROTTER`: Qiskit `PauliEvolutionGate` + `LieTrotter` synthesizer.

---

## KQD configuration

```python
from qpubench.schemas.mqsdk_qse import KQDConfig, KQDMethod, RegularizationConfig, EigensolverMethod

config = KQDConfig(
    method=KQDMethod.HADAMARD_TEST,
    krylov_dim=6,
    num_references=2,
    dt=dt,
    num_trotter_steps=6,
    regularization=RegularizationConfig(
        threshold=1.0e-6,       # discard S eigenvalues below ε
        num_eigenvalues_k=4,
        solver=EigensolverMethod.SCIPY_EIGH,
    ),
)
```

---

## Hadamard test path

The Hadamard test measures matrix elements of both the overlap matrix S and the projected Hamiltonian H:

```python
from qpubench.schemas.mqsdk_qse import (
    KrylovMatrixSpec, KrylovSubspaceMatrices,
    HadamardTestIterationResult,
    KrylovEigenResult,
)

# 6×6 subspace (krylov_dim=6, num_references=1)
dim = 6
S = KrylovMatrixSpec(
    label="S", dim=dim,
    matrix_real=[...],   # flattened 6×6 overlap matrix
    matrix_imag=[0.0] * 36,
)
H_mat = KrylovMatrixSpec(
    label="H", dim=dim,
    matrix_real=[...],   # flattened 6×6 projected Hamiltonian
    matrix_imag=[0.0] * 36,
)
matrices = KrylovSubspaceMatrices(
    S_matrix=S,
    H_matrix=H_mat,
    assembly_method="hadamard_test",
    krylov_dim=6,
)

# One Hadamard test measurement result
meas = HadamardTestIterationResult(
    circuit_label=[0, 3],    # reference 0, Krylov power 3
    observable_index=7,
    real_part=-0.4831,
    imag_part=0.0,
)

# Eigenvalue solve result
eigen = KrylovEigenResult(
    eigenvalues=[-4.258, -3.11, -2.01, -0.87, 0.45, 1.92],
    ground_state_energy=-4.258,
    S_eigenvalues=[0.99, 0.94, 0.85, 0.62, 0.31, 0.04],
    num_eigenvalues_discarded=0,
    krylov_dim_effective=6,
)
```

---

## Sample-based path (SQD)

The SQD path measures Krylov circuits in the computational basis and accumulates bitstrings across steps:

```python
from qpubench.schemas.mqsdk_qse import (
    SQDPostselectionConfig, SQDStep, SQDConvergenceResult,
    KrylovBitstringCounts, CumulativeKrylovCounts,
)

postsel = SQDPostselectionConfig(num_ones=2, min_unique=5)

steps = [
    SQDStep(krylov_step=0, num_bitstrings=14, subspace_dim=14, energy_hartree=-1.10),
    SQDStep(krylov_step=1, num_bitstrings=22, subspace_dim=22, energy_hartree=-1.128),
    SQDStep(krylov_step=2, num_bitstrings=28, subspace_dim=28, energy_hartree=-1.135),
    SQDStep(krylov_step=3, num_bitstrings=31, subspace_dim=31, energy_hartree=-1.1371),
]

sqd_result = SQDConvergenceResult(
    steps=steps,
    final_energy=-1.1371,
    exact_energy=-1.1373,
)
print(f"Error: {sqd_result.error_mha:.3f} mHa")   # milli-Hartree

# Cumulative bitstring pool
pool = CumulativeKrylovCounts(
    cumulative_counts=[
        {"1010": 42, "0110": 38, "1001": 35},    # after step 0
        {"1010": 78, "0110": 71, "1001": 64, "0101": 18},  # after step 1
    ],
    postselection=postsel,
    num_references_pooled=1,
)
```

---

## Cholesky decomposition

For molecular Hamiltonians, the two-electron integrals can be stored in low-rank Cholesky form:

```python
from qpubench.schemas.mqsdk_qse import CholeskyDecompositionSpec

chol = CholeskyDecompositionSpec(
    num_orbitals=4,     # H2 in cc-pVDZ: 4 spatial orbitals → 10 active
    eps=1.0e-6,         # pivoted Cholesky convergence threshold
    n_chol=12,          # number of Cholesky vectors retained
    max_cholesky=80,    # = 20 × num_orbitals
    accuracy=3.2e-7,    # max |V - LLᵀ| achieved
)
```

---

## Full pipeline

```python
from qpubench.schemas.mqsdk_qse import KQDPipelineSpec
from qpubench.schemas.result import QuantumResult
from qpubench.schemas.primitives import ComputingModel

pipeline = KQDPipelineSpec(
    num_qubits=10,
    hamiltonian_label="heisenberg_chain_10",
    kqd_config=config,
    time_evolution=te_spec,
    reference_states=[ref0, ref1],
    krylov_matrices=matrices,
    hadamard_results=[meas],
    eigen_result=eigen,
    exact_energy=-4.2588,
    hf_energy=None,         # not applicable for spin chain
    cholesky_spec=None,
)

result = QuantumResult(
    computing_model=ComputingModel.GATE_BASED,
    vendor_results={"kqd_pipeline": pipeline},
)
```

---

## Circuit family metadata

```python
from qpubench.schemas.mqsdk_qse import KrylovCircuitFamilySpec, KQDMethod

# Multi-reference Hadamard test: 2² × 6² = 144 circuits for (I,J,m,n)
fam = KrylovCircuitFamilySpec(
    method=KQDMethod.MULTI_REF_HADAMARD,
    num_qubits_system=10,
    krylov_dim=6,
    num_references=2,
    num_circuits=144,
    circuit_labels=[[i, j, m, n]
                    for i in range(2) for j in range(2)
                    for m in range(6) for n in range(6)],
    shots_per_circuit=2048,
    ancilla_qubits=1,
)
```

---

## Backend

```python
from qpubench.schemas.backend import BackendSpec

# Qiskit Aer for KQD (modality=KQD)
BackendSpec.qiskit_aer(method="statevector", num_qubits=12)
BackendSpec.qiskit_aer(method="matrix_product_state", num_qubits=40)
```

Noiseless statevector is the default for benchmarking; MPS extends reach to larger systems at the cost of bond dimension truncation.
