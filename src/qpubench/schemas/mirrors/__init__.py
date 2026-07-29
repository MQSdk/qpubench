"""Project mirrors — one module per external project.

Each module models the input and output formats of a single upstream project,
so a run performed with that project can be recorded, stored and compared
alongside runs from anything else. Files are named
``<org_or_maintainer>_<package>.py`` so the filename alone says who maintains
the upstream and what it is called — which matters when dozens of mirrors
model overlapping concepts in incompatible ways.

Mirrors never import each other's SDKs; they are Pydantic models only. See
docs/schemas.md for the full index.

Everything is re-exported from ``qpubench.schemas``; import from there.
"""
