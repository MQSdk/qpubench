"""qrunch guide: "Choose a Contraction Path Finder"

Verdict: Yes — real. Checked qrunch's own guide page directly
(qrunch.docs.kvantify.net/docs/guides/components/
choose_contraction_path_finder.html): four strategies (Sequential, Random
Greedy x128, Multi-Strategy, None) for picking how a tensor network
contracts — all real via `quimb` + `cotengra` (per direct instruction to
build this on quimb/cotengra, not bare `opt_einsum`).

Mechanism: `qpubench.tensor_network.contraction_path.
choose_contraction_path()` builds a real `quimb.tensor.Circuit` from a
CircuitSpec and costs each strategy via real `opt_einsum.contract.
PathInfo` stats (`opt_cost`, `largest_intermediate`) — `SEQUENTIAL` maps to
quimb/opt_einsum's own `"auto"`; `RANDOM_GREEDY_128`/`MULTI_STRATEGY` map
to real `cotengra.HyperOptimizer` instances; `NONE` bypasses path
pre-optimization entirely (`opt_einsum.contract_path(..., optimize=False)`
directly — quimb's own `contraction_info(optimize=False)` has a real bug,
worked around here, see `tensor_network/contraction_path.py`).

Requires: pip install 'qpubench[tensor_network]'

Run:
    python examples/guides/choose_contraction_path_finder.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.contraction_path import ContractionPathConfig, ContractionPathStrategy
from qpubench.schemas.primitives import CircuitFormat

_GHZ4_QASM2 = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[4];
h q[0];
cx q[0],q[1];
cx q[1],q[2];
cx q[2],q[3];
"""


def main() -> None:
    try:
        from qpubench.tensor_network import choose_contraction_path
    except ImportError:
        print("quimb/cotengra not installed — run: pip install 'qpubench[tensor_network]'")
        return

    circuit = CircuitSpec(num_qubits=4, format=CircuitFormat.QASM2, serialized=_GHZ4_QASM2)

    print("4-qubit GHZ circuit — real contraction-path cost per strategy:\n")
    for strategy in ContractionPathStrategy:
        config = ContractionPathConfig(strategy=strategy, num_repeats=16)
        result = choose_contraction_path(circuit, config)
        print(f"  {strategy.value:20s} opt_cost={result.opt_cost:8.1f}  "
              f"largest_intermediate={result.largest_intermediate:6.1f}")

    print("\nNONE (no path pre-optimization) is expected to be the most "
          "expensive — confirms path optimization is doing real work, not "
          "a no-op.")


if __name__ == "__main__":
    main()
