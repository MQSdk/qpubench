"""PySCF interoperability: molecules, mean-field/DFT, solvation, and
embedding (DMET / projection-based WF-in-DFT) problem specs.

PySCF (pip-installable, no compiler required — verified in this repo's own
CI sandbox) covers embedding and periodic-boundary quantum chemistry with no
commercial SDK required:

  - Mean-field / DFT           pyscf.scf, pyscf.dft         — verified, real
  - Continuum solvation        pyscf.solvent.pcm (PCM/COSMO) — verified, real
  - Periodic boundary conditions  pyscf.pbc.gto.Cell         — verified, real
  - Projection-based WF-in-DFT embedding   PsiEmbed (external, PySCF-based)
  - DMET embedding             libDMET (external, PySCF-based) + PennyLane
                                for the Jordan-Wigner qubit mapping

The first three are exercised by real PySCF calls in
``examples/guides/create_solvent_model.py`` — this schema module models
their inputs/outputs directly from the real PySCF API (``gto.M()``,
``pbc.gto.Cell()``, ``PCM.method``/``.eps``), not guessed.

The embedding types (``ProjectionEmbeddingConfig``, ``DMETConfig``,
``EmbeddedHamiltonianResult``) are schema-only, same "container, not
solver" boundary as ``erikkjellgren_slowquant.py``/``microsoft_qdk.py``:
PsiEmbed and libDMET are real, documented, PySCF-based packages, but
neither ships on PyPI (both are GitHub-only research code), so unlike the
solvation/periodic pieces above, nothing here calls them for real — write
that adapter yourself once you've installed one from source. Field names
follow the Manby-Miller projection-embedding formulation (active region +
environment level-shift) and the standard DMET impurity/bath/correlation-
potential formulation respectively; verify exact field names against
whichever package you wire in.

PySCF (+ PsiEmbed/libDMET) covers projection-based embedding and periodic PBC
drivers for free, fitting qpubench's zero-commercial-SDK-in-core posture. See
docs/integrations/pyscf.md for the full writeup.
"""
from __future__ import annotations

import enum

import pydantic

# ---------------------------------------------------------------------------
# Molecule / periodic cell — real pyscf.gto.M() / pyscf.pbc.gto.Cell() shape
# ---------------------------------------------------------------------------

class PySCFAtomSpec(pydantic.BaseModel):
    """One atom line, matching PySCF's own ``atom`` string/list format."""
    symbol: str
    x: float
    y: float
    z: float   # Angstrom, PySCF's default unit


class PySCFMoleculeSpec(pydantic.BaseModel):
    """Input for ``pyscf.gto.M(...)`` — a real, verified molecule spec.

    charge / spin follow PySCF's own convention: spin = n_alpha - n_beta
    (NOT multiplicity - 1, though they coincide for the common case of one
    unpaired electron).
    """
    atoms:     list[PySCFAtomSpec]
    basis:      str            = "sto-3g"
    charge:      int            = 0
    spin:         int            = 0
    unit:          str            = "angstrom"

    def to_pyscf_atom_string(self) -> str:
        """The exact string PySCF's ``gto.M(atom=...)`` accepts."""
        return "; ".join(f"{a.symbol} {a.x} {a.y} {a.z}" for a in self.atoms)


class PySCFCellSpec(pydantic.BaseModel):
    """Input for ``pyscf.pbc.gto.Cell()`` — periodic boundary conditions.

    lattice_vectors  3x3 matrix (Angstrom), rows are the lattice vectors —
                      matches Cell.a directly.
    dimension         0 (molecule), 1, 2, or 3 (fully periodic) — matches
                      Cell.dimension.

    Verified real (Cell() constructs and builds successfully with this
    field shape) — see examples/guides/create_solvent_model.py's periodic
    cell smoke test.
    """
    atoms:               list[PySCFAtomSpec]
    basis:                 str                              = "sto-3g"
    lattice_vectors:         tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    dimension:                int                              = 3
    charge:                    int                              = 0
    spin:                       int                              = 0

    def to_pyscf_atom_string(self) -> str:
        return "; ".join(f"{a.symbol} {a.x} {a.y} {a.z}" for a in self.atoms)


# ---------------------------------------------------------------------------
# Mean-field / DFT
# ---------------------------------------------------------------------------

