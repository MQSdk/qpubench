"""Real molecular geometries for the tutorials, as an alternative to the
illustrative toy Hamiltonians in `toy_hamiltonians.py`.

See each function's docstring for the chemistry each geometry models.
All geometries are STO-3G-appropriate (rough but chemically sane — not
DFT/MP2-optimized; the same convention used for `create_solvent_model.py`
etc.: real chemistry, illustrative precision).

Every geometry function returns the real
``list[(symbol, (x, y, z))]`` shape ``openfermion.chem.MolecularData``
(and this repo's own
``qpubench.hamiltonian_sources.ab_initio.build_qubit_hamiltonian``)
expects, in Angstrom.
"""
from __future__ import annotations

Geometry = list[tuple[str, tuple[float, float, float]]]

# ---------------------------------------------------------------------------
# Butyronitrile Dissociation — real molecule, real bond (github: butyronitrile-
# tutorial/butyronitrile_dissociation.ipynb confirms: n-butyronitrile,
# dissociates the C#N bond specifically, STO-3G, real active space is 8
# orbitals/8 electrons = 16 qubits, 9-frame scan).
# ---------------------------------------------------------------------------

BUTYRONITRILE_BASIS = "sto-3g"
# Reduced active space actually run through this repo's toy ADAPT-VQE engine
# (a real 16-qubit/5793-term Hamiltonian was confirmed to build in 0.26s,
# but that's too many terms for the toy engine's dense-matrix-per-call
# approach to run ADAPT-VQE against in reasonable time — same class as the
# already-confirmed 12-qubit/631-term LiH timeout).
BUTYRONITRILE_ACTIVE_ELECTRONS = 2
BUTYRONITRILE_ACTIVE_ORBITALS = 2
# The full active space — used once for a capability check
# (build only, don't run ADAPT-VQE on it).
BUTYRONITRILE_REAL_ACTIVE_ELECTRONS = 8
BUTYRONITRILE_REAL_ACTIVE_ORBITALS = 8


def butyronitrile_geometry(cn_distance: float = 1.16) -> Geometry:
    """n-butyronitrile, CH3-CH2-CH2-C#N. `cn_distance` is the
    dissociation coordinate (the nitrile C#N bond length, Angstrom);
    1.16 A is the real equilibrium nitrile C#N bond length.
    """
    return [
        ("C", (0.00, 0.00, 0.00)),
        ("N", (0.00, 0.00, cn_distance)),
        ("C", (1.50, 0.00, -0.40)),
        ("C", (2.20, 1.30, -0.05)),
        ("C", (3.70, 1.35, -0.45)),
        ("H", (1.55, -0.15, -1.48)),
        ("H", (2.00, -0.85, -0.02)),
        ("H", (1.75, 2.15, -0.55)),
        ("H", (2.15, 1.45, 1.03)),
        ("H", (4.20, 0.50, -0.02)),
        ("H", (4.25, 2.24, -0.15)),
        ("H", (3.75, 1.30, -1.54)),
    ]


# ---------------------------------------------------------------------------
# Dehalogenase Reaction (SN2) — the haloalkane dehalogenase active site is
# a carboxylate nucleophile (two oxygens) attacking a C-Cl carbon, i.e. the
# Asp-mediated haloalkane dehalogenase mechanism (ester-intermediate SN2).
# CH3Cl + formate (HCOO-) models that carboxylate attack.
# ---------------------------------------------------------------------------

DEHALOGENASE_BASIS = "sto-3g"
DEHALOGENASE_CHARGE = -1
DEHALOGENASE_ACTIVE_ELECTRONS = 2
DEHALOGENASE_ACTIVE_ORBITALS = 2

_CL_BONDED, _CL_BROKEN = 1.78, 3.50   # C-Cl: intact -> broken
_O_FAR, _O_BONDED = 3.50, 1.40         # nucleophile O: far -> new bond formed


def dehalogenase_sn2_geometry(progress: float) -> Geometry:
    """CH3Cl + HCOO- backside-attack SN2 geometry.

    `progress` in [0, 1]: 0 = reactant (C-Cl intact, nucleophile far,
    opposite side of Cl along the same axis — real SN2 backside-attack
    geometry), 1 = product (C-Cl broken, new C-O bond formed).
    """
    d_cl = _CL_BONDED + progress * (_CL_BROKEN - _CL_BONDED)
    d_o = _O_FAR - progress * (_O_FAR - _O_BONDED)
    return [
        ("C", (0.0, 0.0, 0.0)),
        ("Cl", (0.0, 0.0, d_cl)),
        ("H", (1.02, 0.0, -0.36)),
        ("H", (-0.51, 0.88, -0.36)),
        ("H", (-0.51, -0.88, -0.36)),
        ("C", (0.0, 0.0, -(d_o + 1.25))),
        ("O", (0.0, 1.1, -(d_o + 1.25) - 0.4)),
        ("O", (0.0, 0.0, -d_o)),   # the attacking oxygen
        ("H", (0.0, -1.1, -(d_o + 1.25) - 0.4)),
    ]


