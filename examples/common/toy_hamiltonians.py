"""Illustrative qubit Hamiltonians for the guide/demo/tutorial examples.

qpubench performs no real electronic-structure calculations (see
INTEGRATION_GUIDE.md and integrations/generic_adapt_vqe/README.md — "Not
molecular electronic structure"). Every "molecule" used by the examples in
guides/, demos/, and tutorials/ is one of the small qubit Hamiltonians
defined here — NOT derived from real orbital integrals, NOT presented as
physically accurate. They exist purely to drive genuinely-executing
ADAPT-VQE demonstrations without requiring PySCF/OpenFermion/QForte.

Where a real molecule matters, see examples/qforte_vqe_benchmark.py
(He/cc-pVDZ via QForte's own test data, requires `pip install qforte`) or
the swap-in points called out in each example's docstring.

Everything here is 4 qubits / 2 electrons, matching the fixture already
used in tests/test_generic_adapt_vqe.py's `_toy_hamiltonian()` — so results
here are directly comparable to that test's ground truth.
"""
from __future__ import annotations

import math

from qpubench.schemas.observable import PauliTerm, SparsePauliObservable
from qpubench.schemas.primitives import ComplexNumber, PauliLabel

NUM_QUBITS    = 4
NUM_ELECTRONS = 2


def occupied_virtual_hamiltonian(gap: float, hop_02: float, hop_13: float) -> SparsePauliObservable:
    """4-qubit Hamiltonian with hopping between occupied {0,1} and virtual
    {2,3} qubits — i.e. between exactly the qubit pairs
    generate_singles_doubles_pool(4, 2)'s single-excitation operators act
    on. That structural match is what gives ADAPT-VQE's gradient screen
    something to find: a Hamiltonian confined to the occupied block alone
    (as a naively "simpler" toy Hamiltonian would be) has zero gradient
    against every occupied->virtual excitation generator in the pool, so
    ADAPT-VQE would trivially "converge" at the HF reference without ever
    improving on it.

    gap      on-site field: +gap on occupied qubits, -gap on virtual qubits
    hop_02   XX+YY coupling strength between qubits 0 (occupied) and 2 (virtual)
    hop_13   XX+YY coupling strength between qubits 1 (occupied) and 3 (virtual)
    """
    terms = [
        PauliTerm(qubit_indices=(0,), pauli_ops=(PauliLabel.Z,), coefficient=ComplexNumber(re=gap)),
        PauliTerm(qubit_indices=(1,), pauli_ops=(PauliLabel.Z,), coefficient=ComplexNumber(re=gap)),
        PauliTerm(qubit_indices=(2,), pauli_ops=(PauliLabel.Z,), coefficient=ComplexNumber(re=-gap)),
        PauliTerm(qubit_indices=(3,), pauli_ops=(PauliLabel.Z,), coefficient=ComplexNumber(re=-gap)),
    ]
    for (a, b), hop in ((0, 2), hop_02), ((1, 3), hop_13):
        for pauli in (PauliLabel.X, PauliLabel.Y):
            terms.append(PauliTerm(
                qubit_indices=(a, b), pauli_ops=(pauli, pauli),
                coefficient=ComplexNumber(re=hop),
            ))
    return SparsePauliObservable(num_qubits=NUM_QUBITS, terms=terms)


def toy_hamiltonian() -> SparsePauliObservable:
    """A fixed, non-trivial 4-qubit toy Hamiltonian.

    Illustrative only — not derived from real orbital integrals. Verified
    (see examples/common/toy_statevector_backend.py) to give ADAPT-VQE real
    work to do: HF energy is -4.0, exact ground state is
    exact_ground_state_energy(toy_hamiltonian()) ~ -4.4721, and ADAPT-VQE
    closes that gap.
    """
    return occupied_virtual_hamiltonian(gap=1.0, hop_02=0.5, hop_13=0.5)


def toy_bond_hamiltonian(r: float) -> SparsePauliObservable:
    """A 4-qubit Hamiltonian parametrized by a scalar "bond length" r.

    This is a toy model, NOT a real potential energy surface: the
    occupied<->virtual coupling strength follows a Morse-like envelope in
    `r` (peaks near r_eq, decays away from it) purely to produce a smooth,
    physically-plausible-looking dissociation curve — equilibrium minimum,
    rising toward a flat dissociation limit as r grows — for demonstrating
    the reaction-path/dissociation-curve *mechanism*
    (examples/demos/reaction_path_pes_sweep.py,
    examples/tutorials/bond_dissociation_curve.py). Same occupied/virtual
    coupling structure as toy_hamiltonian() — see
    occupied_virtual_hamiltonian's docstring for why that structure matters.

    Swap in a real per-geometry qubit Hamiltonian (OpenFermion / PySCF /
    QForte molecule JSON, one per geometry) at the call site for physically
    meaningful numbers — this function's signature (r -> SparsePauliObservable)
    is exactly the shape that swap-in needs to match.
    """
    r_eq  = 0.74     # loosely evokes the H2 equilibrium bond length (Angstrom)
    decay = 1.2
    hop_02 = 0.6 * math.exp(-decay * abs(r - r_eq))
    hop_13 = 0.4 * math.exp(-decay * abs(r - r_eq))
    return occupied_virtual_hamiltonian(gap=1.0, hop_02=hop_02, hop_13=hop_13)


# ---------------------------------------------------------------------------
# Exact diagonalization — a real, verifiable ground truth (not fabricated)
# ---------------------------------------------------------------------------
# Same dense Jordan-Wigner matrix construction used to independently verify
# pool.py in tests/test_generic_adapt_vqe.py (`_observable_matrix`). Reused
# here to compute real "FCI-in-this-truncated-space" ground-state energies
# for VQAConfig.ground_truth / chemical_accuracy — not textbook numbers —
# and by toy_statevector_backend.py to score circuits against the same
# observable during an actual ADAPT-VQE run.

def observable_matrix(observable: SparsePauliObservable):
    """Dense (2**n x 2**n) matrix for `observable`. Requires numpy."""
    import numpy as np

    n = observable.num_qubits
    i2 = np.eye(2, dtype=complex)
    x = np.array([[0, 1], [1, 0]], dtype=complex)
    y = np.array([[0, -1j], [1j, 0]], dtype=complex)
    z = np.array([[1, 0], [0, -1]], dtype=complex)
    label_map = {"X": x, "Y": y, "Z": z}

    dim = 2 ** n
    matrix = np.zeros((dim, dim), dtype=complex)
    for term in observable.terms:
        ops = [i2] * n
        for qubit_index, pauli in zip(term.qubit_indices, term.pauli_ops):
            ops[qubit_index] = label_map[pauli.value]
        term_matrix = ops[0]
        for op in ops[1:]:
            term_matrix = np.kron(term_matrix, op)
        coeff = term.coefficient.re + 1j * term.coefficient.im
        matrix += coeff * term_matrix
    return matrix


def exact_ground_state_energy(observable: SparsePauliObservable) -> float:
    """Ground-state energy of `observable` via dense diagonalization (numpy).

    Requires numpy (`pip install 'qpubench[adapt_vqe]'` or numpy directly).
    Only practical for the small (<= ~12 qubit) toy Hamiltonians in this
    module — not a general-purpose eigensolver.
    """
    import numpy as np

    eigenvalues = np.linalg.eigvalsh(observable_matrix(observable))
    return float(eigenvalues[0])