class PySCFMeanFieldMethod(str, enum.Enum):
    RHF = "rhf"
    UHF = "uhf"
    RKS = "rks"
    UKS = "uks"


class PySCFMeanFieldConfig(pydantic.BaseModel):
    """Input for pyscf.scf.RHF/UHF or pyscf.dft.RKS/UKS.

    xc is required for RKS/UKS (e.g. "b3lyp", "pbe"), ignored for RHF/UHF —
    matches ``mf.xc = ...`` in the real API. Verified real: both RHF and
    RKS(xc="b3lyp") converge on H2/STO-3G in this repo's own smoke test.
    """
    method:    PySCFMeanFieldMethod = PySCFMeanFieldMethod.RHF
    xc:          str | None           = None
    conv_tol:     float                 = 1.0e-9


class PySCFMeanFieldResult(pydantic.BaseModel):
    """Output of a PySCF mean-field/DFT calculation.

    energy      total SCF/DFT energy (Hartree) — ``mf.kernel()``'s return
                value, or equivalently ``mf.e_tot`` after convergence
    converged    ``mf.converged``
    """
    energy:      float
    converged:    bool


# ---------------------------------------------------------------------------
# Solvation — pyscf.solvent.pcm (real, verified)
# ---------------------------------------------------------------------------

class PCMMethod(str, enum.Enum):
    """Confirmed real PCM.method values (pyscf.solvent.pcm.PCM.method)."""
    C_PCM   = "C-PCM"
    IEF_PCM = "IEF-PCM"
    COSMO   = "COSMO"


class PySCFSolvationConfig(pydantic.BaseModel):
    """Input for ``mf.PCM()`` + ``mf.with_solvent`` config — continuum
    solvation, PySCF's free equivalent of Cebule's ``COSMO`` task (see
    ``mqsdk_cebule.CosmoInput``).

    eps default (78.3553) is PySCF's own default (water); method default
    ("C-PCM") is also PySCF's own default. Both confirmed by inspecting a
    real ``PCM(mol)`` instance's attributes — not guessed.
    """
    method:            PCMMethod = PCMMethod.C_PCM
    eps:                 float     = 78.3553
    lebedev_order:        int       = 29   # angular grid density for the cavity surface


class PySCFSolvationResult(pydantic.BaseModel):
    """Output of a PCM/COSMO-solvated mean-field calculation.

    energy               total solvated SCF/DFT energy (Hartree)
    gas_phase_energy      unsolvated reference energy, if computed, for
                          a solvation free-energy estimate
    """
    energy:               float
    converged:              bool
    gas_phase_energy:        float | None = None

    @property
    def solvation_energy(self) -> float | None:
        """energy - gas_phase_energy, if the gas-phase reference was computed."""
        if self.gas_phase_energy is None:
            return None
        return self.energy - self.gas_phase_energy


# ---------------------------------------------------------------------------
# Embedding — schema-only (PsiEmbed / libDMET are real but not on PyPI)
# ---------------------------------------------------------------------------

class ProjectionEmbeddingConfig(pydantic.BaseModel):
    """Projection-based WF-in-DFT embedding (Manby-Miller formulation);
    PsiEmbed (github.com/danclaudino/PsiEmbed, PySCF-based) is the free
    reference implementation of the technique.

    Schema-only: no adapter in this repo calls PsiEmbed (it isn't on PyPI —
    install from source to use this for real). Field names follow the
    Manby-Miller formulation (level-shift projection operator, no optimized
    effective potential needed) rather than a specific PsiEmbed API version
    — verify against whichever PsiEmbed commit you install.

    active_atom_indices   0-based indices into the full molecule's atom
                           list that define the "active" (high-level) region
    environment_method     level of theory for the frozen environment
                           (e.g. "b3lyp") — always DFT in this formulation
    active_method           level of theory for the active region (e.g.
                           "ccsd", or "adapt-vqe" once mapped to a qubit
                           Hamiltonian via GenericAdaptVQEEngine)
    level_shift_mu           level-shift parameter (Hartree) enforcing
                           orthogonality between active and environment
                           subsystems; PsiEmbed's own default is 1e6
    """
    active_atom_indices:     list[int]
    environment_method:        str
    active_method:              str
    level_shift_mu:              float = 1.0e6


