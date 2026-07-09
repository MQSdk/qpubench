"""qrunch guides: "Create a FAST Gate Selector" / "Create a Brute Force
Gate Selector"

Verdict: Yes — real. Checked qrunch's own guide pages directly
(qrunch.docs.kvantify.net/docs/guides/components/
create_{fast,brute_force}_gate_selector.html): FAST scores every pool
operator by a cheap heuristic gradient, no re-optimization; Brute Force
evaluates each candidate by temporarily adding it and running a *complete*
optimization, keeping whichever gives the lowest energy — both real,
swappable `GateSelector` strategies (integrations/generic_adapt_vqe/
gate_selector.py) plugged into `GenericAdaptVQEEngine(gate_selector=...)`.

Mechanism: `FastGateSelector` is exactly the engine's original gradient
screen (central finite differences), extracted unchanged.
`BruteForceGateSelector` runs one full `scipy.optimize.minimize` per
remaining pool operator, every macro-iteration — more expensive, exact per
iteration, matching qrunch's own "computationally intensive... provides
exact results... works best with small systems" framing.

Runs both on a real H2 qubit Hamiltonian (STO-3G, 4 qubits) built via
`hamiltonian_sources.ab_initio.build_qubit_hamiltonian` (real PySCF +
OpenFermion, offline, no network dataset download) and compares operator
count / CNOT count / final energy against each other.

Requires: pip install 'qpubench[adapt_vqe,openfermion]'

Run:
    python examples/guides/gate_selector.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def main() -> None:
    try:
        from qpubench.hamiltonian_sources.ab_initio import build_qubit_hamiltonian
    except ImportError:
        print("openfermion/openfermionpyscf/pyscf not installed — "
              "run: pip install 'qpubench[openfermion]'")
        return

    from examples.common.toy_statevector_backend import ToyStatevectorAdapter
    from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine
    from integrations.generic_adapt_vqe.gate_selector import (
        BruteForceGateSelector,
        FastGateSelector,
        GateSelector,
    )
    from qpubench.schemas.execution import AdaptVQEConfig

    h2_geometry = [("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 0.7414))]
    hamiltonian, record = build_qubit_hamiltonian(
        h2_geometry, basis="sto-3g", molecule_name="H2",
    )
    num_qubits = record.num_qubits
    num_electrons = 2
    print(f"H2/STO-3G qubit Hamiltonian: {num_qubits} qubits, "
          f"{len(hamiltonian.terms)} Pauli terms\n")

    config = AdaptVQEConfig(max_macro_iterations=6)

    selectors: list[tuple[str, GateSelector]] = [
        ("FastGateSelector", FastGateSelector()),
        ("BruteForceGateSelector", BruteForceGateSelector()),
    ]
    for name, selector in selectors:
        engine = GenericAdaptVQEEngine(
            hamiltonian=hamiltonian,
            num_qubits=num_qubits,
            num_electrons=num_electrons,
            energy_backend=ToyStatevectorAdapter(),
            config=config,
            gate_selector=selector,
        )
        result, vqa = engine.run()
        energy = result.expectation_values[0].value
        print(f"{name:24s} energy={energy:.8f} Ha  "
              f"n_operators={vqa.num_parameters}  n_cnot={vqa.n_cnot}  "
              f"converged={result.metadata['converged']}")


if __name__ == "__main__":
    main()
