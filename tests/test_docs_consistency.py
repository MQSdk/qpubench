"""Guards against numeric drift between code and documentation.

The schema version and module count are stated canonically in the README;
these tests derive the true values from the code and fail if the README
disagrees.  docs/schemas.md must NOT re-pin those numbers — it points at the
README instead — so a version bump touches one document, not many.
"""
import pathlib
import re

import pytest

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

CAMPAIGN_DIR = REPO / "data" / "benchmarks" / "ibm_tn-vqe_qesem"
CSV_PATH = CAMPAIGN_DIR / "stage1_screening_matrix.csv"


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
    """Every backticked token in the first cell of the campaign README's
    column table.

    The table lives with the campaign rather than in `data/README.md`,
    which is only an index across scenarios: a column list belongs to the
    scenario that has those columns.

    Rows may group several columns in one cell
    (`Mapper`, `Method`, `Ansatz`), so this collects them all.
    """
    doc = (CAMPAIGN_DIR / "README.md").read_text(encoding="utf-8")
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
        f"{CSV_PATH.relative_to(REPO)} is stale — regenerate it with "
        "`PYTHONPATH=src python examples/guides/build_benchmark_matrix.py`"
    )


def test_every_column_is_documented_and_every_documented_column_exists():
    module = _benchmark_matrix_module()
    documented = _documented_columns()
    actual = set(module.FIELDNAMES)
    assert not actual - documented, (
        f"columns missing from the campaign README's table: "
        f"{sorted(actual - documented)}"
    )
    assert not documented - actual, (
        f"the campaign README documents columns the CSV does not have: "
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


def test_classical_only_rows_cost_nothing_and_take_no_measurements():
    """optimization_mode="network" takes no quantum measurements at all.

    That -- not "runs no circuit" -- is what defines the control. The
    circuit exists at the frozen phi_init the other arms start from and
    IS the reference state theta is optimised against, so this asserts
    zero cost and zero measurements rather than the particular cells an
    earlier revision used to blank out.
    """
    module = _benchmark_matrix_module()
    controls = [r for r in _csv_rows() if r["Optimization_Mode"] == "network"]
    assert controls, "the zero-QPU classical-only control rows are missing"
    for row in controls:
        # Shots do not APPLY here; 0 was a real shot count, and would be
        # wrong the moment such a row were re-run in "both" mode.
        assert row["Shots"].startswith("n/a"), row["Shots"]
        assert row["Measurement_Method"].startswith("n/a"), row["Measurement_Method"]
        # The circuit it freezes is recorded honestly, so a control on one
        # family is distinguishable from a control on another.
        assert row["Ansatz"] in module.ANSATZE, row["Ansatz"]
        assert int(row["Ansatz_Reps"]) > 0
        assert int(row["Num_Opt_Params_Phi"]) > 0


def test_phi_init_is_fixed_by_the_circuit_family():
    """One circuit family, one initialisation -- whatever else differs.

    phi is the CIRCUIT's parameter vector, so every row has one: a plain
    VQE row has circuit parameters exactly as a TN-VQE row does, and a
    `network` row has them frozen rather than absent. If two rows sharing
    an ansatz started from different phi, a difference between their
    results would be attributable to the starting point rather than to
    the method, which is the comparison this campaign exists to make.

    So the column is keyed on `Ansatz` alone: neither `Method` nor
    `Optimization_Mode` may move it, and no row may leave it unpinned --
    an unseeded upstream default is the defect being fixed.
    """
    by_ansatz: dict[str, set[str]] = {}
    for row in _csv_rows():
        assert not row["Phi_Init"].startswith("n/a"), (
            f"Case_ID {row['Case_ID']} ({row['Ansatz']}) leaves phi "
            f"unpinned: {row['Phi_Init']!r}"
        )
        by_ansatz.setdefault(row["Ansatz"], set()).add(row["Phi_Init"])

    assert by_ansatz, "no rows to check"
    for ansatz, values in by_ansatz.items():
        assert len(values) == 1, (
            f"{ansatz} rows start from {len(values)} different phi: "
            f"{sorted(values)}"
        )
    # Zeros where zero amplitudes ARE the reference state (UCCSD), the
    # seeded draw on the hardware-efficient families, whose identity at
    # zero is a barren starting point rather than a reference determinant.
    module = _benchmark_matrix_module()
    for ansatz, values in by_ansatz.items():
        expected_zeros = ansatz in module.PHI_INIT_ZEROS_ANSATZE
        value = next(iter(values))
        assert (value == "zeros") is expected_zeros, f"{ansatz}: {value}"
        if not expected_zeros:
            assert value.startswith("random(seed="), f"{ansatz}: {value}"


def test_every_ansatz_is_run_by_all_three_methods():
    """The comparison is only a comparison at a fixed circuit.

    An earlier revision screened plain VQE on one set of families and
    TN-VQE on another, so the two methods shared no circuit and every
    difference between them carried the circuit as well as the method.
    Each family must therefore appear under plain VQE, under TN-VQE's
    `both` mode and under the classical-only `network` control -- on the
    same Hamiltonian, and pinning the same QASM file.
    """
    module = _benchmark_matrix_module()
    rows = _csv_rows()

    def arm(row: dict[str, str]) -> str:
        if row["Method"] == "VQE":
            return "VQE"
        return f"TN-VQE/{row['Optimization_Mode']}"

    arms_by_ansatz: dict[str, set[str]] = {}
    for row in rows:
        arms_by_ansatz.setdefault(row["Ansatz"], set()).add(arm(row))
    assert set(arms_by_ansatz) == set(module.ANSATZE), (
        f"stage 1 runs {sorted(arms_by_ansatz)}, the generator lists "
        f"{module.ANSATZE}"
    )
    for ansatz, arms in arms_by_ansatz.items():
        assert arms == {"VQE", "TN-VQE/both", "TN-VQE/network"}, (
            f"{ansatz} is run by {sorted(arms)} only"
        )

    # Same circuit, not merely the same family name: a triple that shares
    # (molecule, basis, mapper, ansatz) must share the pinned file and the
    # phi it starts from, or the three arms differ in more than method.
    by_case: dict[tuple[str, ...], set[tuple[str, str, str]]] = {}
    for row in rows:
        key = (row["Molecule"], row["Basis"], row["Mapper"], row["Ansatz"])
        by_case.setdefault(key, set()).add(
            (row["Qasm_Ansatz_SHA256"], row["Phi_Init"], row["Ansatz_Reps"])
        )
    for key, pins in by_case.items():
        assert len(pins) == 1, f"{key} runs {len(pins)} different circuits: {pins}"


def test_no_column_describes_the_circuit_per_method():
    """The circuit's repetition count is a property of the circuit.

    `TN_Layers_Circuit` used to carry it, and only on TN-VQE rows, so a
    plain-VQE row and the TN-VQE row running the identical pinned file
    disagreed about how many repetitions that file has -- the column read
    as though the two methods ran different circuits. `Ansatz_Reps` is
    the one place it lives now, set on every row alike, and the pinned
    QASM is what fixes it.
    """
    module = _benchmark_matrix_module()
    assert "TN_Layers_Circuit" not in module.FIELDNAMES
    for row in _csv_rows():
        assert row["Ansatz_Reps"].isdigit(), row["Ansatz_Reps"]


def test_phi_init_seed_matches_the_generator():
    """The cost estimate transpiles the state the row starts from.

    `_ansatz_builders.circuit_spec` binds phi to the campaign's own draw
    so that the estimate describes the circuit the row runs; it mirrors
    the seed rather than importing the generator, so the two must be
    checked against each other.
    """
    import importlib.util

    module = _benchmark_matrix_module()
    path = REPO / "examples" / "guides" / "_ansatz_builders.py"
    spec = importlib.util.spec_from_file_location("_ansatz_builders", path)
    builders = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builders)
    assert builders.PHI_INIT_SEED == module.PHI_INIT_SEED
    assert module.PHI_INIT_RANDOM == f"random(seed={builders.PHI_INIT_SEED})"


