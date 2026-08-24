# Campaign machinery

The code a benchmarking campaign is built from: it generates the runs,
pins the circuit each one executes, counts what a measurement costs, and
partitions the result into batches sized to a hardware access plan.

These are not demonstrations of the `qpubench` library. They are the
tools that produce the committed campaign files under `data/benchmarks/`,
so a campaign can be regenerated from its generator rather than edited by
hand. Everything under `examples/` is the other thing: runnable guides to
the library itself.

| Module | What it does |
|---|---|
| [`build_benchmark_matrix.py`](build_benchmark_matrix.py) | Crosses the experimental factors into a campaign's runs, in three stages. Writes `stage1_screening_matrix.csv`; stages 2 and 3 are generated on demand from the stage before |
| [`_ansatz_builders.py`](_ansatz_builders.py) | Builds the named ansatz circuits the runs ask for, as real Qiskit circuits. Imported by the two modules below rather than run |
| [`pin_qasm_ansatz.py`](pin_qasm_ansatz.py) | Writes each distinct circuit to committed OpenQASM under `data/qasm/`, so a run's circuit is part of the record rather than whatever the installed library versions resolve to |
| [`count_measurement_bases.py`](count_measurement_bases.py) | Counts the measurement bases one cost-function evaluation submits, which is what the QPU cost is proportional to |
| [`classical_reference_energies.py`](classical_reference_energies.py) | Computes the HF, MP2, CCSD and FCI energies a quantum result is scored against, at the same geometry the campaign pins |
| [`split_benchmark_batches.py`](split_benchmark_batches.py) | Costs every run against measured hardware billing and cuts the campaign into per-plan batches |
| [`estimate_ibm_cost.py`](estimate_ibm_cost.py) | Prices a campaign under each IBM access plan, from real transpilation against the target device's calibration |

Each runs directly and needs no arguments for the committed campaign:

```bash
PYTHONPATH=src python utils/build_benchmark_matrix.py
```

Dependencies vary by module. `split_benchmark_batches.py` and
`build_benchmark_matrix.py` need only the standard library;
`classical_reference_energies.py` needs `pip install 'qpubench[pyscf]'`;
the rest need `[qiskit]`, and `count_measurement_bases.py` needs both.
Each module's docstring states its own requirement.

The IBM TN-VQE campaign these currently build is documented in
[`data/benchmarks/ibm_tn-vqe_qesem/README.md`](../data/benchmarks/ibm_tn-vqe_qesem/README.md),
alongside a notebook that runs the whole pipeline.
