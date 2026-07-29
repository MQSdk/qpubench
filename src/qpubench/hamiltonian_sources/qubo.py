"""Pre-defined QUBO Hamiltonians from the standard public benchmark libraries.

Install: pip install 'qpubench[qubo]'   (requests)

This module **loads** QUBO Hamiltonians. It does not construct them: nothing
here turns a problem description into a QUBO. See
``docs/qubo_generator_roadmap.md`` for the analysis of what a molecule-to-QUBO
generator (an ``ab_initio.py`` for QUBOs) would take.

Three sources, and one deliberate omission
------------------------------------------

**OR-Library (Beasley)** — ``load_orlib()``. The canonical originals, and the
only one of the three that publishes QUBO matrices *as QUBO matrices*. Seven
files (``bqp50`` … ``bqp2500``, ``bqpgka``) each bundle 10 instances. Format is
documented at people.brunel.ac.uk/~mastjjb/jeb/orlib/bqpinfo.html and confirmed
against the real ``bqp100.txt`` in this repo's sandbox::

    <number of instances>
    for each: <n> <nnz>
              <i> <j> <q_ij>       1-indexed, symmetric, one triangle stored

Note the sign convention: OR-Library states the problem as **maximise**
``sum_ij q_ij x_i x_j``. qpubench normalises everything to minimisation, so
``load_orlib()`` negates on read and records ``"orlib_sense": "maximise"`` in
the record's extras. Getting this backwards silently gives you the *worst*
solution instead of the best.

**MQLib** — ``load_mqlib()``. 3506 instances (``data/metrics.csv`` in the
repo), payloads in the anonymously-readable ``mqlibinstances`` S3 bucket over
plain HTTPS — no boto3 and no AWS account, despite what the project's own
``scripts/downloadGraph.py`` implies. Its ``be*``/``gka*`` families are the
OR-Library instances **already converted to Max-Cut**, on ``n + 1`` nodes: the
extra node is the reference vertex of the standard QUBO-to-Max-Cut reduction.
``load_mqlib()`` therefore returns the Max-Cut form as-is; pass
``recover_qubo=True`` to invert the reduction and get the QUBO matrix back.
(Verified: ``be100.1`` is 101 nodes / 564 edges for a 100-variable QUBO.)

**QUBO.jl / QUBOTools.jl** — ``read_qubo_file()`` and ``read_bqpjson()``. This
one ships no instances at all; it is a Julia *format* ecosystem. The useful
integration is therefore to read the formats it writes, so anything produced by
that toolchain loads here: the qbsolv ``.qubo`` text format (0-indexed, ``p
qubo`` program line) and LANL-ANSI's ``BQPJSON``.

**QBPP / QUBO++ (Hiroshima)** — *not wired in, on purpose.* It is a C++ library
for *building* QUBO and HUBO models programmatically, with bundled solvers. It
publishes neither a benchmark instance library nor an interchange format of its
own, so there is nothing here to load. A QBPP model exported to ``.qubo`` reads
back through ``read_qubo_file()`` like any other.

Everything returns ``(QUBOInstance, HamiltonianLibraryRecord)``. Use
``QUBOInstance.to_ising_observable()`` to get a ``SparsePauliObservable`` for
the rest of the framework.
"""
from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pydantic

from ..schemas.catalogs.hamiltonian_library import (
    HamiltonianLibraryRecord,
    HamiltonianSource,
)
from ..schemas.observable import PauliTerm, SparsePauliObservable
from ..schemas.primitives import ComplexNumber, PauliLabel

_ORLIB_BASE = "https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files"
_MQLIB_INSTANCE_BASE = "https://mqlibinstances.s3.amazonaws.com"
_MQLIB_METRICS_URL = (
    "https://raw.githubusercontent.com/MQLib/MQLib/master/data/metrics.csv"
)
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "qpubench" / "hamiltonian_sources" / "qubo"

#: The seven OR-Library QUBO files, with the instance size each contains.
ORLIB_FILES: dict[str, int] = {
    "bqp50": 50,
    "bqp100": 100,
    "bqp250": 250,
    "bqp500": 500,
    "bqp1000": 1000,
    "bqp2500": 2500,
    "bqpgka": 0,  # mixed sizes (Glover-Kochenberger-Alidaee set)
}


