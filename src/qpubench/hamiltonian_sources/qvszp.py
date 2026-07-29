"""q-vSZP basis-set loader — github.com/grimme-lab/qvSZP (Grimme group).

Install: pip install 'qpubench[qvszp]'   (requests)

Corrected 2026-07-09: an earlier version of `schemas.basis_sets` claimed
q-vSZP has no offline/Python-accessible representation at all and that
ORCA + the Fortran CLI were required just to know its composition — wrong.
Verified for real in this session by downloading and parsing the actual
`q-vSZP_basis/` files from the repository:

  - `basisq` / `basisq_lesspolfunc` / `basisq_gxtb` (the three real
    `QvSZPVariant`s) are **static, per-element shell tables covering
    Z=1-103** — plain text, no ORCA/Fortran needed to read them. Each
    primitive row has an exponent plus *two* coefficient columns: a base
    value and a linear-in-charge slope (confirmed against
    `basis_qvSZP_CP2K_format`'s own header comment: "The source basis
    carries charge/environment-dependent coefficient columns. CP2K
    BASIS_SET files are static, so this file uses the first contraction
    coefficient column.") — i.e. only the *coefficients* are
    charge-dependent, never the shell composition, so
    `count_basis_functions()` below is exact and molecule-independent.
  - `ecpq` (effective core potentials) covers Z=3-103 with `ncore=2`
    (removes the 1s core) — confirmed present for every element from Li
    up, not just f-block as an earlier docstring guessed. H/He (Z=1,2)
    have no ECP entry (all-electron).

Cross-checked against the independently-generated
`basis_qvSZP_CP2K_format` file: shell composition for H/Li/O matches the
`basisq` parse exactly (H: 1s+1p=4, Li=O: 1s+1p+1d=9), and the CP2K file
is directly usable in CP2K with no further conversion — so ORCA is not a
hard requirement for *using* q-vSZP, only for one specific workflow
(running an ORCA calculation with the true molecule-charge-adapted
coefficients, still schema-only — see `schemas.basis_sets.QvSZPRunConfig`).

Downloads are cached locally (default
`~/.cache/qpubench/hamiltonian_sources/qvszp/`), same pattern as
`hamlib.py`, and never re-fetched once present.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..schemas.catalogs.basis_sets import QvSZPVariant

_BASE_URL = "https://raw.githubusercontent.com/grimme-lab/qvSZP/main/q-vSZP_basis"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "qpubench" / "hamiltonian_sources" / "qvszp"

_VARIANT_FILENAMES: dict[QvSZPVariant, str] = {
    QvSZPVariant.FULL: "basisq",
    QvSZPVariant.NO_POLARIZATION: "basisq_lesspolfunc",
    QvSZPVariant.GXTB: "basisq_gxtb",
}
_ECPQ_FILENAME = "ecpq"
_CP2K_FILENAME = "basis_qvSZP_CP2K_format"

# Z=1..103 element symbols — the exact range q-vSZP's own basisq covers.
_ELEMENT_SYMBOLS = [
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
    "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
    "Md", "No", "Lr",
]
_Z_FROM_SYMBOL = {sym: z for z, sym in enumerate(_ELEMENT_SYMBOLS, start=1)}

_L_FROM_LETTER = {"s": 0, "p": 1, "d": 2, "f": 3, "g": 4}
_SHELL_HEADER_RE = re.compile(r"^\s*(\d+)\s+([spdfg])\s*$")


def element_z(symbol: str) -> int:
    """Atomic number for `symbol` — raises if outside q-vSZP's Z=1-103
    coverage (confirmed range of the real `basisq` file)."""
    try:
        return _Z_FROM_SYMBOL[symbol]
    except KeyError:
        raise ValueError(
            f"{symbol!r} is not a recognized element symbol in q-vSZP's "
            f"Z=1-103 coverage."
        ) from None


def _cache_dir(cache_dir: Path | str | None) -> Path:
    path = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download(filename: str, cache_dir: Path) -> str:
    local_path = cache_dir / filename
    if not local_path.exists():
        import requests

        response = requests.get(f"{_BASE_URL}/{filename}", timeout=60)
        response.raise_for_status()
        local_path.write_text(response.text)
    return local_path.read_text()


def parse_qvszp_shells(text: str) -> dict[int, list[str]]:
    """Parse a real q-vSZP `basisq`-format file into `{Z: [shell_letter, ...]}`.

    Real format (confirmed against `q-vSZP_basis/basisq` in this session):
    each element block is delimited by `*` lines; the first content line
    is `<Z> <float> <float> <float>` (atomic number + 3 global fit
    parameters, not basis data); each shell is introduced by a
    `<n_primitives> <letter>` header line followed by exactly
    `n_primitives` primitive rows (`exponent  base_coeff  charge_slope`).
    Each shell header contributes exactly ONE contracted function of that
    angular momentum — the two coefficient columns are a
    charge-independent base value and a linear-in-charge slope for the
    *same* function, not two separate functions (confirmed against
    `basis_qvSZP_CP2K_format`, which keeps only the first column and
    produces the identical shell composition).
    """
    elements: dict[int, list[str]] = {}
    current_z: int | None = None
    current_shells: list[str] = []
    lines = text.splitlines()

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "*":
            if current_z is not None:
                elements[current_z] = current_shells
            current_z, current_shells = None, []
            i += 1
            continue
        tokens = stripped.split()
        if current_z is None and len(tokens) == 4:
            try:
                z = int(tokens[0])
                float(tokens[1]), float(tokens[2]), float(tokens[3])
            except ValueError:
                i += 1
                continue
            current_z = z
            i += 1
            continue
        match = _SHELL_HEADER_RE.match(lines[i])
        if match:
            n_primitives = int(match.group(1))
            current_shells.append(match.group(2))
            i += 1 + n_primitives   # skip the primitive rows for this shell
            continue
        i += 1
    return elements


def parse_qvszp_ecp_core_electrons(text: str) -> dict[int, int]:
    """Parse a real q-vSZP `ecpq`-format file into `{Z: ncore}`.

    Real format: each element block (`*`-delimited) starts with `<Z>` then
    an `ncore = <n> lmax = <n>` line — `ncore` is the number of core
    electrons the ECP replaces (confirmed: Z=3-103 all present with
    `ncore=2`, i.e. the 1s core; Z=1,2 (H, He) have no block at all —
    all-electron).
    """
    result: dict[int, int] = {}
    lines = text.splitlines()
    current_z: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.isdigit() and current_z is None:
            current_z = int(stripped)
            continue
        ncore_match = re.match(r"ncore\s*=\s*(\d+)", stripped)
        if ncore_match and current_z is not None:
            result[current_z] = int(ncore_match.group(1))
            current_z = None
    return result


def count_basis_functions(
    element: str,
    variant: QvSZPVariant = QvSZPVariant.FULL,
    *,
    cache_dir: Path | str | None = None,
) -> int:
    """Real spatial AO function count for `element` in q-vSZP's `variant`
    — spherical-harmonic convention (`2*l + 1` per shell, one shell per
    contracted function; see `parse_qvszp_shells`'s docstring). Fixed per
    element, independent of any molecule's charges.
    """
    z = element_z(element)
    path = _cache_dir(cache_dir)
    text = _download(_VARIANT_FILENAMES[variant], path)
    shells = parse_qvszp_shells(text)
    if z not in shells:
        raise ValueError(f"{element!r} (Z={z}) not found in q-vSZP {variant.value} basis.")
    return sum(2 * _L_FROM_LETTER[letter] + 1 for letter in shells[z])


def ecp_core_electrons(element: str, *, cache_dir: Path | str | None = None) -> int | None:
    """Real ECP core-electron count for `element` (`None` if all-electron
    — true only for H/He in q-vSZP, confirmed against the real `ecpq`
    file)."""
    z = element_z(element)
    path = _cache_dir(cache_dir)
    text = _download(_ECPQ_FILENAME, path)
    return parse_qvszp_ecp_core_electrons(text).get(z)


def list_available_elements(variant: QvSZPVariant = QvSZPVariant.FULL, *, cache_dir: Path | str | None = None) -> list[str]:
    """Real element symbols covered by q-vSZP's `variant`."""
    path = _cache_dir(cache_dir)
    text = _download(_VARIANT_FILENAMES[variant], path)
    shells = parse_qvszp_shells(text)
    return [_ELEMENT_SYMBOLS[z - 1] for z in sorted(shells)]


def get_cp2k_format_text(*, cache_dir: Path | str | None = None) -> str:
    """Raw text of the real `basis_qvSZP_CP2K_format` file — directly
    usable as a CP2K `BASIS_SET` file, no ORCA and no further conversion
    needed (it's the FULL variant with only the charge-independent
    coefficient column kept, per the file's own header comment)."""
    path = _cache_dir(cache_dir)
    return _download(_CP2K_FILENAME, path)


__all__ = [
    "count_basis_functions",
    "ecp_core_electrons",
    "element_z",
    "get_cp2k_format_text",
    "list_available_elements",
    "parse_qvszp_ecp_core_electrons",
    "parse_qvszp_shells",
]