class DMETConfig(pydantic.BaseModel):
    """Density Matrix Embedding Theory (DMET) configuration — the technique
    PennyLane's own DMET-embedding demo runs end to end (PySCF mean-field +
    libDMET impurity Hamiltonian + PennyLane Jordan-Wigner mapping),
    including on a periodic system (a hydrogen chain).

    Schema-only here for the same reason as ProjectionEmbeddingConfig:
    libDMET isn't on PyPI. Field names follow the standard DMET
    impurity/bath/correlation-potential formulation.

    impurity_atom_indices   0-based indices defining the impurity fragment
    bath_orbital_count        number of bath orbitals per impurity (typically
                             equal to the impurity orbital count in
                             single-shot DMET)
    localization              orbital localization scheme for building the
                             impurity/bath partition (libDMET's own default
                             is intrinsic atomic orbitals, "iao")
    max_scf_cycles              DMET correlation-potential self-consistency
                             loop iteration cap
    """
    impurity_atom_indices:   list[int]
    bath_orbital_count:         int | None = None
    localization:                 str        = "iao"
    max_scf_cycles:                int        = 20


class EmbeddedHamiltonianResult(pydantic.BaseModel):
    """Output of either embedding method: an active-space qubit-ready
    Hamiltonian plus the frozen environment's energy contribution.

    one_electron_integrals / two_electron_integrals  active-space integrals
                                                       in the embedded
                                                       orbital basis
    core_energy      constant energy contribution from the frozen
                     environment + nuclear repulsion — add this to any
                     active-space eigenvalue to get the total system energy
    num_active_orbitals / num_active_electrons        active-space size;
                     feed directly into
                     integrations/generic_adapt_vqe's
                     generate_singles_doubles_pool(2 * num_active_orbitals,
                     num_active_electrons) once JW-mapped
    """
    one_electron_integrals:   list[list[float]]
    two_electron_integrals:     list[list[list[list[float]]]]
    core_energy:                  float
    num_active_orbitals:            int
    num_active_electrons:             int


# ---------------------------------------------------------------------------
# Electron-repulsion integral (ERI) builder — real, both paths (2026-07-09)
# ---------------------------------------------------------------------------

class ERIBuilderMethod(str, enum.Enum):
    """Confirmed real via PySCF: standard 4-center ERIs
    (``mol.intor('int2e')``) vs. resolution-of-the-identity/density-fitting
    (``mf.density_fit(auxbasis=...)``, a real 3-center-factorized
    approximation)."""
    STANDARD = "standard"
    RESOLUTION_OF_IDENTITY = "resolution_of_identity"


class ERIBuilderConfig(pydantic.BaseModel):
    """Input for choosing how two-electron repulsion integrals are built.

    method       STANDARD (exact 4-center) or RESOLUTION_OF_IDENTITY (RI/DF
                 — auxiliary-basis factorization into 3-center integrals,
                 cheaper in memory/compute, PySCF's own real approximation).
    auxbasis     RI auxiliary basis name (e.g. "cc-pvtz-ri",
                 "def2-universal-jfit"). ``None`` lets PySCF auto-select a
                 matching auxiliary basis for the given orbital basis
                 (real PySCF behavior — confirmed via `density_fit()`'s own
                 default). Ignored for STANDARD.
    """
    method:    ERIBuilderMethod = ERIBuilderMethod.STANDARD
    auxbasis:   str | None        = None


class ERIBuilderResult(pydantic.BaseModel):
    """Output of building electron-repulsion integrals.

    energy                 total SCF energy computed with these ERIs.
    method_used             mirrors ERIBuilderConfig.method.
    auxbasis_used            the real auxiliary basis PySCF selected/used
                             (only set for RESOLUTION_OF_IDENTITY).
    """
    energy:        float
    converged:      bool
    method_used:     ERIBuilderMethod
    auxbasis_used:    str | None = None


# ---------------------------------------------------------------------------
# Orbital optimizer — real, both paths (2026-07-09)
# ---------------------------------------------------------------------------