class QUBOInstance(pydantic.BaseModel):
    """One loaded QUBO Hamiltonian, normalised to a minimisation problem.

    The objective is ``sum_ij Q_ij x_i x_j`` over ``x in {0,1}^n``, to be
    **minimised**. Sources that publish a maximisation problem are negated on
    read, and say so in the loader's record extras.

    ``quadratic`` holds the strict upper triangle only (``i < j``), so each
    pair appears once; ``linear`` holds the diagonal. That split is what makes
    the Ising conversion unambiguous, and it is why a raw symmetric matrix is
    not stored: the same coefficient written twice means twice the weight, and
    every source in this module differs on whether it does that.
    """

    name: str
    num_variables: int
    linear: dict[int, float] = {}
    quadratic: dict[str, float] = {}

    @property
    def num_terms(self) -> int:
        """Non-zero coefficients — the size of the problem, not of the matrix."""
        return len(self.linear) + len(self.quadratic)

    @staticmethod
    def _pair_key(i: int, j: int) -> str:
        """Canonical dict key for an unordered index pair.

        A string, not a tuple: JSON object keys must be strings, and these
        instances round-trip through the result store like anything else.
        """
        lo, hi = (i, j) if i < j else (j, i)
        return f"{lo},{hi}"

    def quadratic_pairs(self) -> list[tuple[int, int, float]]:
        """Yield ``(i, j, coefficient)`` triples with ``i < j``."""
        pairs = []
        for key, value in self.quadratic.items():
            i, j = key.split(",")
            pairs.append((int(i), int(j), value))
        return pairs

    def objective(self, assignment: dict[int, int] | list[int]) -> float:
        """Evaluate the objective at a binary assignment.

        Present so a benchmark can check a returned bitstring itself rather
        than trusting a backend's reported energy.
        """
        x = (
            assignment
            if isinstance(assignment, dict)
            else dict(enumerate(assignment))
        )
        total = sum(coeff * x.get(i, 0) for i, coeff in self.linear.items())
        total += sum(
            coeff * x.get(i, 0) * x.get(j, 0) for i, j, coeff in self.quadratic_pairs()
        )
        return total

    def to_ising_observable(self) -> tuple[SparsePauliObservable, float]:
        """Convert to an Ising Hamiltonian, returning it with a constant offset.

        Substituting ``x_i = (1 - z_i) / 2`` into ``sum_ij Q_ij x_i x_j`` turns
        the QUBO into a Z/ZZ Hamiltonian. The identity part is returned
        separately as a float rather than folded in as an identity Pauli term:
        an energy has to be comparable against the classical objective, and a
        constant hidden inside the observable is the standard way that
        comparison quietly goes wrong.

        The mapping is exact, not a heuristic — it is a change of variable, so
        the ground state of the returned observable is the QUBO's optimum.
        """
        offset = 0.0
        z_coefficients: dict[int, float] = {}
        zz_terms: list[PauliTerm] = []

        for i, coefficient in self.linear.items():
            # Q_ii x_i = Q_ii (1 - z_i) / 2
            offset += coefficient / 2.0
            z_coefficients[i] = z_coefficients.get(i, 0.0) - coefficient / 2.0

        for i, j, coefficient in self.quadratic_pairs():
            # Q_ij x_i x_j = Q_ij (1 - z_i)(1 - z_j) / 4
            offset += coefficient / 4.0
            z_coefficients[i] = z_coefficients.get(i, 0.0) - coefficient / 4.0
            z_coefficients[j] = z_coefficients.get(j, 0.0) - coefficient / 4.0
            zz_terms.append(
                PauliTerm(
                    qubit_indices=(i, j),
                    pauli_ops=(PauliLabel.Z, PauliLabel.Z),
                    coefficient=ComplexNumber(re=coefficient / 4.0),
                )
            )

        terms = [
            PauliTerm(
                qubit_indices=(i,),
                pauli_ops=(PauliLabel.Z,),
                coefficient=ComplexNumber(re=value),
            )
            for i, value in sorted(z_coefficients.items())
            if value != 0.0
        ]
        terms.extend(zz_terms)

        observable = SparsePauliObservable(
            num_qubits=self.num_variables, terms=terms
        )
        return observable, offset