def test_iterations_matches_the_generators_proportional_rule():
    """`Iterations` is the rule's output, not a number typed beside it.

    The floor test below is the safety net; this one pins the column to
    `optimizer_iterations` exactly, so a change to either multiplier has
    to be regenerated into the CSV rather than drifting away from it.
    """
    module = _benchmark_matrix_module()
    checked = 0
    for row in _csv_rows():
        if row["Iterations"] == "1":        # stage-3 refinement: one job, no optimizer
            continue
        free_params = sum(
            int(row[column])
            for column in ("Num_Opt_Params_Phi", "Num_Opt_Params_Theta")
            if row[column].isdigit()
        )
        if row["Optimization_Mode"] == "network":       # phi is frozen
            free_params -= int(row["Num_Opt_Params_Phi"])
        expected = module.optimizer_iterations(
            free_params, module.stage_evals_per_param(row["Stage"])
        )
        assert int(row["Iterations"]) == expected, (
            f"Case_ID {row['Case_ID']} budgets {row['Iterations']} evaluations "
            f"for {free_params} free parameters; the {row['Stage']} rule gives "
            f"{expected}"
        )
        checked += 1
    assert checked, "no rows carry an optimizer budget"


def test_every_row_budgets_at_least_cobylas_simplex():
    """A flat iteration count is not a conservative assumption.

    COBYLA cannot take a single descent step before it has built an
    initial simplex of n+1 points, and scipy raises a maxiter set below
    that rather than honouring it. So a row budgeted under n+2 does not
    run cheaply -- it runs long and optimises nothing, and the estimate
    that billed it is wrong in both directions at once.
    """
    for row in _csv_rows():
        params = sum(
            int(row[column])
            for column in ("Num_Opt_Params_Phi", "Num_Opt_Params_Theta")
            if row[column].isdigit()
        )
        if row["Optimization_Mode"] == "network":       # phi is frozen
            params -= int(row["Num_Opt_Params_Phi"])
        assert int(row["Iterations"]) >= params + 2, (
            f"Case_ID {row['Case_ID']} budgets {row['Iterations']} iterations "
            f"for {params} free parameters; COBYLA needs at least {params + 2}"
        )


