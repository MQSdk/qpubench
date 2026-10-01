"""Pin the exact circuit each benchmark row runs, as committed QASM.

Requires: pip install 'qpubench[qiskit]'

Every named family is pinned, VQE's as well as TN-VQE's. A name is not a
circuit: "EfficientSU2" is resolved by whichever library version is
installed, and two rows that name it are only comparable if they resolve
it the same way. Pinning each family to a file makes the circuit part of
the committed record, so a VQE row and a TN-VQE row that share an ansatz
demonstrably share a circuit, and anyone reproducing either -- or
comparing against a method this campaign does not run -- starts from the
same file rather than from a name.

Why pin it at all
-----------------
Until cebule-tn_vqe commit a760489, four of the five paths to an
expectation value disagreed with Qiskit's `q[i] = Hamiltonian index i`
convention, and with each other: on `default.qubit` at identical
parameters the two quantum modes gave 0.14497300 where the classical mode
gave 0.42729423 — the latter matching a hand-built expectation value. All
five now agree, pinned upstream by `test_qasm_uses_qiskit_qubit_ordering`
against a hand-built value rather than against another code path.

That is what makes a single pinned QASM string give the *same* energy on
both platforms and both measurement methods, which is the precondition
for the cross-backend comparison this benchmark is built to make. Before
that commit it did not hold, so pinning would have pinned an ambiguity.

Why files rather than a CSV column
----------------------------------
A multi-line QASM program does not belong in a CSV cell. The matrix
records the path and a SHA-256 prefix instead, so a silently edited
circuit is detectable — the hash in the CSV stops matching the file.
A campaign's matrix builder fills both cells for any row whose circuit
file exists here, and leaves them blank otherwise, so running this script
is optional and the matrix is generatable without Qiskit.

One interaction worth knowing: supplying `qasm_ansatz` to TN_QC_OPT
changes `n_layers_circuit`'s effective default from 3 to 1 (the circuit
is fully specified by the QASM, so the task stops building reps of its
own). Pass it explicitly whenever you pin a circuit.

Each campaign pins into its own `qasm/` folder (its campaign.py's
QASM_DIR), and the stale-file sweep below stays inside that folder, so
one campaign's pinning never deletes another's circuits.

Run:
    PYTHONPATH=src python utils/pin_qasm_ansatz.py [--campaign NAME]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _campaign
from _ansatz_builders import SUPPLIED_ANSATZE, build_ansatz, can_build, qasm_stem

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def circuit_shapes(
    rows: list[dict[str, str]],
) -> set[tuple[str, int, int, str, int, int, str]]:
    """The distinct (ansatz, qubits, reps, mapper, electrons, orbitals,
    entanglement) run.

    Every row, not only the TN-VQE ones. A comparison between VQE and
    TN-VQE is only a comparison if both sides' circuits are fixed, and a
    named ansatz is not a fixed circuit: it is a name that two libraries,
    or two versions of one library, may resolve differently. So each
    named family is pinned to a file, and each row points at the file it
    runs.

    `network` rows are included too. They freeze phi rather than running
    no circuit -- `optimize_network` opens with `circuit_to_mps(circuit,
    phi)` -- so the circuit they freeze is part of what defines them.

    Mapper, electrons and orbitals are zeroed off the mapper-independent
    families, matching `qasm_stem`: they are fixed by (qubits, reps,
    entanglement) alone, so carrying the rest would make one circuit look
    like several and write the same file once per molecule that reaches
    that width. `Entanglement` stays "" (never None) where the column is
    blank, so shapes differing only there stay comparable for `sorted()`
    below; qasm_path/write_pinned_qasm treat "" as "each family's own
    default" the same way None does in qasm_stem/build_ansatz.
    """
    shapes = set()
    for row in rows:
        if not (row["Ansatz"] and row["N_Qubit"]):
            continue
        supplied = row["Ansatz"] in SUPPLIED_ANSATZE
        entanglement = row.get("Entanglement") or ""
        shapes.add((
            row["Ansatz"], int(row["N_Qubit"]), int(row["Ansatz_Reps"]),
            row["Mapper"] if supplied else "JW",
            int(row["Active_Electrons"]) if supplied else 0,
            int(row["Active_Orbitals"]) if supplied else 0,
            entanglement,
        ))
    return shapes


def qasm_path(
    qasm_dir: pathlib.Path, ansatz: str, num_qubits: int, reps: int,
    mapper: str = "JW", num_electrons: int = 0, num_orbitals: int = 0,
    entanglement: str = "",
) -> pathlib.Path:
    """Where one circuit's pinned QASM lives.  See `qasm_stem`."""
    stem = qasm_stem(
        ansatz, num_qubits, reps, mapper=mapper,
        num_electrons=num_electrons, num_orbitals=num_orbitals,
        entanglement=entanglement or None,
    )
    return qasm_dir / f"{stem}.qasm"


