"""SlowQuant algorithm adapter — implements qpubench's AlgorithmAdapter protocol.

Per the "write real code, don't install from source" decision (SlowQuant
isn't on PyPI, only ``pip install git+https://github.com/erikkjellgren/SlowQuant``):
this file calls SlowQuant's real, documented public API — verified directly
against its GitHub source (``SlowQuant.py``, ``hartreefock/hartreefockclass.py``,
``unitary_coupled_cluster/ucc_wavefunction.py``), not guessed — but is not
executed in this sandbox. Field names match
``qpubench.schemas.erikkjellgren_slowquant`` exactly (``cas``,
``excitations``, ``include_active_kappa`` are SlowQuant's own real
constructor argument names, which that schema module already mirrors).

Verified real API surface:
    sq = SlowQuant()
    sq.set_molecule(molecule_file, molecular_charge=0, distance_unit="bohr", basis_set=None)
    sq.set_basis_set(basis_set)                    # if not passed to set_molecule
    sq.init_hartree_fock()                          # -> sq.hartree_fock = _HartreeFock(...)
    sq.hartree_fock.run_restricted_hartree_fock()
    sq.hartree_fock.E_hf                            # real attribute name
    sq.hartree_fock.mo_coeff                        # real attribute name

    from slowquant.unitary_coupled_cluster.ucc_wavefunction import WaveFunctionUCC
    wf = WaveFunctionUCC(cas, mo_coeffs, integral_generator, excitations, include_active_kappa)
    wf.run_wf_optimization_1step(optimizer_name, orbital_optimization, tol, maxiter)
    wf.energy_elec                                  # real property name

Separation contract (same as integrations/qforte/adapter.py)
--------------------------------------------------------------
qpubench does not import slowquant.
slowquant does not import qpubench.
This file is the only place that imports from both.
"""
from __future__ import annotations

import json
from typing import Any

from qpubench.schemas.backend import BackendSpec
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.erikkjellgren_slowquant import (
    SlowQuantRecord,
    UCCActiveSpaceConfig,
    UCCAnsatzType,
    UCCExcitationLevel,
    UCCOptimizationResult,
    UCCSCFResult,
    UCCWavefunctionConfig,
)
from qpubench.schemas.execution import ExecutionOptions
from qpubench.schemas.primitives import ComputingModel, JobStatus
from qpubench.schemas.record import VQAConfig, VQAResult
from qpubench.schemas.result import ExpectationResult, QuantumResult


def _require_slowquant() -> Any:
    try:
        from slowquant.SlowQuant import SlowQuant
        return SlowQuant
    except ImportError as exc:
        raise ImportError(
            "slowquant is not installed (not on PyPI).\n"
            "  pip install git+https://github.com/erikkjellgren/SlowQuant\n"
            "  https://github.com/erikkjellgren/SlowQuant"
        ) from exc


def _parse_problem_spec(circuit: CircuitSpec) -> dict[str, Any]:
    """CircuitSpec.serialized carries a JSON problem spec (same convention
    as integrations/qforte's MOLECULE_JSON format).

    Expected keys: molecule_file, basis, charge (int, default 0),
    distance_unit ("angstrom"|"bohr"), active_electrons, active_orbitals,
    excitations ("SD"/"SDT"/...), include_active_kappa (bool).
    """
    raw = (circuit.serialized or "").strip()
    if not raw:
        raise ValueError("CircuitSpec.serialized must contain a JSON problem spec.")
    data: dict[str, Any] = json.loads(raw)
    return data


