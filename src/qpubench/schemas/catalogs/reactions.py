"""Reaction-pathway analysis: PES sweeps, real chemical-kinetics data
(Cantera-style mechanisms), and quantum-to-classical rate-constant
bridging (PennyLane-style).

Not a framework-core type — like `hamiltonian_library.py`/`contraction_path.py`,
this module bridges several real external tools rather than being a shape
qpubench invented outright:

  - **Cantera** (https://cantera.org) — `ReactionMechanism` /
    `KineticsSpeciesSpec` / `KineticsReactionSpec` / `ArrheniusRateConstant`
    follow Cantera's own YAML mechanism format field-for-field: species
    `composition` mapping, reaction `equation` string, modified-Arrhenius
    `rate-constant` `{A, b, Ea}`, `type` (`elementary`/`three-body`/
    `falloff`), third-body `efficiencies`. `ReactionMechanism.to_cantera_yaml()`
    produces text `cantera.Solution(yaml=...)` loads and evaluates for
    real — verified in this repo's own sandbox (`cantera==3.2.0`) for all
    three reaction types, including two real Cantera conventions that are
    easy to get wrong:

    1. **Cantera's default `quantity` unit is `kmol`, not `mol`.** An
       `Ea` value written assuming J/mol is silently reinterpreted as
       J/kmol (1000x smaller) unless the YAML declares
       `units: {quantity: mol, activation-energy: J/mol}` — confirmed by
       loading the *same* `rate-constant: {A: 1e13, b: 0, Ea: 50000}`
       twice, with and without that `units` block: `rate(1000 K)` comes
       back `9.94e12` (wrong) vs. `2.45e10` (correct, matches this
       module's own `ArrheniusRateConstant.rate_at()` to full precision).
       `to_cantera_dict()` always emits that `units` block so this can't
       silently happen.
    2. **Three-body/falloff reactions need an explicit third-body marker
       in the `equation` string itself** (`+ M` for three-body, `(+M)`
       for falloff) — `type: three-body` alone does not imply it. This
       schema doesn't generate the marker (it doesn't parse/write chemical
       equations, same "schema, not solver" boundary as everywhere else in
       this package) — the caller's `equation` string must include it.

    No thermo (NASA7 polynomials) or transport data is modeled — Cantera
    happily loads and evaluates reaction *rate constants* without them
    (verified: `gas.reaction(0).rate(T)` works with no species thermo at
    all), it's only whole-phase thermodynamic/equilibrium calculations
    that need it. This schema exists to package kinetics *for* Cantera,
    not to reimplement Cantera.

  - **PennyLane's chemical-reactions demo**
    (https://pennylane.ai/demos/tutorial_chemical_reactions) —
    `ReactionPathResult.rate_constant()`/`.to_arrhenius_rate_constant()`
    are the same construction the demo uses: scan a bond length or
    reaction coordinate, find the potential-energy-surface barrier
    (highest point relative to the reactant), and convert that barrier
    into a classical Arrhenius rate constant `k = A * exp(-Ea / RT)`.
    `ReactionCoordinateSpec`/`ReactionPathResult` below are what ties a
    `BenchmarkRunner.sweep()` of quantum energy calculations into one such
    PES scan in the first place — `BenchmarkRunner.sweep()` itself only
    returns a flat `list[BenchmarkRecord]`, with nothing recording which
    coordinate varied, in what order, or which points are the reactant,
    product, or transition state.

  - **Cebule SDK's `RXN_OPT` / catalyst-design tasks**
    (`mqsdk_cebule.py`, docs.mqs.dk's "RN Catalyst Design" section) — a
    complementary, coarser-grained concept: optimizing flux through a
    whole reaction *network* under fixed/unit cost constraints, rather
    than computing one reaction's energetics from a PES scan. A
    `ReactionPathResult.rate_constant()` could reasonably inform an
    `RXNOptInput` reaction's cost bounds, but the two schemas serve
    different granularities (one path's energetics vs. a whole network's
    flux) and aren't merged into one type here.

Still no chemistry solved in this module itself — `problems` in
`ReactionCoordinateSpec` can be built however you like (a raw `CircuitSpec`
per geometry, a qubit Hamiltonian from `integrations/generic_adapt_vqe`, a
QForte molecule JSON, ...); this module only assembles results into one
object, and converts an already-computed barrier into standard kinetics
parameters.

Computing model: not tied to any one `ComputingModel` — a reaction
coordinate is a sweep over *any* problem type qpubench already models
(molecular VQE most commonly, but nothing here assumes that).
"""
from __future__ import annotations

