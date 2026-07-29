"""ActiveSpaceFinder (ASF) — automatic active-space selection (HQS).

ASF answers the question every quantum-chemistry benchmark has to answer
before it can run and almost none of them record: *which orbitals go in the
active space, and why?*  Its pipeline is

    1. SCF (UHF recommended, even for singlets — a broken-symmetry solution
       exposes the strong correlation the selection is looking for)
    2. MP2 natural orbitals, to pick a tractable initial orbital subspace
       (MP2 natural orbitals also sit closer to converged CASSCF orbitals
       than canonical Hartree-Fock ones)
    3. a fast, deliberately low-accuracy DMRG in that subspace, yielding
       single-orbital entropies s₁(i) and the two-electron cumulant
    4. threshold + pair analysis over those, producing *several* candidate
       active spaces rather than one

Step 4 is the part worth mirroring carefully.  ASF returns a set of
candidates keyed by (nel, norb), and choosing among them is a judgement call —
so a benchmark that reports "CAS(6,6)" without saying which candidate that
was, or what entropy threshold produced it, has not recorded a reproducible
input.

Relationship to the other active-space types in this package
------------------------------------------------------------
There are now four, and they are not redundant — they sit at different points
in the pipeline:

    ``record.VQAConfig.active_electrons`` / ``.active_orbitals``
        the two numbers, at record level, for cross-run filtering
    ``bestquark_gsopt.ActiveSpaceSpec``
        the chosen space as orbital *indices* (occupied + active)
    ``microsoft_qdk.ActiveSpaceSelectionConfig`` / ``…Result``
        one selector's inputs and outputs, spin-resolved (alpha/beta indices)
    ``ASFActiveSpace`` (here)
        the space *plus the MO coefficient matrix its indices refer to*

That last point is ASF's own emphatic warning, and it is a genuine
correctness trap: orbital indices are meaningless without the orbitals.  The
MP2-natural-orbital step reorders and remixes the MOs, so index 7 in an ASF
result is not index 7 in the preceding SCF calculation.  ``mo_coeff_ref``
below is how a record avoids losing that link; ``to_gsopt_active_space``
converts to the index-only form for callers that have the orbitals elsewhere.

Numerical arrays
----------------
``mo_coeff`` is an AO×MO matrix — for a real molecule, hundreds of thousands
of floats.  Storing it inline would make every benchmark record enormous, so
this mirror stores a *reference* (``mo_coeff_ref``: a path, checkpoint key or
content hash) plus the shape, and leaves the array itself to whatever the
caller already uses for bulk data.  This is the same choice
``molssi_qcschema`` makes for wavefunction data.

References
----------
ActiveSpaceFinder  https://github.com/HQSquantumsimulations/ActiveSpaceFinder
Docs               https://hqsquantumsimulations.github.io/ActiveSpaceFinder
Built on           PySCF (SCF/CASCI) + Block2 (DMRG, via pyscf.dmrgscf)
"""
from __future__ import annotations

import enum
import math

import pydantic

from .bestquark_gsopt import ActiveSpaceSpec

# ---------------------------------------------------------------------------
# Upstream defaults (asf/asfbase.py, asf/dmrg.py)
# ---------------------------------------------------------------------------

#: -0.1 * ln(0.25) ≈ 0.1386.  An orbital whose single-site entropy exceeds
#: this is considered correlated enough to be active.  The odd-looking form
#: is a natural-log entropy scale, not a tuned constant.
DEFAULT_ENTROPY_THRESHOLD = -0.1 * math.log(0.25)
DEFAULT_PLATEAU_THRESHOLD = 0.1
DEFAULT_REL_COMPARISON_THRESHOLD = 0.05
DEFAULT_CUMULANT_MINIMUM_THRESHOLD = 1.0e-6
#: Default DMRG bond dimension for the *selection* calculation.  Low on
#: purpose: the entropies only need to be qualitatively right, and a cheap
#: DMRG is the whole point of the screening step.
DEFAULT_DMRG_MAX_BOND_DIMENSION = 500
DEFAULT_DMRG_TOLERANCE = 1.0e-6
#: Orbital count at which the wrappers switch from exact FCI to DMRG.
DEFAULT_DMRG_SWITCH_NORB = 12


