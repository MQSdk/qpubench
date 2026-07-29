"""QForte (evangelistalab/qforte) data schemas.

QForte (github.com/evangelistalab/qforte) is a pybind11 hybrid package —
performance-critical state-vector simulation and operator algebra in C++,
orchestration (ADAPT-VQE, UCCN-VQE, UCCN-PQE, SPQE, quantum Krylov methods)
in Python. Two layers are modeled here, verified against the real source:

pybind11 object layer (src/qforte/bindings.cc)
-----------------------------------------------
Mirrors the C++ classes exposed to Python 1:1 — QForteGateSpec, QForte
CircuitSpec, QForteQubitOperatorSpec, QForteQubitOpPoolSpec — the same
bit-exact-mirroring spirit as johnrscott_mbqc_fpga.py's FPGA word layout,
just for a pybind11 boundary instead of a VHDL one.

Algorithm layer (src/qforte/abc/algorithm.py, abc/ansatz.py, ucc/adaptvqe.py)
-------------------------------------------------------------------------
QForteAlgorithmConfig wraps the package-agnostic AdaptVQERunConfig
(execution.py) plus QForte-only knobs; QForteRunResult captures the real
Algorithm / AnsatzAlgorithm / ADAPTVQE instance attributes (verified against
upstream source — many of these were previously read via bare getattr() in
integrations/qforte/converters.py with no typed contract and several
attributes silently dropped, e.g. _tops, _tamps, _commutator_pool).

Schema version: 2.1.0
"""

from __future__ import annotations

import pydantic

from ..execution import AdaptVQERunConfig
from ..observable import PauliTerm, SparsePauliObservable
from ..primitives import ComplexNumber, PauliLabel

# ---------------------------------------------------------------------------
# pybind11 object layer — mirrors src/qforte/bindings.cc
# ---------------------------------------------------------------------------


class QForteGateSpec(pydantic.BaseModel):
    """Mirrors the pybind11-exposed Gate class (src/qforte/gate.cc).

    gate_id     gate type identifier, e.g. "X", "Y", "Z", "H", "Rz", "CNOT".
    target      target qubit index.
    control     control qubit index; None for single-qubit gates.
    parameter   rotation angle for parametrized gates (has_parameter() gates).
    """

    gate_id: str
    target: int
    control: int | None = None
    parameter: float | None = None


class QForteCircuitSpec(pydantic.BaseModel):
    """Mirrors the pybind11-exposed Circuit class (src/qforte/circuit.cc).

    An ordered list of QForteGateSpec — Circuit.gates() in pybind11.
    is_pauli / num_cnots mirror Circuit.is_pauli() / Circuit.get_num_cnots().
    """

    gates: list[QForteGateSpec] = []
    is_pauli: bool = False
    num_cnots: int | None = None

    @property
    def size(self) -> int:
        """Mirrors Circuit.size()."""
        return len(self.gates)


class QForteQubitOperatorTerm(pydantic.BaseModel):
    """One (coefficient, Pauli circuit) pair from QubitOperator.terms().

    QForte stores a qubit Hamiltonian / operator as a list of these pairs;
    each pauli_circuit is a Circuit whose gates are single-qubit X/Y/Z
    Paulis (Circuit.is_pauli() == True).
    """

    coefficient: ComplexNumber
    pauli_circuit: QForteCircuitSpec


class QForteQubitOperatorSpec(pydantic.BaseModel):
    """Mirrors the pybind11-exposed QubitOperator class (qubit_operator.cc).

    num_qubits is not itself a QForte field (QubitOperator.num_qubits() is
    derived from the widest gate target across all terms) but is carried
    here so to_sparse_pauli_observable() doesn't need a second argument.
    """

    terms: list[QForteQubitOperatorTerm] = []
    num_qubits: int

    def to_sparse_pauli_observable(self) -> SparsePauliObservable:
        """Convert to qpubench's canonical cross-package Pauli representation.

        Replaces the old ad hoc qforte_op_to_sparse_pauli() free function —
        terms whose pauli_circuit contains a non-Pauli gate are skipped,
        matching the previous best-effort behaviour.
        """
        _GATE_TO_PAULI = {"X": PauliLabel.X, "Y": PauliLabel.Y, "Z": PauliLabel.Z}
        observable_terms: list[PauliTerm] = []
        for term in self.terms:
            qubit_indices: list[int] = []
            pauli_ops: list[PauliLabel] = []
            for gate in term.pauli_circuit.gates:
                label = _GATE_TO_PAULI.get(gate.gate_id)
                if label is not None:
                    qubit_indices.append(gate.target)
                    pauli_ops.append(label)
            if qubit_indices:
                observable_terms.append(
                    PauliTerm(
                        qubit_indices=tuple(qubit_indices),
                        pauli_ops=tuple(pauli_ops),
                        coefficient=term.coefficient,
                    )
                )
        return SparsePauliObservable(num_qubits=self.num_qubits, terms=observable_terms)


class QForteQubitOpPoolSpec(pydantic.BaseModel):
    """Mirrors the pybind11-exposed QubitOpPool class (qubit_op_pool.cc).

    A pool of QubitOperator terms grown by ADAPT-VQE / measured for the
    gradient screen. coeffs mirrors QubitOpPool.set_coeffs()/set_op_coeffs().
    """

    operators: list[QForteQubitOperatorSpec] = []
    coeffs: list[float] = []


class QForteSqOpPoolSpec(pydantic.BaseModel):
    """Mirrors the pybind11-exposed SQOpPool class (sq_op_pool.cc).

    Second-quantized (fermionic, pre-Jordan-Wigner) operator pool — the
    representation SQOpPool.get_qubit_op_pool() converts into a
    QForteQubitOpPoolSpec. Stored as opaque term strings (SQOperator.str())
    since the fermionic term algebra itself is not re-implemented here.
    """

    term_strings: list[str] = []
    coeffs: list[float] = []


