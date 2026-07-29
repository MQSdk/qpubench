"""Gaussian basis-set catalogue — Basis Set Exchange + q-vSZP, both real.

Added 2026-07-09 to back the ``Basis`` column of ``data/
IBM_VQE_Test_Benchmark.csv`` with something more than a free-text string:
every basis name that appears there is now a real catalogue entry, and all
seven — including q-vSZP — are backed by real, independently-parseable
data. This module stays free of any ``basis_set_exchange``/``requests``
import (those lazy imports live in ``hamiltonian_sources/
basis_set_exchange.py`` and ``hamiltonian_sources/qvszp.py``), same as
``hamiltonian_library.py`` vs. ``hamiltonian_sources/hamlib.py``.

- **Basis Set Exchange** (basissetexchange.org, pip-installable as
  ``basis_set_exchange`` — confirmed on PyPI, bundles its data locally, no
  network needed at runtime) — covers the six standard bases above.
  Confirmed present via ``bse.get_metadata()`` in this repo's own sandbox.
- **q-vSZP** (github.com/grimme-lab/qvSZP, Grimme group, J. Chem. Phys.
  2023, 10.1063/5.0158703) — corrected 2026-07-09 after actually
  downloading and parsing the real basis-set data files in
  ``q-vSZP_basis/`` (an earlier version of this module wrongly claimed
  ORCA/the Fortran CLI was required just to know the basis composition —
  it isn't). What's real, checked directly against those files in this
  session:

  - ``q-vSZP_basis/basisq`` (full basis), ``basisq_lesspolfunc``
    (polarization functions dropped), and ``basisq_gxtb`` (a smaller
    variant matched to the g-xTB charge model) are **static, per-element
    shell tables covering Z=1-103** — the *number* of contracted
    functions per element (and therefore any qubit count derived from
    it) is fixed and independent of charge/molecule, not something that
    only becomes known after running the tool. E.g. H = 1s+1p (4
    functions), Li = O = 1s+1p+1d (9 functions each) in the FULL variant
    — confirmed by parsing the real file, and cross-checked against the
    independently-generated ``basis_qvSZP_CP2K_format`` file, which
    agrees exactly.
  - What *is* charge-dependent is only the **contraction coefficients**:
    each primitive row carries two coefficient columns (a base value plus
    a linear-in-charge slope), not two separate functions — confirmed by
    the CP2K conversion's own header comment: "The source basis carries
    charge/environment-dependent coefficient columns. CP2K BASIS_SET
    files are static, so this file uses the first contraction coefficient
    column." That first column is exactly the ``q=0`` (isolated-atom)
    reference contraction.
  - ``q-vSZP_basis/ecpq`` (effective core potentials) covers Z=3-103
    (everything except H/He) with ``ncore=2`` (1s core replaced) starting
    at Li — **not** "f-block only" as an earlier version of this
    docstring claimed.
  - None of the above needs ORCA or the Fortran CLI: it's plain-text data,
    parsed for real by ``hamiltonian_sources/qvszp.py`` (downloads +
    caches straight from the GitHub repo, same pattern as
    ``hamiltonian_sources/hamlib.py``).
  - What genuinely *does* still need the real CLI (or a from-scratch
    ``tblite`` GFN2-xTB charge calculation, itself pip-installable and
    independent of ORCA) is producing the true molecule-specific
    charge-adapted contraction coefficients for an actual ORCA
    calculation — that part is schema-only here (``QvSZPRunConfig``/
    ``QvSZPBasisResult``), same "container, not solver" boundary as
    ``pyscf.ProjectionEmbeddingConfig``/``DMETConfig`` (PsiEmbed/libDMET).

Schema version: 2.9.0
"""
from __future__ import annotations

import enum

import pydantic


class BasisSetFamily(str, enum.Enum):
    """Structural family — orthogonal to `BasisSetSource` (family is
    *what kind* of basis it is; source is *where its data comes from*)."""
    MINIMAL                    = "minimal"                      # STO-nG
    POPLE                      = "pople"                        # 6-31G, 6-311G, ...
    DUNNING_CORRELATION_CONSISTENT = "dunning_correlation_consistent"  # cc-pVXZ
    KARLSRUHE_DEF2              = "karlsruhe_def2"                # def2-SVP, def2-TZVP, ...
    ADAPTIVE_ATOM_IN_MOLECULE    = "adaptive_atom_in_molecule"     # q-vSZP