class ASFCorrelatedMethod(str, enum.Enum):
    """Which correlated method produces the entropies and cumulant.

    Both are subclasses of ASF's ``ASFBase``; the wrapper functions pick
    between them by orbital count (``switch_dmrg``, default 12).
    """
    CASCI = "casci"   # asf.casci.ASFCI  — exact FCI in the initial subspace
    DMRG  = "dmrg"    # asf.dmrg.ASFDMRG — approximate, for larger subspaces


class ASFPreselection(str, enum.Enum):
    """How the *initial* orbital subspace is chosen, before the DMRG step.

    This is a distinct decision from the final selection and is often the one
    that determines the answer: the final active space can only ever be a
    subset of the initial subspace.
    """
    MP2_NATURAL_ORBITALS = "mp2_natural_orbitals"
    RI_MP2_PAIRINFO      = "rimp2_pairinfo"    # RI-MP2 pair-correlation energies
    ALL_ORBITALS         = "all_orbitals"      # no preselection; full MO space
    USER_SUPPLIED        = "user_supplied"     # caller passed nel/norb or mo_list


class ASFSelectionMode(str, enum.Enum):
    """Which ASF entry point produced the space — they answer different questions.

    ENTROPY    ``find_from_mol`` / ``find_from_scf``: "what does the molecule
               need?"  The size is an output.
    SIZED      ``sized_space_from_mol`` / ``sized_space_from_scf``: "give me
               the best N orbitals."  The size is an input — the usual mode
               for a NISQ benchmark with a fixed qubit budget.
    MANY       ``find_many``: return every reasonable candidate, keyed by
               (nel, norb), and let the caller choose.
    """
    ENTROPY = "entropy"
    SIZED   = "sized"
    MANY    = "many"


# ---------------------------------------------------------------------------
# The active space itself
# ---------------------------------------------------------------------------

