"""ADAPT-VQE benchmark via qpubench — using qpubench-qforte bridge.

Requires:
    pip install qforte                  # QForte with C++ extension
    pip install -e ../qpubench          # qpubench framework
    pip install -e .                    # this bridge package

QForte uses its own statevector simulator.  qpubench records the results.
Neither package imports from the other — this file is the only coupling.

Run:
    python examples/adapt_vqe_benchmark.py
"""
from __future__ import annotations

import pathlib
import sys

# ---------------------------------------------------------------------------
# Locate He-ccpvdz.json (ships with QForte tests/)
# ---------------------------------------------------------------------------

def _find_molecule_json(name: str) -> pathlib.Path:
    try:
        import qforte
        root = pathlib.Path(qforte.__file__).parent
    except ImportError:
        print("QForte is not installed.  See: https://github.com/evangelistalab/qforte")
        sys.exit(1)

    hits = list(root.rglob(name)) or list(pathlib.Path(".").rglob(name))
    if not hits:
        raise FileNotFoundError(
            f"{name} not found.  Install QForte from source; "
            "it ships in qforte/tests/."
        )
    return hits[0]


# ---------------------------------------------------------------------------
# qpubench imports (no qforte here)
# ---------------------------------------------------------------------------

from qpubench import (
    BenchmarkRunner,
    NDJSONStore,
)

# ---------------------------------------------------------------------------
# Bridge imports (knows about both)
# ---------------------------------------------------------------------------

from qpubench_qforte import (
    AdaptVQERunner,
    QForteAlgorithmAdapter,
)
from qpubench_qforte.converters import molecule_spec_from_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_summary(table: list[dict]) -> None:
    print(f"\n{'Algorithm':<12} {'Optimizer':<10} {'Pool':<6} "
          f"{'Energy':>16} {'Error':>10} {'ChmAcc':>8} "
          f"{'CNOTs':>6} {'Params':>7} {'ADAPT iters':>12} {'Time':>7}")
    print("-" * 100)
    for row in table:
        e   = row["final_energy"]
        err = row["energy_error"]
        print(
            f"{row['algorithm']:<12} {row['optimizer']:<10} {row['pool_type']:<6} "
            f"{e:+16.8f} {err:10.2e} {str(row['chem_accuracy']):>8} "
            f"{str(row['n_cnot'] or '?'):>6} {str(row['n_params'] or '?'):>7} "
            f"{str(row['adapt_iters'] or '-'):>12} "
            f"{row['total_time_s']:>7.1f}s"
        )


def _print_adapt_convergence(records) -> None:
    rows = AdaptVQERunner.convergence_table(records)
    adapt_rows = [r for r in rows if r["algorithm"] == "ADAPTVQE"]
    if not adapt_rows:
        return
    print("\n  ADAPT-VQE convergence (energy per macro-iteration):")
    current_exp = None
    for row in adapt_rows:
        if row["experiment_id"] != current_exp:
            current_exp = row["experiment_id"]
            print(f"\n  optimizer={row['optimizer']}  pool={row['pool_type']}")
            print(f"  {'Iter':>4}  {'Energy':>16}  {'|∇|':>10}  "
                  f"{'Ops':>5}  {'CNOTs':>6}")
        print(f"  {row['iteration']:>4}  {row['energy']:+16.8f}  "
              f"{row['grad_norm']:10.2e}  {row['n_operators']:>5}  "
              f"{row['n_cnot']:>6}")


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------

def main() -> None:
    he_json = _find_molecule_json("He-ccpvdz.json")
    mol     = molecule_spec_from_file(he_json)
    print(f"Molecule file : {he_json}")

    store  = NDJSONStore(pathlib.Path("results/adapt_vqe_he.ndjson"))
    runner = BenchmarkRunner(store=store)
    runner.register(QForteAlgorithmAdapter(), name="qforte")

    adapt_runner = AdaptVQERunner(
        runner,
        on_iteration=lambda it: print(
            f"  [ADAPT iter {it.iteration}]  "
            f"E={it.energy:+.8f}  |∇|={it.grad_norm:.2e}  "
            f"ops={it.n_operators}  CNOTs={it.n_cnot}"
        ),
    )

    # ---- 1. Compare ADAPT-VQE optimizers ----------------------------------
    print("\n" + "=" * 60)
    print("1. ADAPT-VQE: BFGS vs jacobi  (pool=SD)")
    print("=" * 60)
    records_opt = adapt_runner.compare_optimizers(
        mol,
        pool_type="SD",
        optimizers=["BFGS", "jacobi"],
        gradient_threshold=1.0e-4,
        run_id="he_adapt_optimizers",
    )
    _print_summary(AdaptVQERunner.summary_table(records_opt))
    _print_adapt_convergence(records_opt)

    # ---- 2. Compare operator pool types -----------------------------------
    print("\n" + "=" * 60)
    print("2. ADAPT-VQE: SD vs GSD pools  (optimizer=BFGS)")
    print("=" * 60)
    records_pool = adapt_runner.compare_pool_types(
        mol,
        pool_types=["SD", "GSD"],
        optimizer="BFGS",
        gradient_threshold=1.0e-4,
        run_id="he_adapt_pools",
    )
    _print_summary(AdaptVQERunner.summary_table(records_pool))
    _print_adapt_convergence(records_pool)

    # ---- 3. ADAPT-VQE vs UCCNVQE ------------------------------------------
    print("\n" + "=" * 60)
    print("3. ADAPT-VQE vs UCCNVQE  (pool=SD, optimizer=BFGS)")
    print("=" * 60)
    records_alg = adapt_runner.compare_algorithms(
        mol,
        alg_names=["UCCNVQE", "ADAPTVQE"],
        pool_type="SD",
        optimizer="BFGS",
        run_id="he_alg_comparison",
    )
    _print_summary(AdaptVQERunner.summary_table(records_alg))

    # ---- Store summary ----------------------------------------------------
    all_records = records_opt + records_pool + records_alg
    print(f"\n{len(all_records)} records → {store._path}")
    ca_count = sum(1 for r in all_records if r.vqa_result and r.vqa_result.chemical_accuracy)
    print(f"Chemically accurate: {ca_count} / {len(all_records)}")

    # ---- Convergence data for plotting ------------------------------------
    conv = AdaptVQERunner.convergence_table(records_opt + records_pool)
    print(f"\nConvergence table rows: {len(conv)}")
    print("(pass conv to pd.DataFrame(conv) for plotting)")


if __name__ == "__main__":
    main()