def test_error_mitigation_is_additive():
    """The QESEM arm must not change the meaning of a committed row.

    `none` is a real value, not a placeholder: every row in the matrix
    today is genuinely unmitigated, and stage 3's paired rows are what
    make `qesem` meaningful by putting both values on otherwise
    identical rows.
    """
    module = _benchmark_matrix_module()
    found = {row["Error_Mitigation"] for row in _csv_rows()}
    assert found == {module.MITIGATION_NONE}, (
        f"stage 1 should be entirely unmitigated; found {sorted(found)}"
    )


def test_every_row_pins_the_circuit_it_runs():
    """A named ansatz is not a circuit; a pinned QASM file is.

    "EfficientSU2" is whatever the installed library resolves it to, so a
    VQE row and a TN-VQE row are comparable -- to each other, and to
    anyone reproducing this with another method -- only once each names
    the file it runs rather than the family it belongs to. Pinning the TN
    rows alone left the other side of the comparison unfixed.
    """
    for row in _csv_rows():
        assert row["Qasm_Ansatz_File"], (
            f"Case_ID {row['Case_ID']} ({row['Ansatz']}, {row['N_Qubit']}q) "
            "pins no circuit -- run pin_qasm_ansatz.py, then regenerate "
            "the matrix"
        )


def test_pinned_qasm_carries_the_parameters_the_matrix_claims():
    """The hash test is a tamper check; this one is a usability check.

    TN-VQE derives phi_shape from the QASM's own num_parameters, so a
    circuit dumped with its parameters bound loads as num_parameters == 0
    and silently optimises theta alone against a frozen |0...0>. No
    exception is raised -- the failure mode is a believable energy on
    purchased QPU time, which is why this is asserted rather than
    assumed.
    """
    qasm3 = pytest.importorskip("qiskit.qasm3")

    checked = 0
    for row in _csv_rows():
        if not row["Qasm_Ansatz_File"]:
            continue
        path = REPO / row["Qasm_Ansatz_File"]
        circuit = qasm3.loads(path.read_text(encoding="utf-8"))
        assert circuit.num_parameters == int(row["Num_Opt_Params_Phi"]), (
            f"{row['Qasm_Ansatz_File']} loads with "
            f"{circuit.num_parameters} free parameters, but Case_ID "
            f"{row['Case_ID']} claims {row['Num_Opt_Params_Phi']} -- re-pin "
            "the circuits with pin_qasm_ansatz.py"
        )
        checked += 1
    assert checked, "no rows pin a QASM circuit — run pin_qasm_ansatz.py"


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


