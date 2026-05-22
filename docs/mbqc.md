# MBQC FPGA

MBQC schemas are bit-exact against [`gitlab.com/johnrscott/mbqc-fpga`](https://gitlab.com/johnrscott/mbqc-fpga) commit `fde787d1` (files: `qubit.vhd`, `byproduct.vhd`, `adapt.vhd`, `ops_update.vhd`, `comm_correct.vhd`, `program.cpp`).

---

## 16-bit program word layout

```
bit:  15  14  13  12  11 | 10   9   8   7   6 |  5   4   3   2   1   0
      ──────────────────   ─────────────────────  ───────────────────────
      c_prog  (5 bits)     s_prog  (5 bits)        b_prog  (6 bits)
      CommutationSpec      AdaptiveSpec             ByproductUpdateSpec
```

`theta` (measurement angle) is **never** encoded in this word — it is an analog-domain quantity tracked in software only (`MBQCRound.theta`).

---

## `b_prog` — byproduct update (`ByproductUpdateSpec`)

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

---

## `s_prog` — adaptive measurement setting (`AdaptiveSpec`)

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

---

## `c_prog` — commutation correction (`CommutationSpec`)

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

---

## File formats

### Xilinx COE (single qubit)

`MBQCPattern.to_single_qubit_coe(qubit_idx)` — radix-2, one 16-bit binary word per line:

```
memory_initialization_radix=2;
memory_initialization_vector=
0000000000000000  ; round=0  theta=0.000000
0010100000000010  ; round=1  theta=-1.047198
```

### Xilinx COE (multi-qubit)

`MBQCPattern.to_multi_qubit_coe()` — radix-16, N qubits concatenated into one hex word per round.

### MTB CSV (testbench)

`MBQCExecutionResult.to_multi_qubit_csv()` — compatible with `mbqc2_tb.vhd`:

```
line,meas,ops,s
0,0001,00010000,0001
1,0010,00100001,0010
```

Parse back: `MBQCExecutionResult.from_multi_qubit_csv(csv_text, num_logical_qubits=N)`

---

## Measurement pattern

```python
from qpubench import MBQCPattern, MBQCRound, MBQCProgramWord
from qpubench.schemas.mbqc import AdaptiveSpec, ByproductUpdateSpec, CommutationSpec
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

---

## Fidelity metric

| Metric | Source | Formula |
|---|---|---|
| `UNITARY` | Qrack `GetUnitaryFidelity()` | Unitary overlap |
| `FUBINI_STUDY` | MBQC-FPGA `qsl::fubiniStudy()` | `1 - fubiniStudy(result, reference)` |

```python
from qpubench.schemas.result import FidelityResult
from qpubench.schemas.primitives import FidelityMetric

f = FidelityResult(fidelity=0.972, metric=FidelityMetric.FUBINI_STUDY, reference_label="Rx_pi_3")
```
