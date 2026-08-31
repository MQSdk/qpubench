"""How many circuits does ONE cost-function evaluation really submit?

Requires: pip install 'qpubench[qiskit]' pyscf

Evaluating <H> takes one circuit per measurement BASIS, and how many
bases that is follows from the Hamiltonian rather than from the circuit
preparing the state.  `split_benchmark_batches.py` costs every row from
that count, so it is what the campaign's QPU time is proportional to.  This script measures that factor for the Jordan-Wigner rows of the
stage-1 matrix.  It is where the `qwc_grouping` values in the matrix's
`Num_ExpVals_Per_Iter` column come from, and it re-derives them so that a
committed value can be checked against the Hamiltonian it claims to
describe.

What is counted
---------------
Each row's own active space is built with PySCF, mapped to qubits with
Jordan-Wigner, and the resulting Pauli sum is grouped into QUBIT-WISE
COMMUTING sets.  Every such set is one measurement basis, hence one
circuit, hence one submission at the row's full shot count.

  terms       distinct Pauli strings in the mapped Hamiltonian; the
              identity is excluded, since it costs no measurement
  E           qubit-wise-commuting groups, i.e. circuits per evaluation,
              or "-" where the term count exceeds MAX_GROUPING_TERMS

Both are structural: they follow from which integrals are non-zero, so
they barely move with bond length.  The equilibrium geometries below are
therefore adequate even though the campaign has not settled its
geometries, which is a separate open decision.

What is NOT counted
-------------------
  * mol_map rows.  Their Hamiltonian is Cebule's constraint encoding over
    determinant indices, which this repository cannot build offline.
  * `Measurement_Method = grouped`.  Cebule's basis-state-pair scheme is
    a different grouping, and its circuit count is an output of a run.
  * TN-VQE rows.  Those measure U(theta)^dag H U(theta), which carries
    MORE Pauli terms than H, so the numbers here are a lower bound for
    them.
  * General (non-qubit-wise) commuting sets, which would be fewer than E
    but need entangling basis-change circuits.

Run:
    PYTHONPATH=src python utils/count_measurement_bases.py
"""
from __future__ import annotations

import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CSV_PATH = (
    _REPO_ROOT / "data" / "benchmarks" / "ibm_tn-vqe_qesem"
    / "stage1_screening_matrix.csv"
)

# Experimental equilibrium geometries, in Angstrom:
#
#   H2   r_e = 0.74144            Huber & Herzberg, via NIST CCCBDB
#   H2O  r_e = 0.9572, 104.52 deg Benedict, Gailar & Plyler (1956)
#
# H2O's hydrogens are placed in the yz-plane with the oxygen at the
# origin, so y = r sin(theta/2) and z = r cos(theta/2) reproduce that
# bond length and angle exactly.
#
# The counts this module produces do not actually depend on these values,
# since a term count is a property of which integrals are non-zero rather
# than of their magnitudes.  They are pinned at equilibrium so that the
# campaign names one geometry everywhere it names a molecule.
GEOMETRIES = {
    "H2": "H 0 0 0; H 0 0 0.74144",
    "Li2": "Li 0 0 0; Li 0 0 2.6729",
    "H2O": "O 0 0 0; H 0 0.75695 0.58588; H 0 -0.75695 0.58588",
}

# Campaign basis name -> PySCF's spelling.
PYSCF_BASIS = {
    "sto-3g": "sto3g", "6-31g": "631g", "cc-pvdz": "ccpvdz",
    "cc-pvtz": "ccpvtz", "def2-svp": "def2svp", "def2-tzvp": "def2tzvp",
}
# qvSZP has no PySCF entry, so its rows are measured on a SHAPE PROXY: a
# space with the same orbital count, which is what fixes the term count.
QVSZP_PROXY = ("ccpvdz", "shape proxy: same orbital count, different basis")

# group_commuting builds a DENSE n x n adjacency matrix and then
# materialises one Python tuple per edge (PauliList._noncommutation_graph:
# list(zip(*np.where(np.triu(adj, k=1))))), so its peak memory is
# quadratic in the term count.  Measured on this repository's own files:
#
#     2,064 terms  0.43 GB     6,401 terms  3.68 GB
#     2,951 terms  0.80 GB     8,240 terms  5.46 GB
#
# which extrapolates to ~80 GB at h2_def2-tzvp_mapped's 32,000 terms.  On
# a 16 GB machine that does not fail cleanly: it invokes the OOM killer,
# which takes the whole parent process group with it.
#
# The campaign's own rows top out at 2,064 terms (qvSZP), so this ceiling
# never binds on a real row.  It exists so that pointing this script at a
# larger basis reports the term count and declines, rather than dying.
MAX_GROUPING_TERMS = 4_000


