# Cross-framework compatibility notes

These encoding differences cause silent errors when porting circuits or results between frameworks. They are encoded in the schema helper methods so you rarely need to deal with them directly, but understanding them prevents subtle bugs.

---

## Qubit ordering / endianness (Qiskit vs PennyLane)

Qiskit and PennyLane label qubits in **opposite order** when interpreting basis states:

- **Qiskit is little-endian**: qubit 0 is the *least* significant bit. The basis state is written `|q_{n-1} … q_1 q_0⟩`, so an X gate on qubit 0 of a 2-qubit register produces the statevector for `|01⟩` (decimal 1), and counts bitstrings put qubit 0 **rightmost**.
- **PennyLane is big-endian**: the first wire is the *most* significant bit. The basis state is `|q_0 q_1 … q_{n-1}⟩`, so the same X gate on wire 0 produces `|10⟩` (decimal 2), and samples put wire 0 **leftmost**.

The consequences when comparing runs across the two frameworks:

- Statevector amplitudes come back in a **permuted order** (bit-reversal of the index), even for the identical circuit.
- Counts histograms for the same circuit have their bitstring keys reversed.
- Multi-qubit observables must be mapped consistently: `Z ⊗ I` acts on *different* physical qubits under the two conventions.

qpubench's own containers fix one convention: `SparsePauliObservable` addresses qubits by explicit `qubit_indices` (no positional string ordering, so the estimator path is unaffected), and `ShotResult.counts` uses **MSB-first bitstrings with qubit 0 rightmost** (the Qiskit convention). Converting at the boundary is the adapter's job. When you post-process counts yourself, or compare stored records produced through different SDKs, check the bit order first; otherwise two physically identical runs will look like they disagree.

---

## Pauli integer encoding (Qrack vs Qiskit)

| Pauli | Qrack (Q# convention) | Qiskit C `QkBitTerm` |
|---|---|---|
| `I` | 0 | 0 |
| `X` | 1 | 0b0010 (2) |
| `Z` | **2** | 0b0001 (1) |
| `Y` | **3** | 0b0011 (3) |

**Qrack Z=2, Y=3, swapped from the alphabetical order most people expect.**

Always use:
```python
PauliLabel.Z.to_qrack_int()       # → 2 (correct)
PauliLabel.Y.to_qrack_int()       # → 3 (correct)
PauliLabel.Z.to_qiskit_c_bit_term()  # → 1 (correct)
```
Never hardcode `2` for Z or `3` for Y; the meaning flips between SDKs.

---

## Complex precision in Qiskit C bridges

`QkComplex64` (the Qiskit C API complex type) is two `float32` values, **not** `float64`.

Passing a Python `complex` (which is always `float64`) to a Qiskit-C ctypes bridge causes silent data corruption; the extra bytes are silently truncated, not an exception.

```python
# Correct: explicitly cast to numpy.complex64 before any ctypes call
import numpy as np
amp = np.complex64(0.707 + 0.707j)

# Wrong: passes float64 to a float32 slot
amp = 0.707 + 0.707j
```

The `ComplexNumber` model stores `re` and `im` as Python `float` (float64). If you are writing a Qiskit-C adapter, cast to `np.complex64` at the boundary.

---

## MBQC `ops` register bit order

In the MBQC-FPGA `byproduct.vhd`, the `ops` register encodes:

```
ops[0] = Z component
ops[1] = X component
```

This is **reversed** from the gate-based X-first convention many people assume. Treating bit 0 as X and bit 1 as Z silently produces wrong byproduct corrections.

The `MBQCQubitState.ops_z` and `ops_x` properties extract the correct bits:

```python
z_bit = state.ops_z   # ops & 1
x_bit = state.ops_x   # (ops >> 1) & 1
```

---

## MBQC byproduct update is a neighbourhood triple

`b_prog` conditions byproduct updates on `(m_below, m_self, m_above)`, three measurements from neighbouring qubits, not on a single measurement outcome.

```python
z_mask = 0b011   # update Z using m_below ^ m_self
spec = ByproductUpdateSpec(z_mask=z_mask, x_mask=0)
dz, dx = spec.update(m_below=1, m_self=0, m_above=0)
# dz = (1 & 1) ^ (0 & 1) ^ (0 & 0) = 1
```

Treating `m[0]` as the only relevant measurement silently miscomputes all byproduct updates.

---

## Shift register direction

In `adapt.vhd`, the 3-bit shift register is indexed:

```
sr[2] = most recent measurement outcome
sr[1] = one round ago
sr[0] = oldest
```

Iterating `sr` as `0 = most recent` produces wrong adaptive measurement settings. The schema preserves this convention; `AdaptiveSpec.compute_s()` accepts `shift_register` as a 3-bit integer with `sr[2]` as the MSB.

---

## `theta` is not in the COE file

The measurement angle `theta` is an **analog-domain** quantity. It is:
- stored in `MBQCRound.theta` for software simulation
- passed to the photon source directly in hardware
- **never** encoded in the 16-bit FPGA program word or the COE initialisation file

The COE file comments include `theta` as a human-readable annotation but it plays no role in the digital logic.

---

## Qrack `MeasureShots` output

Qrack's `MeasureShots` C function returns bitstring outcomes as packed **integers**, not per-qubit bit arrays. The Qrack adapter must convert:

```python
# Correct
bitstring = format(outcome, f"0{n_qubits}b")   # MSB-first (Qiskit convention)

# Wrong: iterating raw integer bytes
```

qpubench's `ShotResult.counts` uses MSB-first bitstrings throughout.

---

## OpenQASM 2.0 vs 3.0 gate names

Some gate names changed between QASM versions:

| Gate | QASM 2.0 | QASM 3.0 (`stdgates.inc`) |
|---|---|---|
| Hadamard | `h` | `h` (unchanged) |
| CNOT | `cx` | `cx` (unchanged) |
| Rx rotation | `rx(θ)` | `rx(θ)` (unchanged) |
| U3 | `u3(θ,φ,λ)` | `u(θ,φ,λ)` (renamed) |
| `u1` | `u1(λ)` | `p(λ)` (phase gate, renamed) |
| `u2` | `u2(φ,λ)` | removed from stdgates (use `u`) |

When serialising a `LayerGenome` to QASM via `to_circuit_spec()`, gate names are passed through as-is. If your genome uses `u3`, the output is QASM 2.0 compatible. Rename to `u` if you target QASM 3.0.

---

## Cebule qubit operator string format

Cebule's TN_QC_OPT task returns `qubit_operators` as space-separated `PauliLabel+index` tokens:

```
"X0 Y1 Z3"   →  X on qubit 0, Y on qubit 1, Z on qubit 3
```

Cebule delivers the operators and their coefficients as two parallel lists, so they convert in bulk:

```python
SparsePauliObservable.from_cebule_operators(operators, coefficients, num_qubits)
```

For observables you write by hand, use `Pauli()`; it reads the same token format, and accepts commas as well as spaces, so `Pauli("X0 Y1 Z3")` and `Pauli("X0,Y1,Z3")` are the same observable.
