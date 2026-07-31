# QuEST integration

[QuEST](https://github.com/QuEST-Kit/QuEST) (Quantum Exact Simulation Toolkit,
v4, developed at EPCC / University of Edinburgh) is a C/C++ state-vector and
density-matrix simulator. qpubench mirrors it in
`src/qpubench/schemas/mirrors/questkit_quest.py`.

## What QuEST is not

It has no circuit object. A QuEST program is a sequence of C calls mutating a
`Qureg` in place, and the "circuit" exists only as the order in which the host
program made them. **A QuEST run therefore has no serialisable circuit**; the
record carries the circuit in whatever form the host used (usually OpenQASM
handed to a translation layer such as `qoqo-quest` or `pyQuEST`).

What QuEST *does* contribute uniquely is the deployment and precision the
numbers were produced at, and those are not decoration. They change both the
runtime and the answer, and `BackendSpec` has no fields for them today.

---

## Deployment: four independent axes

```python
from qpubench.schemas import QuESTDeployment, QuESTPrecision, QuESTQuregSpec

spec = QuESTQuregSpec(
    num_qubits=30,
    precision=QuESTPrecision.SINGLE,
    deployment=QuESTDeployment(
        multithreaded=True,      # OpenMP
        gpu_accelerated=True,    # CUDA / HIP
        distributed=True,        # MPI
        cuquantum=True,          # build-time only, unlike the other three
        num_nodes=8,
    ),
)
spec.deployment.summary   # "omp+cuquantum+mpi(8)"
spec.bytes_per_node       # state split across the MPI world
```

QuEST probes hardware at runtime and enables what it finds, unless
`initCustomQuESTEnv` forces a choice. The validator rejects the combinations
that cannot mean anything: `distributed=True` with `num_nodes=1`,
`num_nodes>1` without `distributed`, a rank outside the world size.

A distributed run's timing is not comparable to a single-node one at the same
qubit count; every amplitude-touching operation carries communication cost.
Recording `num_nodes` is what makes that visible.

## Precision is compile-time

`FLOAT_PRECISION` is 1, 2 or 4 → `float`, `double`, `long double`. A QuEST
build is one of those and cannot switch. `QuESTPrecision.epsilon` bounds the
accuracy claim a run can make:

```python
QuESTPrecision.SINGLE.epsilon   # 1.2e-07
QuESTPrecision.DOUBLE.epsilon   # 2.2e-16
```

A single-precision run reporting agreement to 1e-8 is reporting noise. Quad
precision is CPU-only; QuEST refuses to build it against CUDA, and
`QuESTQuregSpec` refuses the same combination.

## State vector vs density matrix

The decision that dominates everything else: 4ⁿ amplitudes against 2ⁿ, halving
the reachable qubit count for the same memory. It is also the only mode in
which QuEST's `mix*` decoherence functions are defined; noise simulation is
not an option on a state vector, and `QuESTRunRecord` enforces that:

```python
QuESTRunRecord(
    qureg=QuESTQuregSpec(num_qubits=4),          # state vector
    noise_channels=[damping_channel],            # ValidationError
)
```

Memory properties are derived, not stored, so they can never disagree with the
flags that determine them: `num_amplitudes`, `bytes_per_amplitude`,
`state_bytes`, `bytes_per_node`. Note that `state_bytes` excludes QuEST's
communication buffer, which a distributed run allocates at the same size
again.

## Observables

`QuESTPauliStrSum` converts both ways with `SparsePauliObservable`:

```python
from qpubench.schemas import QuESTPauliStrSum
quest_sum = QuESTPauliStrSum.from_sparse_pauli_observable(hamiltonian)
quest_sum.to_sparse_pauli_observable(num_qubits=4)
```

`is_approx_hermitian` mirrors QuEST's lazily-evaluated tri-state flag
(0 / 1 / −1 for unknown; `None` here). A non-Hermitian sum must go through
`calcExpecNonHermitianPauliStrSum`, which returns a complex value; QuEST only
checks when a function requiring Hermiticity is called.