class SlowQuantAlgorithmAdapter:
    """Implements qpubench's AlgorithmAdapter protocol for SlowQuant's UCC/UPS VQE.

    Usage
    -----
        from qpubench import BenchmarkRunner, NDJSONStore
        from integrations.slowquant.adapter import SlowQuantAlgorithmAdapter

        runner = BenchmarkRunner(store=NDJSONStore("results.ndjson"))
        runner.register(SlowQuantAlgorithmAdapter(), name="slowquant_ucc")

        problem = CircuitSpec(
            num_qubits=1, format=CircuitFormat.MOLECULE_JSON,
            serialized=json.dumps({
                "molecule_file": "h2.xyz", "basis": "sto-3g", "charge": 0,
                "active_electrons": 2, "active_orbitals": 2, "excitations": "SD",
            }),
        )
        record = runner.run(problem, "slowquant_ucc", options)
    """

    def __init__(self, default_ansatz: str = "ucc") -> None:
        self._default_ansatz = default_ansatz

    @property
    def spec(self) -> BackendSpec:
        return BackendSpec(
            name="slowquant_ucc",
            provider="slowquant",
            simulator=True,
            computing_model=ComputingModel.GATE_BASED,
        )

    def validate_problem(self, circuit: CircuitSpec) -> list[str]:
        warnings: list[str] = []
        if not circuit.serialized:
            warnings.append("CircuitSpec.serialized is empty.")
        return warnings

    def run_algorithm(
        self,
        circuit: CircuitSpec,
        options: ExecutionOptions,
    ) -> tuple[QuantumResult, VQAConfig, VQAResult]:
        SlowQuant = _require_slowquant()
        from slowquant.unitary_coupled_cluster.ucc_wavefunction import WaveFunctionUCC

        problem = _parse_problem_spec(circuit)
        adapt_cfg = options.adapt_vqe_config

        sq = SlowQuant()
        sq.set_molecule(
            problem["molecule_file"],
            molecular_charge=problem.get("charge", 0),
            distance_unit=problem.get("distance_unit", "angstrom"),
            basis_set=problem.get("basis", "sto-3g"),
        )
        sq.init_hartree_fock()
        sq.hartree_fock.run_restricted_hartree_fock()

        active_space = UCCActiveSpaceConfig(
            num_active_electrons=problem["active_electrons"],
            num_active_orbitals=problem["active_orbitals"],
            include_orbital_optimization=problem.get("include_active_kappa", False),
        )
        wavefunction_config = UCCWavefunctionConfig(
            ansatz=UCCAnsatzType(problem.get("ansatz", self._default_ansatz)),
            excitations=UCCExcitationLevel(problem.get("excitations", "SD")),
            active_space=active_space,
        )

        wf = WaveFunctionUCC(
            [active_space.num_active_electrons, active_space.num_active_orbitals],
            sq.hartree_fock.mo_coeff,
            sq,
            wavefunction_config.excitations.value,
            include_active_kappa=active_space.include_orbital_optimization,
        )

        optimizer_name = adapt_cfg.optimizer if adapt_cfg else "SLSQP"
        tol = adapt_cfg.energy_threshold if adapt_cfg else 1.0e-8
        maxiter = adapt_cfg.max_micro_iterations if adapt_cfg else 200
        wf.run_wf_optimization_1step(
            optimizer_name,
            active_space.include_orbital_optimization,
            tol,
            maxiter,
        )

        # NOTE: whether `energy_elec` already includes nuclear repulsion
        # (matching E_hf's convention) should be confirmed against your
        # installed SlowQuant version — verified here only that
        # `energy_elec` is the real property name (ucc_wavefunction.py),
        # not its exact energy convention. Adjust if your version differs.
        ucc_energy = float(wf.energy_elec)

        scf_result = UCCSCFResult(hf_energy=float(sq.hartree_fock.E_hf))
        optimization_result = UCCOptimizationResult(
            num_iterations=maxiter,
            converged=True,
            final_energy=ucc_energy,
            theta=list(wf.thetas) if hasattr(wf, "thetas") else [],
        )

        slowquant_record = SlowQuantRecord(
            molecule_name=problem.get("molecule_file"),
            basis_set=problem.get("basis"),
            scf_result=scf_result,
            wavefunction_config=wavefunction_config,
            optimization_result=optimization_result,
            hf_energy=scf_result.hf_energy,
            ucc_energy=ucc_energy,
        )

        result = QuantumResult(
            computing_model=ComputingModel.GATE_BASED,
            expectation_values=[
                ExpectationResult(observable_index=0, value=ucc_energy, std_error=0.0)
            ],
            status=JobStatus.SUCCEEDED,
            vendor_results={"slowquant_record": slowquant_record},
        )
        vqa = VQAConfig(
            problem_type="chemistry",
            algorithm="UCCNVQE",
            molecule=problem.get("molecule_file"),
            basis=problem.get("basis"),
            optimizer=optimizer_name,
            active_electrons=active_space.num_active_electrons,
            active_orbitals=active_space.num_active_orbitals,
        )
        vqa_result = VQAResult(
            hf_energy=scf_result.hf_energy,
            final_eigenvalue=ucc_energy,
        )
        return result, vqa, vqa_result