# ---------------------------------------------------------------------------
# OR-Library (Beasley) — the canonical QUBO originals
# ---------------------------------------------------------------------------

def load_orlib(
    file_name: str = "bqp100",
    index: int = 0,
    *,
    cache_dir: Path | str | None = None,
) -> tuple[QUBOInstance, HamiltonianLibraryRecord]:
    """Load one instance from an OR-Library QUBO file.

    Parameters
    ----------
    file_name:
        One of ``ORLIB_FILES`` — ``"bqp50"`` … ``"bqp2500"``, or ``"bqpgka"``.
    index:
        Which of the file's bundled instances to return (each holds 10).
    cache_dir:
        Where to keep the downloaded file. Defaults to
        ``~/.cache/qpubench/hamiltonian_sources/qubo/``; nothing is
        re-downloaded once present.

    The published objective is a *maximisation*; the returned instance is
    negated so that minimising it is equivalent, with ``extras["orlib_sense"]``
    recording the original direction.
    """
    if file_name not in ORLIB_FILES:
        raise ValueError(
            f"Unknown OR-Library file {file_name!r}. "
            f"Available: {', '.join(sorted(ORLIB_FILES))}"
        )
    text = _fetch_text(
        f"{_ORLIB_BASE}/{file_name}.txt",
        _cache_dir(cache_dir) / f"{file_name}.txt",
    )
    instances = _parse_orlib(text, file_name)
    if not 0 <= index < len(instances):
        raise IndexError(
            f"{file_name} holds {len(instances)} instances; index {index} is out of range"
        )
    instance = instances[index]
    return instance, HamiltonianLibraryRecord(
        source=HamiltonianSource.QUBO_ORLIB,
        molecule_name=instance.name,
        num_qubits=instance.num_variables,
        num_terms=instance.num_terms,
        encoding="ising_z",
        extras={
            "library": "orlib_beasley",
            "file": file_name,
            "index": index,
            "orlib_sense": "maximise",
            "note": "coefficients negated on read; minimise the returned instance",
        },
    )


def _parse_orlib(text: str, file_name: str) -> list[QUBOInstance]:
    """Parse an OR-Library bqp file into its bundled instances.

    Format (from the OR-Library documentation, confirmed against bqp100.txt):
    a count of instances, then per instance ``n nnz`` followed by ``nnz`` lines
    of ``i j q_ij``, 1-indexed with only one triangle stored.
    """
    tokens = text.split()
    position = 0

    def take() -> str:
        nonlocal position
        value = tokens[position]
        position += 1
        return value

    count = int(take())
    instances: list[QUBOInstance] = []
    for number in range(count):
        num_variables = int(take())
        num_entries = int(take())
        linear: dict[int, float] = {}
        quadratic: dict[str, float] = {}
        for _ in range(num_entries):
            i = int(take()) - 1  # OR-Library is 1-indexed
            j = int(take()) - 1
            value = -float(take())  # published as maximise; store as minimise
            if i == j:
                linear[i] = linear.get(i, 0.0) + value
            else:
                key = QUBOInstance._pair_key(i, j)
                quadratic[key] = quadratic.get(key, 0.0) + value
        instances.append(
            QUBOInstance(
                name=f"{file_name}.{number + 1}",
                num_variables=num_variables,
                linear=linear,
                quadratic=quadratic,
            )
        )
    return instances


# ---------------------------------------------------------------------------
# MQLib — 3506 Max-Cut / QUBO instances
# ---------------------------------------------------------------------------

def list_mqlib_instances(
    *, cache_dir: Path | str | None = None
) -> list[str]:
    """Return every instance name in MQLib's catalogue (3506 of them)."""
    text = _fetch_text(_MQLIB_METRICS_URL, _cache_dir(cache_dir) / "mqlib_metrics.csv")
    lines = text.splitlines()[1:]  # header
    return [line.split(",", 1)[0].removesuffix(".zip") for line in lines if line]