class ASFActiveSpace(pydantic.BaseModel):
    """ASF's ``ActiveSpace`` — electrons, orbital indices, and their basis.

    nel           active electrons
    mo_list       active MO indices, 0-based, referring to the *columns of the
                  MO coefficient matrix identified by ``mo_coeff_ref``* —
                  not to any other calculation's orbitals
    mo_coeff_ref  reference to that matrix (file path, checkpoint key, or
                  content hash).  ASF's documentation is blunt about this:
                  "one should not attempt to combine the list of MO indices
                  with orbitals originating from an SCF calculation or
                  elsewhere".  A space without its orbitals is not a
                  reproducible input.
    mo_coeff_shape  (n_ao, n_mo) of that matrix, so a reader can sanity-check
                  the reference resolves to the right thing

    ``norb`` is derived, matching upstream, where it is ``len(mo_list)``.
    """
    nel:            int
    mo_list:        list[int]
    mo_coeff_ref:   str | None            = None
    mo_coeff_shape: tuple[int, int] | None = None

    @pydantic.model_validator(mode="after")
    def _validate(self) -> ASFActiveSpace:
        if self.nel < 0:
            raise ValueError(f"active electron count must be non-negative, got {self.nel}")
        if len(set(self.mo_list)) != len(self.mo_list):
            raise ValueError(f"mo_list contains duplicate indices: {self.mo_list}")
        if any(i < 0 for i in self.mo_list):
            raise ValueError(f"negative MO index in mo_list: {self.mo_list}")
        if self.mo_coeff_shape is not None:
            n_ao, n_mo = self.mo_coeff_shape
            if n_mo > n_ao:
                raise ValueError(
                    f"more MOs ({n_mo}) than AOs ({n_ao}); bad MO coefficient matrix?"
                )
            if self.mo_list and max(self.mo_list) >= n_mo:
                raise ValueError(
                    f"mo_list index {max(self.mo_list)} outside the "
                    f"{n_mo}-column MO coefficient matrix"
                )
        if self.nel > 2 * len(self.mo_list):
            raise ValueError(
                f"{self.nel} electrons cannot fit in {len(self.mo_list)} spatial "
                "orbitals (max 2 per orbital)"
            )
        return self

    @property
    def norb(self) -> int:
        return len(self.mo_list)

    @property
    def cas_label(self) -> str:
        """The conventional ``CAS(nel,norb)`` label."""
        return f"CAS({self.nel},{self.norb})"

    @property
    def num_qubits_jordan_wigner(self) -> int:
        """Qubits needed under a spin-orbital mapping: 2 × norb."""
        return 2 * self.norb

    def to_active_indices(self, mo_list: list[int]) -> list[int]:
        """Map full-space MO indices onto positions within the active space."""
        return [self.mo_list.index(i) for i in mo_list]

    def from_active_indices(self, mo_list: list[int]) -> list[int]:
        """Map active-space-relative indices back onto full-space MO indices."""
        return [self.mo_list[i] for i in mo_list]

    def to_gsopt_active_space(
        self,
        occupied_indices: list[int] | None = None,
    ) -> ActiveSpaceSpec:
        """Convert to the index-only ``ActiveSpaceSpec`` used elsewhere.

        Lossy by design: ``ActiveSpaceSpec`` has nowhere to put
        ``mo_coeff_ref``, so the link back to the orbitals the indices refer
        to is dropped.  Keep this model alongside the conversion when the
        orbitals are not otherwise recorded.
        """
        return ActiveSpaceSpec(
            active_electrons=self.nel,
            active_orbitals=self.norb,
            occupied_indices=occupied_indices or [],
            active_indices=list(self.mo_list),
        )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ASFDMRGConfig(pydantic.BaseModel):
    """Settings for the screening DMRG (``ASFDMRG``, via ``pyscf.dmrgscf`` / Block2).

    max_bond_dimension  DMRG's ``maxM``.  Low on purpose (500): this run
                        exists to rank orbitals by entropy, not to produce a
                        converged energy, and its cost is what keeps the
                        whole selection tractable.
    nroots              electronic states to compute; >1 selects a space that
                        works for excited states too, which typically makes
                        it larger
    """
    max_bond_dimension: int   = DEFAULT_DMRG_MAX_BOND_DIMENSION
    tolerance:          float = DEFAULT_DMRG_TOLERANCE
    nroots:             int   = 1


