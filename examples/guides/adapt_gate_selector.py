"""qrunch guide: "Create an ADAPT Gate Selector"

Verdict: Yes — real, runnable qpubench mechanism.
Mechanism: integrations/generic_adapt_vqe/pool.py's
generate_singles_doubles_pool() / single_excitation_observable() /
double_excitation_observable() — a genuine fermionic-singles-and-doubles
ADAPT operator pool, Jordan-Wigner mapped, independently verified against
dense-matrix ground truth in tests/test_generic_adapt_vqe.py.

Run:
    python examples/guides/adapt_gate_selector.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from integrations.generic_adapt_vqe.pool import (
    double_excitation_observable,
    generate_singles_doubles_pool,
    single_excitation_observable,
)


def main() -> None:
    num_qubits, num_electrons = 4, 2
    pool = generate_singles_doubles_pool(num_qubits, num_electrons)

    print(f"Occupied qubits (electrons): {list(range(num_electrons))}")
    print(f"Virtual qubits:              {list(range(num_electrons, num_qubits))}")
    print(f"\nGenerated pool ({len(pool)} operators):")
    for op in pool:
        print(f"  {op.label:16s} indices={op.indices}  {len(op.observable.terms)} Pauli terms")

    # Build one operator directly to show what's inside a pool entry.
    single = single_excitation_observable(p=2, q=0, num_qubits=num_qubits)
    print("\nsingle_excitation_observable(p=2, q=0):")
    for term in single.terms:
        print(f"  {term.pauli_ops} on qubits {term.qubit_indices}, "
              f"coeff={term.coefficient.re}+{term.coefficient.im}j")

    double = double_excitation_observable(p=3, q=2, r=1, s=0, num_qubits=num_qubits)
    print(f"\ndouble_excitation_observable(p=3, q=2, r=1, s=0): "
          f"{len(double.terms)} Pauli terms")


if __name__ == "__main__":
    main()
