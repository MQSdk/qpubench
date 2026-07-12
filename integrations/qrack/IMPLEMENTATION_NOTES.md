# QrackAdapter implementation notes

`src/qpubench/backends/qrack_adapter.py` ships as a stub — `run()` raises
`NotImplementedError`. This file preserves the implementation plan and the
Qrack-specific gotchas so they don't live in a shipped docstring.

## Estimator path (circuit.observables populated)

```python
from pyqrack import QrackSimulator
from ctypes import c_ulonglong, POINTER

qsim = QrackSimulator(
    qubit_count=self._num_qubits,
    is_gpu=self._gpu,
    is_stabilizer_hybrid=self._stabilizer_hybrid,
)
# Load circuit from QASM2 (via Qiskit) or .qgc directly
if circuit.format == CircuitFormat.QGC:
    qsim.in_from_file(circuit.serialized)   # load from path
else:
    # Convert QASM → Qiskit circuit → apply gates to qsim
    pass

evs = []
for i, obs in enumerate(circuit.observables):
    qubits, paulis = obs.to_qrack_flat_arrays()  # handles I=0,X=1,Z=2,Y=3
    n = len(qubits)
    q_arr = (c_ulonglong * n)(*qubits)
    p_arr = (c_ulonglong * n)(*paulis)
    ev = qsim.pauli_expectation_eigenvals(n, q_arr, p_arr)  # → float
    evs.append(ExpectationResult(
        observable_index=i,
        value=ev,
        std_error=0.0,   # statevector is exact
    ))
fidelity = qsim.get_unitary_fidelity()   # GetUnitaryFidelity()
qsim.release()

return QuantumResult(
    computing_model=ComputingModel.GATE_BASED,
    expectation_values=evs,
    fidelity=FidelityResult(
        fidelity=fidelity,
        metric=FidelityMetric.UNITARY,
    ),
    status=JobStatus.SUCCEEDED,
)
```

## Sampler path (circuit.observables empty, options.shots set)

```python
from ctypes import c_ulonglong, POINTER

shots   = options.shots or 1024
q_arr   = (c_ulonglong * self._num_qubits)(
    *range(self._num_qubits)
)
out_arr = (c_ulonglong * shots)()

# MeasureShots(sid, n_qubits, q_arr, n_shots, out_arr)
# outcomes are bitstring integers, NOT individual bit values
qsim.measure_shots(self._num_qubits, q_arr, shots, out_arr)

counts: dict[str, int] = {}
for outcome in out_arr:
    key = format(outcome, f"0{self._num_qubits}b")
    counts[key] = counts.get(key, 0) + 1

qsim.release()
return QuantumResult(
    computing_model=ComputingModel.GATE_BASED,
    shots=ShotResult(
        num_qubits=self._num_qubits,
        num_shots=shots,
        counts=counts,
    ),
    status=JobStatus.SUCCEEDED,
)
```

## IMPORTANT Qrack-specific gotchas

1. Pauli encoding: Z=2, Y=3 (non-sequential Q# convention).
   Use `PauliLabel.to_qrack_int()` — do NOT use raw 0/1/2/3 order.
2. `MeasureShots` returns outcome integers, not per-qubit bits.
   Convert via `format(outcome, f"0{n}b")` for MSB-first bitstring.
3. `GetUnitaryFidelity()` resets the internal fidelity accumulator.
   Call it once at the end, not between gates.
4. `real1_type` precision: check `QRACK_FPPOW` env var at runtime.
   Use `ctypes.c_float` if `QRACK_FPPOW < 6`, else `ctypes.c_double`.
5. `QrackCircuit` (.qgc) pre-compilation: compile once with
   `init_qcircuit()` / `qcircuit_append_*` / `qcircuit_out_to_file()`,
   then replay cheaply with `qcircuit_run(cid, sid)` for each
   parameter point in a VQE sweep.