def measurement_bases(
    molecule: str, basis: str, active_electrons: int, active_orbitals: int,
    full_space: bool,
) -> tuple[int, int, int | None, str]:
    """(qubits, Pauli terms, qubit-wise-commuting groups, proxy note).

    groups is None where the term count exceeds MAX_GROUPING_TERMS.
    """
    from qiskit_nature.second_q.drivers import PySCFDriver
    from qiskit_nature.second_q.mappers import JordanWignerMapper
    from qiskit_nature.second_q.transformers import ActiveSpaceTransformer

    proxy_note = ""
    if basis == "qvSZP":
        pyscf_basis, proxy_note = QVSZP_PROXY
        restrict = True                      # cut the proxy down to shape
    else:
        pyscf_basis = PYSCF_BASIS[basis]
        restrict = not full_space

    problem = PySCFDriver(atom=GEOMETRIES[molecule], basis=pyscf_basis).run()
    if restrict:
        problem = ActiveSpaceTransformer(
            active_electrons, active_orbitals
        ).transform(problem)

    operator = JordanWignerMapper().map(
        problem.hamiltonian.second_q_op()
    ).simplify()
    identity = "I" * operator.num_qubits
    terms = sum(1 for pauli in operator.paulis if str(pauli) != identity)
    if terms > MAX_GROUPING_TERMS:
        groups = None
    else:
        groups = len(operator.group_commuting(qubit_wise=True))
    return operator.num_qubits, terms, groups, proxy_note


def main() -> None:
    with _CSV_PATH.open(encoding="utf-8") as f:
        matrix = list(csv.DictReader(f))

    # One measurement per distinct (molecule, basis) among the JW rows:
    # the Hamiltonian does not depend on the ansatz or the method.
    classes: dict[tuple[str, str], dict[str, str]] = {}
    for row in matrix:
        if row["Mapper"] != "JW":
            continue
        classes.setdefault((row["Molecule"], row["Basis"]), row)

    print(f"Measurement bases per evaluation, JW rows of {_CSV_PATH.name}")
    print(f"{'molecule/basis':22} {'space':12} {'qubits':>6} {'terms':>7} {'E':>6}")
    # Keyed by (molecule, qubits), not by qubits: two different active
    # spaces reach 8 qubits here with different term counts, and keying on
    # width alone silently costs one of them at the other's E.
    measured: dict[tuple[str, int], int] = {}
    for (molecule, basis), row in sorted(
        classes.items(), key=lambda kv: int(kv[1]["N_Qubit"])
    ):
        qubits, terms, groups, proxy = measurement_bases(
            molecule, basis,
            int(row["Active_Electrons"]), int(row["Active_Orbitals"]),
            row["Active_Space"] == "full",
        )
        assert qubits == int(row["N_Qubit"]), (
            f"{molecule}/{basis}: built {qubits} qubits, matrix says "
            f"{row['N_Qubit']}"
        )
        # Left out of `measured` when the grouping was declined, so the
        # comparison below reports the row as uncomputed rather than
        # against a value this run never produced.
        if groups is not None:
            measured[(molecule, qubits)] = groups
        note = proxy
        if groups is None:
            note = (f"{terms:,} terms > MAX_GROUPING_TERMS "
                    f"({MAX_GROUPING_TERMS:,}): grouping skipped")
        print(f"{molecule + '/' + basis:22} {row['Active_Space']:12} "
              f"{qubits:>6} {terms:>7} {'-' if groups is None else groups:>6}"
              + (f"   ({note})" if note else ""))

    # Against what the matrix carries.  The committed column takes a
    # measured value where a real run supplies one, so a difference here
    # is not necessarily an error: qubit-wise grouping is greedy and
    # order-dependent, and reads high against a real submission.
    print(f"\n{'row class':22} {'committed':>10} {'source':>14} {'computed here':>14}")
    for row in matrix:
        if row["Mapper"] != "JW" or not row["Num_ExpVals_Per_Iter"].isdigit():
            continue
        key = (row["Molecule"], int(row["N_Qubit"]))
        if key not in measured:
            continue
        label = f"{row['Molecule']}/{row['Basis']}"
        print(f"{label:22} {row['Num_ExpVals_Per_Iter']:>10} "
              f"{row['Num_ExpVals_Source']:>14} {measured[key]:>14}")
        measured.pop(key)


if __name__ == "__main__":
    main()
