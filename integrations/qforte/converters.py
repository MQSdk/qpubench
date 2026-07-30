"""Type conversion utilities: QForte ↔ qpubench schemas.

Neither qpubench nor qforte import from each other.
This module is the only place that knows about both.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.execution import AlgorithmSpec
from qpubench.schemas.mirrors.evangelistalab_qforte import (
    QForteAlgorithmConfig,
    QForteCircuitSpec,
    QForteGateSpec,
    QForteQubitOperatorSpec,
    QForteQubitOperatorTerm,
    QForteRunResult,
)
from qpubench.schemas.observable import SparsePauliObservable
from qpubench.schemas.primitives import CircuitFormat, ComplexNumber, ComputingModel, JobStatus
from qpubench.schemas.record import VQAConfig, VQAResult
from qpubench.schemas.result import AdaptIteration, ExpectationResult, QuantumResult

# ---------------------------------------------------------------------------
# Locating QForte's bundled test molecules
# ---------------------------------------------------------------------------

_QFORTE_TESTS_RAW_URL = "https://raw.githubusercontent.com/evangelistalab/qforte/master/tests"

# Relative locations of a molecule JSON under any candidate root.
_MOLECULE_SUBDIRS = (Path(), Path("tests"), Path("qforte") / "tests", Path("share") / "qforte")


def _distribution_source_dir(dist_name: str) -> Path | None:
    """Source directory recorded by ``pip install .`` / ``pip install -e .``.

    PEP 610 makes pip write ``direct_url.json`` into the ``.dist-info`` of
    anything installed from a local path, which is how we get from an
    installed QForte back to the checkout its ``tests/`` directory lives in.
    """
    try:
        from importlib.metadata import distribution
        raw = distribution(dist_name).read_text("direct_url.json")
    except Exception:
        return None
    if not raw:
        return None
    try:
        url = json.loads(raw).get("url", "")
    except json.JSONDecodeError:
        return None
    if not url.startswith("file://"):
        return None

    from urllib.parse import unquote, urlparse
    path = Path(unquote(urlparse(url).path))
    return path if path.is_dir() else None


def _qforte_search_roots() -> list[Path]:
    """Directories that may contain (or contain a parent of) QForte's tests/."""
    roots: list[Path] = []

    try:
        import qforte
    except ImportError:
        qforte = None  # type: ignore[assignment]

    pkg_dir: Path | None = None
    if qforte is not None and getattr(qforte, "__file__", None):
        pkg_dir = Path(qforte.__file__).resolve().parent
        # setup.py develop / editable installs leave qforte importable from
        # inside the checkout: <clone>/src/qforte/__init__.py → <clone>/tests/.
        roots += [pkg_dir, *list(pkg_dir.parents)[:3]]

    src_dir = _distribution_source_dir("qforte")
    if src_dir is not None:
        roots.append(src_dir)

    cwd = Path.cwd().resolve()
    roots += [cwd, *list(cwd.parents)[:3]]

    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            unique.append(root)
    return unique


def find_molecule_json(name: str, *, env_var: str | None = None) -> Path:
    """Locate a molecule JSON that ships in QForte's ``tests/`` directory.

    QForte's setup.py does not install ``tests/``, so these files exist only
    in a source checkout — an installed-only QForte will never have them.
    Search order:

      1. ``$env_var``, either the file itself or a directory holding it
      2. the installed ``qforte`` package directory (recursively)
      3. the checkout: parents of the package directory, plus the source
         path pip recorded for a ``pip install .`` / ``pip install -e .``
      4. the current directory and its parents

    Raises FileNotFoundError listing the searched roots and how to fix it.
    """
    override = os.environ.get(env_var) if env_var else None
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_dir():
            candidate = candidate / name
        if not candidate.is_file():
            raise FileNotFoundError(
                f"${env_var} is set to {override!r}, but {candidate} is not a file."
            )
        return candidate.resolve()

    roots = _qforte_search_roots()
    for root in roots:
        for subdir in _MOLECULE_SUBDIRS:
            candidate = root / subdir / name
            if candidate.is_file():
                return candidate.resolve()

    # Last resort: walk the installed package itself (small, and would find
    # the file if a future QForte release starts shipping its test data).
    try:
        import qforte
        pkg_dir = Path(qforte.__file__).resolve().parent
    except (ImportError, AttributeError, TypeError):
        pass
    else:
        for hit in pkg_dir.rglob(name):
            return hit.resolve()

    searched = "\n".join(f"    {root}" for root in roots)
    env_hint = env_var or "QFORTE_MOLECULE_PATH"
    raise FileNotFoundError(
        f"{name} not found.\n\n"
        "QForte does not install its tests/ directory, so this file is only\n"
        "present in a source checkout.  Any of these fixes work:\n\n"
        "  1. Point at a checkout you already have:\n"
        f"       export {env_hint}=/path/to/qforte/tests/{name}\n"
        "  2. Download the single file:\n"
        f"       curl -LO {_QFORTE_TESTS_RAW_URL}/{name}\n"
        f"       export {env_hint}=$PWD/{name}\n"
        "  3. Install QForte from a git clone (keep the clone in place):\n"
        "       git clone https://github.com/evangelistalab/qforte.git\n"
        "       pip install ./qforte\n\n"
        f"Searched under:\n{searched}\n"
    )