def write_pinned_qasm(
    qasm_dir: pathlib.Path, ansatz: str, num_qubits: int, reps: int,
    mapper: str = "JW", num_electrons: int = 0, num_orbitals: int = 0,
    entanglement: str = "",
) -> tuple[pathlib.Path, str]:
    """Write one circuit as OpenQASM 3.0, parameters left free; return
    (path, sha256 prefix).

    The circuit is dumped *unbound*. OpenQASM 3's `input` declarations
    carry the free parameters through the file, so what is pinned is the
    structure, the qubit ordering and the parameterisation together, and
    the consumer derives its parameter shape from the loaded circuit's
    `num_parameters`.

    Binding them away is not a neutral simplification: TN-VQE takes its
    phi count from the QASM, so a circuit dumped at zero loads as
    `num_parameters == 0` and the row silently optimises theta alone
    against a frozen |0...0>, with no exception raised. That is what
    `test_pinned_qasm_carries_the_parameters_the_matrix_claims` guards.
    """
    from qiskit import qasm3

    circuit = build_ansatz(
        ansatz, num_qubits, reps=reps, num_electrons=num_electrons,
        parameterize=True, entanglement=entanglement or None,
    )

    path = qasm_path(
        qasm_dir, ansatz, num_qubits, reps, mapper, num_electrons, num_orbitals,
        entanglement,
    )
    # UTF-8 explicitly, not the locale default: an unbound dump names its
    # parameters `input float[64] _{θ}_0_;`, so these files are not pure
    # ASCII and must not depend on the writer's locale.
    path.write_text(qasm3.dumps(circuit) + "\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    _campaign.add_argument(parser)
    campaign = _campaign.load(parser.parse_args().campaign)
    qasm_dir = campaign.QASM_DIR

    qasm_dir.mkdir(parents=True, exist_ok=True)
    sources = [p for p in (campaign.CSV,) if p.exists()]
    rows: list[dict[str, str]] = []
    for path in sources:
        with path.open() as f:
            rows.extend(csv.DictReader(f))

    shapes = sorted(circuit_shapes(rows))
    if not shapes:
        raise SystemExit(f"no rows with a circuit found in {campaign.CSV.name}")

    names = ", ".join(p.name for p in sources)
    print(f"Pinning {len(shapes)} distinct circuits from {names}:")
    # Every file some row points at, whether this script wrote it or not.
    # The stale sweep below deletes against THIS set rather than against
    # what was written, because a circuit this repository cannot build --
    # a mol_map UCCSD, supplied from outside -- is still a circuit the
    # campaign runs, and deleting it would be the worst kind of tidying.
    expected: set[pathlib.Path] = set()
    supplied: list[pathlib.Path] = []
    for ansatz, num_qubits, reps, mapper, num_electrons, num_orbitals, entanglement in shapes:
        path = qasm_path(
            qasm_dir, ansatz, num_qubits, reps, mapper, num_electrons, num_orbitals,
            entanglement,
        )
        expected.add(path)
        if not can_build(ansatz, mapper):
            supplied.append(path)
            continue
        _, digest = write_pinned_qasm(
            qasm_dir, ansatz, num_qubits, reps, mapper, num_electrons, num_orbitals,
            entanglement,
        )
        print(f"  {path.relative_to(_REPO_ROOT)}  sha256:{digest}")

    for path in sorted(supplied):
        state = "present" if path.exists() else "MISSING"
        print(f"  {path.relative_to(_REPO_ROOT)}  supplied externally, {state}")

    # The pinned set is exactly what the matrix runs. A circuit left
    # behind by an earlier matrix is not a spare -- it is a file no row
    # points at, which invites being read as one the campaign runs.
    for stale in sorted(set(qasm_dir.glob("*.qasm")) - expected):
        stale.unlink()
        print(f"  removed {stale.relative_to(_REPO_ROOT)} (no row runs it)")

    print(
        "\nRe-run the campaign's matrix builder to fill Qasm_Ansatz_File / "
        "Qasm_Ansatz_SHA256 from these."
    )


if __name__ == "__main__":
    main()
