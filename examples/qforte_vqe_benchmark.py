"""QForte VQE benchmark — interfacing qforte with qpubench.

Requires:
    pip install qforte           # C++ extension, needs a compiler
    pip install 'qpubench[dev]'

This example benchmarks three QForte VQE methods on the He atom (cc-pvdz)
using QForte's built-in statevector simulator via the AlgorithmAdapter
protocol.  Results are recorded in qpubench's BenchmarkRecord schema and
stored to an NDJSON file.

The molecule is supplied as a path to a QForte external JSON file that
ships with QForte's test suite.  If you have Psi4 installed, replace
HE_JSON_PATH with an inline psi4 spec (see inline_psi4_spec() below).

Run:
    python examples/qforte_vqe_benchmark.py
"""
from __future__ import annotations

import json
import pathlib
import sys

# ---------------------------------------------------------------------------
# Locate QForte's He test molecule JSON
# ---------------------------------------------------------------------------

def _find_he_json() -> pathlib.Path:
    """Search for He-ccpvdz.json in the QForte package directory."""
    try:
        import qforte
        qforte_root = pathlib.Path(qforte.__file__).parent
    except ImportError:
        print("QForte is not installed.  See: https://github.com/evangelistalab/qforte")
        sys.exit(1)

    candidates = list(qforte_root.rglob("He-ccpvdz.json"))
    if not candidates:
        # Also check relative to wherever qforte was cloned
        candidates = list(pathlib.Path(".").rglob("He-ccpvdz.json"))
    if not candidates:
        raise FileNotFoundError(
            "Could not find He-ccpvdz.json.  "
            "Either install QForte from source (it ships in tests/) or "
            "provide a path manually via HE_JSON_PATH."
        )
    return candidates[0]


def inline_psi4_spec(mol_geometry: list, basis: str = "sto-6g") -> str:
    """Return a CircuitSpec.serialized string for on-the-fly Psi4 builds.

    Use this instead of a JSON file path if Psi4 is installed:
        circuit = CircuitSpec(
            ...,
            serialized=inline_psi4_spec([("H", (0,0,0)), ("H", (0,0,0.735))]),
        )
    """
    return json.dumps({
        "build_type":   "psi4",
        "mol_geometry": mol_geometry,
        "basis":        basis,
        "run_fci":      1,
    })


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

from qpubench import (
    AdaptVQERunConfig,
    AlgorithmFamily,
    AlgorithmSpec,
    BenchmarkRecord,
    BenchmarkRunner,
    ExecutionOptions,
    NDJSONStore,
)
from qpubench.schemas.circuit import CircuitSpec
from qpubench.schemas.primitives import CircuitFormat

# integrations/ is not an installed package — add the repo root so the
# integrations/qforte/ bridge (adapter.py + converters.py) is importable
# when running this example in place. Copy integrations/qforte/ into your
# own project (see its README) instead of relying on this path shim.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from integrations.qforte.adapter import QForteAlgorithmAdapter


ALGORITHMS: list[tuple[AlgorithmSpec, AdaptVQERunConfig]] = [
    (
        AlgorithmSpec(name="UCCNVQE", family=AlgorithmFamily.VQE),
        AdaptVQERunConfig(pool_type="SD", optimizer="BFGS", use_analytic_gradient=True,
                       energy_threshold=1.0e-5),
    ),
    (
        AlgorithmSpec(name="UCCNVQE", family=AlgorithmFamily.VQE),
        AdaptVQERunConfig(pool_type="SD", optimizer="jacobi", use_analytic_gradient=True,
                       energy_threshold=1.0e-5),
    ),
    (
        AlgorithmSpec(name="ADAPTVQE", family=AlgorithmFamily.ADAPT_VQE),
        AdaptVQERunConfig(pool_type="SD", optimizer="BFGS", use_analytic_gradient=True,
                       gradient_threshold=1.0e-4, energy_threshold=1.0e-5,
                       max_macro_iterations=20),
    ),
]


def print_record(record: BenchmarkRecord) -> None:
    alg_name = record.vqa.algorithm if record.vqa else "?"
    energy   = record.result.expectation_values[0].value if record.result.expectation_values else float("nan")
    err      = record.vqa_result.energy_error if record.vqa_result else None
    ca       = record.vqa_result.chemical_accuracy if record.vqa_result else None
    n_cnot   = ((record.vqa_result.n_cnot if record.vqa_result else None)
                or record.result.metadata.get("n_cnot", "?"))
    n_params = (record.vqa_result.num_parameters if record.vqa_result else None) or "?"
    t        = record.result.total_time_s

    print(f"  {alg_name:<20}  E={energy:+.8f} Ha  "
          f"err={err:.2e} Ha  chem_acc={ca}  "
          f"CNOTs={n_cnot}  params={n_params}  t={t:.1f}s")

    if record.result.adapt_history:
        print(f"    ADAPT iterations: {len(record.result.adapt_history)}")
        for it in record.result.adapt_history:
            print(f"      iter {it.iteration:2d}  E={it.energy:+.8f}  "
                  f"|∇|={it.grad_norm:.2e}  CNOTs={it.n_cnot}")


def main() -> None:
    he_json = _find_he_json()
    print(f"Using molecule file: {he_json}\n")

    # The CircuitSpec represents the problem (He molecule), not a pre-written circuit.
    # num_qubits is filled in after QForte builds the system; set 0 as a placeholder.
    mol_spec = CircuitSpec(
        num_qubits=0,
        format=CircuitFormat.MOLECULE_JSON,
        serialized=str(he_json),
    )

    store  = NDJSONStore(pathlib.Path("results/qforte_he_benchmark.ndjson"))
    runner = BenchmarkRunner(store=store)
    runner.register(QForteAlgorithmAdapter(), name="qforte")

    print("QForte VQE benchmark — He / cc-pvdz")
    print("=" * 70)

    records = runner.sweep(
        circuits=[mol_spec],
        backend_names=["qforte"],
        options_list=[
            ExecutionOptions(algorithm_spec=alg_spec, adapt_vqe_run_config=cfg)
            for alg_spec, cfg in ALGORITHMS
        ],
        run_id="he_ccpvdz_vqe_sweep",
        tags=["qforte", "he", "cc-pvdz"],
    )

    print(f"\n{'Algorithm':<20}  {'Energy':>16}  {'Error':>10}  "
          f"{'ChmAcc':>8}  {'CNOTs':>6}  {'Params':>7}  {'Time':>7}")
    print("-" * 80)
    for record in records:
        print_record(record)

    # ---------------------------------------------------------------------------
    # Query stored results
    # ---------------------------------------------------------------------------
    print(f"\n{len(records)} records written to {store._path}")

    # Compare final energies
    energies = {
        r.vqa.algorithm + "/" + (r.options.adapt_vqe_run_config.optimizer if r.options.adapt_vqe_run_config else "?"):
        r.result.expectation_values[0].value
        for r in records
        if r.result.expectation_values
    }
    best = min(energies, key=energies.__getitem__)
    print(f"\nLowest energy: {best}  →  {energies[best]:+.10f} Ha")

    # Filter to chemically accurate runs
    chem_accurate = [
        r for r in records
        if r.vqa_result and r.vqa_result.chemical_accuracy
    ]
    print(f"Chemically accurate runs: {len(chem_accurate)} / {len(records)}")


if __name__ == "__main__":
    main()
