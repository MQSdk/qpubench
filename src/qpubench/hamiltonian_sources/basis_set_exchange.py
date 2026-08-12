"""Basis Set Exchange (BSE) loader — basissetexchange.org.

Install: pip install 'qpubench[bse]'   (basis_set_exchange)

Real, verified: `basis_set_exchange` ships its data locally in the wheel
(confirmed in this repo's own sandbox — `get_metadata()`/`get_basis()`
both return immediately with no network access), so this loader is
offline-safe, unlike `hamlib.py`/`pennylane_qchem.py`.

`count_basis_functions()`'s spherical-harmonic function counts
(`2*l + 1` per shell) were cross-checked in this session against real
`pyscf.gto.M(...).nao` values for every (molecule, basis) pair in
`data/benchmarks/ibm_tn-vqe_qesem/stage1_screening_matrix.csv` (sto-3g/6-31g/cc-pvdz/cc-pvtz/def2-svp/
def2-tzvp on H2/Li2/H2O) — exact match in every case, e.g. O/cc-pVDZ:
3 s-type + 2 p-type + 1 d-type contracted shells -> 3*1 + 2*3 + 1*5 = 14,
matching PySCF's own `nao` for that atom exactly.

q-vSZP is NOT covered here — it has no PyPI package/Python API at all
(see `schemas/catalogs/basis_sets.QvSZPRunConfig` for the real, schema-only CLI
shape). Calling `get_basis_set_entry("qvszp")` here raises.
"""
from __future__ import annotations

from ..schemas.catalogs.basis_sets import BASIS_SET_CATALOG, BasisSetCatalogEntry, BasisSetSource


def _require_bse_backed(name: str) -> BasisSetCatalogEntry:
    key = name.lower()
    if key not in BASIS_SET_CATALOG:
        raise ValueError(
            f"{name!r} is not in BASIS_SET_CATALOG; known names: "
            f"{sorted(BASIS_SET_CATALOG)}"
        )
    entry = BASIS_SET_CATALOG[key]
    if entry.source is not BasisSetSource.BASIS_SET_EXCHANGE:
        raise ValueError(
            f"{name!r} is a {entry.source.value} basis, not Basis Set "
            f"Exchange — it has no Python API; see "
            f"schemas.basis_sets.QvSZPRunConfig instead."
        )
    return entry


def get_basis_set_entry(name: str) -> BasisSetCatalogEntry:
    """Look up `name` in `BASIS_SET_CATALOG`, confirming it's real via a
    live `basis_set_exchange.get_metadata()` call (raises if BSE doesn't
    actually carry this basis, even though it's in the static catalogue).
    """
    entry = _require_bse_backed(name)

    import basis_set_exchange as bse

    metadata = bse.get_metadata()
    if entry.name not in metadata:
        raise ValueError(
            f"{entry.name!r} is in BASIS_SET_CATALOG but not found in the "
            f"installed basis_set_exchange metadata — check spelling "
            f"against bse.get_metadata().keys()."
        )
    return entry


def list_available_elements(name: str) -> list[str]:
    """Real element symbols this basis covers, straight from BSE's own
    metadata (`bse.get_metadata()[name]['versions'][latest]['elements']`).
    """
    entry = _require_bse_backed(name)

    import basis_set_exchange as bse
    from basis_set_exchange import lut

    metadata = bse.get_metadata()[entry.name]
    latest_version = max(metadata["versions"], key=lambda v: [int(p) for p in v.split(".")])
    element_numbers = metadata["versions"][latest_version]["elements"]
    return [lut.element_sym_from_Z(z, normalize=True) for z in element_numbers]


def count_basis_functions(name: str, element: str) -> int:
    """Real spatial AO function count for one element in `name`, computed
    from BSE's own shell data (spherical-harmonic convention — matches
    PySCF's default and this session's cross-check against
    `pyscf.gto.M(...).nao`, see module docstring).

    BSE's shell dict has two real shapes (confirmed against its own data
    in this session, not guessed): a "general contraction" shell
    (`angular_momentum` is a single `[l]`, `coefficients` holds one column
    per contracted function of that same `l` — e.g. cc-pVDZ's 3 s-type
    contractions on O) and a combined "SP/SPD" shell (`angular_momentum`
    is `[0, 1, ...]`, exactly one column per `l`, one-to-one — e.g.
    6-31G's combined SP shells on Li). Mixing these up (naively multiplying
    `len(coefficients)` by every `l` in the shell) overcounts SP/SPD
    shells; handled correctly here by branching on `len(angular_momentum)`.
    """
    entry = _require_bse_backed(name)

    import basis_set_exchange as bse

    basis = bse.get_basis(entry.name, elements=[element], fmt=None)
    from basis_set_exchange import lut

    z = lut.element_Z_from_sym(element)
    shells = basis["elements"][str(z)]["electron_shells"]

    total = 0
    for shell in shells:
        ams = shell["angular_momentum"]
        n_cols = len(shell["coefficients"])
        if len(ams) == 1:
            total += n_cols * (2 * ams[0] + 1)   # general contraction: n_cols functions, all this l
        else:
            total += sum(2 * am + 1 for am in ams)   # SP/SPD shell: one function per l
    return total


__all__ = [
    "count_basis_functions",
    "get_basis_set_entry",
    "list_available_elements",
]
