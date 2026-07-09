"""Reaction-coordinate / potential-energy-surface schema.

qpubench's `BenchmarkRunner.sweep()` runs a list of problems and returns a
flat `list[BenchmarkRecord]` — enough to *execute* a series of point
calculations, but nothing ties the points together as one reaction path:
which coordinate varied, in what order, and which points are the reactant,
product, or transition state.

This module is the typed container for that shape. It is intentionally
thin — no chemistry, no interpolation, no curve fitting — the same
"schema, not solver" boundary every other module in this package keeps.
Build `problems` however you like (a raw `CircuitSpec` per geometry, a
qubit Hamiltonian from `integrations/generic_adapt_vqe`, a QForte molecule
JSON, ...); this module only assembles the results into one object.

Computing model: not tied to any one `ComputingModel` — a reaction
coordinate is a sweep over *any* problem type qpubench already models
(molecular VQE most commonly, but nothing here assumes that).
"""
from __future__ import annotations

import pydantic

from .circuit import CircuitSpec
from .record import BenchmarkRecord


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
        """VQAConfig.final_eigenvalue if present, else the first expectation value."""
        if record.vqa is not None and record.vqa.final_eigenvalue is not None:
            return record.vqa.final_eigenvalue
        if record.result.expectation_values:
            return record.result.expectation_values[0].value
        return None

    @property
    def energies(self) -> list[float | None]:
        """Energy per point, same order as spec.coordinate_values."""
        return [self._record_energy(r) for r in self.records]

    @property
    def barrier_height(self) -> float | None:
        """energy[transition_state_index] - energy[reactant_index], if both are known."""
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
        """energy[product_index] - energy[reactant_index], if both are known."""
        product, reactant = self.spec.product_index, self.spec.reactant_index
        if product is None or reactant is None:
            return None
        energies = self.energies
        e_product, e_reactant = energies[product], energies[reactant]
        if e_product is None or e_reactant is None:
            return None
        return e_product - e_reactant

    def to_dict_for_plot(self) -> dict[str, list[float | None]]:
        """{coordinate_name: values, "energy": energies} — ready for a plotting library."""
        return {
            self.spec.coordinate_name: list(self.spec.coordinate_values),
            "energy": self.energies,
        }
