# Compute architectures: CPUs, GPUs, and FPGAs

Every simulator benchmark in qpubench ultimately runs on classical hardware, and *which* classical hardware is a benchmark variable in its own right: the same circuit on the same simulator can differ by orders of magnitude in wall-clock time between a laptop CPU, a data-center GPU, and dedicated FPGA control logic. This page explains how each architecture is used by the simulators qpubench supports, and how to record which one you ran on.

A statevector simulation of `n` qubits stores `2^n` complex amplitudes (16 bytes each in double precision): ~16 MB at 20 qubits, ~16 GB at 30, ~16 TB at 40. CPUs handle small-to-medium circuits comfortably; GPUs push the practical statevector ceiling several qubits higher and dominate on deep circuits with many shots; FPGAs are not used for amplitude simulation at all, but for the *real-time control logic* that measurement-based (MBQC) computing needs between measurement rounds.

## At a glance

| Simulator | Registered via | CPU | GPU | Notes |
|---|---|---|---|---|
| Qiskit Aer (IBM) | `AerAdapter` | ✅ default | ✅ `qiskit-aer-gpu` | `AerSimulator(device="GPU")`, NVIDIA cuStateVec/Thrust |
| PennyLane Lightning (Xanadu) | `PennyLaneLightningAdapter` | ✅ `lightning.qubit` | ✅ `lightning.gpu` / `lightning.kokkos` | `lightning.gpu` uses NVIDIA cuQuantum; Kokkos also targets AMD HIP |
| CUDA-Q (NVIDIA) | `BackendSpec.cudaq(target=...)` | ✅ `qpp-cpu` | ✅ `nvidia`, `tensornet` | GPU-first by design; multi-GPU tensor-network target |
| Qrack | `QrackAdapter` (stub) | ✅ | ✅ OpenCL/CUDA | Vendor-neutral GPU support (NVIDIA, AMD, Intel) |
| AWS Braket local | `BraketAdapter` (`device_arn="local"`) | ✅ | — | CPU statevector/density-matrix |
| Strawberry Fields (Xanadu, photonic) | `BackendSpec.strawberry_fields(...)` | ✅ `fock` / `gaussian` | ✅ `tf` backend | The TensorFlow backend runs on GPU if TensorFlow sees one |
| thewalrus / photochipsim (photonic) | `BackendSpec.photochipsim(...)` | ✅ multithreaded | — | Hafnian/permanent computation is CPU-parallel |
| Bloqade emulator (neutral atom) | `BackendSpec.bloqade_emulator(...)` | ✅ | — | Exact statevector, practical to ~20 atoms |
| Stub adapters | `StubGateAdapter` / `StubMBQCAdapter` | ✅ | — | No SDK; random results for pipeline testing |
| MBQC-FPGA | copy `backend_adapter_template.py` | — | — | **FPGA** — real-time MBQC control logic, see below |

## CPUs — the default everywhere

Every adapter qpubench ships runs on CPU out of the box, with no extra installation:

- **Qiskit Aer** (`AerAdapter`) uses OpenMP-parallelized statevector and QASM methods; Aer also offers `matrix_product_state` and `stabilizer` methods (`BackendSpec.qiskit_aer(method=...)`) that trade generality for much larger tractable circuits on CPU.
- **PennyLane `lightning.qubit`** (`PennyLaneLightningAdapter`, `BackendSpec.lightning_qubit()`) is Xanadu's C++ OpenMP statevector kernel.
- **Braket's local backend** (`BraketAdapter` with `device_arn="local"`) runs Amazon's CPU statevector simulator with no AWS account.
- **Photonic simulators** (Strawberry Fields Fock/Gaussian backends, photochipsim via thewalrus) compute permanents and hafnians — `#P`-hard matrix functions — with multithreaded CPU code; this is exactly why Gaussian boson sampling is a quantum-advantage candidate.
- **Bloqade's Python emulator** integrates the neutral-atom Rydberg Hamiltonian exactly on CPU up to roughly 20 atoms.

For benchmarking, CPU runs are the reproducibility baseline: results depend only on core count and BLAS/OpenMP settings, not on driver/toolkit versions.

## GPUs — same adapters, bigger circuits

GPU execution is available in the SDKs behind several supported simulators. qpubench's shipped adapters construct the CPU defaults; switching to GPU is a one-line change in a copied adapter (adapters are plain classes — copy, edit, register under a new name, and the records stay comparable):

