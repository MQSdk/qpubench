# Integrations

qpubench's schema layer bridges several external frameworks. Each integration is a **data schema bridge only** — the external library is not imported into qpubench.

| Integration | External repo | Schema module | Detail |
|---|---|---|---|
| Cebule SDK | [docs.mqs.dk](https://docs.mqs.dk/sections/section_014_quantum_computing/) | `schemas/cebule.py` | [cebule.md](integrations/cebule.md) |
| Xenakis GA | [github.com/mqsdk/xenakis](https://github.com/mqsdk/xenakis) + `Xenakis_extended/` | `schemas/xenakis.py` | [xenakis.md](integrations/xenakis.md) |
| ExcitationSolve | [github.com/dlr-wf/ExcitationSolve](https://github.com/dlr-wf/ExcitationSolve) | `schemas/excitation_solve.py` | [excitation_solve.md](integrations/excitation_solve.md) |
| GSOpt | [github.com/bestquark/gsopt](https://github.com/bestquark/gsopt) | `schemas/gsopt.py` | [gsopt.md](integrations/gsopt.md) |

For adapters (code that calls the library and returns a `QuantumResult`), see [backends.md](backends.md) and the templates in `integrations/`.