# ---------------------------------------------------------------------------
# Algorithm layer — mirrors abc/algorithm.py, abc/ansatz.py, ucc/adaptvqe.py
# ---------------------------------------------------------------------------


class QForteAlgorithmConfig(pydantic.BaseModel):
    """Full QForte algorithm.run() configuration.

    Wraps the package-agnostic AdaptVQERunConfig (base) plus QForte-only knobs
    that have no equivalent in other ADAPT-VQE implementations. Field names
    on `base` map onto QForte's run() kwargs as documented on AdaptVQERunConfig;
    the extras below map onto AnsatzAlgorithm / ADAPTVQE constructor and
    run() kwargs directly (verified against upstream source).

    use_cumulative_thresh  ADAPTVQE.run(): compare cumulative vs per-step
                            gradient norm against gradient_threshold
    add_equiv_ops           ADAPTVQE.run(): add symmetry-equivalent operators
                            together each macro-iteration
    qubit_excitations       AnsatzAlgorithm.__init__: use qubit (not
                            fermionic) excitation operators in the pool
    compact_excitations     AnsatzAlgorithm.__init__: compact multi-qubit
                            Pauli-string exponential circuit synthesis
    diis_max_dim             AnsatzAlgorithm.__init__: DIIS acceleration
                            dimension; 0/omitted disables it
    opt_ftol                 UCCNVQE-only: optimizer function-value tolerance
    noise_factor              UCCNVQE-only: artificial shot-noise injection
    """

    base: AdaptVQERunConfig = pydantic.Field(default_factory=AdaptVQERunConfig)
    use_cumulative_thresh: bool = False
    add_equiv_ops: bool = False
    qubit_excitations: bool = False
    compact_excitations: bool = False
    diis_max_dim: int = 0
    opt_ftol: float | None = None
    noise_factor: float | None = None

    def to_run_kwargs(self, algorithm_name: str) -> dict[str, object]:
        """Translate to the kwargs QForte's <Algorithm>.run() expects.

        algorithm_name  upper-cased QForte class name, e.g. "ADAPTVQE".
        """
        kwargs: dict[str, object] = dict(
            pool_type=self.base.pool_type,
            optimizer=self.base.optimizer,
            use_analytic_grad=self.base.use_analytic_gradient,
            opt_thresh=self.base.energy_threshold,
            opt_maxiter=self.base.max_micro_iterations,
        )
        name = algorithm_name.upper()
        if name == "ADAPTVQE":
            kwargs["avqe_thresh"] = self.base.gradient_threshold
            kwargs["adapt_maxiter"] = self.base.max_macro_iterations
            kwargs["use_cumulative_thresh"] = self.use_cumulative_thresh
            kwargs["add_equiv_ops"] = self.add_equiv_ops
        elif name == "UCCNVQE":
            if self.opt_ftol is not None:
                kwargs["opt_ftol"] = self.opt_ftol
            if self.noise_factor is not None:
                kwargs["noise_factor"] = self.noise_factor
        return kwargs


class QForteRunResult(pydantic.BaseModel):
    """Post-run state of a completed QForte Algorithm/AnsatzAlgorithm object.

    Field ↔ real attribute mapping (verified against upstream source —
    abc/algorithm.py, abc/ansatz.py, ucc/adaptvqe.py):

      final_energy              alg.get_gs_energy()  (== alg._Egs)
      hf_energy                 alg._hf_energy
      n_qubits                  alg._nqb
      converged                 alg._converged        (ADAPTVQE only)
      final_gradient_norm       alg._curr_grad_norm    (ADAPTVQE only)
      selected_operators        alg._tops               (AnsatzAlgorithm)
      amplitudes                alg._tamps               (AnsatzAlgorithm)
      n_cnot                    alg._n_cnot
      n_classical_params        alg._n_classical_params
      n_pauli_trm_measures      alg._n_pauli_trm_measures
      n_ham_measurements        alg._n_ham_measurements  (ADAPTVQE only)
      n_commut_measurements     alg._n_commut_measurements (ADAPTVQE only)
      energies_history          alg._energies             (ADAPTVQE only)
      grad_norms_history        alg._grad_norms           (ADAPTVQE only)
      n_cnot_history            alg._n_cnot_lst           (ADAPTVQE only)
      n_classical_params_history alg._n_classical_params_lst (ADAPTVQE only)
      n_pauli_trm_measures_history alg._n_pauli_trm_measures_lst (ADAPTVQE only)
      max_circuit_depth_repr    str(alg._Umaxdepth) if set, else None

    Previously these were scraped ad hoc via getattr() in
    integrations/qforte/converters.py with no typed contract; several
    real attributes (_tops, _tamps, _commutator_pool, _n_ham_measurements,
    _n_commut_measurements, _curr_grad_norm) were silently dropped.
    """

    final_energy: float
    hf_energy: float | None = None
    n_qubits: int | None = None
    converged: bool = True
    final_gradient_norm: float | None = None
    selected_operators: list[int] = []
    amplitudes: list[float] = []
    n_cnot: int = 0
    n_classical_params: int = 0
    n_pauli_trm_measures: int = 0
    n_ham_measurements: int | None = None
    n_commut_measurements: int | None = None
    energies_history: list[float] = []
    grad_norms_history: list[float] = []
    n_cnot_history: list[int] = []
    n_classical_params_history: list[int] = []
    n_pauli_trm_measures_history: list[int] = []
    max_circuit_depth_repr: str | None = None
