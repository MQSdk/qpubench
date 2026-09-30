"""Fermionic ansatze (UCCSD, pp-tUPS) and mol_map spin-block reordering.

Vendored from CompareVQEs/ansatze.py (user-supplied 2026-09-29), per
integrations/'s own pattern: copied into this project rather than
imported across repos, so this campaign's pinned circuits cannot change
because that repo's code did. Trimmed to the fermionic-ansatz and
reordering machinery this campaign needs; the hardware-efficient wrapper
functions (real_amplitudes, efficient_su2, rzryrz, excitation_preserving)
are NOT vendored -- _ansatz_builders.py already has its own.

All circuits follow the convention of the Hamiltonians this produces:

  * Jordan-Wigner: spin-orbitals interleaved (mode 2p = orbital p alpha,
    2p+1 = orbital p beta), and mode m on Qiskit qubit n_qubits - 1 - m,
    i.e. the leftmost character of a Pauli label is mode 0.
  * Mapped: row k of the mapping matrix D is Qiskit basis state k.
    Columns of D are JW basis states in the same convention as above.

The fermionic ansatze are products of exponentials of excitation
generators applied to Hartree-Fock,

    |psi(theta)> = prod_k exp(theta_k G_k) |HF>,

and are exact in both encodings: on the JW side every G_k is a sum of
commuting Pauli strings, and on the mapped side D G_k D^dagger pairs up
basis states so exp(theta_k G_k) is a set of Givens rotations.

Parameters are named theta_<k> (zero-padded, so they sort in generator
order); `circuit.metadata["generators"]` gives the excitation behind each.
"""

from __future__ import annotations

import functools
import itertools
import warnings
from collections import defaultdict

import numpy as np
import scipy.sparse as sparse
from openfermion import (
    FermionOperator,
    get_sparse_operator,
    hermitian_conjugated,
    jordan_wigner,
)
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit.circuit.library import PauliEvolutionGate
from qiskit.quantum_info import SparsePauliOp
from scipy.sparse.linalg import norm as sparse_norm

TOLERANCE = 1e-10


# ============================================================
# Basis states
# ============================================================


def basis_state_circuit(bits) -> QuantumCircuit:
    """
    Circuit preparing a computational-basis state.

    `bits` is in Pauli-label order (leftmost = highest qubit).
    """
    circuit = QuantumCircuit(len(bits))
    for qubit, occupied in enumerate(reversed(bits)):
        if occupied:
            circuit.x(qubit)
    return circuit


def _mode(orbital: int, spin: int) -> int:
    return 2 * orbital + spin


def _hf_index(n_spatial, n_alpha, n_beta) -> int:
    """JW basis index of the Hartree-Fock determinant."""
    n_qubits = 2 * n_spatial
    modes = [_mode(i, 0) for i in range(n_alpha)] + [_mode(i, 1) for i in range(n_beta)]
    return sum(1 << (n_qubits - 1 - m) for m in modes)


def hf_state_jw(n_spatial: int, n_alpha: int, n_beta: int) -> list[int]:
    """Hartree-Fock basis state under JW, as a bit list in Pauli-label
    order (leftmost = highest qubit) -- the form hf_parameters expects."""
    n_qubits = 2 * n_spatial
    index = _hf_index(n_spatial, n_alpha, n_beta)
    return [index >> q & 1 for q in reversed(range(n_qubits))]


# ============================================================
# Mapping matrix
# ============================================================


def _as_mapping_matrix(mapping_matrix, n_jw_qubits):
    """Load D as a sparse matrix, and check it is a partial isometry."""
    D = sparse.csr_matrix(mapping_matrix, dtype=complex)

    n_rows, n_cols = D.shape
    if n_cols != 2**n_jw_qubits:
        raise ValueError(f"D has {n_cols} columns, expected 2**{n_jw_qubits}.")
    if n_rows & (n_rows - 1):
        raise ValueError(f"D has {n_rows} rows, which is not a power of two.")
    gram = (D @ D.conj().T).toarray()
    if np.linalg.norm(gram @ gram - gram) > 1e-8:
        raise ValueError("The rows of D are not orthonormal.")
    return D


