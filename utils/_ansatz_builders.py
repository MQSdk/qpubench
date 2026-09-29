"""Build the named ansatz circuits benchmark rows ask for, as real Qiskit
circuits, for resource estimation.

Shared by `estimate_ibm_cost.py` and `split_benchmark_batches.py` so both
cost the same circuit for the same row. Not a guide itself (hence the
leading underscore), and deliberately not in `src/qpubench/`: `uccsd()`
below builds on `integrations/generic_adapt_vqe/`, which pyproject
excludes from the installed package, so a library module importing it
would break for pip-installed users.

`VQERunConfig.ansatz` and `BenchmarkRecord.ansatz` carry an ansatz *name*
("EfficientSU2", "UCCSD", ...) on the understanding that "each adapter
maps this onto its own constructor". This is that mapping for the
resource-estimation path.

Why it exists as real code rather than an assumption: an earlier revision
of the benchmark tooling substituted `EfficientSU2` for every row
regardless of the named ansatz, which understated cost badly. At 12
qubits a real Trotterized UCCSD transpiles to roughly 17x the QPU time of
EfficientSU2, so that substitution was the single largest error in those
estimates.

TN_QC_OPT has *two* circuit sides, one per platform, and they are
different circuits — which is why both are here:

`n_local_rzryrz_sca` is TN_QC_OPT's Qiskit path (`functions_qiskit.py:36`):
`n_local(n, ["rz","ry","rz"], "cx", entanglement="sca")` — the circuit the
task builds for itself when no QASM is supplied. Parameter count
`3n(R+1)`, the trailing rotation layer being the difference from
PennyLane's. No current benchmark scenario names it; it is kept here so
that a caller who wants the task's own default circuit can build the same
object the task would.

`StronglyEntanglingLayers` is PennyLane's (`functions_pennylane.py:28`),
which the task uses on `default.qubit` / `lightning.qubit`. Rebuilt here
in Qiskit to PennyLane's own definition: per layer, a general
single-qubit rotation (Rot = RZ then RY then RZ) on every wire, then a
ring of CNOTs whose stride varies with the layer index. Parameter count
`3nR`, the (L, N, 3) shape.

Costing a row on the wrong platform's circuit is a real (if small)
error: at stage-1 sizes it moves the estimate by under 2%. It is worth
getting right because the estimate should describe the circuit that
runs, and because the 50% understatement it caused in
`Num_Opt_Params_Phi` was not small.

`excitation_preserving_linear` is the in-sector alternative for stage 2:
with `givens` or `number_preserving`, U(θ) commutes with the number
operator, so U†HU stays in the particle-number sector and the RzRyRz/cx
circuit spends depth on amplitude the transformed Hamiltonian cannot use.
`entanglement="linear"`, never the default `"full"` — that is n(n−1)/2
two-qubit gates per rep. Note `xx_plus_yy` is not a FakeBrisbane basis
gate and decomposes into more than one `ecr`, so parity with the RzRyRz
default cannot be assumed; measure it.

`UCCSD` is built from this project's own Jordan-Wigner
singles-and-doubles excitation generators rather than qiskit-nature, so
it needs no extra dependency. It is a first-order Trotterization: one
`PauliEvolutionGate` per excitation operator over a Hartree-Fock
reference. Adequate for resource estimation, which is all this is for;
it is not a converged-energy UCCSD implementation.
"""
from __future__ import annotations

import pathlib
import sys
from typing import TYPE_CHECKING

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

if TYPE_CHECKING:
    from qiskit import QuantumCircuit

SUPPORTED_ANSATZE = (
    "EfficientSU2",
    "EfficientSU2_circular",
    "RealAmplitudes",
    "StronglyEntanglingLayers",
    "n_local_rzryrz_sca",
    "excitation_preserving_linear",
    "UCCSD",
    "tUPS",
)

# Ansatze whose circuit is supplied as pinned QASM rather than built here --
# both need a reference determinant and an occupied/virtual split the way
# UCCSD does (tUPS is number-conserving and HF-initialized the same way),
# so both depend on mapper and electron count, not just (qubits, reps).
SUPPLIED_ANSATZE = {"UCCSD", "tUPS"}

# Families whose circuit is fixed by (qubits, reps) alone, so that two rows
# reaching the same width share one pinned file however they got there.
_MAPPER_INDEPENDENT = tuple(a for a in SUPPORTED_ANSATZE if a not in SUPPLIED_ANSATZE)

