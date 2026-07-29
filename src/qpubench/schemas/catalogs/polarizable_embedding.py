"""Polarizable embedding ("The Frame") schema — CPPE + PyFraME real potfile format.

Added because no qpubench schema existed for polarizable embedding at all
(unlike PCM/COSMO continuum solvation and DMET/projection-based embedding,
already modeled in ``pyscf.py``). Unlike DMET/projection embedding, both
real packages here — CPPE (github.com/maxscheurer/cppe) and PyFraME
(github.com/FraME-projects/PyFraME) — are on PyPI and confirmed installed
and working in this repo's own sandbox, wired through PySCF's own
``pyscf.solvent.PE`` bridge (``pyscf.solvent.pol_embed``).

Field names and the ``to_potfile_string()`` output format were verified
directly against PySCF's own test data
(``pyscf/solvent/test/test_pol_embed.py``, fetched from GitHub) — not
guessed — and confirmed to converge for real via
``pyscf.solvent.PE(scf.RHF(mol), {"potfile": ...})`` in this sandbox (see
``examples/demos/polarizable_embedding_frame.py``).

Schema version: 2.4.0
"""
from __future__ import annotations

import pydantic


class PolarizableEmbeddingSite(pydantic.BaseModel):
    """One embedding-potential site — one atom's worth of multipole + polarizability data.

    Field shapes and defaults match the real CPPE Potfile format.

    site_index      1-based index, must match this site's position among
                    ``PolarizableEmbeddingConfig.sites`` (potfile convention).
    element         atomic symbol, or "X" for a non-atomic dummy site.
    x / y / z       Angstrom (matches the potfile's "AA" coordinate-unit flag).
    charge          ORDER 0 multipole (point charge, a.u.).
    polarizability_xx/xy/xz/yy/yz/zz   ORDER 1 1 dipole-polarizability tensor
                    components (a.u.) — upper triangle, matches CPPE's own
                    ``Polarizability`` layout.
    excluded_sites  1-based indices of OTHER sites in the same potfile
                    excluded from this site's induced-dipole interaction
                    (EXCLISTS block) — real fragments exclude their own
                    atoms from each other; a site should never list itself.
    """
    site_index: int
    element: str
    x: float
    y: float
    z: float
    charge: float = 0.0
    polarizability_xx: float = 0.0
    polarizability_xy: float = 0.0
    polarizability_xz: float = 0.0
    polarizability_yy: float = 0.0
    polarizability_yz: float = 0.0
    polarizability_zz: float = 0.0
    excluded_sites: list[int] = []

    @pydantic.model_validator(mode="after")
    def _no_self_exclusion(self) -> PolarizableEmbeddingSite:
        if self.site_index in self.excluded_sites:
            raise ValueError(
                f"site {self.site_index} lists itself in excluded_sites "
                "(confirmed to break CPPE's induced-dipole solver — a "
                "single self-excluding site diverges rather than converging)"
            )
        return self


class PolarizableEmbeddingConfig(pydantic.BaseModel):
    """Full polarizable-embedding environment — one CPPE potfile's worth of sites.

    sites            ordered list of PolarizableEmbeddingSite.
    induced_thresh   CPPE induced-dipole SCF convergence threshold
                     (``cppe.valid_option_keys`` — confirmed real option name).
    maxiter          CPPE induced-dipole SCF iteration cap.
    """
    sites: list[PolarizableEmbeddingSite]
    induced_thresh: float = 1.0e-8
    maxiter: int = 50

    def to_potfile_string(self) -> str:
        """Emit the real CPPE Potfile format.

        Verified against PySCF's own test data and confirmed to parse and
        converge for real via ``pyscf.solvent.PE``.
        """
        lines = ["!"]
        lines.append("@COORDINATES")
        lines.append(str(len(self.sites)))
        lines.append("AA")
        for s in self.sites:
            lines.append(f"{s.element}   {s.x:.8f}   {s.y:.8f}   {s.z:.8f}   {s.site_index}")

        lines.append("@MULTIPOLES")
        lines.append("ORDER 0")
        lines.append(str(len(self.sites)))
        for s in self.sites:
            lines.append(f"{s.site_index}   {s.charge:.8f}")

        lines.append("@POLARIZABILITIES")
        lines.append("ORDER 1 1")
        lines.append(str(len(self.sites)))
        for s in self.sites:
            lines.append(
                f"{s.site_index}   {s.polarizability_xx:.8f}   {s.polarizability_xy:.8f}   "
                f"{s.polarizability_xz:.8f}   {s.polarizability_yy:.8f}   "
                f"{s.polarizability_yz:.8f}   {s.polarizability_zz:.8f}"
            )

        lines.append("EXCLISTS")
        row_width = 1 + max((len(s.excluded_sites) for s in self.sites), default=0)
        lines.append(f"{len(self.sites)} {row_width}")
        for s in self.sites:
            excl = "   ".join(str(i) for i in s.excluded_sites)
            lines.append(f"{s.site_index}   {excl}".rstrip())

        return "\n".join(lines)

    def to_pe_options(self, potfile_path: str) -> dict[str, object]:
        """The options dict ``pyscf.solvent.PE(mf, options)`` accepts directly."""
        return {
            "potfile": potfile_path,
            "induced_thresh": self.induced_thresh,
            "maxiter": self.maxiter,
        }


class PolarizableEmbeddingResult(pydantic.BaseModel):
    """Output of a polarizable-embedding SCF calculation (``pyscf.solvent.PE``).

    energy               total PE-embedded SCF energy (Hartree).
    gas_phase_energy      unsolvated reference energy, if computed.
    polarization_energy   the CPPE "Polarization"/"Electronic" energy term,
                          if extracted separately from ``with_solvent``.
    """
    energy: float
    converged: bool
    gas_phase_energy: float | None = None
    polarization_energy: float | None = None

    @property
    def embedding_shift(self) -> float | None:
        """energy - gas_phase_energy, if the gas-phase reference was computed."""
        if self.gas_phase_energy is None:
            return None
        return self.energy - self.gas_phase_energy


__all__ = [
    "PolarizableEmbeddingConfig",
    "PolarizableEmbeddingResult",
    "PolarizableEmbeddingSite",
]
