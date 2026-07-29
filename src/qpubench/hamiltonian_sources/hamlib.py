"""HamLib Chemistry loader — portal.nersc.gov/cfs/m888/dcamps/hamlib/chemistry/

Install: pip install 'qpubench[hamlib]'   (h5py + requests)

Real, verified format (downloaded `chemistry/electronic/standard/H2.zip`
and inspected directly in this repo's own sandbox, not guessed):

  - Each `<molecule>.zip` contains one `<molecule>.hdf5` file with several
    scalar datasets named `ham_<ENCODING>-<NQUBITS>`
    (`ENCODING` in `JW`/`BK`/`parity`/`molec`) — usually more than one
    per molecule (different basis/active-space truncations bundled
    together).
  - Each dataset holds a UTF-8 byte string in OpenFermion's
    `QubitOperator.__str__()` text format:
    `"(coeff+0j) [X0 Y1 ...] +\\n(coeff+0j) [] +\\n..."` (an empty
    bracket `[]` is the identity term). Parsed here with a small regex —
    no `openfermion` dependency needed just to read it.
  - `attrs` on each dataset carry `nqubits`/`terms`/`one_norm` — matched
    exactly against the parsed term count in this session's verification.
  - No reference energies (FCI/HF) are shipped anywhere in HamLib.

Only the `chemistry/electronic/*` categories are covered
(`standard`/`bond_breaking`/`hydrogen_data`/`transition_metals` — same
`<molecule>.zip` convention confirmed for all four via their real
directory listings). HamLib's separate `chemistry/vibrational/` tree uses
a different, phonon-mode-based format and is out of scope here — not
silently ignored, just not yet wired in.

`bond_breaking` archives are large (up to ~330MB) — downloads are cached
locally (default `~/.cache/qpubench/hamiltonian_sources/hamlib/`) and
never re-fetched once present.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import TypedDict

from ..schemas.catalogs.hamiltonian_library import HamiltonianLibraryRecord, HamiltonianSource
from ..schemas.observable import PauliTerm, SparsePauliObservable
from ..schemas.primitives import ComplexNumber, PauliLabel


class HamlibDatasetInfo(TypedDict):
    encoding: str
    num_qubits: int
    key: str
    nqubits: int
    terms: int | None
    one_norm: float | None

_BASE_URL = "https://portal.nersc.gov/cfs/m888/dcamps/hamlib/chemistry/electronic"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "qpubench" / "hamiltonian_sources" / "hamlib"

# Matches "(coeff+0j) [X0 Y1 ...]" (HamLib's stored format, always
# parenthesized-complex) or bare "coeff [X0 Y1 ...]" (OpenFermion's live
# QubitOperator.__str__() drops the parens/imaginary part for purely real
# coefficients — confirmed empirically, not documented) — both real
# OpenFermion QubitOperator text serializations.
_TERM_RE = re.compile(r"\(([^)]+)\)\s*\[([^\]]*)\]|([+-]?[0-9.eE+-]*[0-9])\s*\[([^\]]*)\]")

_DATASET_KEY_RE = re.compile(r"^ham_([A-Za-z]+)-(\d+)$")


def _cache_dir(cache_dir: Path | str | None) -> Path:
    path = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_and_extract(molecule: str, category: str, cache_dir: Path) -> Path:
    hdf5_path = cache_dir / f"{molecule}.hdf5"
    if hdf5_path.exists():
        return hdf5_path

    import requests

    zip_path = cache_dir / f"{molecule}.zip"
    if not zip_path.exists():
        url = f"{_BASE_URL}/{category}/{molecule}.zip"
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        zip_path.write_bytes(response.content)

    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(cache_dir)

    if not hdf5_path.exists():
        raise FileNotFoundError(
            f"Expected {hdf5_path.name} inside {molecule}.zip but it wasn't there "
            f"— HamLib's archive layout may have changed."
        )
    return hdf5_path


def parse_hamlib_qubit_operator(raw: bytes | str, num_qubits: int) -> SparsePauliObservable:
    """Parse a real OpenFermion `QubitOperator` text serialization —
    HamLib's stored format (always parenthesized-complex) or
    OpenFermion's live `str()` output (bare real coefficients, no
    parens, when the imaginary part is zero).

    Verified in this repo's own sandbox: round-trips the real HamLib H2
    `ham_JW-4` string into 15 terms, matching that dataset's own
    `attrs['terms']` exactly, and round-trips a live
    `jordan_wigner(...)` `str()` output (bare-real form) identically.
    """
    text = raw.decode() if isinstance(raw, bytes) else raw
    terms: list[PauliTerm] = []
    for paren_coeff, paren_pauli, bare_coeff, bare_pauli in _TERM_RE.findall(text):
        coeff_str = paren_coeff or bare_coeff
        pauli_str = paren_pauli or bare_pauli
        coeff = complex(coeff_str)
        tokens = pauli_str.split()
        indices = tuple(int(tok[1:]) for tok in tokens)
        ops = tuple(PauliLabel(tok[0]) for tok in tokens)
        terms.append(PauliTerm(
            qubit_indices=indices,
            pauli_ops=ops,
            coefficient=ComplexNumber(re=coeff.real, im=coeff.imag),
        ))
    return SparsePauliObservable(num_qubits=num_qubits, terms=terms)


def list_hamlib_datasets(
    molecule: str,
    *,
    category: str = "standard",
    cache_dir: Path | str | None = None,
) -> list[HamlibDatasetInfo]:
    """List the real `ham_<ENCODING>-<NQUBITS>` datasets available for
    `molecule` (downloads/caches the archive if not already present).

    Returns one `HamlibDatasetInfo` per dataset, straight from the file's
    own attrs.
    """
    import h5py

    path = _cache_dir(cache_dir)
    hdf5_path = _download_and_extract(molecule, category, path)

    datasets: list[HamlibDatasetInfo] = []
    with h5py.File(hdf5_path, "r") as f:
        for key in f.keys():
            match = _DATASET_KEY_RE.match(key)
            if not match:
                continue
            encoding, num_qubits = match.group(1), int(match.group(2))
            attrs = f[key].attrs
            datasets.append({
                "encoding": encoding,
                "num_qubits": num_qubits,
                "key": key,
                "nqubits": int(attrs.get("nqubits", num_qubits)),
                "terms": int(attrs["terms"]) if "terms" in attrs else None,
                "one_norm": float(attrs["one_norm"]) if "one_norm" in attrs else None,
            })
    return datasets


def load_hamlib_chemistry(
    molecule: str,
    *,
    category: str = "standard",
    encoding: str = "JW",
    num_qubits: int | None = None,
    cache_dir: Path | str | None = None,
) -> tuple[SparsePauliObservable, HamiltonianLibraryRecord]:
    """Load a real chemistry Hamiltonian from HamLib.

    Parameters
    ----------
    molecule:
        HamLib's own molecule label, e.g. ``"H2"``, ``"LiH"``, ``"BH"``.
    category:
        ``"standard"`` (small diatomics/triatomics — default),
        ``"bond_breaking"`` (F2/N2/O2 dissociation curves, large archives),
        ``"hydrogen_data"`` (H2..H60 clusters), or ``"transition_metals"``.
    encoding:
        ``"JW"`` (Jordan-Wigner, default), ``"BK"`` (Bravyi-Kitaev),
        ``"parity"``, or ``"molec"``.
    num_qubits:
        Which of the (usually several) bundled sizes to load. Defaults to
        the smallest available for the requested encoding.
    cache_dir:
        Where to cache the downloaded archive/HDF5. Defaults to
        ``~/.cache/qpubench/hamiltonian_sources/hamlib/``. Re-download is
        skipped if the file is already present.
    """
    path = _cache_dir(cache_dir)
    hdf5_path = _download_and_extract(molecule, category, path)

    available = list_hamlib_datasets(molecule, category=category, cache_dir=cache_dir)
    matching = [d for d in available if d["encoding"] == encoding]
    if not matching:
        found = sorted({str(d["encoding"]) for d in available})
        raise ValueError(
            f"No {encoding!r}-encoded Hamiltonian for {molecule!r} in "
            f"category {category!r}; available encodings: {found}"
        )
    if num_qubits is None:
        chosen = min(matching, key=lambda d: d["num_qubits"])
    else:
        exact = [d for d in matching if d["num_qubits"] == num_qubits]
        if not exact:
            sizes = sorted(d["num_qubits"] for d in matching)
            raise ValueError(
                f"No {num_qubits}-qubit {encoding!r} Hamiltonian for "
                f"{molecule!r}; available sizes: {sizes}"
            )
        chosen = exact[0]

    import h5py

    with h5py.File(hdf5_path, "r") as f:
        raw = f[chosen["key"]][()]

    observable = parse_hamlib_qubit_operator(raw, chosen["num_qubits"])
    record = HamiltonianLibraryRecord(
        source=HamiltonianSource.HAMLIB_CHEMISTRY,
        molecule_name=molecule,
        num_qubits=chosen["num_qubits"],
        encoding=encoding,
        num_terms=chosen["terms"] if chosen["terms"] is not None else len(observable.terms),
        one_norm=chosen["one_norm"],
        extras={"category": category, "dataset_key": chosen["key"]},
    )
    return observable, record


__all__ = [
    "HamlibDatasetInfo",
    "list_hamlib_datasets",
    "load_hamlib_chemistry",
    "parse_hamlib_qubit_operator",
]
