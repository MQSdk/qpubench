"""Guide: choose a minimizer and a stopping criterion.

``qpubench.schemas.catalogs.optimizer_catalog`` provides ``MINIMIZER_CATALOG`` /
``STOPPING_CRITERION_CATALOG``: a catalogue/registry object to "choose"
from, so ``AdaptVQERunConfig.optimizer`` isn't just free text. The catalogue
is a lookup table over the same
AdaptVQERunConfig fields generic_adapt_vqe already consumes — not a new
execution mechanism — so this example now iterates the catalogue entries
instead of a hardcoded list of names.

Requires: pip install 'qpubench[adapt_vqe]'

Run:
    python examples/guides/minimizer_and_stopping_criterion.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.execution import AdaptVQERunConfig
from qpubench.schemas.catalogs.optimizer_catalog import MINIMIZER_CATALOG, STOPPING_CRITERION_CATALOG

from examples.common.toy_hamiltonians import (
    NUM_ELECTRONS,
    NUM_QUBITS,
    exact_ground_state_energy,
    toy_hamiltonian,
)
from examples.common.toy_statevector_backend import ToyStatevectorAdapter
from integrations.generic_adapt_vqe.engine import GenericAdaptVQEEngine


def run_with(optimizer: str, gradient_threshold: float) -> tuple[float, int]:
    hamiltonian = toy_hamiltonian()
    engine = GenericAdaptVQEEngine(
        hamiltonian=hamiltonian,
        num_qubits=NUM_QUBITS,
        num_electrons=NUM_ELECTRONS,
        energy_backend=ToyStatevectorAdapter(),
        config=AdaptVQERunConfig(
            optimizer=optimizer,
            gradient_threshold=gradient_threshold,
            max_macro_iterations=15,
            max_micro_iterations=200,
        ),
    )
    _, _vqa, vqa_result = engine.run()
    return vqa_result.final_eigenvalue, len(vqa_result.convergence_values)


def main() -> None:
    exact = exact_ground_state_energy(toy_hamiltonian())
    print(f"Exact ground state: {exact:.6f}\n")

    print("-- Minimizer catalogue (gradient_threshold fixed at 1e-5) --")
    for entry in MINIMIZER_CATALOG.values():
        energy, n_iters = run_with(entry.scipy_method, gradient_threshold=1e-5)
        print(f"  {entry.name:12s} energy={energy:.6f}  error={abs(energy - exact):.2e}  "
              f"macro_iters={n_iters}  grad={entry.supports_gradient}  "
              f"-- {entry.description}")

    print("\n-- Stopping-criterion catalogue (optimizer fixed at BFGS) --")
    grad_norm = STOPPING_CRITERION_CATALOG["gradient_norm"]
    for threshold in [10.0, 2.0, 1.5, 1.0, 1e-5]:
        energy, n_iters = run_with("BFGS", gradient_threshold=threshold)
        print(f"  {grad_norm.field_name}={threshold:<8g} energy={energy:.6f}  "
              f"error={abs(energy - exact):.2e}  macro_iters={n_iters}")
    print(f"\n  ({grad_norm.name}: {grad_norm.description})")

    print("\nAll catalogued stopping criteria:")
    for entry in STOPPING_CRITERION_CATALOG.values():
        print(f"  {entry.name:20s} -> AdaptVQERunConfig.{entry.field_name:22s} "
              f"[{entry.applies_to}] {entry.description}")


if __name__ == "__main__":
    main()