def load_mqlib(
    instance_name: str = "be100.1",
    *,
    recover_qubo: bool = False,
    cache_dir: Path | str | None = None,
) -> tuple[QUBOInstance, HamiltonianLibraryRecord]:
    """Load one MQLib instance.

    Parameters
    ----------
    instance_name:
        Name from ``list_mqlib_instances()``, e.g. ``"be100.1"``, ``"gka.1a"``.
    recover_qubo:
        MQLib stores the ``be``/``gka`` QUBO families already converted to
        Max-Cut on ``n + 1`` nodes. Left False (the default) the Max-Cut
        instance is returned as it is published — itself a perfectly good
        benchmark Hamiltonian. Set True to invert the reduction and recover the
        ``n``-variable QUBO, using the last node as the reference vertex.
    cache_dir:
        Download cache; nothing is re-fetched once present.

    Fetched over plain HTTPS from the anonymously-readable ``mqlibinstances``
    bucket — no boto3 and no AWS credentials, despite MQLib's own
    ``downloadGraph.py`` using the boto client.
    """
    path = _cache_dir(cache_dir) / f"{instance_name}.txt"
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        payload = _fetch_bytes(f"{_MQLIB_INSTANCE_BASE}/{instance_name}.zip")
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            text = archive.read(archive.namelist()[0]).decode("utf-8")
        path.write_text(text, encoding="utf-8")

    instance = _parse_mqlib(text, instance_name)
    if recover_qubo:
        instance = _maxcut_to_qubo(instance)

    return instance, HamiltonianLibraryRecord(
        source=HamiltonianSource.QUBO_MQLIB,
        molecule_name=instance.name,
        num_qubits=instance.num_variables,
        num_terms=instance.num_terms,
        encoding="ising_z",
        extras={
            "library": "mqlib",
            "instance": instance_name,
            "form": "qubo_recovered" if recover_qubo else "maxcut",
        },
    )


def _parse_mqlib(text: str, instance_name: str) -> QUBOInstance:
    """Parse MQLib's ``n m`` header plus ``a b w`` lines (1-indexed, '#' comments)."""
    lines = [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    num_nodes, num_entries = (int(value) for value in lines[0].split()[:2])

    linear: dict[int, float] = {}
    quadratic: dict[str, float] = {}
    for line in lines[1 : 1 + num_entries]:
        a_text, b_text, w_text = line.split()[:3]
        i, j, weight = int(a_text) - 1, int(b_text) - 1, float(w_text)
        if i == j:
            linear[i] = linear.get(i, 0.0) + weight
        else:
            key = QUBOInstance._pair_key(i, j)
            quadratic[key] = quadratic.get(key, 0.0) + weight

    return QUBOInstance(
        name=instance_name,
        num_variables=num_nodes,
        linear=linear,
        quadratic=quadratic,
    )


def _maxcut_to_qubo(maxcut: QUBOInstance) -> QUBOInstance:
    """Invert MQLib's QUBO-to-Max-Cut reduction exactly.

    The reduction adds a reference vertex ``r`` (last node, so index ``n - 1``
    after the 1-to-0 shift) and, writing ``Q`` for the original matrix in
    OR-Library's *maximise* convention:

        w_ij  = -Q_ij                       for real nodes i < j
        w_ir  =  Q_ii + sum_{j != i} Q_ij   for the reference edges

    So the diagonal is not carried on the reference edge alone — each row sum
    of the off-diagonal is folded into it too. Reading only ``w_ir`` back as a
    linear term (the obvious-looking inverse) recovers a *different* QUBO;
    the row sum has to be subtracted out again.

    Since this module stores the minimisation form, ``Q_ij^min = -Q_ij = w_ij``
    and the off-diagonal weights carry over unchanged; only the diagonal needs
    reconstructing. Verified exactly, coefficient for coefficient, against
    OR-Library's ``bqp100.1`` — see ``tests/test_qubo_sources.py``.
    """
    reference = maxcut.num_variables - 1
    reference_weight: dict[int, float] = {}
    quadratic: dict[str, float] = {}
    row_sum: dict[int, float] = {}

    for i, j, weight in maxcut.quadratic_pairs():
        if reference in (i, j):
            reference_weight[j if i == reference else i] = weight
        else:
            quadratic[QUBOInstance._pair_key(i, j)] = weight
            row_sum[i] = row_sum.get(i, 0.0) + weight
            row_sum[j] = row_sum.get(j, 0.0) + weight

    linear = {
        i: -(weight + row_sum.get(i, 0.0))
        for i, weight in reference_weight.items()
        if weight + row_sum.get(i, 0.0) != 0.0
    }

    return QUBOInstance(
        name=f"{maxcut.name}.qubo",
        num_variables=maxcut.num_variables - 1,
        linear=linear,
        quadratic=quadratic,
    )


# ---------------------------------------------------------------------------
# QUBOTools / QUBO.jl interchange formats
# ---------------------------------------------------------------------------

def read_qubo_file(path: Path | str) -> QUBOInstance:
    """Read the qbsolv ``.qubo`` text format that QUBOTools.jl writes.

    Structure: ``c``-prefixed comments, then a program line
    ``p qubo <topology> <maxNodes> <nNodes> <nCouplers>``, then ``nNodes``
    diagonal entries and ``nCouplers`` off-diagonal ones as ``i j value``.
    Indices are **0-based** here — unlike OR-Library and MQLib, which are both
    1-based. That difference is the single easiest thing to get wrong when
    moving an instance between these libraries.
    """
    path = Path(path)
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("c")
    ]
    if not lines or not lines[0].split()[:2] == ["p", "qubo"]:
        raise ValueError(f"{path} has no 'p qubo' program line")

    fields = lines[0].split()
    num_variables = int(fields[3])  # maxNodes
    num_nodes, num_couplers = int(fields[4]), int(fields[5])

    linear: dict[int, float] = {}
    quadratic: dict[str, float] = {}
    for line in lines[1 : 1 + num_nodes + num_couplers]:
        i_text, j_text, value_text = line.split()[:3]
        i, j, value = int(i_text), int(j_text), float(value_text)
        if i == j:
            linear[i] = linear.get(i, 0.0) + value
        else:
            key = QUBOInstance._pair_key(i, j)
            quadratic[key] = quadratic.get(key, 0.0) + value

    return QUBOInstance(
        name=path.stem,
        num_variables=num_variables,
        linear=linear,
        quadratic=quadratic,
    )


