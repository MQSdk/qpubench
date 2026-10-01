"""Helpers for writing a campaign matrix: row numbering, CSV output, and
looking up pinned circuits.

Imported, not run. Standard library only, so a campaign's matrix builder
needs no quantum SDK to run.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]


def assign_case_ids(rows: list[dict[str, str]]) -> None:
    """Number rows 1..N by position, in place.

    Call before dropping any row, or every row after the drop gets a
    different number than the one already-collected results were filed
    under.
    """
    for i, row in enumerate(rows, start=1):
        row["Case_ID"] = str(i)


def dedupe_rows(
    rows: list[dict[str, str]], ignore: tuple[str, ...] = ("Case_ID", "Notes"),
) -> list[dict[str, str]]:
    """Keep the first occurrence of each distinct row, comparing every field
    but `ignore`.

    Call after `assign_case_ids`, so a dropped duplicate leaves a gap
    rather than shifting any other row's Case_ID.
    """
    seen: set[tuple[str, ...]] = set()
    kept = []
    for row in rows:
        key = tuple(v for k, v in row.items() if k not in ignore)
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def write_csv(
    path: pathlib.Path, rows: list[dict[str, str]], fieldnames: list[str],
    renumber: bool = True,
) -> None:
    if renumber:
        assign_case_ids(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def qiskit_version() -> str:
    """Installed Qiskit version, or "" if it isn't installed.

    Worth recording per row: transpile's default optimization level, which
    tn-vqe relies on, differs between Qiskit 1.x and 2.x.
    """
    try:
        return importlib.metadata.version("qiskit")
    except importlib.metadata.PackageNotFoundError:
        return ""


def pinned_parameter_count(path: pathlib.Path) -> int | None:
    """Free parameters a pinned OpenQASM 3 circuit declares, or None if the
    file does not exist.

    Counted off the `input` declarations rather than by loading the
    circuit, so no Qiskit is needed: an unbound dump declares exactly one
    `input` per free parameter.
    """
    if not path.exists():
        return None
    return sum(
        1 for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("input ")
    )


def pinned_circuit(qasm_dir: pathlib.Path, stem: str) -> tuple[str, str]:
    """(repo-relative path, sha256 prefix) of a pinned circuit, or ("", "")
    if it has not been pinned yet."""
    path = qasm_dir / f"{stem}.qasm"
    if not path.exists():
        return "", ""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return str(path.relative_to(REPO)), digest
