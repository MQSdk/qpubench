"""Guards against numeric drift between code and documentation.

The schema version and module count are stated canonically in the README;
these tests derive the true values from the code and fail if the README
disagrees.  docs/schemas.md must NOT re-pin those numbers — it points at the
README instead — so a version bump touches one document, not many.
"""
import pathlib
import re

from qpubench.schemas.record import SCHEMA_VERSION

REPO = pathlib.Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO / "src" / "qpubench" / "schemas"


def _module_count() -> int:
    """Count schema modules across all three groups.

    rglob, not glob: the catalogues and project mirrors live in
    schemas/catalogs/ and schemas/mirrors/ sub-packages.
    """
    return len([p for p in SCHEMAS_DIR.rglob("*.py") if p.name != "__init__.py"])


def test_readme_schema_badge_matches_code():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    badge_versions = set(re.findall(r"schema-v(\d+\.\d+\.\d+)", readme))
    assert badge_versions == {SCHEMA_VERSION}, (
        f"README badge says {badge_versions}, code says {SCHEMA_VERSION}"
    )
    inline_versions = set(re.findall(r"[Ss]chema v(\d+\.\d+\.\d+)", readme))
    assert inline_versions <= {SCHEMA_VERSION}, (
        f"README mentions schema version(s) {inline_versions - {SCHEMA_VERSION}}, "
        f"code says {SCHEMA_VERSION}"
    )


def test_readme_module_count_matches_code():
    """The README is the canonical home for the module count."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    counts = {int(n) for n in re.findall(r"(\d+) schema modules", readme)}
    assert counts == {_module_count()}, (
        f"README states {counts} schema modules, actual is {_module_count()}"
    )


def test_schemas_doc_does_not_repin_version_or_count():
    """Version and module count live in the README, not in schemas.md."""
    doc = (REPO / "docs" / "schemas.md").read_text(encoding="utf-8")
    assert not re.search(
        r"Schema version \*\*\d+\.\d+\.\d+\*\* — \d+ modules", doc
    ), (
        "docs/schemas.md must not re-pin the schema version / module count; "
        "state them in the README instead"
    )


def test_schema_version_mentions_in_code_are_consistent():
    """Docstrings that pin a schema version ('as of schema vX.Y.Z') must not
    claim a version newer than SCHEMA_VERSION."""
    for path in SCHEMAS_DIR.glob("*.py"):
        for m in re.finditer(r"schema v(\d+\.\d+\.\d+)", path.read_text(encoding="utf-8")):
            claimed = tuple(int(x) for x in m.group(1).split("."))
            actual = tuple(int(x) for x in SCHEMA_VERSION.split("."))
            assert claimed <= actual, (
                f"{path.name} mentions schema v{m.group(1)} but "
                f"SCHEMA_VERSION is {SCHEMA_VERSION}"
            )


# ---------------------------------------------------------------------------
# Benchmark matrix vs. its own documentation and the mirrored vocabularies.
#
# Three of the four sections of the 2026-08-07 TN-VQE review were "the CSV
# and the docs disagree with the code". These catch that class of drift at
# the commit that introduces it: the `qasm_gen_grouped` misnomer and the
# `full`/`phase` rotation names would both have failed here.
# ---------------------------------------------------------------------------

CSV_PATH = REPO / "data" / "IBM_VQE_Test_Benchmark.csv"


def _benchmark_matrix_module():
    """Import the generator, which lives in examples/ rather than the package."""
    import importlib.util

    path = REPO / "examples" / "guides" / "build_benchmark_matrix.py"
    spec = importlib.util.spec_from_file_location("build_benchmark_matrix", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _csv_rows():
    import csv

    with CSV_PATH.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _documented_columns() -> set[str]:
    """Every backticked token in the first cell of data/README.md's column table.

    Rows may group several columns in one cell
    (`Mapper`, `Method`, `Ansatz`), so this collects them all.
    """
    doc = (REPO / "data" / "README.md").read_text(encoding="utf-8")
    table = doc.split("## Columns", 1)[1].split("\n### ", 1)[0]
    columns: set[str] = set()
    for line in table.splitlines():
        if not line.startswith("| `"):
            continue
        columns.update(re.findall(r"`([A-Z][A-Za-z0-9_]*)`", line.split("|")[1]))
    return columns


def test_csv_header_matches_generator_fieldnames():
    """The committed CSV must be what the generator currently produces."""
    module = _benchmark_matrix_module()
    with CSV_PATH.open(encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    assert header == module.FIELDNAMES, (
        "data/IBM_VQE_Test_Benchmark.csv is stale — regenerate it with "
        "`PYTHONPATH=src python examples/guides/build_benchmark_matrix.py`"
    )


def test_every_column_is_documented_and_every_documented_column_exists():
    module = _benchmark_matrix_module()
    documented = _documented_columns()
    actual = set(module.FIELDNAMES)
    assert not actual - documented, (
        f"columns missing from data/README.md's table: {sorted(actual - documented)}"
    )
    assert not documented - actual, (
        f"data/README.md documents columns the CSV does not have: "
        f"{sorted(documented - actual)}"
    )


def test_tn_ansatz_column_uses_the_mirrors_vocabulary():
    """Values must be real TNAnsatz members, not a parallel spelling.

    `full` / `phase` named only the two non-entangling families and were
    ambiguous once `givens` (also a rotation) and `number_preserving`
    (also "full") were modelled.
    """
    from qpubench.schemas.mirrors.mqsdk_cebule import TNAnsatz

    allowed = {a.value for a in TNAnsatz} | {"n/a (no TN layers)", "n/a (not TN-VQE)"}
    found = {row["TN_Ansatz"] for row in _csv_rows()}
    assert found <= allowed, f"unknown TN_Ansatz values: {sorted(found - allowed)}"


def test_measurement_method_column_uses_cebules_vocabulary():
    """`pauli` / `grouped`, exactly as TNQCOptInput.measurement_method defines them."""
    allowed = {"pauli", "grouped", "n/a (network mode)"}
    found = {row["Measurement_Method"] for row in _csv_rows()}
    assert found <= allowed, (
        f"unknown Measurement_Method values: {sorted(found - allowed)}"
    )


def test_classical_only_rows_cost_nothing_and_run_no_circuit():
    """optimization_mode="network" takes no quantum measurements at all."""
    controls = [r for r in _csv_rows() if r["Optimization_Mode"] == "network"]
    assert controls, "the zero-QPU classical-only control rows are missing"
    for row in controls:
        assert row["Shots"] == "0"
        assert row["Num_Opt_Params_Phi"] == "0"
        assert row["TN_Layers_Circuit"] == "0"
        assert not row["Qasm_Ansatz_File"]


def test_pinned_qasm_hashes_match_the_committed_circuits():
    """A silently edited circuit must stop matching the CSV."""
    import hashlib

    checked = 0
    for row in _csv_rows():
        if not row["Qasm_Ansatz_File"]:
            continue
        path = REPO / row["Qasm_Ansatz_File"]
        assert path.exists(), f"{row['Qasm_Ansatz_File']} is referenced but missing"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        assert digest == row["Qasm_Ansatz_SHA256"], (
            f"{row['Qasm_Ansatz_File']} has changed since the matrix was "
            f"generated (expected {row['Qasm_Ansatz_SHA256']}, got {digest})"
        )
        checked += 1
    assert checked, "no rows pin a QASM circuit — run pin_qasm_ansatz.py"