class OrbitalOptimizerMethod(str, enum.Enum):
    """Confirmed real via PySCF: NEWTON uses ``mcscf.CASSCF``'s own internal
    second-order/augmented-Hessian orbital optimizer (verified to converge
    to exact FCI on a test system); SIMPLE parametrizes orbital rotations by
    an antisymmetric kappa matrix (``scipy.linalg.expm(kappa)`` applied to
    ``mo_coeff``), re-evaluating ``mcscf.CASCI`` at the rotated orbitals as
    a classical-minimizer objective — the standard "estimator + classical
    minimizer" split, with CASCI-at-rotated-orbitals as the real
    estimator."""
    NEWTON = "newton"
    SIMPLE = "simple"


class OrbitalOptimizerBasinHoppingConfig(pydantic.BaseModel):
    """Optional global search over kappa via ``scipy.optimize.
    basinhopping`` wrapping the SIMPLE method's objective — real scipy
    mechanism, not hand-rolled.

    active               enable basin-hopping around the SIMPLE local
                         minimizer (ignored for NEWTON).
    n_macro_iterations     number of basin-hopping steps
                         (``basinhopping(niter=...)``).
    temperature            Metropolis acceptance temperature
                         (``basinhopping(T=...)``).
    stepsize                random-displacement size for kappa between
                         hops (``basinhopping(stepsize=...)``).
    seed                    RNG seed for reproducibility
                         (``basinhopping(seed=...)``).
    """
    active:                  bool          = False
    n_macro_iterations:         int           = 20
    temperature:                  float         = 1.0
    stepsize:                      float         = 0.5
    seed:                           int | None    = None


class OrbitalOptimizerConfig(pydantic.BaseModel):
    """Input for orbital optimization ahead of/within an active-space
    calculation.

    method                    NEWTON (``mcscf.CASSCF``) or SIMPLE
                             (kappa-rotation + ``scipy.optimize.minimize``).
    active_electrons /
    active_orbitals            active-space size (feeds ``mcscf.CASSCF``/
                             ``CASCI``'s ``ncas``/``nelecas`` directly).
    basin_hopping               optional global search wrapper, SIMPLE only.
    """
    method:              OrbitalOptimizerMethod = OrbitalOptimizerMethod.NEWTON
    active_electrons:       int
    active_orbitals:         int
    basin_hopping:            OrbitalOptimizerBasinHoppingConfig = (
        OrbitalOptimizerBasinHoppingConfig()
    )


class OrbitalOptimizerResult(pydantic.BaseModel):
    """Output of an orbital optimization run.

    final_energy       CASSCF/CASCI-at-optimized-orbitals total energy
                       (Hartree).
    converged            NEWTON: ``mc.converged``; SIMPLE:
                       ``OptimizeResult.success`` (or
                       ``basinhopping``'s own convergence flag when
                       ``basin_hopping.active``).
    num_iterations         NEWTON: ``mc.niter``; SIMPLE:
                       ``OptimizeResult.nit`` (or basin-hopping's
                       ``nit``).
    kappa                    SIMPLE only: the optimized rotation-generator
                       parameters, restricted to the real non-redundant
                       core-active/core-virtual/active-virtual blocks
                       PySCF's own ``mc.uniq_var_indices()`` identifies
                       (core-core/active-active/virtual-virtual rotations
                       don't change the CASCI energy, so they're excluded,
                       same as PySCF's own CASSCF parametrization) —
                       ``None`` for NEWTON (CASSCF optimizes orbitals
                       internally, no explicit kappa vector is exposed).
    """
    final_energy:     float
    converged:          bool
    num_iterations:       int
    kappa:                  list[float] | None = None


__all__ = [
    "DMETConfig",
    "EmbeddedHamiltonianResult",
    "ERIBuilderConfig",
    "ERIBuilderMethod",
    "ERIBuilderResult",
    "OrbitalOptimizerBasinHoppingConfig",
    "OrbitalOptimizerConfig",
    "OrbitalOptimizerMethod",
    "OrbitalOptimizerResult",
    "PCMMethod",
    "ProjectionEmbeddingConfig",
    "PySCFAtomSpec",
    "PySCFCellSpec",
    "PySCFMeanFieldConfig",
    "PySCFMeanFieldMethod",
    "PySCFMeanFieldResult",
    "PySCFMoleculeSpec",
    "PySCFSolvationConfig",
    "PySCFSolvationResult",
]
