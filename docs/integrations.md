# Integrations

qpubench's schema layer bridges several external frameworks. Each integration is a **data schema bridge only** — the external library is not imported into qpubench.

| Integration | External repo | Schema module | Modality | Detail |
|---|---|---|---|---|
| Cebule SDK | [docs.mqs.dk](https://docs.mqs.dk/sections/section_014_quantum_computing/) | `schemas/cebule.py` | `GATE_BASED` | [cebule.md](integrations/cebule.md) |
| Xenakis GA | [github.com/mqsdk/xenakis](https://github.com/mqsdk/xenakis) | `schemas/xenakis.py` | `GATE_BASED` | [xenakis.md](integrations/xenakis.md) |
| ExcitationSolve | [github.com/dlr-wf/ExcitationSolve](https://github.com/dlr-wf/ExcitationSolve) | `schemas/excitation_solve.py` | `GATE_BASED` | [excitation_solve.md](integrations/excitation_solve.md) |
| GSOpt | [github.com/bestquark/gsopt](https://github.com/bestquark/gsopt) | `schemas/gsopt.py` | `GATE_BASED` | [gsopt.md](integrations/gsopt.md) |
| Photochipsim / FBQC | DTU photochipsim + Photonic QC | `schemas/photonic.py` | `PHOTONIC_LINEAR_OPTICS` / `FUSION_BASED` | [photonic.md](integrations/photonic.md) |
| QDK Chemistry / QuNorth | [microsoft/qsharp](https://github.com/microsoft/qsharp) + QuNorth | `schemas/qdk_chemistry.py` | `QPE` | [qdk_chemistry.md](integrations/qdk_chemistry.md) |
| DTU-GBS / photonic_QC | DTU-GBS + photonic_QC | `schemas/gbs.py` | `GBS` | [gbs.md](integrations/gbs.md) |
| MQSdk/qse (KQD) | [github.com/MQSdk/qse](https://github.com/MQSdk/qse) | `schemas/qse.py` | `KQD` | [qse.md](integrations/qse.md) |
| QESEM (Qedma) | [docs.qedma.io](https://docs.qedma.io/) | `schemas/qesem.py` | `GATE_BASED` + `QESEM` | [qesem.md](integrations/qesem.md) |
| QCSchema / QCElemental / PennyLane | [MolSSI QCSchema](https://github.com/MolSSI/QCSchema) · [QCElemental](https://github.com/MolSSI/QCElemental) · [PennyLane qchem](https://pennylane.ai/datasets/collection/qchem) | `schemas/qcschema.py` | all (chemistry) | [qcschema.md](integrations/qcschema.md) |
| Bloqade / Aquila (QuEra) | [github.com/QuEraComputing/bloqade](https://github.com/QuEraComputing/bloqade) | `schemas/neutral_atom.py` | `NEUTRAL_ATOM` | [neutral_atom.md](integrations/neutral_atom.md) |
| SlowQuant | [github.com/erikkjellgren/SlowQuant](https://github.com/erikkjellgren/SlowQuant) · [slowquant.readthedocs.io](https://slowquant.readthedocs.io/en/latest/) | `schemas/slowquant.py` | `GATE_BASED` | [slowquant.md](integrations/slowquant.md) |

For adapters (code that calls the library and returns a `QuantumResult`), see [backends.md](backends.md) and the templates in `integrations/`.