# ---------------------------------------------------------------------------
# Covalent Ligand Binding — cathepsin K is targeted by reversible +
# irreversible covalent inhibitors. Its covalent warheads are nitrile
# groups reacting with the catalytic cysteine thiol (thioimidate
# formation). CH3CN + CH3SH models that.
# ---------------------------------------------------------------------------

COVALENT_LIGAND_BASIS = "sto-3g"
COVALENT_LIGAND_ACTIVE_ELECTRONS = 2
COVALENT_LIGAND_ACTIVE_ORBITALS = 2

BOUND_CS_DISTANCE = 1.85     # real C-S single-bond length (thioimidate formed)
UNBOUND_CS_DISTANCE = 4.5    # well-separated, non-interacting


def covalent_ligand_geometry(c_s_distance: float) -> Geometry:
    """CH3-C#N (nitrile warhead) + CH3-SH (cysteine thiol surrogate),
    approaching along the nitrile-carbon...sulfur axis (the real bond a
    nitrile-warhead covalent inhibitor forms with a catalytic cysteine).
    """
    s_z = -c_s_distance
    return [
        ("C", (0.0, 0.0, 0.0)),
        ("C", (0.0, 0.0, 1.46)),
        ("N", (0.0, 0.0, 2.62)),
        ("H", (1.02, 0.0, -0.36)),
        ("H", (-0.51, 0.88, -0.36)),
        ("H", (-0.51, -0.88, -0.36)),
        ("S", (0.0, 0.0, s_z)),
        ("C", (1.5, 0.0, s_z - 0.5)),
        ("H", (1.5, 0.0, s_z - 1.6)),
        ("H", (2.0, 0.87, s_z - 0.1)),
        ("H", (2.0, -0.87, s_z - 0.1)),
        ("H", (-0.6, 0.8, s_z + 0.4)),
    ]


# ---------------------------------------------------------------------------
# Carbon Capture with COF-999 — a simplified, illustrative model of the
# amine-CO2 binding/carbamate-formation chemistry that COF-999's
# amine-functionalized pores exploit, not COF-999's own binding site.
# ---------------------------------------------------------------------------

CARBON_CAPTURE_BASIS = "sto-3g"
CARBON_CAPTURE_ACTIVE_ELECTRONS = 2
CARBON_CAPTURE_ACTIVE_ORBITALS = 2

BOUND_CN_DISTANCE = 2.00     # closest sterically-sane approach along this axis (verified: shorter
                              # distances start climbing back up in energy at STO-3G/this geometry)
UNBOUND_CN_DISTANCE = 4.5    # well-separated, non-interacting


def carbon_capture_geometry(c_n_distance: float) -> Geometry:
    """CO2 + NH3, N approaching the electrophilic CO2 carbon along the
    x-axis — perpendicular to the linear O-C-O axis (z), so the
    incoming amine never collides with either oxygen regardless of
    `c_n_distance` (unlike a colinear approach, which clashes with the
    nearer oxygen well before reaching a bonding-relevant N...C distance).
    Models the first step of carbamate formation — the mechanism
    amine-functionalized CO2 sorbents like COF-999 use.
    """
    return [
        ("C", (0.0, 0.0, 0.0)),
        ("O", (0.0, 0.0, 1.16)),
        ("O", (0.0, 0.0, -1.16)),
        ("N", (c_n_distance, 0.0, 0.0)),
        ("H", (c_n_distance + 0.6, 0.94, 0.0)),
        ("H", (c_n_distance + 0.6, -0.47, 0.82)),
        ("H", (c_n_distance + 0.6, -0.47, -0.82)),
    ]


__all__ = [
    "BOUND_CN_DISTANCE",
    "BOUND_CS_DISTANCE",
    "BUTYRONITRILE_ACTIVE_ELECTRONS",
    "BUTYRONITRILE_ACTIVE_ORBITALS",
    "BUTYRONITRILE_BASIS",
    "BUTYRONITRILE_REAL_ACTIVE_ELECTRONS",
    "BUTYRONITRILE_REAL_ACTIVE_ORBITALS",
    "CARBON_CAPTURE_ACTIVE_ELECTRONS",
    "CARBON_CAPTURE_ACTIVE_ORBITALS",
    "CARBON_CAPTURE_BASIS",
    "COVALENT_LIGAND_ACTIVE_ELECTRONS",
    "COVALENT_LIGAND_ACTIVE_ORBITALS",
    "COVALENT_LIGAND_BASIS",
    "DEHALOGENASE_ACTIVE_ELECTRONS",
    "DEHALOGENASE_ACTIVE_ORBITALS",
    "DEHALOGENASE_BASIS",
    "DEHALOGENASE_CHARGE",
    "UNBOUND_CN_DISTANCE",
    "UNBOUND_CS_DISTANCE",
    "Geometry",
    "butyronitrile_geometry",
    "carbon_capture_geometry",
    "covalent_ligand_geometry",
    "dehalogenase_sn2_geometry",
]