def read_bqpjson(path: Path | str) -> QUBOInstance:
    """Read LANL-ANSI's BQPJSON format (QUBOTools.jl's richest interchange).

    BQPJSON is spin-or-boolean: ``variable_domain`` is ``"spin"`` or
    ``"boolean"``. Only the boolean domain is a QUBO; a spin instance is an
    Ising model and is rejected here rather than silently reinterpreted, since
    the two differ by exactly the change of variable
    ``to_ising_observable()`` performs.
    """
    path = Path(path)
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    domain = document.get("variable_domain")
    if domain != "boolean":
        raise ValueError(
            f"{path} has variable_domain={domain!r}; only 'boolean' is a QUBO. "
            "A 'spin' instance is an Ising model — convert it upstream, or use "
            "QUBOInstance.to_ising_observable() in the other direction."
        )

    variable_ids = list(document.get("variable_ids", []))
    index_of = {variable: position for position, variable in enumerate(variable_ids)}

    linear = {
        index_of[entry["id"]]: float(entry["coeff"])
        for entry in document.get("linear_terms", [])
    }
    quadratic: dict[str, float] = {}
    for entry in document.get("quadratic_terms", []):
        key = QUBOInstance._pair_key(index_of[entry["id_head"]], index_of[entry["id_tail"]])
        quadratic[key] = quadratic.get(key, 0.0) + float(entry["coeff"])

    return QUBOInstance(
        name=str(document.get("id", path.stem)),
        num_variables=len(variable_ids),
        linear=linear,
        quadratic=quadratic,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cache_dir(cache_dir: Path | str | None) -> Path:
    path = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fetch_bytes(url: str) -> bytes:
    try:
        import requests
    except ImportError as exc:
        raise ImportError(
            "Downloading QUBO instances requires requests. "
            "Install with: pip install 'qpubench[qubo]'"
        ) from exc
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return bytes(response.content)


def _fetch_text(url: str, cache_path: Path) -> str:
    """Return the URL's text, downloading it into ``cache_path`` if absent."""
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    text = _fetch_bytes(url).decode("utf-8")
    cache_path.write_text(text, encoding="utf-8")
    return text


__all__ = [
    "ORLIB_FILES",
    "QUBOInstance",
    "list_mqlib_instances",
    "load_mqlib",
    "load_orlib",
    "read_bqpjson",
    "read_qubo_file",
]
