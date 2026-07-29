# QrackAdapter — implementation record

`src/qpubench/backends/qrack_adapter.py` is **implemented**. `run()` executes
both the estimator and the sampler path against a real PyQrack simulator; the
tests in `tests/test_qrack_adapter.py` run it for real on the CPU, with no
credentials and no GPU.

This file used to hold the *plan*. It now holds what changed between that plan
and the working code, because several points in it were wrong against the
PyQrack that actually ships — worth knowing if you write another ctypes-backed
adapter.

## What the plan got wrong

Verified against **pyqrack 2.14.0**.

**1. `pauli_expectation` does not sum an observable's terms.** The plan called
`to_qrack_flat_arrays()` once per observable, concatenating every term's qubits
and Paulis into one call. Qrack's `PauliExpectation` computes the expectation
of a *single Pauli tensor product* — the product over the listed qubits — so
even setting aside the wrong quantity, a multi-term observable repeats qubit
indices, and Qrack's C++ layer rejects that from
`ExpectationFloatsFactorized()` with `std::invalid_argument`. That exception
cannot cross the ctypes boundary: it reaches `terminate()` and aborts the
interpreter. Not an exception you can catch — a core dump.

The adapter therefore calls `pauli_expectation` **once per term** and sums the
coefficient-weighted results. `to_qrack_flat_arrays()` is left in
`schemas/observable.py` for the different multi-term C entry point it was
written for, and is deliberately unused here.

**2. The Python layer builds the ctypes arrays for you.** The plan constructed
`(c_ulonglong * n)(*qubits)` by hand and passed pointers. `QrackSimulator`
methods now take plain Python lists — `pauli_expectation(q, b)`,
`measure_shots(q, s)` — and marshal internally via `_ulonglong_byref`. No
`ctypes` import is needed in the adapter at all.

**3. `QRACK_FPPOW` no longer matters at this layer.** The plan said to branch on
`c_float` vs `c_double` by reading the env var. PyQrack handles precision
internally and returns Python floats; the env var still selects the build's
precision, but the adapter never sees it.

**4. `release()` does not free the simulator.** It releases a *qubit*
(`release(self, q)`). `QrackSimulator.__del__` calls `destroy(sid)`, so a
simulator is freed when it goes out of scope. The adapter allocates one per
`run()` and lets it fall out of scope — which also guarantees runs are
independent, since Qrack mutates state in place.

**5. `get_unitary_fidelity()` has an explicit reset now.** The plan warned that
reading it resets the accumulator. There is now `reset_unitary_fidelity()`, and
`m_all()` resets it as a side effect — so the meaningful place to read it is
the estimator path, before any measurement. It is only informative under
approximate simulation (`set_sdrp`); exact simulation reports 1.0.

**6. Constructor keyword is `qubit_count`, not `qubitCount`.** And near-Clifford
mode is `is_near_clifford_tableau_writer`.

## Circuit loading

PyQrack has no QASM parser. The adapter reuses
`backends/_qiskit_common.load_qiskit_circuit()` — the same QASM2/QASM3 loader
the Aer, IBM, IQM and Braket adapters use — and hands the result to the static
`QrackCircuit.in_from_qiskit_circuit()`, then `.run(simulator)`. This is why
the `qrack` extra depends on `qiskit` and `qiskit_qasm3_import` as well as
`pyqrack`.

A `CircuitFormat.QGC` spec instead names a pre-compiled `.qgc` file, loaded via
`QrackCircuit.in_from_file()`. That is the path worth using for a VQE sweep:
compile the ansatz structure once, then replay it per parameter point.

## Verified numbers

Bell state `h q[0]; cx q[0],q[1];` on the CPU simulator:

| Quantity | Value |
|---|---|
| `<ZZ>` | +1.000000 |
| `<XX>` | +1.000000 |
| `<YY>` | −1.000000 |
| `<Z0>` | 0 |
| `0.5*ZZ + 0.5*XX` | 1.000000 (the multi-term path from point 1) |
| unitary fidelity | 1.0 |
| 4000 shots | 1980 × `"00"`, 2020 × `"11"` |

Bit order: `x q[0]` on two qubits yields outcome integer 1, so bit *i* of the
returned integer is qubit *i* and `format(outcome, f"0{n}b")` gives the same
MSB-first string Qiskit's counts use. No reversal needed — unlike the MBQC
byproduct register, which *is* reversed (see `AGENTS.md`).

## Environment note

The prebuilt `pyqrack` wheel links against a recent `libstdc++`. On a host
whose Python comes from conda, `import pyqrack` can fail with
`GLIBCXX_3.4.32 not found` because conda's bundled `libstdc++.so.6` is older
than the system one. Preloading the system library
(`LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libstdc++.so.6`) is enough; a system
Python needs nothing. Unrelated to qpubench, but it is the first thing that
goes wrong.

Constructing with `is_gpu=True` on a host with no OpenCL platform prints
`No platforms found. Check OpenCL installation!` and continues on CPU. Pass
`QrackAdapter(..., gpu=False)` to skip the probe.
