# SlowQuant integration

Real `AlgorithmAdapter` implementation for
[SlowQuant](https://github.com/erikkjellgren/SlowQuant) (UCC/UPS
wavefunctions, Hartree-Fock, linear response), written against SlowQuant's
actual public API — verified directly against its GitHub source, not
guessed.

**Not pip-installable.** SlowQuant isn't on PyPI:

```sh
pip install git+https://github.com/erikkjellgren/SlowQuant
```

Because it can't be installed from PyPI, this adapter has not been
executed against the real package in this repo's own CI/sandbox — the
call sequence (`SlowQuant().set_molecule()` / `.init_hartree_fock()`,
`WaveFunctionUCC(cas, mo_coeffs, integral_generator, excitations,
include_active_kappa)`, `.run_wf_optimization_1step(...)`) is checked
field-by-field against SlowQuant's own source, and structurally
round-tripped against a mock of that API, but not against SlowQuant itself.
Verify against whichever version you install.

## Files

| File | Purpose |
|------|---------|
| `adapter.py` | `SlowQuantAlgorithmAdapter` |

## Setup

```sh
pip install qpubench
pip install git+https://github.com/erikkjellgren/SlowQuant
```

Copy this directory into your project:

```sh
cp -r integrations/slowquant/ my_project/slowquant_adapter/
```

## Usage

```python
import json
from qpubench import BenchmarkRunner, NDJSONStore, CircuitSpec, ExecutionOptions
from qpubench.schemas.primitives import CircuitFormat
from qpubench.schemas.execution import AdaptVQERunConfig
from integrations.slowquant.adapter import SlowQuantAlgorithmAdapter

runner = BenchmarkRunner(store=NDJSONStore("results.ndjson"))
runner.register(SlowQuantAlgorithmAdapter(), name="slowquant_ucc")

problem = CircuitSpec(
    num_qubits=1,
    format=CircuitFormat.MOLECULE_JSON,
    serialized=json.dumps({
        "molecule_file": "h2.xyz",
        "basis": "sto-3g",
        "charge": 0,
        "active_electrons": 2,
        "active_orbitals": 2,
        "excitations": "SD",
    }),
)
options = ExecutionOptions(adapt_vqe_run_config=AdaptVQERunConfig(optimizer="SLSQP"))
record = runner.run(problem, "slowquant_ucc", options)
print(record.result.slowquant_record.ucc_energy)
```

See `examples/tutorials/ionization_potential.py` for a construction-only
demonstration alongside the always-runnable toy ADAPT-VQE fallback.
