"""Real tensor-network contraction path selection — quimb + cotengra.

Install: pip install 'qpubench[tensor_network]'

Contraction-path selection for tensor-network simulation. Real, verified
pipeline: `quimb.tensor.Circuit.from_openqasm2_str()` builds a real tensor
network from a circuit's QASM2 text; `.amplitude(bitstring, optimize=...)`
and `.psi.contraction_info(optimize=...)` execute/cost a chosen
contraction path. `optimize=` accepts either a string strategy name
(quimb/opt_einsum's own `"auto"`, `"greedy"`, `False`) or a real
`cotengra.HyperOptimizer` instance for randomized/multi-method search —
confirmed by running all four strategies below on a real Bell circuit.

quimb has no QASM3 loader (only QASM2 — confirmed by inspecting its
`Circuit` class) — QASM3 `CircuitSpec`s are bridged via
`qiskit.qasm2.dumps(load_qiskit_circuit(circuit))`, reusing
`backends/_qiskit_common.py`'s existing QASM2/3 loader and Qiskit's own
QASM2 exporter (both already real dependencies elsewhere in this repo).
"""
from __future__ import annotations

from typing import Any

from ..schemas.circuit import CircuitSpec
from ..schemas.catalogs.contraction_path import (
    ContractionPathConfig,
    ContractionPathResult,
    ContractionPathStrategy,
)
from ..schemas.primitives import CircuitFormat


def build_quimb_circuit(circuit: CircuitSpec) -> Any:
    """Build a real `quimb.tensor.Circuit` from a QASM2/3 CircuitSpec."""
    import quimb.tensor as qtn

    if circuit.format == CircuitFormat.QASM2:
        return qtn.Circuit.from_openqasm2_str(circuit.serialized or "")
    if circuit.format == CircuitFormat.QASM3:
        from qiskit import qasm2

        from ..backends._qiskit_common import load_qiskit_circuit

        qc = load_qiskit_circuit(circuit)
        return qtn.Circuit.from_openqasm2_str(qasm2.dumps(qc))
    raise ValueError(
        f"build_quimb_circuit needs QASM2/QASM3; got {circuit.format}"
    )


def _resolve_optimize(config: ContractionPathConfig) -> Any:
    """Map the non-NONE strategies onto real quimb/cotengra `optimize=`
    values (NONE is handled separately in choose_contraction_path — see
    there for why)."""
    if config.strategy == ContractionPathStrategy.SEQUENTIAL:
        return "auto"   # quimb/opt_einsum's own tiered greedy -> fuller search

    import cotengra as ctg

    if config.strategy == ContractionPathStrategy.RANDOM_GREEDY_128:
        return ctg.HyperOptimizer(
            methods=["greedy"], max_repeats=config.num_repeats, progbar=False,
        )
    if config.strategy == ContractionPathStrategy.MULTI_STRATEGY:
        target_size = int(config.max_memory_fraction * config.memory_budget_elements)
        return ctg.HyperOptimizer(
            methods=["greedy"],
            minimize="combo",
            max_repeats=config.num_repeats,
            slicing_opts={"target_size": target_size},
            progbar=False,
        )
    raise ValueError(f"Unknown strategy: {config.strategy}")


def choose_contraction_path(
    circuit: CircuitSpec,
    config: ContractionPathConfig | None = None,
) -> ContractionPathResult:
    """Choose and cost a real contraction path for `circuit`.

    Returns real `opt_cost`/`largest_intermediate` from
    `opt_einsum.contract.PathInfo` — not fabricated.
    """
    config = config or ContractionPathConfig()
    quimb_circuit = build_quimb_circuit(circuit)
    tn = quimb_circuit.psi

    if config.strategy == ContractionPathStrategy.NONE:
        # quimb's own contraction_info() wrapper rejects optimize=False
        # (confirmed: raises "'bool' object is not callable" — cotengra's
        # dispatch treats any non-None/non-string value as a custom
        # path-finder callable). Bypass it and call opt_einsum directly —
        # the real "delegate to the contraction engine itself" case, i.e.
        # no path pre-optimization at all.
        import opt_einsum as oe

        equation = tn.get_equation()
        shapes = [t.shape for t in tn]
        _, info = oe.contract_path(equation, *shapes, shapes=True, optimize=False)
    else:
        optimize = _resolve_optimize(config)
        info = tn.contraction_info(optimize=optimize)

    return ContractionPathResult(
        strategy_used=config.strategy,
        opt_cost=float(info.opt_cost),
        largest_intermediate=float(info.largest_intermediate),
    )


__all__ = [
    "build_quimb_circuit",
    "choose_contraction_path",
]
