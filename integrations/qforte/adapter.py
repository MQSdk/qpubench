"""QForte algorithm adapters — implements qpubench's AlgorithmAdapter protocol.

Two adapters are provided:

QForteAlgorithmAdapter
    Wraps QForte end-to-end using QForte's own internal C++ statevector.
    Energy evaluation: QForte Computer (fast, exact).

ExternalEvalAlgorithmAdapter
    Overrides QForte's energy_feval via EnergyEvaluatorHook so that
    every energy evaluation is forwarded to a qpubench BackendAdapter.
    Energy evaluation: any registered qpubench backend (Aer, Qrack, IBM, …).

Separation contract
-------------------
qpubench does not import qforte.
qforte does not import qpubench.
This file is the only place that imports from both.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qpubench.backends.base import AlgorithmAdapter
from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.evangelistalab_qforte import QForteAlgorithmConfig
from qpubench.schemas.execution import AdaptVQEConfig, AlgorithmSpec, ExecutionOptions
from qpubench.schemas.primitives import AlgorithmFamily, CircuitFormat, ComputingModel
from qpubench.schemas.record import VQAConfig
from qpubench.schemas.result import QuantumResult, JobStatus

from .converters import (
    extract_quantum_result,
    extract_vqa_config,
    qforte_op_to_sparse_pauli,
)

_SUPPORTED_ALGORITHMS = frozenset({
    "UCCNVQE", "ADAPTVQE", "UCCNPQE", "SPQE",
})


# ---------------------------------------------------------------------------
# Internal helpers (shared by both adapters)
# ---------------------------------------------------------------------------

def _require_qforte() -> Any:
    try:
        import qforte as qf
        return qf
    except ImportError as exc:
        raise ImportError(
            "qforte is not installed.\n"
            "  pip install qforte\n"
            "  or: https://github.com/evangelistalab/qforte"
        ) from exc


def _build_system(qf: Any, circuit: CircuitSpec) -> Any:
    """Build a QForte molecular system from CircuitSpec.serialized."""
    raw = (circuit.serialized or "").strip()
    if not raw:
        raise ValueError("CircuitSpec.serialized must contain a molecule path or JSON spec.")

    if not raw.startswith("{"):
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"Molecule file not found: {path}")
        return qf.system_factory(
            system_type="molecule",
            build_type="external",
            basis="",
            filename=str(path),
        )

    spec = json.loads(raw)
    build_type = spec.get("build_type", "external")

    if build_type == "external":
        return qf.system_factory(
            system_type="molecule",
            build_type="external",
            basis=spec.get("basis", ""),
            filename=spec["filename"],
        )

    if build_type == "psi4":
        geom = [(sym, tuple(xyz)) for sym, xyz in spec["mol_geometry"]]
        return qf.system_factory(
            system_type="molecule",
            build_type="psi4",
            basis=spec.get("basis", "sto-6g"),
            mol_geometry=geom,
            multiplicity=spec.get("multiplicity", 1),
            charge=spec.get("charge", 0),
            symmetry=spec.get("symmetry", "c1"),
            run_fci=spec.get("run_fci", 1),
            num_frozen_docc=spec.get("num_frozen_docc", 0),
            num_frozen_uocc=spec.get("num_frozen_uocc", 0),
        )

    raise ValueError(f"Unknown build_type: {build_type!r}")


def _build_qforte_config(
    alg_spec: AlgorithmSpec,
    adapt_vqe_config: AdaptVQEConfig | None,
) -> QForteAlgorithmConfig:
    """Compose the package-agnostic AdaptVQEConfig with QForte-only extras.

    QForte-only knobs (diis_max_dim, use_cumulative_thresh, add_equiv_ops,
    qubit_excitations, compact_excitations, opt_ftol, noise_factor) are
    passed via AlgorithmSpec.extra_params — the escape hatch documented on
    AlgorithmSpec for adapter-specific kwargs.
    """
    base = adapt_vqe_config or AdaptVQEConfig()
    extras = {
        k: v for k, v in alg_spec.extra_params.items()
        if k in QForteAlgorithmConfig.model_fields and k != "base"
    }
    return QForteAlgorithmConfig(base=base, **extras)


def _make_algorithm(
    qf: Any,
    mol: Any,
    alg_name: str,
    qforte_config: QForteAlgorithmConfig,
    cls_override: Any = None,
) -> Any:
    """Instantiate a QForte algorithm (does NOT call run())."""
    name = alg_name.upper()
    if name not in _SUPPORTED_ALGORITHMS:
        raise ValueError(
            f"Unsupported algorithm {alg_name!r}. "
            f"Supported: {sorted(_SUPPORTED_ALGORITHMS)}"
        )
    cls = cls_override if cls_override is not None else getattr(qf, name)
    kwargs: dict[str, Any] = {}
    if qforte_config.compact_excitations:
        kwargs["compact_excitations"] = True
    if qforte_config.qubit_excitations:
        kwargs["qubit_excitations"] = True
    if qforte_config.diis_max_dim > 0:
        kwargs["diis_max_dim"] = qforte_config.diis_max_dim
    return cls(mol, print_summary_file=False, **kwargs)


def _execute_algorithm(alg: Any, alg_name: str, qforte_config: QForteAlgorithmConfig) -> None:
    """Call alg.run() with parameters translated from qforte_config."""
    alg.run(**qforte_config.to_run_kwargs(alg_name))


# ---------------------------------------------------------------------------
# QForteAlgorithmAdapter — uses QForte's internal simulator end-to-end
# ---------------------------------------------------------------------------

class QForteAlgorithmAdapter:
    """Implements qpubench's AlgorithmAdapter protocol for QForte.

    Energy evaluation: QForte's own C++ statevector (exact, no shots).

    Usage
    -----
        from qpubench import BenchmarkRunner, NDJSONStore
        from qpubench_qforte import QForteAlgorithmAdapter
        from qpubench_qforte.converters import molecule_spec_from_file

        runner = BenchmarkRunner(store=NDJSONStore("results.ndjson"))
        runner.register(QForteAlgorithmAdapter(), name="qforte")
        mol = molecule_spec_from_file("He-ccpvdz.json")
        record = runner.run(mol, "qforte", options)
    """

    def __init__(self, default_algorithm: str = "UCCNVQE") -> None:
        self._default = default_algorithm

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(
            name="qforte_statevector",
            provider="qforte",
            simulator=True,
            computing_model=ComputingModel.GATE_BASED,
        )

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if circuit.format != CircuitFormat.MOLECULE_JSON:
            warnings.append(
                f"QForteAlgorithmAdapter expects format=MOLECULE_JSON; "
                f"got {circuit.format.value!r}"
            )
        if not circuit.serialized:
            warnings.append("CircuitSpec.serialized is empty.")
        return warnings

    def run_algorithm(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[QuantumResult, VQAConfig]:
        qf            = _require_qforte()
        alg_spec      = options.algorithm_spec or AlgorithmSpec(
            name=self._default, family=AlgorithmFamily.ADAPT_VQE
        )
        qforte_config = _build_qforte_config(alg_spec, options.adapt_vqe_config)
        mol           = _build_system(qf, circuit)
        alg           = _make_algorithm(qf, mol, alg_spec.name, qforte_config)
        _execute_algorithm(alg, alg_spec.name, qforte_config)
        result        = extract_quantum_result(alg, alg_spec)
        vqa           = extract_vqa_config(alg, mol, alg_spec, qforte_config)
        return result, vqa


# ---------------------------------------------------------------------------
# ExternalEvalAlgorithmAdapter — QForte ansatz + qpubench backend energy eval
# ---------------------------------------------------------------------------

class ExternalEvalAlgorithmAdapter:
    """QForte adapter that forwards every energy evaluation to a qpubench backend.

    QForte selects operators, grows the ansatz, and drives scipy.minimize.
    The qpubench backend evaluates ⟨H⟩ for each parameter trial.

    This enables ADAPT-VQE (or UCCNVQE) to run on:
      - Aer statevector simulator    (exact, fastest for comparison)
      - Qrack GPU simulator          (GPU-accelerated, higher qubit counts)
      - IBM Quantum hardware          (real device noise)
      - Any other BackendAdapter     (MBQC, custom simulators, …)

    Parameters
    ----------
    energy_backend:
        A qpubench BackendAdapter used for energy evaluation.
    energy_options:
        ExecutionOptions forwarded to energy_backend.run().
        Use shots=None for statevector (exact), integer shots for sampling.
    default_algorithm:
        Algorithm used when ExecutionOptions.algorithm_spec is None.
    """

    def __init__(
        self,
        energy_backend: Any,
        energy_options: ExecutionOptions | None = None,
        default_algorithm: str = "ADAPTVQE",
    ) -> None:
        self._energy_backend  = energy_backend
        self._energy_options  = energy_options or ExecutionOptions()
        self._default         = default_algorithm

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(
            name=f"qforte+{self._energy_backend.spec.name}",
            provider="qforte_hybrid",
            simulator=self._energy_backend.spec.simulator,
            computing_model=ComputingModel.GATE_BASED,
        )

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        warns: list[str] = []
        if circuit.format != CircuitFormat.MOLECULE_JSON:
            warns.append(
                f"ExternalEvalAlgorithmAdapter expects MOLECULE_JSON; "
                f"got {circuit.format.value!r}"
            )
        if not circuit.serialized:
            warns.append("CircuitSpec.serialized is empty.")
        return warns

    def run_algorithm(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[QuantumResult, VQAConfig]:
        from .energy_hook import EnergyEvaluatorHook, make_hooked_class

        qf            = _require_qforte()
        alg_spec      = options.algorithm_spec or AlgorithmSpec(
            name=self._default, family=AlgorithmFamily.ADAPT_VQE
        )
        qforte_config = _build_qforte_config(alg_spec, options.adapt_vqe_config)
        mol           = _build_system(qf, circuit)

        # Probe the base algorithm for system metadata (no run)
        base_cls  = getattr(qf, alg_spec.name.upper())
        probe     = base_cls(mol, print_summary_file=False)
        n_qubits  = int(probe._nqb)
        ref       = list(getattr(probe, "_ref", []))
        hamiltonian = qforte_op_to_sparse_pauli(probe._qb_ham, n_qubits)
        del probe

        # Wire up the hook
        hook = EnergyEvaluatorHook(
            backend=self._energy_backend,
            hamiltonian=hamiltonian,
            n_qubits=n_qubits,
            ref=ref,
            options=self._energy_options,
        )

        # Build the hooked algorithm and run it
        HookedCls = make_hooked_class(base_cls, hook)
        alg       = _make_algorithm(qf, mol, alg_spec.name, qforte_config, cls_override=HookedCls)
        _execute_algorithm(alg, alg_spec.name, qforte_config)

        result = extract_quantum_result(alg, alg_spec)
        vqa    = extract_vqa_config(alg, mol, alg_spec, qforte_config)

        # Annotate result with hook telemetry
        result = result.model_copy(update={
            "metadata": {
                **result.metadata,
                "energy_backend":  self._energy_backend.spec.name,
                "hook_call_count": hook.call_count,
            }
        })
        return result, vqa