# THE CAMPAIGN'S UCCSD CIRCUITS ARE SUPPLIED, NOT BUILT HERE -- under
# either mapper.  `uccsd()` below builds the GENERALIZED ansatz, one
# amplitude per singles-and-doubles excitation out of the reference
# determinant; the campaign runs a restricted version with materially
# fewer parameters (15 against 40 at 8 qubits / 2 electrons), matched
# between the two encodings so that a JW row and a mol_map row differ in
# the encoding rather than in the ansatz.
#
# mol_map could never have been built here in any case: UCCSD's
# excitation operators are built from FERMIONIC MODES and need qubits
# that index spin orbitals, while mol_map's index determinants under a
# constraint encoding and have no occupied/virtual split to work from.
#
# So `pin_qasm_ansatz` names these files and reports whether they are
# present, and never writes or deletes one.  Overwriting a supplied
# circuit with this module's generalized one would change what the
# campaign runs without changing anything that says so.
#
# HISTORICAL, RESOLVED 2026-09-17 -- kept because it explains why these six
# files read the way they do, not because the mismatch is still live.
#
# Through commits eb554c6/566f37c (2026-09-03), all six files carried the
# reference determinant on the WRONG end of the register: Qiskit and old
# Cebule disagreed about which end of a Pauli string like "ZZII" is qubit
# 0, so a circuit whose X gates were written against Qiskit's convention
# put the determinant where old Cebule's reversed h_operators reading
# would see it as something else -- X gates originally sat on qubits 6,7
# for an 8-qubit H2, where Jordan-Wigner puts the occupied spin orbitals
# at 0,1. Those commits reversed all six circuits with
# QuantumCircuit.reverse_bits() to compensate: cancel old Cebule's
# Hamiltonian-reading bug from the CIRCUIT side, since the Hamiltonian
# files themselves were Cebule's own and not this repository's to hand-edit.
# mol_map was affected identically to JW, not exempt from it -- an earlier
# revision of this comment claimed otherwise from a check
# (UCCSD_molmap_4q_2r_2e_4o's Hartree-Fock energy) that could not have
# shown the bug either way, since H2's reference is symmetric under
# bit-reversal; water's is not, and reproduced the same failure.
#
# On 2026-09-17 Cebule's own h_operators reader was corrected to match
# Qiskit's convention directly (deployed and confirmed live), which
# resolves the SAME mismatch from the other side: see
# hamiltonian_data/*.json, whose Pauli strings were reversed that day to
# match. Because the 2026-09-03 compensation lived entirely in these
# circuit files and already reads correctly in Qiskit's own convention
# (X gates at 0,1, matching uccsd()'s own reference-state convention
# below), NO FURTHER CHANGE TO THESE SIX FILES WAS NEEDED -- verified
# numerically against both a JW and a mol_map cell, zero-phi energy
# against the newly-reversed Hamiltonian reproduces RHF exactly. Only the
# Hamiltonian files moved.
UCCSD_BUILDABLE_MAPPERS: tuple[str, ...] = ()


def can_build(ansatz: str, mapper: str = "JW") -> bool:
    """Whether `build_ansatz` may construct this circuit for the campaign.

    False for UCCSD under every mapper -- see UCCSD_BUILDABLE_MAPPERS --
    and False for every SUPPLIED_ANSATZE for the same reason: `uccsd()`
    itself still works and `estimate_ibm_cost.py` still uses it, but what
    this governs is whether a pinned campaign file may be generated here;
    tUPS has no local builder at all, supplied or not.
    """
    if ansatz == "UCCSD":
        return mapper in UCCSD_BUILDABLE_MAPPERS
    if ansatz in SUPPLIED_ANSATZE:
        return False
    return ansatz in SUPPORTED_ANSATZE