class BasisSetSource(str, enum.Enum):
    BASIS_SET_EXCHANGE = "basis_set_exchange"   # real, pip-installable, offline data
    GRIMME_QVSZP        = "grimme_qvszp"          # real static data files, downloaded + parsed (hamiltonian_sources/qvszp.py)


class BasisSetCatalogEntry(pydantic.BaseModel):
    """One basis set's identity + provenance.

    cardinality            zeta level (1=minimal/single-zeta,
                            2=double-zeta, 3=triple-zeta, ...), `None` if
                            not a fixed-cardinality basis (q-vSZP — its
                            shell composition is fixed per element, but
                            doesn't follow the usual zeta-level naming).
    polarization / diffuse   whether the *default* variant includes
                            polarization/diffuse functions (both bases
                            with and without them exist for some
                            families; this reflects the name given in
                            `BASIS_SET_CATALOG`, e.g. "cc-pVDZ" has
                            polarization by construction, "6-31G" does not).
    all_electron             `False` only for entries that use an
                            effective core potential for *some* elements
                            (q-vSZP: Z=3-103, i.e. everything except H/He
                            — confirmed against its real `ecpq` file).
    requires_external_tool    `True` only for the piece of this basis
                            that genuinely has no offline/Python path:
                            producing q-vSZP's true molecule-specific,
                            charge-adapted contraction *coefficients*
                            ready for an ORCA run. Element coverage and
                            basis-function *counts* do NOT require this —
                            see `hamiltonian_sources/qvszp.py`.
    citation                 DOI or reference string, where known.
    """
    name:                    str
    family:                    BasisSetFamily
    source:                      BasisSetSource
    cardinality:                   int | None    = None
    polarization:                    bool          = False
    diffuse:                          bool          = False
    all_electron:                      bool          = True
    requires_external_tool:              bool          = False
    citation:                              str | None    = None
    notes:                                    str           = ""


BASIS_SET_CATALOG: dict[str, BasisSetCatalogEntry] = {
    e.name: e
    for e in [
        BasisSetCatalogEntry(
            name="sto-3g", family=BasisSetFamily.MINIMAL, source=BasisSetSource.BASIS_SET_EXCHANGE,
            cardinality=1,
            citation="10.1063/1.1672392",
            notes="Minimal basis, 3 primitive Gaussians per Slater-type orbital.",
        ),
        BasisSetCatalogEntry(
            name="6-31g", family=BasisSetFamily.POPLE, source=BasisSetSource.BASIS_SET_EXCHANGE,
            cardinality=2,
            citation="10.1063/1.1677527",
            notes="Split-valence double-zeta, no polarization/diffuse functions.",
        ),
        BasisSetCatalogEntry(
            name="cc-pvdz", family=BasisSetFamily.DUNNING_CORRELATION_CONSISTENT,
            source=BasisSetSource.BASIS_SET_EXCHANGE,
            cardinality=2, polarization=True,
            citation="10.1063/1.456153",
            notes="Correlation-consistent polarized double-zeta.",
        ),
        BasisSetCatalogEntry(
            name="cc-pvtz", family=BasisSetFamily.DUNNING_CORRELATION_CONSISTENT,
            source=BasisSetSource.BASIS_SET_EXCHANGE,
            cardinality=3, polarization=True,
            citation="10.1063/1.456153",
            notes="Correlation-consistent polarized triple-zeta.",
        ),
        BasisSetCatalogEntry(
            name="def2-svp", family=BasisSetFamily.KARLSRUHE_DEF2, source=BasisSetSource.BASIS_SET_EXCHANGE,
            cardinality=2, polarization=True,
            citation="10.1039/B508541A",
            notes="Karlsruhe split-valence polarized double-zeta.",
        ),
        BasisSetCatalogEntry(
            name="def2-tzvp", family=BasisSetFamily.KARLSRUHE_DEF2, source=BasisSetSource.BASIS_SET_EXCHANGE,
            cardinality=3, polarization=True,
            citation="10.1039/B508541A",
            notes="Karlsruhe split-valence polarized triple-zeta.",
        ),
        BasisSetCatalogEntry(
            name="qvszp", family=BasisSetFamily.ADAPTIVE_ATOM_IN_MOLECULE,
            source=BasisSetSource.GRIMME_QVSZP,
            cardinality=None, polarization=True, all_electron=False,
            requires_external_tool=False,
            citation="10.1063/5.0158703",
            notes=(
                "Valence single-zeta + polarization, atom-in-molecule "
                "adaptive: contraction *coefficients* are charge-dependent, "
                "but the shell composition (and so the function/qubit "
                "count) is fixed per element and directly computable "
                "offline via hamiltonian_sources.qvszp.count_basis_functions "
                "— no ORCA or Fortran CLI needed for that. ECP (ncore=2) "
                "for Z=3-103; all-electron only for H/He. "
                "github.com/grimme-lab/qvSZP."
            ),
        ),
    ]
}