import enum
import math
from typing import Any

import pydantic

from ..circuit import CircuitSpec
from ..record import BenchmarkRecord

# CODATA 2018 values — matches scipy.constants.physical_constants["Hartree
# energy"][0], .N_A, and .R (cross-checked in this repo's own sandbox).
_HARTREE_TO_J = 4.359744722206e-18
_AVOGADRO = 6.02214076e23
_HARTREE_TO_J_PER_MOL = _HARTREE_TO_J * _AVOGADRO
_GAS_CONSTANT_J_PER_MOL_K = 8.31446261815324


class ReactionCoordinateSpec(pydantic.BaseModel):
    """One reaction path: an ordered sweep over a scalar coordinate.

    label              human-readable name, e.g. "N-Cl bond dissociation"
    coordinate_name    what varies, e.g. "bond_length_angstrom", "dihedral_deg"
    coordinate_values  ordered scalar values, one per point
    problems           one CircuitSpec per point, same order/length as
                        coordinate_values (typically MOLECULE_JSON or a
                        bound VQE ansatz — whatever the energy source needs)
    reactant_index      index into coordinate_values marking the reactant
    product_index       index into coordinate_values marking the product
    transition_state_index  index into coordinate_values marking the
                        highest-energy point along the path, if known
                        ahead of time (leave unset and use
                        ReactionPathResult to find it from computed energies)
    """
    label:                    str
    coordinate_name:          str
    coordinate_values:        list[float]
    problems:                 list[CircuitSpec]
    reactant_index:           int | None = None
    product_index:            int | None = None
    transition_state_index:   int | None = None

    @pydantic.model_validator(mode="after")
    def _check_lengths(self) -> ReactionCoordinateSpec:
        if len(self.problems) != len(self.coordinate_values):
            raise ValueError(
                "problems and coordinate_values must be the same length "
                f"(got {len(self.problems)} problems, "
                f"{len(self.coordinate_values)} coordinate_values)"
            )
        for name, idx in (
            ("reactant_index", self.reactant_index),
            ("product_index", self.product_index),
            ("transition_state_index", self.transition_state_index),
        ):
            if idx is not None and not (0 <= idx < len(self.coordinate_values)):
                raise ValueError(
                    f"{name}={idx} out of range for "
                    f"{len(self.coordinate_values)} coordinate_values"
                )
        return self


class ArrheniusRateConstant(pydantic.BaseModel):
    """Modified-Arrhenius rate-constant parameters — Cantera's own
    `rate-constant` shape: `k(T) = A * T**b * exp(-Ea / (R*T))`.

    A   pre-exponential factor. Units depend on reaction order/molecularity
        (Cantera convention: s^-1 for unimolecular, m^3/kmol/s-style for
        bimolecular, etc.) — this schema doesn't infer order from
        `equation`, same as Cantera itself doesn't without parsing it.
    b   temperature exponent (0.0 for simple, unmodified Arrhenius)
    Ea  activation energy, **J/mol** (this schema's own fixed unit choice
        — always emitted with an explicit `units` declaration in
        `to_cantera_dict()` so Cantera never falls back to its own
        kmol-based default; see module docstring).
    """
    A:  float
    b:  float = 0.0
    Ea: float

    def rate_at(self, temperature_k: float) -> float:
        """k(T) = A * T**b * exp(-Ea / (R T)) — the real modified-Arrhenius law.

        Verified against real Cantera (`ArrheniusRate.__call__`) to full
        float precision for A=1e13, b=0, Ea=50000 J/mol at T=1000 K.
        """
        return float(
            self.A
            * temperature_k**self.b
            * math.exp(-self.Ea / (_GAS_CONSTANT_J_PER_MOL_K * temperature_k))
        )

    def to_cantera_dict(self) -> dict[str, float]:
        """`{"A": ..., "b": ..., "Ea": ...}` — Cantera's own `rate-constant` mapping."""
        return {"A": self.A, "b": self.b, "Ea": self.Ea}


class ReactionType(str, enum.Enum):
    """Cantera reaction `type` field — the three most common parameterizations."""
    ELEMENTARY = "elementary"
    THREE_BODY = "three-body"
    FALLOFF = "falloff"


class KineticsSpeciesSpec(pydantic.BaseModel):
    """One Cantera-style species: name + elemental composition.

    composition   element symbol -> count, e.g. {"C": 1, "H": 4} for
                  methane (Cantera's own `composition` mapping shape)
    charge        net charge, elementary charges (0 for neutral species)
    """
    name:        str
    composition: dict[str, float]
    charge:      int = 0

    def to_cantera_dict(self) -> dict[str, Any]:
        """Cantera YAML-compatible species mapping (one `species:` list entry)."""
        entry: dict[str, Any] = {"name": self.name, "composition": self.composition}
        if self.charge:
            entry["charge"] = self.charge
        return entry