def qasm_stem(
    ansatz: str, num_qubits: int, reps: int, *, mapper: str = "JW",
    num_electrons: int = 0, num_orbitals: int = 0, entanglement: str | None = None,
) -> str:
    """The filename stem identifying one pinned circuit.

    The stem lists exactly what the circuit depends on, and nothing else,
    so that two rows share a file when and only when they share a circuit.

    The hardware-efficient families depend on (qubits, reps, entanglement):
    a ring of CX and a stack of rotation layers is the same object
    whichever mapper produced the register, so their stem carries neither
    the mapper nor the electron count. `entanglement=None` (each family's
    own DEFAULT_ENTANGLEMENT) is left OUT of the stem -- that is the common
    case, and every file pinned before this parameter existed already
    matches it -- an alternate topology is spelled out so it pins to its
    own file instead of colliding with the default one.

    UCCSD and tUPS (SUPPLIED_ANSATZE) depend on more, and on different
    things per mapper:

      JW       qubits are spin orbitals, so (qubits, electrons) fixes the
               occupied/virtual split and therefore the excitation pool.
               The orbital count is qubits/2 and would be redundant.
      mol_map  qubits index DETERMINANTS, and the qubit count is
               ceil(log2(C(m, n_alpha) * C(m, n_beta))), which does not
               invert: 6 qubits is CAS(2,8) for H2/qvSZP and CAS(4,4) for
               H2O.  So the orbital count is load-bearing here and is in
               the stem.

    The mapper is named on every such file even where the orbital count
    would already separate them.  A JW UCCSD and a mol_map UCCSD are not
    the same kind of object -- one acts on spin orbitals, the other on a
    determinant index -- and a stem that let them collide would surface as
    a spurious "the pinned circuit changed" from the SHA256 check rather
    than as the name clash it is.
    """
    if ansatz in _MAPPER_INDEPENDENT:
        stem = f"{ansatz}_{num_qubits}q_{reps}r"
        default = DEFAULT_ENTANGLEMENT.get(ansatz)
        if entanglement is not None and entanglement != default:
            stem += f"_{entanglement}"
        return stem
    stem = f"{ansatz}_{mapper.replace('_', '')}_{num_qubits}q_{reps}r_{num_electrons}e"
    if mapper != "JW":
        stem += f"_{num_orbitals}o"
    return stem


# Each hardware-efficient family's own default topology -- what it builds
# when `build_ansatz` is asked for entanglement=None, and what `qasm_stem`
# leaves OUT of the filename since it is the common case. An alternate
# topology (e.g. "full") is spelled out in the stem so it pins to its own
# file rather than colliding with the default one at the same (qubits, reps).
DEFAULT_ENTANGLEMENT = {
    "RealAmplitudes": "reverse_linear",
    "EfficientSU2_circular": "circular",
    "n_local_rzryrz_sca": "sca",
}


def build_ansatz(
    ansatz: str,
    num_qubits: int,
    *,
    reps: int = 1,
    num_electrons: int | None = None,
    parameterize: bool = False,
    entanglement: str | None = None,
) -> "QuantumCircuit":
    """Build `ansatz` on `num_qubits` qubits at `reps` repetitions.

    `num_electrons` is required by UCCSD alone, which needs a reference
    determinant and an occupied/virtual split; the hardware-efficient
    families ignore it.

    `parameterize` affects UCCSD alone as well. The other families are
    always built with free parameters; UCCSD's Trotter angles are bound
    to a placeholder by default, because that is what the resource
    estimate wants, and are left free when the circuit is being pinned as
    QASM (`pin_qasm_ansatz.py`), because that is what a pinned circuit
    has to carry.

    `entanglement` only affects RealAmplitudes and n_local_rzryrz_sca
    (None means each family's own DEFAULT_ENTANGLEMENT). EfficientSU2_circular
    already names its one non-default topology outright; the rest have no
    entanglement pattern to vary.
    """
    if ansatz == "EfficientSU2":
        from qiskit.circuit.library import efficient_su2
        return efficient_su2(num_qubits, reps=reps)
    if ansatz == "EfficientSU2_circular":
        # Same rotations as EfficientSU2, ring entanglement instead of the
        # library default reverse-linear chain: one extra CX per rep (the
        # wrap-around), same parameter count.  At 2 qubits a ring is the
        # linear chain, so the two coincide there.
        from qiskit.circuit.library import efficient_su2
        return efficient_su2(num_qubits, reps=reps, entanglement="circular")
    if ansatz == "RealAmplitudes":
        from qiskit.circuit.library import real_amplitudes
        return real_amplitudes(
            num_qubits, reps=reps,
            entanglement=entanglement or DEFAULT_ENTANGLEMENT["RealAmplitudes"],
        )
    if ansatz == "StronglyEntanglingLayers":
        return strongly_entangling_layers(num_qubits, reps=reps)
    if ansatz == "n_local_rzryrz_sca":
        return n_local_rzryrz_sca(
            num_qubits, reps=reps,
            entanglement=entanglement or DEFAULT_ENTANGLEMENT["n_local_rzryrz_sca"],
        )
    if ansatz == "excitation_preserving_linear":
        return excitation_preserving_linear(num_qubits, reps=reps)
    if ansatz == "UCCSD":
        if num_electrons is None:
            raise ValueError("UCCSD needs num_electrons to place the reference determinant")
        return uccsd(num_qubits, num_electrons, reps=reps, parameterize=parameterize)
    if ansatz == "tUPS":
        raise ValueError("tUPS is supplied as pinned QASM, not built here -- see can_build")
    raise ValueError(
        f"no builder for ansatz {ansatz!r}; supported: {', '.join(SUPPORTED_ANSATZE)}"
    )