### Pauli integer encoding: a real trap

QuEST packs Pauli strings as base-4 numerals with **I=0, X=1, Y=2, Z=3**
(sequential). Qrack and Q# use **I=0, X=1, Z=2, Y=3**. Mixing the two silently
swaps Y and Z, which produces a plausible-looking wrong energy rather than an
error:

```python
QuESTPauliStr(qubit_indices=(0,), pauli_ops=(PauliLabel.Y,)).to_base4_masks()
# (2, 0)   QuEST's Y digit
PauliLabel.Y.to_qrack_int()
# 3        Qrack's Y integer
```

`to_base4_masks(split_at=32)` produces QuEST's `(lowPaulis, highPaulis)` pair;
the split is why a single `PauliStr` has a strict upper bound on how many
Paulis it can carry.

## Noise channels carry a position

```python
from qpubench.schemas import QuESTChannelType, QuESTNoiseChannel

QuESTNoiseChannel(
    channel=QuESTChannelType.DAMPING,
    targets=[0], probability=0.01, position=4,
)
```

`position` is the index into the host program's call sequence after which the
channel was applied. QuEST has no circuit object, so this is the *only* record
of where the channel went, and placement is not a detail: the same channel
before and after an entangling gate gives different states.

The nine channels are the named probability ones plus the general
`mixKrausMap` / `mixSuperOp`. Validation requires each channel's own arguments
(`mixPaulis` needs all three of `prob_x`/`prob_y`/`prob_z`, not one).

## Results

QuEST returns a scalar per `calc*` call: no job object, no result bundle. That
is why `QuESTCalculation` is an enum: recording *which* call produced a number
is what makes it interpretable. `calcFidelity` against a reference state and
`calcPurity` are both "a number near 1" and mean entirely different things.

```python
record = QuESTRunRecord(qureg=spec, calculations=[...])
record.result_for(QuESTCalculation.EXPEC_PAULI_STR_SUM)
```

`QuESTCalculationResult` has no standard error, deliberately: QuEST computes
exactly to the precision it was built at, so an uncertainty would be invented.
A shot-sampled comparison belongs in `result.ShotResult`.

Attach the whole thing to `QuantumResult.vendor_results["quest_run"]`.

## Backend

```python
from qpubench.schemas import BackendSpec

BackendSpec.quest(30, density_matrix=False, gpu=True, distributed_nodes=8)
```

Deployment and precision go into `auth` because `BackendSpec` has no fields
for them. That is a workaround, not a design; see
[finding A3](../schema_review.md#a3-simulator-runtime-is-being-smuggled-through-auth).
`QuESTQuregSpec.to_backend_spec()` produces the same shape from the typed
model.

## Relationship to the other noise models here

Three packages describe open-system dynamics, and they are complementary
rather than duplicates:

| Package | Form | What it is |
|---|---|---|
| `hqs_struqture.StruqtureOpenSystem` | Lindblad generator | the continuous-time master equation |
| `questkit_quest.QuESTNoiseChannel` | discrete channel + position | applied at a point in the program |
| `hqs_qoqo.QoqoNoiseModelSpec` | in-circuit PRAGMA / device model | the same channel positioned in a portable circuit |

## Installation

QuEST is a C/C++ library built with CMake; there is no official Python
package. Community bindings: `pyQuEST` (Cython), `PyQuEST-cffi` (CFFI),
`QuEST.jl` (Julia), and HQS's `qoqo-quest` (Rust), the last of which makes
QuEST usable as a qoqo backend, tying this module to
[hqs.md](hqs.md).

qpubench's schema module has no such dependency: it is Pydantic models and
imports with none of the above installed.

## Reference

Full type table: [schemas.md](../schemas.md): `questkit_quest`.