class KineticsReactionSpec(pydantic.BaseModel):
    """One Cantera-style elementary/three-body/falloff reaction.

    equation             Cantera equation syntax, e.g. "O2 + CO <=> O + CO2"
                          (`<=>` reversible, `=>` irreversible). Three-body
                          reactions need an explicit `+ M` in the equation;
                          falloff reactions need `(+M)` — see module docstring.
    type                  ELEMENTARY (default) | THREE_BODY | FALLOFF
    rate_constant         modified-Arrhenius parameters — the high-pressure
                          limit for FALLOFF, the only rate for the other two
    low_p_rate_constant   low-pressure-limit Arrhenius params, FALLOFF only
    efficiencies          third-body collision efficiencies, THREE_BODY/
                          FALLOFF only (species name -> efficiency — must
                          reference species already declared in the
                          enclosing ReactionMechanism, or Cantera rejects
                          the mechanism at load time)
    reversible            whether the reaction runs both directions
    """
    equation:            str
    type:                ReactionType = ReactionType.ELEMENTARY
    rate_constant:       ArrheniusRateConstant
    low_p_rate_constant: ArrheniusRateConstant | None = None
    efficiencies:        dict[str, float] = {}
    reversible:          bool = True

    @pydantic.model_validator(mode="after")
    def _check_falloff(self) -> KineticsReactionSpec:
        if self.type == ReactionType.FALLOFF and self.low_p_rate_constant is None:
            raise ValueError(
                "type=FALLOFF requires low_p_rate_constant "
                "(Cantera's low-P-rate-constant; rate_constant supplies the high-P limit)"
            )
        return self

    def to_cantera_dict(self) -> dict[str, Any]:
        """Cantera YAML-compatible reaction mapping (one `reactions:` list entry)."""
        equation = self.equation if self.reversible else self.equation.replace("<=>", "=>")
        entry: dict[str, Any] = {"equation": equation}
        if self.type == ReactionType.FALLOFF:
            assert self.low_p_rate_constant is not None
            entry["type"] = self.type.value
            entry["low-P-rate-constant"] = self.low_p_rate_constant.to_cantera_dict()
            entry["high-P-rate-constant"] = self.rate_constant.to_cantera_dict()
        else:
            if self.type != ReactionType.ELEMENTARY:
                entry["type"] = self.type.value
            entry["rate-constant"] = self.rate_constant.to_cantera_dict()
        if self.efficiencies:
            entry["efficiencies"] = dict(self.efficiencies)
        return entry


class ReactionMechanism(pydantic.BaseModel):
    """Cantera-style reaction mechanism: one phase's species + reactions.

    Real, Cantera-loadable shape — `to_cantera_yaml()` produces text
    `cantera.Solution(yaml=...)` can evaluate rate constants from directly
    (verified in this repo's own sandbox, all three ReactionType values).
    Deliberately thin: no thermo (NASA7) or transport data, since qpubench
    itself never computes classical kinetics — this schema packages
    results *for* Cantera, not a reimplementation of it.

    phase_name      Cantera `name` field for the phase
    thermo_model    Cantera `thermo` field, e.g. "ideal-gas"
    kinetics_model  Cantera `kinetics` field, e.g. "gas"
    species         list of KineticsSpeciesSpec
    reactions       list of KineticsReactionSpec
    """
    phase_name:     str
    thermo_model:   str = "ideal-gas"
    kinetics_model: str = "gas"
    species:        list[KineticsSpeciesSpec]
    reactions:      list[KineticsReactionSpec]

    def to_cantera_dict(self) -> dict[str, Any]:
        """Full Cantera YAML document structure: `phases`/`species`/`reactions`.

        Always declares `units: {quantity: mol, activation-energy: J/mol}`
        explicitly — Cantera's own default `quantity` unit is `kmol`, which
        silently reinterprets an `Ea` meant as J/mol as J/kmol (1000x too
        small an activation energy) if left unstated. See module docstring.
        """
        return {
            "units": {"quantity": "mol", "activation-energy": "J/mol"},
            "phases": [
                {
                    "name": self.phase_name,
                    "thermo": self.thermo_model,
                    "kinetics": self.kinetics_model,
                    "species": [s.name for s in self.species],
                    "reactions": "all",
                }
            ],
            "species": [s.to_cantera_dict() for s in self.species],
            "reactions": [r.to_cantera_dict() for r in self.reactions],
        }

    def to_cantera_yaml(self) -> str:
        """Serialize to a Cantera-loadable YAML mechanism file.

        Deferred import (`pip install pyyaml`) — this schema module has no
        hard dependency beyond pydantic, matching every other schema module
        in this package.
        """
        import yaml

        return str(yaml.safe_dump(self.to_cantera_dict(), sort_keys=False))