# ---------------------------------------------------------------------------
# q-vSZP — charge-adapted coefficients are schema-only (real CLI, no PyPI
# package/Python API for that specific step); element/shell/function data
# is real and covered by hamiltonian_sources/qvszp.py, not this class.
# ---------------------------------------------------------------------------

class QvSZPVariant(str, enum.Enum):
    """The three real basis-set variants q-vSZP ships in `q-vSZP_basis/`
    (confirmed by downloading and parsing each file in this session, not
    guessed from the README alone — an earlier version of this enum had a
    `NO_CORE_ECP` member that doesn't correspond to any real file)."""
    FULL              = "full"               # basisq — complete q-vSZP basis
    NO_POLARIZATION    = "no_polarization"     # basisq_lesspolfunc — polarization shell dropped
    GXTB                 = "gxtb"                # basisq_gxtb — smaller basis matched to the g-xTB charge model


class QvSZPRunConfig(pydantic.BaseModel):
    """Input to a real ``qvSZP`` CLI invocation
    (``qvSZP --struc <structure_file>``) — schema-only for this specific
    step: producing the true molecule-specific, charge-adapted contraction
    coefficients (and ORCA-ready ``.basisq``/``.ecpq`` files) requires
    either the real Fortran CLI (build from source via FPM; no PyPI
    package) or an equivalent GFN2-xTB charge calculation via ``tblite``
    (pip-installable, ORCA-independent) plus reimplementing the
    charge-interpolation formula by hand — nothing in this repo does
    either. If you only need basis-function counts or a static
    (isolated-atom-charge) basis usable outside ORCA, you don't need this
    at all — see ``hamiltonian_sources.qvszp``.

    structure_file    path to a ``.xyz``/``coord``/mctc-lib-format geometry,
                      matches the CLI's own ``--struc`` argument.
    charge / uhf        total molecular charge / number of unpaired
                      electrons, forwarded to the underlying GFN2-xTB
                      charge calculation (tblite).
    variant              which of the three real basis variants to build.
    orca_version          ORCA version the generated ``.basisq``/``.ecpq``
                      files target; qvSZP's own README requires >=5.0.4 —
                      only relevant if you intend to run ORCA itself, not
                      for the basis definition.
    """
    structure_file:   str
    charge:              int              = 0
    uhf:                   int              = 0
    variant:                 QvSZPVariant     = QvSZPVariant.FULL
    orca_version:              str              = "5.0.4"


class QvSZPBasisResult(pydantic.BaseModel):
    """Output of a real ``qvSZP`` run — schema-only (nothing in this repo
    produces this for real; fill it in from the CLI's own output once
    you've built/run it).

    basisq_file / ecpq_file    paths to the generated ORCA-format basis /
                                effective-core-potential files (``.basisq``/
                                ``.ecpq`` — `None` if the molecule's
                                elements needed no ECP, i.e. H/He only).
    num_basis_functions_by_element   spatial AO function count per element
                                symbol. Note this is a fixed, real,
                                per-element property of the chosen
                                `QvSZPVariant` — it does NOT vary with the
                                molecule's charges (only the coefficient
                                *values* do) and can be obtained without a
                                real run via
                                ``hamiltonian_sources.qvszp.count_basis_functions``;
                                it's populated here for convenience when
                                you already have a real run's output.
    """
    basisq_file:                     str
    ecpq_file:                          str | None    = None
    num_basis_functions_by_element:       dict[str, int] = {}


__all__ = [
    "BASIS_SET_CATALOG",
    "BasisSetCatalogEntry",
    "BasisSetFamily",
    "BasisSetSource",
    "QvSZPBasisResult",
    "QvSZPRunConfig",
    "QvSZPVariant",
]
