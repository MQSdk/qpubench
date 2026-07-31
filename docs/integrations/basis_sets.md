# Basis-set library

Two Gaussian basis-set sources back the `Basis` column of
`data/IBM_VQE_Test_Benchmark.csv` (and any future VQE benchmark scenario):
the real [Basis Set Exchange](https://www.basissetexchange.org/) (BSE) for
the six standard fixed bases, and Grimme group's
[q-vSZP](https://github.com/grimme-lab/qvSZP) for the charge-adaptive one
and **both are real and independently usable without ORCA**. Typed Pydantic
schemas live in `src/qpubench/schemas/catalogs/basis_sets.py`; the loaders live in
`src/qpubench/hamiltonian_sources/basis_set_exchange.py` and
`src/qpubench/hamiltonian_sources/qvszp.py`, the same
core-never-imports-a-quantum-library boundary as `hamiltonian_library.py`
vs. `hamiltonian_sources/hamlib.py`.

---

## Installation

```sh
pip install 'qpubench[bse]'      # Basis Set Exchange
pip install 'qpubench[qvszp]'    # q-vSZP downloader (just `requests`)
```

`basis_set_exchange` bundles its own basis-set data in the wheel; no
network access needed at runtime. `qvszp` downloads directly from
github.com/grimme-lab/qvSZP and caches locally (same pattern as
`hamlib.py`).

---

## Basis Set Exchange: real, verified

```python
from qpubench.hamiltonian_sources.basis_set_exchange import (
    count_basis_functions, get_basis_set_entry, list_available_elements,
)

entry = get_basis_set_entry("cc-pvdz")          # confirms it's real via bse.get_metadata()
elements = list_available_elements("sto-3g")     # ['H', 'He', 'Li', ...]
n = count_basis_functions("def2-tzvp", "O")       # 31, spatial AO functions
```

`count_basis_functions()` computes real spherical-harmonic AO counts from
BSE's own shell data and was cross-checked in this session against real
`pyscf.gto.M(...).nao` for every (element, basis) pair in
`data/IBM_VQE_Test_Benchmark.csv`, an exact match in all 18 cases (H, Li, O
× sto-3g/6-31g/cc-pvdz/cc-pvtz/def2-svp/def2-tzvp), see
`tests/test_basis_sets.py`. Two real BSE shell shapes are handled
correctly, not just the simple case: general-contraction shells (one `l`,
several contracted columns, e.g. cc-pVDZ's 3 s-type contractions on O)
and combined SP/SPD shells (several `l`s, one column each, e.g. 6-31G's
combined SP shell on Li).

`BASIS_SET_CATALOG` covers the six standard bases currently in the
benchmark CSV:

| Name | Family | Cardinality | Polarization |
|---|---|---|---|
| `sto-3g` | minimal | 1 | no |
| `6-31g` | Pople | 2 | no |
| `cc-pvdz` | Dunning correlation-consistent | 2 | yes |
| `cc-pvtz` | Dunning correlation-consistent | 3 | yes |
| `def2-svp` | Karlsruhe def2 | 2 | yes |
| `def2-tzvp` | Karlsruhe def2 | 3 | yes |

---

## q-vSZP: real, verified via its own data files (ORCA NOT required)

**Correction (2026-07-09):** an earlier version of this doc claimed q-vSZP
had no offline representation at all, and that ORCA + the Fortran CLI
were required just to know its composition. That was wrong, as caught by
actually downloading and parsing the real files in
[`q-vSZP_basis/`](https://github.com/grimme-lab/qvSZP/tree/main/q-vSZP_basis)
rather than only reading the top-level README.

What's actually there: five real, plain-text files, no ORCA/Fortran
needed to read any of them:

| File | `QvSZPVariant` | What it is |
|---|---|---|
| `basisq` | `FULL` | Complete q-vSZP basis, Z=1-103 |
| `basisq_lesspolfunc` | `NO_POLARIZATION` | Polarization shell dropped |
| `basisq_gxtb` | `GXTB` | Smaller basis matched to the g-xTB charge model |
| `ecpq` | n/a | Effective core potentials, Z=3-103 (`ncore=2`, i.e. the 1s core) |
| `basis_qvSZP_CP2K_format` | n/a | The `FULL` basis, pre-converted, directly usable as a CP2K `BASIS_SET` file |

The key fact that makes this usable offline: **each primitive row carries
two coefficient columns, a charge-independent base value and a
linear-in-charge slope for the *same* function, not two separate
functions.** Only the coefficient *values* are charge-dependent; the
*number* of shells/functions per element is fixed. This is confirmed
directly by the CP2K file's own header comment:

> "The source basis carries charge/environment-dependent coefficient
> columns. CP2K BASIS_SET files are static, so this file uses the first
> contraction coefficient column."

i.e. CP2K's own maintainers already treat q-vSZP this way, as a static,
`q=0`-reference basis, no per-molecule regeneration step, no ORCA.

```python
from qpubench.hamiltonian_sources.qvszp import (
    count_basis_functions, ecp_core_electrons, get_cp2k_format_text,
)
from qpubench.schemas.catalogs.basis_sets import QvSZPVariant

count_basis_functions("Li")                      # 9  (1s + 1p + 1d)
count_basis_functions("H", QvSZPVariant.GXTB)      # 1  (s only)
ecp_core_electrons("Li")                             # 2  (1s core replaced)
ecp_core_electrons("H")                                # None (all-electron)

cp2k_basis = get_cp2k_format_text()   # ready to drop into a CP2K &BASIS_SET
```

`count_basis_functions()` is verified in this session against a live
download+parse of the real `basisq` file, cross-checked against the
independently-generated CP2K file (identical shell composition), and
against `ecpq`'s real element coverage; see `tests/test_qvszp.py`.

**Real per-element function counts, FULL variant:**

| Element | Shells | Functions | ECP core |
|---|---|---|---|
| H | 1s + 1p | 4 | none (all-electron) |
| Li | 1s + 1p + 1d | 9 | 2 (1s) |
| O | 1s + 1p + 1d | 9 | 2 (1s) |

This also corrected a real error in the original benchmark CSV draft: its
qvSZP/Li2 qubit count was `34`, which is impossible for a homonuclear
diatomic (`34` spin-orbitals implies `17` spatial orbitals total, an odd
number that can't split evenly across two chemically-equivalent Li
atoms). The real value, from the data above, is `2 x 9 x 2 = 36`.

### What's still genuinely CLI/tool-only

Producing the *true*, molecule-specific charge-adapted coefficients (the
actual q-vSZP method, not the static `q=0` reference used above), and
writing ORCA-ready `.basisq`/`.ecpq` files for a specific molecule, still
needs either the real Fortran CLI (build from source via FPM; no PyPI
package) or a from-scratch GFN2-xTB charge calculation via `tblite`
(pip-installable, ORCA-independent) plus reimplementing the
charge-interpolation formula. That specific step remains schema-only here
(`QvSZPRunConfig`/`QvSZPBasisResult`), same "container, not solver"
boundary as `pyscf.ProjectionEmbeddingConfig`/`DMETConfig`
(PsiEmbed/libDMET):

```python
from qpubench.schemas.catalogs.basis_sets import QvSZPRunConfig, QvSZPVariant

config = QvSZPRunConfig(
    structure_file="h2o.xyz",
    variant=QvSZPVariant.FULL,   # or NO_POLARIZATION / GXTB
)
# write your own adapter around the real `qvSZP` CLI (or a real tblite
# GFN2-xTB charge calculation) to produce a real QvSZPBasisResult with
# molecule-adapted coefficients; nothing here calls either for real.
```

But **basis-function/qubit counts, element coverage, and a usable static
basis (including for CP2K directly) do not need any of that**; use
`hamiltonian_sources.qvszp` instead.

---

## Why not just PySCF's built-in basis strings?

`pyscf.gto.M(basis=...)` already accepts any of the six BSE names directly
(and is what `hamiltonian_sources/ab_initio.py` uses); this module isn't
a replacement for that. It exists for what PySCF's string argument doesn't
give you: a catalogue you can enumerate/validate a `Basis` CSV column
against, element coverage per basis, and real q-vSZP support (which PySCF
has no built-in knowledge of at all).
