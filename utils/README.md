# Shared campaign toolkit

The code any benchmarking campaign can build on: building and pinning
ansatz circuits, budgeting tn-vqe's optimizers, submitting and collecting
Cebule `TN_QC_OPT` runs, and costing a matrix on IBM hardware.

Nothing here is specific to one campaign. Each campaign lives in its own
folder under [`campaigns/`](../campaigns/), and the tools here take it as
an argument (`--campaign NAME`, optional while there is only one). What
only a campaign knows -- where its files are, how its Hamiltonians are
named, Hartree-Fock states under its mappers -- comes from that
campaign's `campaign.py`; see [`_campaign.py`](_campaign.py) for what it
defines.

These are not demonstrations of the `qpubench` library, and are not
installed with it. Everything under `examples/` is the other thing:
runnable guides to the library itself.

## Tools (run directly)

| Module | What it does |
|---|---|
| [`run_campaign.py`](run_campaign.py) | Submits a campaign's runs to Cebule and collects them later, filtered with `--where` and resumed by repeating the command. Dry-runs by default; refuses hardware unless told |
| [`pin_qasm_ansatz.py`](pin_qasm_ansatz.py) | Writes each distinct circuit a campaign's matrix names to OpenQASM in that campaign's `qasm/`, so a run's circuit is part of the record rather than whatever the installed library versions resolve to |
| [`estimate_ibm_cost.py`](estimate_ibm_cost.py) | Prices a campaign's matrix under each IBM access plan, from real transpilation against the device's calibration |
| [`count_measurement_bases.py`](count_measurement_bases.py) | Counts the measurement bases one cost-function evaluation submits for a campaign's JW rows, which is what the QPU cost is proportional to |
| [`classical_reference_energies.py`](classical_reference_energies.py) | Computes the HF, MP2, CCSD and FCI energies a quantum result is scored against, for any geometry and basis |

```bash
PYTHONPATH=src python utils/run_campaign.py --campaign ibm_tn-vqe_qesem --group-by Molecule,Basis,Mapper
PYTHONPATH=src python utils/pin_qasm_ansatz.py --campaign ibm_tn-vqe_qesem
```

## Modules (imported)

| Module | What it provides |
|---|---|
| [`_campaign.py`](_campaign.py) | Finds a campaign and loads its `campaign.py` |
| [`_campaign_runner.py`](_campaign_runner.py) | Builds one run's Cebule task input from its CSV row, and submits and polls it. Used by `run_campaign.py` and by campaign notebooks, so the two cannot drift |
| [`_ansatz_builders.py`](_ansatz_builders.py) | Builds named ansatz circuits as real Qiskit circuits, names their pinned files, and starts hardware-efficient circuits at Hartree-Fock |
| [`_fermionic_ansatz.py`](_fermionic_ansatz.py) | UCCSD and tUPS/pp-tUPS built from exact Givens rotations, under Jordan-Wigner or a reduced (mapping-matrix) encoding, and the spin-block reordering of such an encoding |
| [`_optimizer_budget.py`](_optimizer_budget.py) | tn-vqe's optimizer cost model: turns an evaluation budget into each optimizer's iterations, so COBYLA, SPSA and ExcitationSolve spend the same budget |
| [`_matrix_io.py`](_matrix_io.py) | Case_ID numbering, de-duplication, CSV output and pinned-circuit lookup for a campaign's matrix builder |

Dependencies vary by module. `_matrix_io.py` and `_optimizer_budget.py`
need only the standard library, so a matrix builder can run without a
quantum SDK; `classical_reference_energies.py` needs
`pip install 'qpubench[pyscf]'`; `run_campaign.py` needs `[cebule]` to
submit; the rest need `[qiskit]`, and `count_measurement_bases.py` needs
PySCF too. Each module's docstring states its own requirement.