# ---------------------------------------------------------------------------
# Row counts stated in prose.
#
# M4: the matrix had been 336 rows for five commits while four documents
# still said 294 — in files the previous gate did not read. Fixing those
# four fixes the instance; this closes the class, and it earns its keep
# immediately, because the QESEM arm changes the count again.
#
# Keyed off the live CSVs and the live generator rather than off literals,
# so it survives the next row-count change instead of becoming the fifth
# stale number.
# ---------------------------------------------------------------------------

# The lookbehind rejects a digit that is part of a preceding word or
# hyphenated term, so "batch2 rows" and "stage-2 rows" are not read as
# claims of 2. "294-row matrix" still is one: only what comes BEFORE the
# number is guarded.
_ROW_CLAIM = re.compile(r"(?<![\w-])([0-9][0-9,]*)[ -]rows?\b")
# Prose like "one row per molecule" or "1 row" is generic, not a count.
_GENERIC_COUNTS = {0, 1}


def _true_row_counts() -> set[int]:
    """Every row count the campaign's own files and generator produce."""
    module = _benchmark_matrix_module()
    rows = _csv_rows()
    counts = {
        len(rows),
        sum(1 for r in rows if r["Optimization_Mode"] != "network"),
    }
    for path in sorted(CAMPAIGN_DIR.glob("batch*.csv")):
        import csv

        with path.open(encoding="utf-8") as f:
            counts.add(len(list(csv.DictReader(f))))

    # Stage 2 is not committed, so its size only exists as a projection in
    # prose -- which is exactly the kind of number that goes stale.
    selection = {molecule.name: "sto-3g" for molecule in module.MOLECULES}
    for sweep in (False, True):
        counts.add(len(module.build_stage2(
            selection, "EfficientSU2", "valence_cas", sweep,
        )))
    return counts


def test_row_counts_stated_in_prose_are_counts_that_really_exist():
    searched = [
        *(REPO / "docs").rglob("*.md"),
        *(REPO / "examples").rglob("*.py"),
        *(REPO / "data").rglob("*.md"),
        *(REPO / "integrations").rglob("*.md"),
        *(REPO / "integrations").rglob("*.py"),
    ]
    truths = _true_row_counts()
    stale: list[str] = []
    for path in searched:
        if "site/assets" in path.as_posix():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in _ROW_CLAIM.finditer(line):
                claimed = int(match.group(1).replace(",", ""))
                if claimed in truths or claimed in _GENERIC_COUNTS:
                    continue
                stale.append(
                    f"{path.relative_to(REPO)}:{line_no}: "
                    f"'{match.group(0)}' is not a row count this repo produces"
                )
    assert not stale, (
        "Row counts in prose have drifted from the data:\n  "
        + "\n  ".join(stale)
        + f"\nReal counts: {sorted(truths)}"
    )
