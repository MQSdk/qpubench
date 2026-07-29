# PySCF integration

[PySCF](https://pyscf.org/) is free, open-source, pip-installable (no
compiler required — pure wheel), and already the engine behind
`erikkjellgren_slowquant.py`. qpubench models molecules, periodic cells,
mean-field/DFT, solvation, and embedding problem specs as typed Pydantic
schemas in `src/qpubench/schemas/mirrors/pyscf_pyscf.py`.

**Why this module exists.** PySCF (+ two smaller PySCF-based packages for
embedding specifically) covers embedding and periodic-boundary quantum
chemistry for free, with no commercial SDK required. See "Embedding" below
for what's real vs. schema-only.

---

## Installation

```sh
pip install 'qpubench[pyscf]'
```

No C/Fortran compiler needed — PySCF ships a `manylinux` wheel.

---

## Molecules and periodic cells — real, verified

`PySCFMoleculeSpec` / `PySCFCellSpec` mirror PySCF's own `gto.M()` /
`pbc.gto.Cell()` argument shapes directly, confirmed by round-tripping
through the real API:

```python
from qpubench.schemas.mirrors.pyscf_pyscf import PySCFAtomSpec, PySCFMoleculeSpec
from pyscf import gto, scf

spec = PySCFMoleculeSpec(atoms=[
    PySCFAtomSpec(symbol="H", x=0.0, y=0.0, z=0.0),
    PySCFAtomSpec(symbol="H", x=0.0, y=0.0, z=0.7414),
], basis="sto-3g")

mol = gto.M(atom=spec.to_pyscf_atom_string(), basis=spec.basis,
            charge=spec.charge, spin=spec.spin, unit=spec.unit)
energy = scf.RHF(mol).kernel()   # -1.1166843870853405 Ha — exact match,
                                  # see tests/test_schemas.py
```

`PySCFCellSpec` adds `lattice_vectors` (3×3, Å) and `dimension` (0–3) for
periodic boundary conditions — builds a real `pbc.gto.Cell()` (verified in
`tests/test_schemas.py`).

---

## Solvation — real, verified; the free equivalent of Cebule's `COSMO`

```python
from qpubench.schemas.mirrors.pyscf_pyscf import PCMMethod, PySCFSolvationConfig
from pyscf import gto, scf

mol = gto.M(atom="O 0 0 0; H 0 0.757 0.587; H 0 -0.757 0.587", basis="sto-3g")

config = PySCFSolvationConfig(method=PCMMethod.C_PCM, eps=78.3553)  # water
mf = scf.RHF(mol).PCM()
mf.with_solvent.method = config.method.value
mf.with_solvent.eps = config.eps
solvated_energy = mf.kernel()
```

Full runnable example: `examples/guides/create_solvent_model.py`.

`PCMMethod` values (`C-PCM`, `IEF-PCM`, `COSMO`) and `PySCFSolvationConfig`'s
defaults (`eps=78.3553`, `lebedev_order=29`) are confirmed against a real
`pcm.PCM(mol)` instance's own attributes, not guessed.

---

## Embedding — schema-only (PsiEmbed / libDMET are real but not on PyPI)

Two embedding families, both genuinely free and PySCF-based, neither
installable with a plain `pip install` (both are GitHub-only research
code) — so unlike everything above, qpubench models their I/O shape but
calls neither for real. Write that adapter yourself once you've installed
one from source, following the `erikkjellgren_slowquant.py` /
`microsoft_qdk.py` "schema, not solver" pattern.

**Projection-based WF-in-DFT embedding** (Manby–Miller formulation):

```python
from qpubench.schemas.mirrors.pyscf_pyscf import ProjectionEmbeddingConfig

config = ProjectionEmbeddingConfig(
    active_atom_indices=[0, 1],      # 0-based indices into the full molecule
    environment_method="b3lyp",       # frozen environment: always DFT
    active_method="ccsd",              # or "adapt-vqe" once JW-mapped
)
```

Free implementation: [PsiEmbed](https://github.com/danclaudino/PsiEmbed)
(PySCF/Psi4-based).

**DMET** (Density Matrix Embedding Theory — PennyLane's own [DMET-embedding
demo](https://pennylane.ai/demos/tutorial_dmet_embedding) runs this
end-to-end, including on a periodic hydrogen chain):

```python
from qpubench.schemas.mirrors.pyscf_pyscf import DMETConfig

config = DMETConfig(impurity_atom_indices=[0], localization="iao")
```

Free implementation: `libDMET` (PySCF mean-field → impurity Hamiltonian) +
PennyLane (Jordan-Wigner mapping to a qubit Hamiltonian).

Both embedding methods produce an `EmbeddedHamiltonianResult`
(active-space one/two-electron integrals + `core_energy`), which feeds
directly into `integrations/generic_adapt_vqe`:

```python
from integrations.generic_adapt_vqe.pool import generate_singles_doubles_pool

pool = generate_singles_doubles_pool(
    2 * result.num_active_orbitals, result.num_active_electrons,
)
# hand the resulting qubit Hamiltonian + pool to GenericAdaptVQEEngine,
# same as any other qpubench VQE problem
```

---
