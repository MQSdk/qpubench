"""How many circuits does ONE cost-function evaluation really submit?

Requires: pip install 'qpubench[qiskit]' pyscf

The per-row QPU estimate in `split_benchmark_batches.py` charges one
circuit submission per cost-function evaluation.  That is a floor, not a
prediction: evaluating <H> takes one circuit per measurement BASIS, and
how many bases that is follows from the Hamiltonian rather than from the
circuit preparing the state.  This script measures that factor for the
Jordan-Wigner rows of the stage-1 matrix, so the campaign's cost
accounting can be corrected by a number rather than by an assumption.

What is counted
---------------
Each row's own active space is built with PySCF, mapped to qubits with
Jordan-Wigner, and the resulting Pauli sum is grouped into QUBIT-WISE
COMMUTING sets.  Every such set is one measurement basis, hence one
circuit, hence one submission at the row's full shot count.

  terms       distinct Pauli strings in the mapped Hamiltonian; the
              identity is excluded, since it costs no measurement
  E           qubit-wise-commuting groups, i.e. circuits per evaluation

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
    PYTHONPATH=src python examples/guides/count_measurement_bases.py
"""
from __future__ import annotations

import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CSV_PATH = (
    _REPO_ROOT / "data" / "benchmarks" / "ibm_tn-vqe_qesem"
    / "stage1_screening_matrix.csv"
)

# Equilibrium geometries, in Angstrom.  The campaign pins no bond length
# (an open decision), and it does not need one here: the term count is a
# property of which integrals are non-zero, not of their values.
GEOMETRIES = {
    "H2": "H 0 0 0; H 0 0 0.735",
    "Li2": "Li 0 0 0; Li 0 0 2.673",
    "H2O": "O 0 0 0; H 0 0.757 0.587; H 0 -0.757 0.587",
}

# Campaign basis name -> PySCF's spelling.
PYSCF_BASIS = {
    "sto-3g": "sto3g", "6-31g": "631g", "cc-pvdz": "ccpvdz",
    "cc-pvtz": "ccpvtz", "def2-svp": "def2svp", "def2-tzvp": "def2tzvp",
}
# qvSZP has no PySCF entry, so its rows are measured on a SHAPE PROXY: a
# space with the same orbital count, which is what fixes the term count.
QVSZP_PROXY = ("ccpvdz", "shape proxy: same orbital count, different basis")


def measurement_bases(
    molecule: str, basis: str, active_electrons: int, active_orbitals: int,
    full_space: bool,
) -> tuple[int, int, int]:
    """(qubits, Pauli terms, qubit-wise-commuting groups) for one row."""
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
        measured[(molecule, qubits)] = groups
        print(f"{molecule + '/' + basis:22} {row['Active_Space']:12} "
              f"{qubits:>6} {terms:>7} {groups:>6}"
              + (f"   ({proxy})" if proxy else ""))

    # What that does to the committed cost estimate, which assumed E = 1.
    floor_s = evaluations = 0.0
    corrected_s = 0.0
    for path in sorted(_CSV_PATH.parent.glob("batch[1-9]*.csv")):
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cost = float(row["Est_QPU_Time_S"])
                floor_s += cost
                evaluations += int(row["Iterations"])
                if row["Mapper"] != "JW":
                    continue
                factor = measured[(row["Molecule"], int(row["N_Qubit"]))]
                corrected_s += cost * factor

    print(f"\nCommitted estimate, at one circuit per evaluation: "
          f"{floor_s / 60:,.0f} min over {evaluations:,.0f} evaluations")
    print(f"Jordan-Wigner rows re-costed at the E above:       "
          f"{corrected_s / 60:,.0f} min ({corrected_s / 3600:,.0f} hours)")
    print("mol_map rows are not re-costed: their measurement count cannot "
          "be computed offline.")


if __name__ == "__main__":
    main()