# ---------------------------------------------------------------------------
# Molecule spec helpers
# ---------------------------------------------------------------------------

def molecule_spec_from_file(
    json_path: str | Path,
    *,
    num_qubits: int = 0,
) -> CircuitSpec:
    """Build a CircuitSpec from a QForte external molecule JSON file.

    num_qubits can be left as 0 when unknown before building the system.
    QForteAlgorithmAdapter will fill it in after calling system_factory().
    """
    return CircuitSpec(
        num_qubits=num_qubits,
        format=CircuitFormat.MOLECULE_JSON,
        serialized=str(Path(json_path).resolve()),
    )


def molecule_spec_from_geometry(
    geometry: list[tuple[str, tuple[float, float, float]]],
    basis: str = "sto-6g",
    *,
    multiplicity: int = 1,
    charge: int = 0,
    symmetry: str = "c1",
    run_fci: int = 1,
    num_frozen_docc: int = 0,
    num_frozen_uocc: int = 0,
) -> CircuitSpec:
    """Build a CircuitSpec for an on-the-fly Psi4 build.

    Requires Psi4 to be installed.

    Example:
        spec = molecule_spec_from_geometry(
            [("H", (0, 0, 0)), ("H", (0, 0, 0.735))],
            basis="sto-6g",
        )
    """
    payload = {
        "build_type":       "psi4",
        "mol_geometry":     [[sym, list(xyz)] for sym, xyz in geometry],
        "basis":            basis,
        "multiplicity":     multiplicity,
        "charge":           charge,
        "symmetry":         symmetry,
        "run_fci":          run_fci,
        "num_frozen_docc":  num_frozen_docc,
        "num_frozen_uocc":  num_frozen_uocc,
    }
    return CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized=json.dumps(payload),
    )


# ---------------------------------------------------------------------------
# QForte pybind11 objects → typed schemas (schemas/mirrors/evangelistalab_qforte.py)
# ---------------------------------------------------------------------------

_QFORTE_PAULI_GATES = frozenset({"X", "Y", "Z"})


def qforte_op_to_qforte_spec(qb_ham: Any, num_qubits: int) -> QForteQubitOperatorSpec:
    """Read a live QForte QubitOperator (pybind11) into QForteQubitOperatorSpec.

    QForte exposes the operator as QubitOperator.terms() → list of
    (coeff, Circuit) pairs where each Circuit is a Pauli string
    (Circuit.is_pauli() == True). This is the one place that reads the
    pybind11 object directly; everything downstream uses the typed schema.
    """
    terms: list[QForteQubitOperatorTerm] = []
    for coeff, pauli_circ in qb_ham.terms():
        gates = [
            QForteGateSpec(gate_id=gate.gate_id(), target=gate.target())
            for gate in pauli_circ.gates()
            if gate.gate_id() in _QFORTE_PAULI_GATES
        ]
        terms.append(QForteQubitOperatorTerm(
            coefficient=ComplexNumber(re=float(coeff.real), im=float(coeff.imag)),
            pauli_circuit=QForteCircuitSpec(gates=gates, is_pauli=True),
        ))
    return QForteQubitOperatorSpec(terms=terms, num_qubits=num_qubits)


def qforte_op_to_sparse_pauli(qb_ham: Any, num_qubits: int) -> SparsePauliObservable:
    """Convert a live QForte QubitOperator directly to a SparsePauliObservable.

    Convenience wrapper around qforte_op_to_qforte_spec(...).to_sparse_pauli_observable()
    for callers (e.g. ExternalEvalAlgorithmAdapter) that only need the
    cross-package Pauli representation, not the QForte-specific one.
    """
    return qforte_op_to_qforte_spec(qb_ham, num_qubits).to_sparse_pauli_observable()


# ---------------------------------------------------------------------------
# QForte algorithm state → typed schemas
# ---------------------------------------------------------------------------