def _blocked_sign(modes):
    """Sign of reordering occupied interleaved modes into all alpha, then all beta."""
    return (-1) ** sum(1 for x in modes for y in modes if x < y and x % 2 and not y % 2)


def spin_product_mapping(mapping_matrix, n_spatial, n_alpha, n_beta):
    """
    Mapping matrix over the same determinants as `mapping_matrix`, reindexed
    so the fermionic ansatze are cheap to synthesise.

    Row = (alpha string index) << n_beta_bits | (beta string index), and the
    entry is the sign of the determinant with all alpha modes written before
    all beta modes.  An excitation then acts on the alpha and beta qubits
    separately, and identically for every string of the other spin, so the
    mapped synthesis can merge its rotations.  Needs
    ceil(log2 C(n, n_alpha)) + ceil(log2 C(n, n_beta)) qubits, which can be
    one more than a compact numbering.

    Args:
        mapping_matrix: The (old-ordering) mapping matrix; each row must
            select a single determinant (entry +-1).
        n_spatial: Number of (active) spatial orbitals.
        n_alpha, n_beta: Number of (active) alpha and beta electrons.

    Returns:
        Sparse mapping matrix D'.
    """
    n_jw = 2 * n_spatial
    D = _as_mapping_matrix(mapping_matrix, n_jw)
    if (np.diff(D.indptr) > 1).any() or not np.allclose(np.abs(D.data), 1):
        raise ValueError("Each row of D must select a single determinant.")

    strings = {spin: {s: k for k, s in enumerate(itertools.combinations(range(n_spatial), n))}
               for spin, n in ((0, n_alpha), (1, n_beta))}
    beta_bits = (len(strings[1]) - 1).bit_length()
    n_qubits = max(1, (len(strings[0]) - 1).bit_length() + beta_bits)

    rows, values = [], []
    for column in D.indices:
        modes = [m for m in range(n_jw) if column >> (n_jw - 1 - m) & 1]
        alpha, beta = (tuple(m // 2 for m in modes if m % 2 == s) for s in (0, 1))
        if alpha not in strings[0] or beta not in strings[1]:
            raise ValueError(
                f"D selects a determinant with {len(alpha)}a+{len(beta)}b electrons, "
                f"expected {n_alpha}a+{n_beta}b."
            )
        rows.append(strings[0][alpha] << beta_bits | strings[1][beta])
        values.append(_blocked_sign(modes))
    return sparse.csr_matrix(
        (np.array(values, dtype=complex), (rows, D.indices)),
        shape=(2**n_qubits, 2**n_jw),
    )


def reorder_mapped_hamiltonian(hamiltonian, mapping_matrix, n_spatial, n_alpha, n_beta):
    """
    Rewrite a mapped Hamiltonian in the `spin_product_mapping` basis.

    Both bases select the same determinants, so they differ by the signed
    permutation Q = D' D^dagger and H' = Q H Q^dagger.  Parts of H on states
    outside the image of D, which no physical state reaches, are dropped.

    Args:
        hamiltonian: The mapped Hamiltonian, as a SparsePauliOp.
        mapping_matrix: Its (old-ordering) mapping matrix.
        n_spatial: Number of (active) spatial orbitals.
        n_alpha, n_beta: Number of (active) alpha and beta electrons.

    Returns:
        hamiltonian: H' as a SparsePauliOp with real coefficients.
        mapping_matrix: D', to build the ansatz with.
        hf_state: The Hartree-Fock basis state of D', as a bit list in
            Pauli-label order.
    """
    D = _as_mapping_matrix(mapping_matrix, 2 * n_spatial)
    if hamiltonian.num_qubits != int(np.log2(D.shape[0])):
        raise ValueError(
            f"The Hamiltonian acts on {hamiltonian.num_qubits} qubits but D maps "
            f"onto {int(np.log2(D.shape[0]))}."
        )
    D_new = spin_product_mapping(D, n_spatial, n_alpha, n_beta)
    Q = D_new @ D.conj().T
    H = (Q @ hamiltonian.to_matrix(sparse=True) @ Q.conj().T).toarray()

    # rtol=0: the default relative cutoff drops terms up to ~1e-5 times the largest.
    reordered = SparsePauliOp.from_operator(H, atol=TOLERANCE, rtol=0.0).simplify(atol=TOLERANCE)
    if np.abs(reordered.coeffs.imag).max() > 1e-9:
        raise ValueError("The reordered Hamiltonian has complex Pauli coefficients.")
    reordered = SparsePauliOp(reordered.paulis, reordered.coeffs.real)

    n_qubits = int(np.log2(D_new.shape[0]))
    hf = int(np.flatnonzero(D_new[:, _hf_index(n_spatial, n_alpha, n_beta)].toarray())[0])
    return reordered, D_new, [hf >> q & 1 for q in reversed(range(n_qubits))]


# ============================================================
# Generators
# ============================================================
#
# A generator is a dict with descriptive fields (type, spin, occupied,
# virtual) and "parts": commuting anti-Hermitian FermionOperators that
# share one parameter.  Splitting a spin-adapted single into its alpha and
# beta hops keeps each part a single excitation, which the mapped
# synthesis needs.


def _excitation(created, annihilated) -> FermionOperator:
    """tau - tau^dagger for tau = a^dag_created... a_annihilated..."""
    tau = FermionOperator(
        tuple((p, 1) for p in created) + tuple((p, 0) for p in annihilated)
    )
    return tau - hermitian_conjugated(tau)


def _generator(kind, spin, occupied, virtual, *parts):
    return {"type": kind, "spin": spin, "occupied": tuple(occupied),
            "virtual": tuple(virtual), "parts": list(parts)}


def uccsd_generators(n_spatial, n_alpha, n_beta):
    """Spin-conserving singles and doubles out of the HF determinant."""
    alpha = [_mode(p, 0) for p in range(n_spatial)]
    beta = [_mode(p, 1) for p in range(n_spatial)]
    occ_a, virt_a = alpha[:n_alpha], alpha[n_alpha:]
    occ_b, virt_b = beta[:n_beta], beta[n_beta:]

    generators = []
    for spin, occ, virt in (("alpha", occ_a, virt_a), ("beta", occ_b, virt_b)):
        for i, a in itertools.product(occ, virt):
            generators.append(_generator("single", spin, (i,), (a,), _excitation((a,), (i,))))

    for spin, occ, virt in (("aa", occ_a, virt_a), ("bb", occ_b, virt_b)):
        for (i, j), (a, b) in itertools.product(
            itertools.combinations(occ, 2), itertools.combinations(virt, 2)
        ):
            generators.append(_generator(
                "double", spin, (i, j), (a, b), _excitation((a, b), (j, i))
            ))

    for i, j, a, b in itertools.product(occ_a, occ_b, virt_a, virt_b):
        generators.append(_generator(
            "double", "ab", (i, j), (a, b), _excitation((a, b), (j, i))
        ))
    return generators


def perfect_pairing_order(n_spatial, n_occupied):
    """
    Orbital order along the tUPS chain that puts each occupied orbital next
    to its partner virtual: HOMO with LUMO, HOMO-1 with LUMO+1, ...

    E.g. 4 orbitals with 2 occupied gives [0, 3, 1, 2].
    """
    if 2 * n_occupied != n_spatial:
        raise ValueError(
            "Perfect pairing needs as many virtual as occupied orbitals, got "
            f"{n_occupied} occupied in {n_spatial}."
        )
    return [p for k in range(n_occupied) for p in (k, n_spatial - 1 - k)]


def occupied_middle_order(n_spatial, n_occupied):
    """
    Orbital order along the tUPS chain with the occupied orbitals in the
    middle, HOMO next to LUMO, and the virtuals alternating outwards by
    energy: LUMO, LUMO+2, ... on one side, LUMO+1, LUMO+3, ... on the other.
    Each layer then reaches virtuals on both sides of the occupied block.

    E.g. 8 orbitals with 1 occupied gives [7, 5, 3, 1, 0, 2, 4, 6].
    """
    virtuals = list(range(n_occupied, n_spatial))
    return virtuals[0::2][::-1] + list(range(n_occupied))[::-1] + virtuals[1::2]


def tups_generators(n_spatial, n_layers, orbital_order, skip_last_singles=False):
    """
    tUPS layers after slowquant: a brick wall of blocks on neighbouring
    chain positions, first p = 0, 2, ... then p = 1, 3, ..., each block a
    spin-adapted single, a pair double and another spin-adapted single.
    """
    generators = []
    for layer in range(n_layers):
        last = layer + 1 == n_layers
        for start in (0, 1):
            for p in range(start, n_spatial - 1, 2):
                i, a = orbital_order[p], orbital_order[p + 1]
                single = _generator(
                    "sa_single", "singlet", (i,), (a,),
                    *(_excitation((_mode(a, s),), (_mode(i, s),)) for s in (0, 1)),
                )
                double = _generator(
                    "pair_double", "ab", (i,), (a,),
                    _excitation((_mode(a, 0), _mode(a, 1)), (_mode(i, 1), _mode(i, 0))),
                )
                generators += [single, double]
                if not (last and skip_last_singles and (start == 1 or n_spatial == 2)):
                    generators.append(single)
    return generators


# ============================================================
# Jordan-Wigner synthesis
# ============================================================


def _jw_hamiltonian(operator, n_qubits) -> SparsePauliOp | None:
    """
    i * operator as a Pauli sum, or None if it vanishes.

    OpenFermion qubit m is written at label position m from the left, which
    is Qiskit qubit n_qubits - 1 - m.
    """
    labels, coefficients = [], []
    for term, coefficient in jordan_wigner(operator).terms.items():
        label = ["I"] * n_qubits
        for qubit, pauli in term:
            label[qubit] = pauli
        labels.append("".join(label))
        coefficients.append(1j * coefficient)
    if not labels:
        return None
    op = SparsePauliOp(labels, coefficients).simplify(atol=TOLERANCE)
    return None if np.all(np.abs(op.coeffs) <= TOLERANCE) else op


# ============================================================
# Mapped synthesis: exact Givens rotations
# ============================================================
#
# D G D^dagger for a single excitation pairs up basis states,
# G|p> = -c|q>, G|q> = c|p>, so exp(theta G) is a set of commuting
# two-level rotations sharing theta.  Each pair is brought to differ in
# one `target` qubit by a CNOT ladder and rotated there by an RY
# controlled on all other qubits.  Control patterns are merged where the
# extra states touched are unreachable (outside the image of D), and per
# group the cheaper of separate multi-controlled RYs and a single
# uniformly controlled RY is emitted.


def _givens_blocks(G):
    """[(p, q, c)] with p < q and G[p, q] = c = -G[q, p], or None."""
    if np.abs(G.imag).max() > TOLERANCE:
        return None
    A = G.real
    nonzero = np.abs(A) > TOLERANCE
    if (
        (nonzero.sum(axis=1) > 1).any()
        or (nonzero != nonzero.T).any()
        or nonzero.diagonal().any()
    ):
        return None
    blocks = []
    for p, q in zip(*np.nonzero(np.triu(nonzero, k=1))):
        if abs(A[p, q] + A[q, p]) > TOLERANCE:
            return None
        blocks.append((int(p), int(q), float(A[p, q])))
    return blocks


def _cover(lows, controls, flip, dont_care):
    """
    Few control patterns ("cubes": qubit -> required value, absent = free)
    covering every state in `lows`.  A cube may also match other states,
    but only ones that are unreachable along with their partner `s ^ flip`.
    """
    def matches(cube):
        free = [b for b in controls if b not in cube]
        base = sum(1 << b for b, v in cube.items() if v)
        for pattern in range(1 << len(free)):
            yield base | sum(1 << b for k, b in enumerate(free) if pattern >> k & 1)

    candidates = []
    for values in itertools.product((None, 0, 1), repeat=len(controls)):
        cube = {b: v for b, v in zip(controls, values) if v is not None}
        states = set(matches(cube))
        if (states & lows) and all(
            s in lows or (s in dont_care and s ^ flip in dont_care) for s in states
        ):
            candidates.append((cube, states & lows))

    # Greedy set cover: most newly covered states per control.
    chosen, remaining = [], set(lows)
    while remaining:
        cube, covered = max(
            candidates,
            key=lambda c: (len(c[1] & remaining) / (len(c[0]) + 1), -len(c[0])),
        )
        chosen.append(cube)
        remaining -= covered
    return chosen


@functools.lru_cache(maxsize=None)
def _mcx_cost(n_controls):
    """CX count of an ancilla-free multi-controlled X."""
    if n_controls <= 1:
        return n_controls
    from qiskit import transpile
    probe = QuantumCircuit(n_controls + 1)
    probe.mcx(list(range(n_controls)), n_controls)
    return transpile(probe, basis_gates=["u", "cx"], optimization_level=0).count_ops()["cx"]


@functools.lru_cache(maxsize=None)
def _gray_code_transform(n_controls):
    """
    (M, cx_controls) for a uniformly controlled RY (Moettoenen et al.):
    RY(phi_j) then CX from control cx_controls[j], for j along a Gray code,
    with phi = M @ angles.  M is linear, so angles may carry a Parameter.
    """
    gray = [j ^ (j >> 1) for j in range(1 << n_controls)]
    M = np.array(
        [[(-1) ** bin(g & i).count("1") for i in range(len(gray))] for g in gray]
    ) / len(gray)
    cx_controls = [
        (g ^ gray[(j + 1) % len(gray)]).bit_length() - 1 for j, g in enumerate(gray)
    ]
    return M, cx_controls


def _controlled_ry(circuit, angle, cube, target):
    open_controls = [b for b, v in cube.items() if not v]
    for b in open_controls:
        circuit.x(b)
    if cube:
        # MCRY(a) = MCX RY(-a/2) MCX RY(a/2), so the parameter only ever sits
        # on a plain RY; Qiskit's QASM 3 exporter mangles parameterised
        # multi-controlled rotations.
        controls = sorted(cube)
        circuit.ry(angle / 2, target)
        circuit.mcx(controls, target)
        circuit.ry(-angle / 2, target)
        circuit.mcx(controls, target)
    else:
        circuit.ry(angle, target)
    for b in open_controls:
        circuit.x(b)


def _multiplexed_ry(circuit, rotations, controls, target, theta):
    angles = np.zeros(1 << len(controls))
    for scale, cube in rotations:
        for index in range(len(angles)):
            if all(index >> k & 1 == cube[b] for k, b in enumerate(controls) if b in cube):
                angles[index] = scale
    M, cx_controls = _gray_code_transform(len(controls))
    for phi, c in zip(M @ angles, cx_controls):
        if phi:
            circuit.ry(float(phi) * theta, target)
        circuit.cx(controls[c], target)


def _append_givens(circuit, G, theta, dont_care):
    """Append exp(theta G) for G a direct sum of 2x2 antisymmetric blocks."""
    blocks = _givens_blocks(G)
    if blocks is None:
        raise ValueError("Mapped generator is not a set of disjoint two-level blocks.")

    # (target, flip) -> {angle scale -> states with target bit 0}
    groups = defaultdict(lambda: defaultdict(set))
    for p, q, c in blocks:
        flip = p ^ q
        target = (flip & -flip).bit_length() - 1
        low = q if p >> target & 1 else p
        # RY(a)|0> = cos(a/2)|0> + sin(a/2)|1>, and exp(tG)|p> = cos(ct)|p> - sin(ct)|q>.
        scale = 2 * (-c if low == p else c)
        groups[target, flip][round(scale, 12)].add(low)

    for (target, flip), by_scale in sorted(groups.items()):
        controls = [b for b in range(circuit.num_qubits) if b != target]
        ladder = [b for b in controls if flip >> b & 1]
        rotations = [
            (scale, cube)
            for scale, lows in sorted(by_scale.items())
            for cube in _cover(lows, controls, flip, dont_care)
        ]

        for b in ladder:
            circuit.cx(target, b)
        if (1 << len(controls)) < sum(2 * _mcx_cost(len(cube)) for _, cube in rotations):
            _multiplexed_ry(circuit, rotations, controls, target, theta)
        else:
            for scale, cube in rotations:
                _controlled_ry(circuit, scale * theta, cube, target)
        for b in reversed(ladder):
            circuit.cx(target, b)


# ============================================================
# Circuit assembly
# ============================================================


def _x_on(circuit, index):
    for qubit in range(circuit.num_qubits):
        if index >> qubit & 1:
            circuit.x(qubit)


def _build(generators, n_spatial, n_alpha, n_beta, mapping_matrix, name):
    """prod_k exp(theta_k G_k) |HF> in the JW or mapped encoding."""
    if n_alpha > n_spatial or n_beta > n_spatial:
        raise ValueError(
            f"{n_alpha}a+{n_beta}b electrons do not fit in {n_spatial} orbitals."
        )
    n_jw = 2 * n_spatial
    hf = _hf_index(n_spatial, n_alpha, n_beta)
    width = len(str(len(generators) - 1))
    parameters = [Parameter(f"theta_{k:0{width}d}") for k in range(len(generators))]
    used = set()

    if mapping_matrix is None:
        circuit = QuantumCircuit(n_jw, name=name)
        _x_on(circuit, hf)
        for k, generator in enumerate(generators):
            for part in generator["parts"]:
                hamiltonian = _jw_hamiltonian(part, n_jw)
                if hamiltonian is not None:
                    # Exact: the Pauli terms of an excitation generator commute.
                    circuit.append(
                        PauliEvolutionGate(hamiltonian, time=parameters[k]), range(n_jw)
                    )
                    used.add(k)
    else:
        D = _as_mapping_matrix(mapping_matrix, n_jw)
        D_dagger = D.conj().T.tocsc()
        column = np.abs(D[:, hf].toarray().ravel())
        mapped_hf = int(np.argmax(column))
        if abs(column[mapped_hf] - 1) > TOLERANCE:
            raise ValueError("D|HF> is not a computational-basis state.")
        # Rows of D that no JW state maps to are never populated.
        dont_care = frozenset(np.flatnonzero(np.diff(D.indptr) == 0).tolist())

        circuit = QuantumCircuit(int(np.log2(D.shape[0])), name=name)
        _x_on(circuit, mapped_hf)
        leakage = 0.0
        for k, generator in enumerate(generators):
            for part in generator["parts"]:
                G_D = get_sparse_operator(part, n_qubits=n_jw).tocsr() @ D_dagger
                G_mapped = (D @ G_D).toarray()
                # ||(1 - D^dag D) G D^dag||: how far G takes states out of D's image.
                leakage = max(leakage, np.sqrt(max(
                    sparse_norm(G_D) ** 2 - np.linalg.norm(G_mapped) ** 2, 0.0
                )))
                if np.linalg.norm(G_mapped) > TOLERANCE:
                    _append_givens(circuit, G_mapped, parameters[k], dont_care)
                    used.add(k)
        if leakage > 1e-8:
            warnings.warn(
                f"The generators take states outside the image of D (leakage "
                f"{leakage:.2e}); the mapped circuit does not reproduce the JW one."
            )

    fields = ("type", "spin", "occupied", "virtual")
    circuit.metadata = {
        "generators": {
            parameters[k].name: {f: generators[k][f] for f in fields} for k in sorted(used)
        }
    }
    return circuit


# ============================================================
# Fermionic ansatze
# ============================================================


def uccsd(n_spatial, n_alpha, n_beta, mapping_matrix=None):
    """
    Single-step Trotterised UCCSD, Hartree-Fock state included.

    Args:
        n_spatial: Number of (active) spatial orbitals.
        n_alpha, n_beta: Number of (active) alpha and beta electrons.
        mapping_matrix: None for Jordan-Wigner, otherwise the mapping
            matrix D (spin_product_mapping's output, for this campaign).

    Returns:
        QuantumCircuit
    """
    return _build(
        uccsd_generators(n_spatial, n_alpha, n_beta),
        n_spatial, n_alpha, n_beta, mapping_matrix, name="UCCSD",
    )


def pp_tups(n_spatial, n_alpha, n_beta, n_layers, mapping_matrix=None,
            orbital_order=None, skip_last_singles=False):
    """
    Tiled unitary product state ansatz (10.1103/PhysRevResearch.6.023300),
    Hartree-Fock state included.

    Args:
        n_spatial: Number of (active) spatial orbitals.
        n_alpha, n_beta: Number of (active) alpha and beta electrons.
        n_layers: Number of layers.
        mapping_matrix: None for Jordan-Wigner, otherwise the mapping
            matrix D (spin_product_mapping's output, for this campaign).
        orbital_order: Canonical orbital at each chain position.  None means
            `perfect_pairing_order` for a closed shell at half filling, and
            otherwise, with a warning that this is plain tUPS,
            `occupied_middle_order`.
        skip_last_singles: Omit the second single of every block in the last
            layer's second column (and of the only block when n_spatial == 2),
            as slowquant does.

    Returns:
        QuantumCircuit
    """
    name = f"pp-tUPS({n_layers})"
    if orbital_order is None:
        if n_alpha != n_beta:
            raise ValueError("Perfect pairing needs n_alpha == n_beta.")
        if 2 * n_alpha == n_spatial:
            orbital_order = perfect_pairing_order(n_spatial, n_alpha)
        else:
            orbital_order = occupied_middle_order(n_spatial, n_alpha)
            name = f"tUPS({n_layers})"
            warnings.warn(
                f"Perfect pairing needs as many virtual as occupied orbitals, got "
                f"{n_alpha} occupied in {n_spatial}; building tUPS with the "
                f"occupied orbitals in the middle of the chain, {orbital_order}."
            )
    if sorted(orbital_order) != list(range(n_spatial)):
        raise ValueError(f"{orbital_order} is not a permutation of the orbitals.")

    return _build(
        tups_generators(n_spatial, n_layers, orbital_order, skip_last_singles),
        n_spatial, n_alpha, n_beta, mapping_matrix, name=name,
    )


# ============================================================
# Hartree-Fock phi_init for a hardware-efficient ansatz
# ============================================================


def hf_parameters(circuit, hf_state):
    """
    Parameter values at which a hardware-efficient circuit prepares
    `hf_state`: zero, except pi for the last RY (or RX) on each qubit that
    is 1 in the state.

    Relies on the circuit leaving |0...0> alone at zero angles, as
    RealAmplitudes, EfficientSU2 and rzryrz do. Only
    parameterised RZs (identities at zero) may follow that last rotation
    on its qubit.

    Args:
        circuit: The ansatz, e.g. as reloaded from QASM.
        hf_state: Bit list in Pauli-label order (leftmost = highest qubit).

    Returns:
        list of values, in `circuit.parameters` order.
    """
    if len(hf_state) != circuit.num_qubits:
        raise ValueError(f"hf_state has {len(hf_state)} bits for {circuit.num_qubits} qubits.")
    values = dict.fromkeys(circuit.parameters, 0.0)
    for qubit, occupied in enumerate(reversed(hf_state)):
        if not occupied:
            continue
        for instruction in reversed(circuit.data):
            wires = [circuit.find_bit(b).index for b in instruction.qubits]
            if qubit not in wires:
                continue
            gate, angle = instruction.operation, instruction.operation.params
            if len(wires) == 1 and gate.name in ("rx", "ry") and isinstance(angle[0], Parameter):
                values[angle[0]] = np.pi
                break
            if len(wires) == 1 and gate.name == "rz" and isinstance(angle[0], Parameter):
                continue
            raise ValueError(
                f"Qubit {qubit} does not end in a parameterised RY or RX followed "
                f"only by RZs (found {gate.name}), so hf_state cannot be set "
                "through the parameters."
            )
        else:
            raise ValueError(f"Qubit {qubit} has no parameterised RY or RX.")
    return [values[p] for p in circuit.parameters]