- **Qiskit Aer (IBM)** — install `qiskit-aer-gpu` (Linux + NVIDIA CUDA) and construct `AerSimulator(device="GPU")` inside your copy of `AerAdapter`; with cuQuantum installed, `cuStateVec_enable=True` switches the kernel to NVIDIA's cuStateVec library. Statevector, density-matrix, unitary, and tensor-network methods all run on GPU.
- **PennyLane (Xanadu)** — replace `lightning.qubit` with `lightning.gpu` (`pennylane-lightning-gpu`, backed by cuQuantum cuStateVec, NVIDIA only) or `lightning.kokkos` (Kokkos kernels — CUDA, AMD HIP, or OpenMP, chosen at build time) in your copy of `PennyLaneLightningAdapter`.
- **CUDA-Q (NVIDIA)** — GPU-first by design: `BackendSpec.cudaq(target="nvidia")` describes the GPU statevector target, `target="tensornet"` the (multi-)GPU tensor-network contraction target, and `target="qpp-cpu"` the CPU fallback.
- **Qrack** — uniquely vendor-neutral: OpenCL kernels run on NVIDIA, AMD, and Intel GPUs alike (plus a CUDA build). `qrack_adapter.py` is still a stub; the schema side (`BackendSpec`, `avg_gate_fidelity` from `GetUnitaryFidelity()`) is ready.
- **Strawberry Fields (Xanadu, photonic)** — the `"tf"` backend (`BackendSpec.strawberry_fields(backend="tf", ...)`) executes the Fock-space simulation as a TensorFlow graph, which runs on GPU whenever TensorFlow detects one.

Because a GPU-backed adapter is registered under its own name, a CPU-vs-GPU comparison is just a two-backend `sweep()`:

```python
records = runner.sweep(
    circuits=[circuit],
    backend_names=["aer_cpu", "aer_gpu"],
    options_list=[ExecutionOptions(shots=8192)],
    run_id="cpu_vs_gpu",
)
```

The per-record `result.total_time_s` / `result.qpu_time_s` timings then give you the architecture comparison directly from the store.

## FPGAs — real-time control for MBQC

