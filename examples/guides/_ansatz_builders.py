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

`n_local_rzryrz_sca` is the Qiskit path (`functions_qiskit.py:36`):
`n_local(n, ["rz","ry","rz"], "cx", entanglement="sca")`. This is the one
that runs in an IBM campaign, so it is what the benchmark matrix names on
its TN rows. Parameter count `3n(R+1)` — the trailing rotation layer is
the difference from PennyLane's.

`StronglyEntanglingLayers` is PennyLane's (`functions_pennylane.py:28`),
which the task uses on `default.qubit` / `lightning.qubit`. Rebuilt here
in Qiskit to PennyLane's own definition: per layer, a general
single-qubit rotation (Rot = RZ then RY then RZ) on every wire, then a
ring of CNOTs whose stride varies with the layer index. Parameter count
`3nR`, the (L, N, 3) shape.

Costing an IBM row on the PennyLane circuit is a real (if small) error:
at stage-1 sizes it moves the estimate by under 2%, and at 8 and 12
qubits `n_local` is the *cheaper* of the two. It is worth getting right
because the estimate should describe the circuit that runs, and because
the 50% understatement it caused in `Num_Opt_Params_Phi` was not small.

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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

if TYPE_CHECKING:
    from qiskit import QuantumCircuit

SUPPORTED_ANSATZE = (
    "EfficientSU2",
    "RealAmplitudes",
    "StronglyEntanglingLayers",
    "n_local_rzryrz_sca",
    "excitation_preserving_linear",
    "UCCSD",
)


def build_ansatz(
    ansatz: str,
    num_qubits: int,
    *,
    reps: int = 1,
    num_electrons: int | None = None,
) -> "QuantumCircuit":
    """Build `ansatz` on `num_qubits` qubits at `reps` repetitions.

    `num_electrons` is required by UCCSD alone, which needs a reference
    determinant and an occupied/virtual split; the hardware-efficient
    families ignore it.
    """
    if ansatz == "EfficientSU2":
        from qiskit.circuit.library import efficient_su2
        return efficient_su2(num_qubits, reps=reps)
    if ansatz == "RealAmplitudes":
        from qiskit.circuit.library import real_amplitudes
        return real_amplitudes(num_qubits, reps=reps)
    if ansatz == "StronglyEntanglingLayers":
        return strongly_entangling_layers(num_qubits, reps=reps)
    if ansatz == "n_local_rzryrz_sca":
        return n_local_rzryrz_sca(num_qubits, reps=reps)
    if ansatz == "excitation_preserving_linear":
        return excitation_preserving_linear(num_qubits, reps=reps)
    if ansatz == "UCCSD":
        if num_electrons is None:
            raise ValueError("UCCSD needs num_electrons to place the reference determinant")
        return uccsd(num_qubits, num_electrons, reps=reps)
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


def n_local_rzryrz_sca(num_qubits: int, *, reps: int = 1) -> "QuantumCircuit":
    """TN_QC_OPT's Qiskit circuit side, exactly as `functions_qiskit.py:36`
    builds it: `n_local(n, ["rz","ry","rz"], "cx", entanglement="sca")`.

    'sca' is Qiskit's shifted-circular-alternating entanglement: a
    circular CX chain whose starting qubit shifts each rep and whose
    control/target orientation alternates.
    """
    from qiskit.circuit.library import n_local

    return n_local(
        num_qubits, ["rz", "ry", "rz"], "cx", reps=reps, entanglement="sca",
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


def uccsd(num_qubits: int, num_electrons: int, *, reps: int = 1) -> "QuantumCircuit":
    """First-order Trotterized UCCSD over a Hartree-Fock reference.

    `num_qubits` are spin orbitals, so this assumes a Jordan-Wigner
    mapping; the excitation operators are the JW-mapped ones the
    ADAPT-VQE pool generator produces.
    """
    from qiskit import QuantumCircuit
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
    for _ in range(reps):
        for operator in pool:
            terms = operator.observable.to_qiskit_pauli_list(num_qubits)
            # The excitation operators are anti-Hermitian (purely
            # imaginary coefficients); PauliEvolutionGate wants the
            # Hermitian generator, hence the imaginary part.
            generator = SparsePauliOp.from_list(
                [(label, coeff.imag) for label, coeff in terms]
            )
            qc.append(PauliEvolutionGate(generator, time=0.1), range(num_qubits))
    return qc


def circuit_spec(
    ansatz: str, num_qubits: int, *, reps: int, num_electrons: int | None = None,
):
    """`build_ansatz` output as a measured, parameter-bound `CircuitSpec`."""
    from qiskit import qasm3

    from qpubench.schemas.circuit import CircuitSpec
    from qpubench.schemas.primitives import CircuitFormat

    qc = build_ansatz(ansatz, num_qubits, reps=reps, num_electrons=num_electrons)
    if qc.num_parameters:
        qc = qc.assign_parameters([0.0] * qc.num_parameters)
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
    if ansatz == "EfficientSU2":
        return 2 * num_qubits * (reps + 1)      # two rotation layers per block
    if ansatz == "RealAmplitudes":
        return num_qubits * (reps + 1)          # one rotation layer per block
    if ansatz == "UCCSD":
        return None
    raise ValueError(f"unknown ansatz {ansatz!r}")