def extract_qforte_run_result(alg: Any) -> QForteRunResult:
    """Read a completed QForte Algorithm/AnsatzAlgorithm/ADAPTVQE object.

    Field ↔ attribute mapping is documented on QForteRunResult itself —
    verified against upstream evangelistalab/qforte source. getattr() with
    a default is unavoidable here (this is the pybind11 boundary); every
    downstream consumer works with the typed QForteRunResult instead.
    """
    umaxdepth = getattr(alg, "_Umaxdepth", None)
    return QForteRunResult(
        final_energy=float(alg.get_gs_energy()),
        hf_energy=getattr(alg, "_hf_energy", None),
        n_qubits=getattr(alg, "_nqb", None),
        converged=bool(getattr(alg, "_converged", True)),
        final_gradient_norm=getattr(alg, "_curr_grad_norm", None),
        selected_operators=list(getattr(alg, "_tops", [])),
        amplitudes=list(getattr(alg, "_tamps", [])),
        n_cnot=int(getattr(alg, "_n_cnot", 0)),
        n_classical_params=int(getattr(alg, "_n_classical_params", 0)),
        n_pauli_trm_measures=int(getattr(alg, "_n_pauli_trm_measures", 0)),
        n_ham_measurements=getattr(alg, "_n_ham_measurements", None),
        n_commut_measurements=getattr(alg, "_n_commut_measurements", None),
        energies_history=list(getattr(alg, "_energies", [])),
        grad_norms_history=list(getattr(alg, "_grad_norms", [])),
        n_cnot_history=list(getattr(alg, "_n_cnot_lst", [])),
        n_classical_params_history=list(getattr(alg, "_n_classical_params_lst", [])),
        n_pauli_trm_measures_history=list(getattr(alg, "_n_pauli_trm_measures_lst", [])),
        max_circuit_depth_repr=str(umaxdepth) if umaxdepth is not None else None,
    )


def extract_adapt_history(qforte_result: QForteRunResult) -> list[AdaptIteration]:
    """Reconstruct per-macro-iteration metrics from a QForteRunResult."""
    energies, grad_norms = qforte_result.energies_history, qforte_result.grad_norms_history
    cnot_lst, param_lst = qforte_result.n_cnot_history, qforte_result.n_classical_params_history
    pauli_lst = qforte_result.n_pauli_trm_measures_history
    n = len(energies)
    return [
        AdaptIteration(
            iteration=i,
            energy=energies[i],
            grad_norm=grad_norms[i] if i < len(grad_norms) else 0.0,
            n_operators=i + 1,
            n_cnot=cnot_lst[i] if i < len(cnot_lst) else 0,
            n_classical_params=param_lst[i] if i < len(param_lst) else 0,
            n_pauli_measures=pauli_lst[i] if i < len(pauli_lst) else 0,
        )
        for i in range(n)
    ]


def extract_quantum_result(alg: Any, alg_spec: AlgorithmSpec) -> QuantumResult:
    """Build a QuantumResult from any completed QForte algorithm object."""
    qforte_result = extract_qforte_run_result(alg)
    adapt_history = (
        extract_adapt_history(qforte_result) if alg_spec.name.upper() == "ADAPTVQE" else None
    )
    return QuantumResult(
        computing_model=ComputingModel.GATE_BASED,
        expectation_values=[
            ExpectationResult(observable_index=0, value=qforte_result.final_energy, std_error=0.0)
        ],
        adapt_history=adapt_history,
        transpiled_circuit=qforte_result.max_circuit_depth_repr,
        status=JobStatus.SUCCEEDED,
        vendor_results={"qforte_result": qforte_result},
    )


def extract_vqa_config(
    alg_spec: AlgorithmSpec,
    qforte_config: QForteAlgorithmConfig,
) -> VQAConfig:
    """Build a VQAConfig (experiment inputs) from the QForte run configuration."""
    return VQAConfig(
        problem_type="chemistry",
        algorithm=alg_spec.name,
        pool_type=qforte_config.base.pool_type,
        optimizer=qforte_config.base.optimizer,
    )


def extract_vqa_result(
    alg: Any,
    mol: Any,
    alg_spec: AlgorithmSpec,
) -> VQAResult:
    """Build a VQAResult (computed outputs) from a completed QForte algorithm."""
    qforte_result = extract_qforte_run_result(alg)
    hf_energy  = qforte_result.hf_energy if qforte_result.hf_energy is not None else float(
        getattr(mol, "hf_energy", 0.0)
    )
    fci_energy = float(getattr(mol, "fci_energy", 0.0))
    adapts_reached = alg_spec.name.upper() == "ADAPTVQE" and not qforte_result.converged
    return VQAResult(
        hf_energy=hf_energy,
        fci_energy=fci_energy if fci_energy != 0.0 else None,
        num_parameters=qforte_result.n_classical_params,
        n_cnot=qforte_result.n_cnot,
        n_pauli_trm_measures=qforte_result.n_pauli_trm_measures,
        convergence_values=qforte_result.energies_history,
        adapt_maxiter_reached=adapts_reached,
        final_eigenvalue=qforte_result.final_energy,
        ground_truth=fci_energy if fci_energy != 0.0 else None,
    )