def strongly_entangling_layers(num_qubits: int, *, reps: int = 1) -> "QuantumCircuit":
    """PennyLane's StronglyEntanglingLayers, as a Qiskit circuit.

    Parameters are left at zero: this is for resource estimation, where
    only the circuit's structure matters.
    """
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(num_qubits)
    for layer in range(reps):
        for qubit in range(num_qubits):
            qc.rz(0.0, qubit)
            qc.ry(0.0, qubit)
            qc.rz(0.0, qubit)
        if num_qubits > 1:
            # PennyLane's default range: a layer-dependent CNOT stride, so
            # successive layers entangle different qubit pairs.
            stride = 1 if num_qubits == 2 else (layer % (num_qubits - 1)) + 1
            for qubit in range(num_qubits):
                qc.cx(qubit, (qubit + stride) % num_qubits)
    return qc


def n_local_rzryrz_sca(
    num_qubits: int, *, reps: int = 1, entanglement: str = "sca",
) -> "QuantumCircuit":
    """TN_QC_OPT's Qiskit circuit side, exactly as `functions_qiskit.py:36`
    builds it: `n_local(n, ["rz","ry","rz"], "cx", entanglement="sca")`.

    'sca' is Qiskit's shifted-circular-alternating entanglement: a
    circular CX chain whose starting qubit shifts each rep and whose
    control/target orientation alternates. `entanglement` is exposed for
    the campaign's own topology comparison (see qasm_stem) -- the task
    itself always builds 'sca' when it builds this circuit for itself.

    Note that the leading Rz layer acts on |0...0>, where Rz is a global
    phase, so `n` of the `3n(R+1)` parameters cannot affect the state.
    """
    from qiskit.circuit.library import n_local

    return n_local(
        num_qubits, ["rz", "ry", "rz"], "cx", reps=reps, entanglement=entanglement,
    )


def excitation_preserving_linear(num_qubits: int, *, reps: int = 1) -> "QuantumCircuit":
    """Number-conserving circuit ansatz, for pairing with a
    number-conserving U(θ) (`givens` / `number_preserving`).

    `entanglement="linear"` is not the library default — `"full"` is, at
    n(n-1)/2 two-qubit gates per rep, which is unaffordable at these
    budgets.
    """
    from qiskit.circuit.library import excitation_preserving

    return excitation_preserving(num_qubits, reps=reps, entanglement="linear")


def uccsd(
    num_qubits: int, num_electrons: int, *, reps: int = 1, parameterize: bool = False,
) -> "QuantumCircuit":
    """First-order Trotterized UCCSD over a Hartree-Fock reference.

    `num_qubits` are spin orbitals, so this assumes a Jordan-Wigner
    mapping; the excitation operators are the JW-mapped ones the
    ADAPT-VQE pool generator produces.

    With `parameterize=True` each excitation carries a free amplitude
    `t[k]` instead of the placeholder time, giving one parameter per
    excitation per repetition -- the count `Num_Opt_Params_Phi` records.
    """
    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector
    from qiskit.circuit.library import PauliEvolutionGate
    from qiskit.quantum_info import SparsePauliOp

    from integrations.generic_adapt_vqe.pool import generate_singles_doubles_pool

    if not 0 <= num_electrons <= num_qubits:
        raise ValueError(
            f"num_electrons={num_electrons} out of range for num_qubits={num_qubits}"
        )

    qc = QuantumCircuit(num_qubits)
    for qubit in range(num_electrons):        # Hartree-Fock reference
        qc.x(qubit)

    pool = generate_singles_doubles_pool(num_qubits, num_electrons)
    amplitudes = (
        ParameterVector("t", len(pool) * reps) if parameterize else None
    )
    for index, operator in enumerate(pool * reps):
        terms = operator.observable.to_qiskit_pauli_list(num_qubits)
        # The excitation operators are anti-Hermitian (purely imaginary
        # coefficients); PauliEvolutionGate wants the Hermitian
        # generator, hence the imaginary part.
        generator = SparsePauliOp.from_list(
            [(label, coeff.imag) for label, coeff in terms]
        )
        time = amplitudes[index] if amplitudes is not None else 0.1
        qc.append(PauliEvolutionGate(generator, time=time), range(num_qubits))
    return qc


