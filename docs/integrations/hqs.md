# HQS Quantum Simulations integration

[HQS](https://quantumsimulations.de/) maintains a stack of small,
sharply-scoped packages rather than one framework, and qpubench mirrors four
of them:

| Package | Schema module | What it is |
|---|---|---|
| [struqture](https://github.com/HQSquantumsimulations/struqture) | `schemas/mirrors/hqs_struqture.py` | A typed serialisation format for operators, Hamiltonians and open quantum systems |
| [qoqo / roqoqo](https://github.com/HQSquantumsimulations/qoqo) | `schemas/mirrors/hqs_qoqo.py` | Circuit representation and measurement post-processing, with no transpiler and no algorithms |
| [qoqo_qasm](https://github.com/HQSquantumsimulations/qoqo_qasm) | `schemas/mirrors/hqs_qoqo_qasm.py` | qoqo ⇄ OpenQASM translation, and its dialects |
| [ActiveSpaceFinder](https://github.com/HQSquantumsimulations/ActiveSpaceFinder) | `schemas/mirrors/hqs_active_space_finder.py` | Automatic active-space selection for CASSCF / NISQ chemistry |

The stack composes: ASF picks an active space, struqture holds the resulting
fermionic Hamiltonian and maps it to qubits, qoqo runs a circuit measuring it,
and qoqo_qasm exports that circuit. A qpubench record can now carry every step
of that chain.

None of these are imported by qpubench; as everywhere in the schema layer,
these are data-shape bridges only.

---

## struqture: operator algebra with provenance

struqture is not a simulator. A struqture object is a sparse map from an index
(a normal-ordered product of single-site operators) to a coefficient, plus
type information saying which algebra the index lives in. Four algebras
(spins, bosons, fermions, mixed), each with the same stack: Product →
Operator → Hamiltonian → LindbladNoiseOperator / LindbladOpenSystem.

### Why it earns a module

`SparsePauliObservable` covers exactly one cell of that grid, qubit operators
with numeric coefficients, because that is all a benchmark *measures*. Two
struqture capabilities have no representation anywhere else in qpubench:

**Second-quantised operators before a qubit mapping is chosen.** A
`SparsePauliObservable` is the *output* of Jordan-Wigner; recording only it
throws away what produced it. `VQAConfig.mapper` names the mapping but has
nothing to name it *on*:

```python
from qpubench.schemas import (
    StruqtureMappedHamiltonian, StruqtureMapping, StruqtureOperator,
    StruqtureSerialisationMeta, StruqtureTerm, StruqtureType, StruqtureValue,
    StruqtureAlgebra, ModeProductSpec, SparsePauliObservable,
)

fermionic = StruqtureOperator(
    meta=StruqtureSerialisationMeta(type_name=StruqtureType.FERMION_HAMILTONIAN.value),
    algebra=StruqtureAlgebra.FERMIONS,
    terms=[
        StruqtureTerm(
            mode_product=ModeProductSpec(creators=(0,), annihilators=(0,)),
            coefficient=StruqtureValue.from_float(-1.25),
        ),
    ],
)

record = StruqtureMappedHamiltonian(
    source=fermionic,
    mapping=StruqtureMapping.JORDAN_WIGNER,
    mapped=StruqtureOperator.from_sparse_pauli_observable(qubit_hamiltonian),
)
```

Now "the same molecule under Jordan-Wigner" is a checkable claim rather than a
label. The validator rejects a spin operator as `source` (there is no mapping
to record) and a non-spin operator as `mapped`.

**Lindblad dissipators as data.** A `LindbladNoiseOperator` is keyed by an
ordered *pair* of products (L_i, L_j) with rate M_ij, the double-index
structure of the master equation:

    dρ/dt = Σ_ij M_ij ( L_i ρ L_j†  −  ½ { L_j† L_i , ρ } )

No core qpubench type has that shape. The diagonal entries are the familiar
per-channel rates; the off-diagonal ones carry coherences between decay
channels that a flat rate list cannot express. `has_off_diagonal_rates` exists
so a consumer can see what it is about to drop:

```python
if noise.has_off_diagonal_rates:
    ...  # a channel-list simulator will silently lose these
```

### Symbolic coefficients

struqture coefficients are `CalculatorComplex`: a number **or** an expression
string. A parametric Hamiltonian is a first-class struqture object.
`StruqtureValue` carries both cases, and `to_sparse_pauli_observable()` raises
rather than inventing a value for an unbound parameter:

```python
StruqtureValue.from_float(0.5)          # numeric
StruqtureValue(symbolic_re="2 * theta") # free parameter
```

### Bases that look alike and are not

Three single-spin bases appear in struqture and they are **not**
interchangeable:

| Type | Basis | Used by |
|---|---|---|
| `PauliProductSpec` | X, Y, Z | Hamiltonians; converts losslessly with `PauliTerm` |
| `DecoherenceProductSpec` | X, **iY**, Z | Lindblad noise; the real-valued basis that keeps rate matrices real |
| `PlusMinusProductSpec` | σ⁺, σ⁻, Z | qoqo's `ContinuousDecoherenceModel`, where damping and excitation are single terms |

Converting a `DecoherenceProduct` to a Pauli string introduces a factor of i
per iY. The types are kept separate so that conversion has to be deliberate.

### Versioning: worth stealing

Every serialised struqture object embeds `{type_name, min_version, version}`
and refuses a load when the reader is older than the writer's declared
minimum. That is a *per-type* contract: adding a field to one type does not
invalidate stored payloads of every other type, which a single library-wide
version number cannot express.

```python
meta.can_be_read_by((2, 1, 0))   # applies struqture's own compatibility rule
```

struqture 2.0 renamed the 1.x `*System` types (`SpinSystem` → `PauliOperator`,
…) and dropped the fixed particle-count layer. `STRUQTURE_1_TO_2_NAMES` maps
the old names for records written against 1.x.

---

## qoqo: the measurement is part of the program

qoqo represents circuits and the classical post-processing that turns raw
readout into expectation values, and explicitly nothing else: no transpiler,
no optimiser, no algorithm library.

### The post-processing rule

`CircuitSpec.observables` says *what* to measure. Nothing in qpubench says how
counts become that number; a record shows `ShotResult.counts` and
`ExpectationResult.value` with no stated relationship between them. qoqo makes
it explicit:

```python
from qpubench.schemas import (
    QoqoExpectationRule, QoqoPauliProductMask, QoqoPauliZProductInput,
)

measurement_input = QoqoPauliZProductInput(
    number_qubits=2,
    use_flipped_measurement=True,
    pauli_products=[
        QoqoPauliProductMask(readout="ro_z", index=0, qubit_mask=[0]),
        QoqoPauliProductMask(readout="ro_z", index=1, qubit_mask=[0, 1]),
    ],
    expectation_rules=[
        QoqoExpectationRule(name="energy", linear={0: -0.47, 1: 0.18}),
    ],
)
measurement_input.num_circuits_per_evaluation   # 2, flipped doubles it
```

After the basis-rotation circuit runs, every observable is diagonal, so a
Pauli product is just the set of measured bits XORed together, and that set is
`qubit_mask`. `linear` is the combination that produces the energy. The
validator rejects a rule referencing a product that was never measured, which
is a silently wrong energy rather than a missing one.

`use_flipped_measurement` is worth noting: it cancels readout asymmetry
(p(1|0) ≠ p(0|1)) by running each basis twice with all qubits flipped. That is
error mitigation expressed as *measurement structure*, which is why it has no
`ErrorMitigationStrategy` value, and why the doubled circuit count belongs in
any comparison against a package that does not do it.

### PRAGMAs are positioned in the circuit

qoqo puts simulator- and hardware-specific directives in the circuit as
first-class operations. qpubench splits the same information between
`ExecutionOptions` and the QASM string, which loses ordering: "damp for 20 µs
*after gate 4*" is not an execution option.

`QoqoPragma` enumerates all 27, grouped by what they do: readout, state
preparation, noise, control flow, scheduling. `QoqoCircuitSpec.pragmas`
returns the ones a circuit uses, in order.

Note that `QoqoCircuitSpec.num_qubits` is *derived*: a qoqo Circuit declares no
width, so its size is whatever its operations imply.

### Devices: time-based, not error-rate-based

`QoqoDeviceSpec` stores gate **durations** plus a per-qubit 3×3 Lindblad rate
matrix over (σ⁺, σ⁻, σᶻ), and lets noise follow from their product. That is a
physically stronger statement than an error-rate table; it predicts the error
of a gate the device was never characterised on.

`to_backend_spec()` projects onto `BackendSpec` with T1 = 1/M₀₀ and
T2 = 1/M₂₂, and leaves `error_rate` unset rather than inventing one:

```python
backend = device.to_backend_spec()
backend.qubit_t1(0)                  # 1 / damping rate
backend.gate_error("CNOT", (0, 1))   # None; qoqo has no error rates
```

Keep the `QoqoDeviceSpec` alongside the projection: off-diagonal M_ij has no
`BackendSpec` representation and is dropped.

### Noise models, by *when* they apply

`QoqoNoiseModelType` distinguishes continuous / on-gate / on-idle / at-readout
/ overrotation. That axis is missing from qpubench's core entirely:
`BackendSpec` records characteristics a device *has*, with no way to say a
simulation should apply them.

`QoqoOverrotationDescription` is the one that does not fit a rate at all; a
miscalibrated rotation is a *coherent* error that accumulates over repetitions
instead of averaging out, and no Lindblad rate expresses it.

The Lindblad operator behind a decoherence model is stored as a plain dict so
this mirror does not import another mirror; rehydrate it explicitly:

```python
from qpubench.schemas import StruqtureNoiseOperator
StruqtureNoiseOperator.model_validate(model.lindblad_noise)
```

### QuantumProgram

`QoqoQuantumProgramSpec` is a measurement plus the **ordered** names its free
parameters are substituted from, qoqo's answer to "what is the callable unit
of quantum work". The ordering is the load-bearing part:
`circuit.ParameterBinding` is name-keyed and therefore order-free, which
cannot express "the same function, called with a different vector", the shape
every variational outer loop has.

---

## qoqo_qasm: "OpenQASM 3.0" is not one format

`roqoqo_qasm::QasmVersion` is a version *and* a dialect:

| `QasmDialect` | Portable? | Pragmas? |
|---|---|---|
| `2.0Vanilla` | yes | n/a |
| `2.0Qulacs` | no, omits gate definitions | n/a |
| `3.0Vanilla` | yes | dropped |
| `3.0Roqoqo` | no, roqoqo pragma syntax | kept |
| `3.0Braket` | no, Braket pragma syntax | kept |

`CircuitFormat` has `QASM2` and `QASM3` and stops there, so two records can
both claim `format=QASM3` while one is portable and the other only loads under
Braket. The enum values are the exact strings upstream parses, so a stored
config is handed back verbatim.

`QoqoQasmTranslationResult` separates two failure modes that are easy to
conflate:

```python
result.succeeded     # False if any operation had no QASM equivalent;
                     # qoqo_qasm refuses rather than emitting a partial circuit
result.is_faithful   # False if it succeeded but dropped noise pragmas;
                     # a valid circuit describing a different experiment
```

A run whose `PragmaDamping` silently vanished into a Vanilla dialect produced
noiseless numbers from what was recorded as a noisy program. That is the exact
class of error a benchmark record exists to catch.

---

## ActiveSpaceFinder: the selection, and the orbitals it refers to

ASF answers the question every quantum-chemistry benchmark must answer and
almost none record: *which orbitals are active, and why?*

```
SCF (UHF, even for singlets; broken symmetry exposes the correlation)
  → MP2 natural orbitals (pick a tractable initial subspace)
    → cheap screening DMRG (maxM ≈ 500; entropies, not energies)
      → entropy + cumulant analysis → several candidate spaces
```

### The MO-basis trap

ASF's own documentation is blunt: do not combine the returned MO indices with
orbitals from anywhere else. The MP2-natural-orbital step reorders and remixes
the MOs, so index 7 in an ASF result is not index 7 in the preceding SCF.
`ASFActiveSpace` is the only active-space type in qpubench that carries the
link:

```python
from qpubench.schemas import ASFActiveSpace

space = ASFActiveSpace(nel=6, mo_list=[3, 4, 5, 6, 7, 8], mo_coeff_ref="chk:mp2no")
space.cas_label                  # "CAS(6,6)"
space.num_qubits_jordan_wigner   # 12
space.to_gsopt_active_space()    # index-only form, drops mo_coeff_ref
```

`mo_coeff` itself (an AO×MO matrix, hundreds of thousands of floats for a
real molecule) is *not* stored inline; `mo_coeff_ref` is a path, checkpoint
key or content hash, and `mo_coeff_shape` lets a reader sanity-check that the
reference resolves to the right thing. This is the same choice
`molssi_qcschema` makes for wavefunction data.

### Four active-space types, one per pipeline stage

They are not redundant:

| Where | Type | What it holds |
|---|---|---|
| record level | `VQAConfig.active_electrons` / `.active_orbitals` | the two numbers, for cross-run filtering |
| chosen space | `bestquark_gsopt.ActiveSpaceSpec` | occupied + active MO indices |
| one selector | `microsoft_qdk.ActiveSpaceSelectionConfig` / `…Result` | spin-resolved alpha/beta indices |
| selection provenance | `hqs_active_space_finder.ASFActiveSpace` | indices **plus the MO basis they refer to** |

### Recording the choice, not just the answer

The distinguishing ASF feature is returning *several* candidates.
`ASFSelectionResult` stores what the chosen space was chosen over:

```python
from qpubench.schemas import ASFSelectionConfig, ASFSelectionMode

# "give me the best 8 orbitals", the usual NISQ framing, size is an input
config = ASFSelectionConfig(mode=ASFSelectionMode.SIZED, requested_size=8)

# "what does the molecule need?", size is an output
config = ASFSelectionConfig(mode=ASFSelectionMode.ENTROPY, entropy_threshold=0.14)
```

`ASFCandidateSpace.max_entropy_excluded` is the diagnostic that matters when
choosing: the highest single-orbital entropy left *out*. A large value means
the candidate cuts through correlated orbitals and is probably too small.

The default `entropy_threshold` is `-0.1 · ln(0.25)` ≈ 0.1386, a natural-log
entropy scale, not a tuned constant. It is the single most consequential knob,
and the one a bare "CAS(6,6)" hides.

---

## Installation

```sh
pip install struqture-py qoqo qoqo_qasm     # HQS stack
pip install .                                # ActiveSpaceFinder, from source;
                                             # then ./init_dmrgscf_settings.sh
```

ActiveSpaceFinder needs Python 3.9–3.11 (Block2 is not packaged for newer),
and PySCF's `dmrgscf` plugin needs a config file; the repo ships
`init_dmrgscf_settings.sh` to write it. qpubench's schema modules have no such
constraint: they are Pydantic models and import on any supported Python with
none of these packages installed.

## Reference

Full type tables: [schemas.md](../schemas.md): `hqs_struqture`,
`hqs_qoqo`, `hqs_qoqo_qasm`, `hqs_active_space_finder`.