class ReactionPathResult(pydantic.BaseModel):
    """Assembled result of running a ReactionCoordinateSpec through the runner.

    spec       the ReactionCoordinateSpec that was run
    records    one BenchmarkRecord per point, same order/length as
               spec.coordinate_values (pass them in the order returned by
               BenchmarkRunner.sweep() when sweeping spec.problems)
    """
    spec:    ReactionCoordinateSpec
    records: list[BenchmarkRecord]

    @pydantic.model_validator(mode="after")
    def _check_lengths(self) -> ReactionPathResult:
        if len(self.records) != len(self.spec.coordinate_values):
            raise ValueError(
                "records and spec.coordinate_values must be the same length "
                f"(got {len(self.records)} records, "
                f"{len(self.spec.coordinate_values)} coordinate_values)"
            )
        return self

    @staticmethod
    def _record_energy(record: BenchmarkRecord) -> float | None:
        """VQAResult.final_eigenvalue if present, else the first expectation value."""
        if record.vqa_result is not None and record.vqa_result.final_eigenvalue is not None:
            return record.vqa_result.final_eigenvalue
        if record.result.expectation_values:
            return record.result.expectation_values[0].value
        return None

    @property
    def energies(self) -> list[float | None]:
        """Energy per point, same order as spec.coordinate_values."""
        return [self._record_energy(r) for r in self.records]

    @property
    def barrier_height(self) -> float | None:
        """energy[transition_state_index] - energy[reactant_index], in Hartree,
        if both are known."""
        ts, reactant = self.spec.transition_state_index, self.spec.reactant_index
        if ts is None or reactant is None:
            return None
        energies = self.energies
        e_ts, e_reactant = energies[ts], energies[reactant]
        if e_ts is None or e_reactant is None:
            return None
        return e_ts - e_reactant

    @property
    def reaction_energy(self) -> float | None:
        """energy[product_index] - energy[reactant_index], in Hartree,
        if both are known."""
        product, reactant = self.spec.product_index, self.spec.reactant_index
        if product is None or reactant is None:
            return None
        energies = self.energies
        e_product, e_reactant = energies[product], energies[reactant]
        if e_product is None or e_reactant is None:
            return None
        return e_product - e_reactant

    def rate_constant(self, temperature_k: float, prefactor_hz: float = 1.0e13) -> float | None:
        """Classical Arrhenius rate constant from `barrier_height` at
        `temperature_k`, the same construction as PennyLane's
        chemical-reactions demo: convert a quantum-computed activation
        barrier into `k = A * exp(-Ea / RT)`.

        prefactor_hz   pre-exponential factor A, Hz. Default 1e13 is a
                       typical transition-state-theory/vibrational-attempt-
                       frequency order of magnitude, not a fitted value —
                       pass a real one if you have it.
        """
        rate = self.to_arrhenius_rate_constant(prefactor_hz)
        return rate.rate_at(temperature_k) if rate is not None else None

    def to_arrhenius_rate_constant(self, prefactor_hz: float = 1.0e13) -> ArrheniusRateConstant | None:
        """Package `barrier_height` (Hartree) as a Cantera-compatible
        ArrheniusRateConstant (b=0, Ea converted to J/mol) — the bridge from
        a quantum-computed reaction path to a `KineticsReactionSpec.rate_constant`
        usable in a `ReactionMechanism`.
        """
        barrier = self.barrier_height
        if barrier is None:
            return None
        return ArrheniusRateConstant(A=prefactor_hz, b=0.0, Ea=barrier * _HARTREE_TO_J_PER_MOL)

    def to_dict_for_plot(self) -> dict[str, list[float | None]]:
        """{coordinate_name: values, "energy": energies} — ready for a plotting library."""
        return {
            self.spec.coordinate_name: list(self.spec.coordinate_values),
            "energy": self.energies,
        }


__all__ = [
    "ArrheniusRateConstant",
    "KineticsReactionSpec",
    "KineticsSpeciesSpec",
    "ReactionCoordinateSpec",
    "ReactionMechanism",
    "ReactionPathResult",
    "ReactionType",
]
