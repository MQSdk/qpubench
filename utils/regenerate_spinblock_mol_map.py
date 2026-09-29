"""Regenerate mol_map Hamiltonians and UCCSD/tUPS circuits under the
spin-block ordering tUPS's efficiency depends on (spin_product_mapping in
_fermionic_ansatz.py, vendored from CompareVQEs/ansatze.py). Also builds
tUPS's own JW layers sweep, which needs no reordering but is not
supplied by hand the way UCCSD's JW circuits are.

Purely local: no new Cebule MOL_MAP submission. The existing committed
hamiltonian_data/*_mapped.json already carries `mapping_matrix`, and
reorder_mapped_hamiltonian(H, D, ...) computes the reordered (H', D',
hf_state) from that alone.

Wrote NEW, distinctly-named files (`mapper == "mol_map_spinblock"`
throughout the campaign) rather than overwriting the old (plain)
`mol_map` data, back when that data and the stage-0 results built on it
were both still live.

NOT RE-RUNNABLE AS WRITTEN: the old `hamiltonian_data/*_mapped.json`
files this script's mol_map-reordering half reads as its SOURCE have
since been deleted (stage 0/1 and the plain `mol_map` mapper were
retired along with them -- see the module docstring of
build_benchmark_matrix.py). Its outputs are already committed and need
no regeneration; this file stays as a record of how they were produced,
and to regenerate anything from it now you would restore those old
Hamiltonian files from backup first. The JW tUPS-layers block below does
not depend on them and remains re-runnable on its own.

THE ROW-REVERSAL FIX: the committed `mapping_matrix`'s row index is NOT
a Qiskit-native computational-basis integer -- it is bit-reversed
relative to one. Discovered here, not assumed: scanning every
computational basis state of the OLD H2O/6-31g mol_map Hamiltonian
against the known Hartree-Fock energy (-75.98399756962218, established
earlier this campaign) found no match among the mapping_matrix's own
declared rows (0-35), but an exact match at state 49 -- which is exactly
row 35 (the true, in-domain HF row) with its 6 bits reversed. Reversing
every row index before building D from the committed triples fixes it,
confirmed against H2/6-31g too (RHF matches there either way, since that
cell's HF row happens to be a bit-palindrome -- the same kind of
insufficient test case noted elsewhere in this campaign's history for
exactly that reason). No prior code in this repo treated
`mapping_matrix`'s rows as Qiskit integers, which is why this was never
caught before.

Run:
    PYTHONPATH=src python utils/regenerate_spinblock_mol_map.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import scipy.sparse as sparse
from _ansatz_builders import qasm_stem
from _fermionic_ansatz import pp_tups, reorder_mapped_hamiltonian, uccsd
from build_benchmark_matrix import CIRCUIT_REPS
from qiskit import qasm3
from qiskit.quantum_info import SparsePauliOp, Statevector

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HAMILTONIAN_DIR = _REPO_ROOT / "data" / "benchmarks" / "ibm_tn-vqe_qesem" / "hamiltonian_data"
_QASM_DIR = _REPO_ROOT / "data" / "qasm"

NEW_MAPPER = "mol_map_spinblock"
N_LAYERS = 2  # tUPS/pp-tUPS default, per instruction
# The JW layers axis is part of build_targeted_screen's own Ansatz-reps
# axis now, so it sweeps the campaign's own CIRCUIT_REPS rather than a
# second, driftable copy of the same list.
TUPS_LAYERS_SWEEP = CIRCUIT_REPS

# (molecule, basis, n_spatial, n_alpha, n_beta, known Hartree-Fock energy).
# The HF energies are cross-checks against numbers already established
# this campaign (RHF for H2/6-31g; the H2O/6-31g CAS(4,4) zero-phi value
# measured earlier via the OLD ordering's own pinned circuit) -- not
# derived here, so a mismatch means something upstream of this script
# broke, not that these numbers were guessed.
CELLS = [
    ("H2", "6-31g", 4, 1, 1, -1.1267333176928163),
    ("H2O", "6-31g", 4, 2, 2, -75.98399756962218),
]

_FILE_MOLECULE = {"H2": "h2", "H2O": "water"}
_FILE_BASIS = {"6-31g": "6-31G"}


def _committed_D(triples: list, n_jw_qubits: int) -> sparse.csr_matrix:
    """D from the committed [row, col, value] triples, with row indices
    corrected from the committed (bit-reversed) convention to Qiskit's
    native computational-basis integer -- see the module docstring."""
    n_mapped_bits = int(np.ceil(np.log2(max(t[0] for t in triples) + 1)))
    rows = [int(format(t[0], f"0{n_mapped_bits}b")[::-1], 2) for t in triples]
    cols = [t[1] for t in triples]
    values = [t[2] for t in triples]
    return sparse.csr_matrix(
        (np.array(values, dtype=complex), (rows, cols)),
        shape=(2**n_mapped_bits, 2**n_jw_qubits),
    )


def _verify(label: str, circuit, H: SparsePauliOp, expected: float) -> None:
    bound = circuit.assign_parameters([0.0] * circuit.num_parameters)
    energy = Statevector(bound).expectation_value(H).real
    status = "OK" if abs(energy - expected) < 1e-6 else "MISMATCH"
    print(f"    {label}: zero-phi E={energy:.10f}  (expected {expected:.10f})  [{status}]")
    if status == "MISMATCH":
        raise SystemExit(f"{label}: does not reproduce the known reference -- not pinning")


def main() -> None:
    _QASM_DIR.mkdir(parents=True, exist_ok=True)
    qubit_counts: dict[tuple[str, str], int] = {}
    term_counts: dict[tuple[str, str], int] = {}

    for molecule, basis, n_spatial, n_alpha, n_beta, expected_hf in CELLS:
        print(f"{molecule}/{basis} CAS({n_alpha + n_beta},{n_spatial}):")
        old_path = (
            _HAMILTONIAN_DIR
            / f"{_FILE_MOLECULE[molecule]}_{_FILE_BASIS[basis]}_mapped.json"
        )
        payload = json.loads(old_path.read_text())
        H_old = SparsePauliOp(payload["h_operators"], payload["h_coeff_values"])
        D_old = _committed_D(payload["mapping_matrix"], n_jw_qubits=2 * n_spatial)

        H_new, D_new, hf_state = reorder_mapped_hamiltonian(
            H_old, D_old, n_spatial, n_alpha, n_beta,
        )
        n_qubits = H_new.num_qubits
        qubit_counts[(molecule, basis)] = n_qubits
        term_counts[(molecule, basis)] = len(H_new.paulis)
        print(f"  qubits: {n_qubits}, Pauli terms: {len(H_new.paulis)}, hf_state: {hf_state}")

        new_path = (
            _HAMILTONIAN_DIR
            / f"{_FILE_MOLECULE[molecule]}_{_FILE_BASIS[basis]}_mapped_spinblock.json"
        )
        new_mapping_matrix = [
            [int(r), int(c), float(v.real)]
            for r, c, v in zip(*sparse.find(D_new))
        ]
        new_payload = {
            "h_coeff_values": H_new.coeffs.real.tolist(),
            "h_operators": [str(p) for p in H_new.paulis],
            "mapping_matrix": new_mapping_matrix,
        }
        new_path.write_text(json.dumps(new_payload))
        print(f"  wrote {new_path.relative_to(_REPO_ROOT)}")

        uccsd_circuit = uccsd(n_spatial, n_alpha, n_beta, mapping_matrix=D_new)
        tups_circuit = pp_tups(n_spatial, n_alpha, n_beta, N_LAYERS, mapping_matrix=D_new)
        _verify(f"UCCSD ({NEW_MAPPER})", uccsd_circuit, H_new, expected_hf)
        _verify(f"{tups_circuit.name} ({NEW_MAPPER})", tups_circuit, H_new, expected_hf)

        for ansatz, circuit in (("UCCSD", uccsd_circuit), ("tUPS", tups_circuit)):
            stem = qasm_stem(
                ansatz, n_qubits, N_LAYERS, mapper=NEW_MAPPER,
                num_electrons=n_alpha + n_beta, num_orbitals=n_spatial,
            )
            path = _QASM_DIR / f"{stem}.qasm"
            path.write_text(qasm3.dumps(circuit) + "\n", encoding="utf-8")
            print(f"  wrote {path.relative_to(_REPO_ROOT)}  ({circuit.num_parameters} params)")

    # tUPS/JW: needs no reordering, but ansatze.py's own JW convention
    # (mode m -> qubit n_qubits-1-m) is the MIRROR of what this repo's
    # committed JW Hamiltonian files use (fixed back in September) --
    # reverse_bits() compensates, exactly as the already-pinned UCCSD/JW
    # circuits were compensated when they were originally supplied.
    # Verified below, not assumed.
    print("H2/6-31g JW tUPS layers sweep (UCCSD/JW is untouched):")
    jw_payload = json.loads((_HAMILTONIAN_DIR / "h2_6-31G_JW.json").read_text())
    H_jw = SparsePauliOp(jw_payload["h_operators"], jw_payload["h_coeff_values"])
    for layers in TUPS_LAYERS_SWEEP:
        tups_jw = pp_tups(4, 1, 1, layers, mapping_matrix=None).reverse_bits()
        _verify(f"tUPS (JW, {layers}L)", tups_jw, H_jw, -1.1267333176928163)
        stem = qasm_stem("tUPS", 8, layers, mapper="JW", num_electrons=2, num_orbitals=0)
        path = _QASM_DIR / f"{stem}.qasm"
        path.write_text(qasm3.dumps(tups_jw) + "\n", encoding="utf-8")
        print(f"  wrote {path.relative_to(_REPO_ROOT)}  ({tups_jw.num_parameters} params)")

    print("\nLookup tables for build_benchmark_matrix.py:")
    print("  qubit counts:", qubit_counts)
    print("  Pauli term counts:", term_counts)


if __name__ == "__main__":
    main()