# Hartree-Fock reference state per mapper, as a bit list in Pauli-label
# order (leftmost = highest qubit) -- the form _fermionic_ansatz.
# hf_parameters expects. JW is a formula (the first `active_electrons`
# qubits, same convention uccsd() above uses); mol_map_spinblock's is data
# this campaign's own regenerate_spinblock_mol_map.py prints when it
# builds the reordered Hamiltonian (reorder_mapped_hamiltonian's own
# returned hf_state), since the reordering is data, not a formula.
MOL_MAP_SPINBLOCK_HF_STATE: dict[tuple[str, str], list[int]] = {
    ("H2", "6-31g"): [0, 0, 0, 0],
    ("H2O", "6-31g"): [0, 0, 0, 0, 0, 0],
}


def hf_state_for(
    mapper: str, molecule: str, basis: str, active_electrons: int, num_qubits: int,
) -> list[int]:
    """The Hartree-Fock reference, as a bit list in Pauli-label order --
    for a hardware-efficient ansatz's HF-approximating phi_init, or for
    verifying a fermionic ansatz's own zero-amplitude reference.
    """
    if mapper == "JW":
        from _fermionic_ansatz import hf_state_jw
        # Every cell this campaign runs is closed-shell (n_alpha == n_beta),
        # so the occupied MODE SET is {0, ..., active_electrons-1} regardless
        # of how the split is spelled here -- but the split still has to be
        # a real closed-shell split, not electrons-into-alpha-only.
        if active_electrons % 2:
            raise ValueError(
                f"{active_electrons} active electrons is not closed-shell; "
                f"hf_state_for assumes n_alpha == n_beta"
            )
        n_alpha = n_beta = active_electrons // 2
        # hf_state_jw follows _fermionic_ansatz's own JW convention (mode m
        # -> qubit n_qubits-1-m), the MIRROR of this repo's (occupied = the
        # FIRST active_electrons qubits -- uccsd()'s own X-gate placement,
        # and what every already-pinned JW circuit in this campaign uses).
        # Reversed to match; verified against RHF for RealAmplitudes.
        return list(reversed(hf_state_jw(num_qubits // 2, n_alpha, n_beta)))
    try:
        return MOL_MAP_SPINBLOCK_HF_STATE[(molecule, basis)]
    except KeyError:
        raise KeyError(
            f"no {mapper} Hartree-Fock state for {molecule}/{basis}; add it to "
            f"MOL_MAP_SPINBLOCK_HF_STATE"
        ) from None


def hf_approx_phi_init(
    ansatz: str, num_qubits: int, reps: int, hf_state: list[int],
    qasm_text: str, *, entanglement: str | None = None,
) -> list[float]:
    """phi_init approximating Hartree-Fock for a hardware-efficient ansatz,
    in the parameter order the pinned QASM text actually binds against.

    The actual per-qubit value comes from _fermionic_ansatz.hf_parameters
    (verified against RHF for RealAmplitudes and n_local_rzryrz_sca, both
    mappers, robust to entanglement topology -- it sets only the LAST
    rotation layer, and a CX gate controlled by a qubit still in |0> is
    the identity, so every earlier entangler leaves |0...0> untouched).

    What this wraps around it is the parameter-ORDER translation, which
    hf_parameters alone does not solve: hf_parameters returns values in
    the FRESHLY-BUILT circuit's own `.parameters` order, but once Cebule
    loads a circuit from QASM text (`qiskit.qasm3.loads`), it binds phi
    positionally against THAT circuit's `.parameters`, which sorts
    alphabetically over the raw identifier string ("_θ_0_", "_θ_10_",
    "_θ_11_", ..., "_θ_1_", ...) -- not numerically. `qasm3.dumps` names
    the i-th authoring parameter "_θ_{i}_", so translation is by that
    name, never by position.
    """
    import re

    from _fermionic_ansatz import hf_parameters
    from qiskit import qasm3

    fresh = build_ansatz(ansatz, num_qubits, reps=reps, entanglement=entanglement)
    authoring_params = list(fresh.parameters)
    fresh_values = hf_parameters(fresh, hf_state)
    desired_by_authoring_name = {
        str(p): v for p, v in zip(authoring_params, fresh_values)
    }

    loaded = qasm3.loads(qasm_text)
    if loaded.num_parameters != len(authoring_params):
        raise ValueError(
            f"{ansatz}: pinned QASM has {loaded.num_parameters} parameters, "
            f"a freshly-built (qubits={num_qubits}, reps={reps}) circuit has "
            f"{len(authoring_params)} -- out of sync"
        )
    vec = []
    for loaded_param in loaded.parameters:
        match = re.fullmatch(r"_θ_(\d+)_", str(loaded_param))
        if match is None:
            raise ValueError(f"unexpected parameter name {str(loaded_param)!r}")
        vec.append(desired_by_authoring_name[str(authoring_params[int(match.group(1))])])
    return vec


# The seed the benchmark campaign initialises phi from
# (`build_benchmark_matrix.PHI_INIT_SEED`, and the `Phi_Init` column).
# Mirrored rather than imported, because the generator is a sibling guide
# rather than a library; `test_phi_init_seed_matches_the_generator` fails
# the build if the two drift apart.
PHI_INIT_SEED = 20260811


def circuit_spec(
    ansatz: str, num_qubits: int, *, reps: int, num_electrons: int | None = None,
    phi_seed: int = PHI_INIT_SEED,
):
    """`build_ansatz` output as a measured, parameter-bound `CircuitSpec`.

    Parameters are bound to the campaign's own phi_init draw
    (`2*pi*U(0,1)` from `default_rng(phi_seed)`), which is the state a row
    really starts from, rather than to zeros.

    Zeros are not a neutral placeholder for a resource estimate. Every
    rotation becomes the identity, so the transpiler removes it, and where
    a family repeats an entangling block the CX pairs then cancel too: at
    2 qubits an all-zero EfficientSU2 or RealAmplitudes transpiles to
    `{'measure': 2}` -- no gates at all -- and the estimate describes an
    empty circuit. At wider rows the effect is partial (single-qubit gate
    counts roughly halve) and barely moves the duration, since `rz` is
    virtual on IBM hardware, but the estimate should describe the circuit
    the row runs.
    """
    import numpy as np
    from qiskit import qasm3

    from qpubench.schemas.circuit import CircuitSpec
    from qpubench.schemas.primitives import CircuitFormat

    qc = build_ansatz(ansatz, num_qubits, reps=reps, num_electrons=num_electrons)
    if qc.num_parameters:
        rng = np.random.default_rng(phi_seed)
        qc = qc.assign_parameters(2 * np.pi * rng.random(qc.num_parameters))
    qc.measure_all()
    return CircuitSpec(
        num_qubits=num_qubits, format=CircuitFormat.QASM3, serialized=qasm3.dumps(qc)
    )


def circuit_parameter_count(ansatz: str, num_qubits: int, reps: int) -> int | None:
    """Variational parameter count, where (ansatz, qubits, reps) fixes it.

    None for UCCSD, whose count follows the generated excitation list
    rather than the qubit count alone.
    """
    if ansatz == "StronglyEntanglingLayers":
        return 3 * reps * num_qubits            # PennyLane's (L, N, 3) shape
    if ansatz == "n_local_rzryrz_sca":
        return 3 * num_qubits * (reps + 1)      # Qiskit's trailing rotation layer
    if ansatz == "excitation_preserving_linear":
        # One RZ per qubit per rotation layer, plus one theta per linear
        # pair per rep -- Qiskit's default mode="iswap" carries a single
        # parameter per XX+YY gate, not two (that is mode="fsim").
        # Verified against the built circuit's num_parameters.
        return num_qubits * (reps + 1) + (num_qubits - 1) * reps
    if ansatz in ("EfficientSU2", "EfficientSU2_circular"):
        return 2 * num_qubits * (reps + 1)      # two rotation layers per block
    if ansatz == "RealAmplitudes":
        return num_qubits * (reps + 1)          # one rotation layer per block
    if ansatz == "UCCSD":
        return None
    raise ValueError(f"unknown ansatz {ansatz!r}")