class ASFSelectionConfig(pydantic.BaseModel):
    """Inputs to one ASF run — everything needed to reproduce the selection.

    mode                 which entry point was called
    requested_size       the ``size=`` argument for SIZED mode: an orbital
                         count, or an explicit (nel, norb)
    entropy_threshold    s₁(i) above which an orbital is active.  The single
                         most consequential knob, and the one a bare
                         "CAS(6,6)" hides.
    plateau_threshold    tolerance for detecting a flat region in the sorted
                         entropy spectrum — a natural cut point between
                         correlated and uncorrelated orbitals
    cumulant_threshold   minimum two-electron cumulant for an orbital pair to
                         count as a correlation partner.  This is what pulls
                         an orbital's partner into the space even when its
                         own entropy is below threshold — the reason ASF
                         produces chemically sensible spaces rather than a
                         top-N entropy list.
    max_norb / min_norb  bounds on the returned space
    switch_dmrg          orbital count above which DMRG replaces exact FCI
    """
    mode:                 ASFSelectionMode = ASFSelectionMode.ENTROPY
    method:               ASFCorrelatedMethod = ASFCorrelatedMethod.DMRG
    preselection:         ASFPreselection  = ASFPreselection.MP2_NATURAL_ORBITALS
    requested_size:       int | tuple[int, int] | None = None
    entropy_threshold:    float = DEFAULT_ENTROPY_THRESHOLD
    plateau_threshold:    float = DEFAULT_PLATEAU_THRESHOLD
    comparison_tolerance: float = DEFAULT_REL_COMPARISON_THRESHOLD
    cumulant_threshold:   float = DEFAULT_CUMULANT_MINIMUM_THRESHOLD
    max_norb:             int | None = None
    min_norb:             int | None = None
    switch_dmrg:          int = DEFAULT_DMRG_SWITCH_NORB
    dmrg:                 ASFDMRGConfig = pydantic.Field(default_factory=ASFDMRGConfig)
    #: SCF settings: ASF recommends UHF even for closed-shell singlets, and
    #: reruns unstable solutions (``asf.scf.stable_scf``) up to this many times.
    scf_method:           str = "UHF"
    scf_stability_analysis: bool = True
    max_scf_restarts:     int  = 5

    @pydantic.model_validator(mode="after")
    def _check_mode(self) -> ASFSelectionConfig:
        if self.mode == ASFSelectionMode.SIZED and self.requested_size is None:
            raise ValueError("sized selection requires requested_size")
        if (
            self.min_norb is not None and self.max_norb is not None
            and self.min_norb > self.max_norb
        ):
            raise ValueError(
                f"min_norb {self.min_norb} > max_norb {self.max_norb}"
            )
        return self


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class ASFOrbitalEntropy(pydantic.BaseModel):
    """Single-orbital entropy s₁(i) for one orbital of the initial subspace.

    mo_index    index into the MO coefficient matrix
    entropy     s₁(i); ≈0 for an orbital that is cleanly occupied or empty,
                growing toward ln(4) ≈ 1.386 for a maximally correlated one
    selected    whether it ended up in the returned active space
    """
    mo_index: int
    entropy:  float
    selected: bool = False


class ASFCandidateSpace(pydantic.BaseModel):
    """One candidate active space from ``find_many``, with its ranking data.

    ASF's distinguishing feature is returning several of these.  ``rank`` is
    the caller's ordering, ``max_entropy_excluded`` is the diagnostic that
    matters when choosing: the highest single-orbital entropy left *out* of
    this space.  A large value means the candidate cuts through correlated
    orbitals and is probably too small.
    """
    active_space:         ASFActiveSpace
    rank:                 int | None   = None
    max_entropy_excluded: float | None = None
    min_entropy_included: float | None = None


class ASFSelectionResult(pydantic.BaseModel):
    """Outcome of an ASF run.

    active_space   the selected space; None for a MANY run that only produced
                   candidates
    candidates     every space ASF considered reasonable, for MANY mode — and
                   worth storing even in ENTROPY/SIZED mode, because it shows
                   what the chosen space was chosen *over*
    entropies      per-orbital s₁(i) over the initial subspace
    initial_norb   size of the subspace the DMRG ran in.  The final space can
                   only be a subset of it, so a small initial subspace bounds
                   the answer regardless of thresholds.
    """
    config:         ASFSelectionConfig
    active_space:   ASFActiveSpace | None      = None
    candidates:     list[ASFCandidateSpace]    = []
    entropies:      list[ASFOrbitalEntropy]    = []
    initial_nel:    int | None                 = None
    initial_norb:   int | None                 = None
    scf_energy:     float | None               = None
    scf_converged:  bool | None                = None
    scf_restarts:   int                        = 0
    wall_seconds:   float | None               = None

    @pydantic.model_validator(mode="after")
    def _check_result(self) -> ASFSelectionResult:
        if self.config.mode != ASFSelectionMode.MANY and self.active_space is None:
            raise ValueError(
                f"{self.config.mode.value} selection must produce an active_space"
            )
        if self.config.mode == ASFSelectionMode.MANY and not self.candidates:
            raise ValueError("find_many selection must produce candidates")
        return self

    @property
    def selected_orbitals(self) -> list[int]:
        return list(self.active_space.mo_list) if self.active_space else []

    @property
    def max_entropy(self) -> float | None:
        """Largest single-orbital entropy over the initial subspace.

        Close to zero across the board means the molecule is single-reference
        and the whole active-space exercise buys little.
        """
        return max((e.entropy for e in self.entropies), default=None)
