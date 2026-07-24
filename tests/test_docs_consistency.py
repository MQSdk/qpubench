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
    return len([p for p in SCHEMAS_DIR.glob("*.py") if p.name != "__init__.py"])


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