FPGAs enter quantum benchmarking in a different role: not simulating amplitudes, but making **feed-forward decisions faster than decoherence**. In measurement-based quantum computing (MBQC), each measurement outcome determines the basis of later measurements, so byproduct tracking and adaptive-setting logic must run in real time between rounds — a job for dedicated hardware, not a Python process. qpubench models the FPGA control program of [`gitlab.com/johnrscott/mbqc-fpga`](https://gitlab.com/johnrscott/mbqc-fpga) bit-exactly (commit `fde787d1`; files: `qubit.vhd`, `byproduct.vhd`, `adapt.vhd`, `ops_update.vhd`, `comm_correct.vhd`, `program.cpp`), so an MBQC-on-FPGA run produces the same `BenchmarkRecord` as any simulator run.

The subsections below are the full reference for that FPGA program format.

### 16-bit program word layout

```
bit:  15  14  13  12  11 | 10   9   8   7   6 |  5   4   3   2   1   0
      ──────────────────   ─────────────────────  ───────────────────────
      c_prog  (5 bits)     s_prog  (5 bits)        b_prog  (6 bits)
      CommutationSpec      AdaptiveSpec             ByproductUpdateSpec
```

`theta` (measurement angle) is **never** encoded in this word — it is an analog-domain quantity tracked in software only (`MBQCRound.theta`).

### `b_prog` — byproduct update (`ByproductUpdateSpec`)

Bits [5:0] encode XOR masks applied to the neighbourhood measurement triple `(m_below, m_self, m_above)` (from `ops_update.vhd`):

```
update_z = (m[0] & z_mask[0]) ^ (m[1] & z_mask[1]) ^ (m[2] & z_mask[2])
update_x = (m[0] & x_mask[0]) ^ (m[1] & x_mask[1]) ^ (m[2] & x_mask[2])

m[0] = qubit below (or 0 at boundary)
m[1] = self
m[2] = qubit above (or 0 at boundary)
```

| Field | Bits | Description |
|---|---|---|
| `z_mask` | [2:0] | 3-bit mask — selects which neighbours update Z byproduct |
| `x_mask` | [5:3] | 3-bit mask — selects which neighbours update X byproduct |

```python
spec = ByproductUpdateSpec(z_mask=0b011, x_mask=0b100)
dz, dx = spec.update(m_below=1, m_self=0, m_above=1)
```

`ops` register convention: **bit 0 = Z, bit 1 = X** (reversed from gate-based X-first order).

### `s_prog` — adaptive measurement setting (`AdaptiveSpec`)

Bits [10:6] compute the adaptive measurement setting `s` (from `adapt.vhd`):

```
s = (sr[0] & sr_mask[0]) ^ (sr[1] & sr_mask[1]) ^ (sr[2] & sr_mask[2])
  ^ (ops_stored_z & z_byp_enable)
  ^ (ops_stored_x & x_byp_enable)
```

Shift register direction: `sr[2]` = most recent, `sr[0]` = oldest.  
`ops_stored` is latched at gate boundaries (`CommutationSpec.store_ops=True`).

| Field | Bits | Description |
|---|---|---|
| `sr_mask` | [2:0] | 3-bit — selects shift-register positions |
| `z_byp_enable` | [3] | XOR in stored Z byproduct |
| `x_byp_enable` | [4] | XOR in stored X byproduct |

```python
spec = AdaptiveSpec(sr_mask=0b011, z_byp_enable=True, x_byp_enable=False)
s = spec.compute_s(shift_register=0b101, ops_stored_z=1, ops_stored_x=0)
```

### `c_prog` — commutation correction (`CommutationSpec`)

Bits [15:11] control CNOT byproduct commutation (from `comm_correct.vhd`):

| Field | Bit(s) | Description |
|---|---|---|
| `store_ops` | [0] | Copy `ops_current → ops_stored` on `clk_r` (gate boundary) |
| `cnot_enable` | [1] | Enable CNOT commutation correction |
| `role` | [3:2] | CNOT role and neighbour direction (see table below) |
| `add_const` | [4] | Add constant correction directly to ops |

**CNOT role encoding** (when `cnot_enable=1`, `add_const=0`):

| `role` | Qubit role | Direction |
|---|---|---|
| `0b11` | Control | Target above |
| `0b10` | Target | Control above |
| `0b01` | Control | Target below |
| `0b00` | Target | Control below |

Convenience constructors:
```python
CommutationSpec.gate_boundary()                  # store_ops=True
CommutationSpec.cnot_control_target_below()      # role=0b01
CommutationSpec.cnot_target_control_above()      # role=0b10
CommutationSpec.cnot_control_target_above()      # role=0b11
CommutationSpec.cnot_target_control_below()      # role=0b00
```

### File formats

**Xilinx COE (single qubit)** — `MBQCPattern.to_single_qubit_coe(qubit_idx)`, radix-2, one 16-bit binary word per line:

```
memory_initialization_radix=2;
memory_initialization_vector=
0000000000000000  ; round=0  theta=0.000000
0010100000000010  ; round=1  theta=-1.047198
```

**Xilinx COE (multi-qubit)** — `MBQCPattern.to_multi_qubit_coe()`, radix-16, N qubits concatenated into one hex word per round.

**MTB CSV (testbench)** — `MBQCExecutionResult.to_multi_qubit_csv()`, compatible with `mbqc2_tb.vhd`:

```
line,meas,ops,s
0,0001,00010000,0001
1,0010,00100001,0010
```

Parse back: `MBQCExecutionResult.from_multi_qubit_csv(csv_text, num_logical_qubits=N)`

### Measurement pattern

```python
from qpubench import MBQCPattern, MBQCRound, MBQCProgramWord
from qpubench.schemas.mirrors.johnrscott_mbqc_fpga import AdaptiveSpec, ByproductUpdateSpec, CommutationSpec
import math

# 4-round single-qubit Rx(π/3)
pattern = MBQCPattern(
    num_logical_qubits=1,
    rounds=[
        [MBQCRound(
            theta=theta,
            program_word=MBQCProgramWord(
                byproduct_update=ByproductUpdateSpec.from_b_prog(b),
                adaptive=AdaptiveSpec.from_s_prog(s),
                commutation=CommutationSpec.from_c_prog(c),
            ),
        )]
        for (theta, s, b, c) in [
            (0.0,         0b000010, 0b01100, 0b00001),
            (-math.pi/3,  0b010000, 0b10100, 0b00000),
            (0.0,         0b000010, 0b01101, 0b00000),
            (0.0,         0b010000, 0b00000, 0b00000),
        ]
    ],
)

print(pattern.to_single_qubit_coe(qubit_idx=0))
```

### Fidelity metric

| Metric | Source | Formula |
|---|---|---|
| `UNITARY` | Qrack `GetUnitaryFidelity()` | Unitary overlap |
| `FUBINI_STUDY` | MBQC-FPGA `qsl::fubiniStudy()` | `1 - fubiniStudy(result, reference)` |

```python
from qpubench.schemas.result import FidelityResult
from qpubench.schemas.primitives import FidelityMetric

f = FidelityResult(fidelity=0.972, metric=FidelityMetric.FUBINI_STUDY, reference_label="Rx_pi_3")
```

## Recording which architecture you ran on

The record format already captures most of what an architecture comparison needs: `BackendSpec.name`/`provider` identify the simulator variant (register CPU and GPU variants under distinct names, e.g. `"aer_cpu"` / `"aer_gpu"`), and `QuantumResult.total_time_s` captures wall-clock time. For anything else — GPU model, driver version, core count — use `tags` and `notes` on `runner.run()` so the information is queryable from the store later:

```python
record = runner.run(circuit, "aer_gpu", shots=8192,
                    tags=["gpu", "rtx4090"],
                    notes="qiskit-aer-gpu 0.17, CUDA 12.4")
```
