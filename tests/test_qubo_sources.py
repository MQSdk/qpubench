"""Tests for hamiltonian_sources/qubo.py.

Split into two halves:

- Offline tests run always. They exercise the parsers, the Ising conversion and
  the Max-Cut inversion against small fixtures written inline, so CI needs no
  network.
- Network tests are marked and skipped unless QPUBENCH_NETWORK_TESTS=1, because
  they download from OR-Library and MQLib. They are the ones that pin the real
  file formats, so run them when touching a parser.
"""

from __future__ import annotations

import json
import os

import pytest

from qpubench.hamiltonian_sources.qubo import (
    QUBOInstance,
    _maxcut_to_qubo,
    _parse_mqlib,
    _parse_orlib,
    read_bqpjson,
    read_qubo_file,
)

requires_network = pytest.mark.skipif(
    os.environ.get("QPUBENCH_NETWORK_TESTS") != "1",
    reason="downloads from OR-Library / MQLib; set QPUBENCH_NETWORK_TESTS=1 to run",
)


def _brute_force_minimum(instance: QUBOInstance) -> tuple[float, tuple[int, ...]]:
    """Exhaustive minimum — only for the tiny instances used here."""
    import itertools

    best_value = float("inf")
    best_bits: tuple[int, ...] = ()
    for bits in itertools.product((0, 1), repeat=instance.num_variables):
        value = instance.objective(list(bits))
        if value < best_value:
            best_value, best_bits = value, bits
    return best_value, best_bits


def _ising_energy(observable, offset: float, bits) -> float:
    """Evaluate a Z/ZZ observable at a computational-basis state."""
    z = {i: 1 - 2 * b for i, b in enumerate(bits)}
    energy = offset
    for term in observable.terms:
        product = term.coefficient.re
        for qubit in term.qubit_indices:
            product *= z[qubit]
        energy += product
    return energy


# ---------------------------------------------------------------------------
# Ising conversion — the bridge to the rest of the framework
# ---------------------------------------------------------------------------

class TestIsingConversion:
    def test_conversion_is_exact_on_every_assignment(self) -> None:
        """x_i = (1 - z_i)/2 is a change of variable, so energies must match."""
        instance = QUBOInstance(
            name="toy", num_variables=4,
            linear={0: 2.0, 2: -3.5},
            quadratic={"0,1": -1.0, "1,2": 4.0, "0,3": 0.5, "2,3": -2.25},
        )
        observable, offset = instance.to_ising_observable()

        import itertools

        for bits in itertools.product((0, 1), repeat=4):
            assert instance.objective(list(bits)) == pytest.approx(
                _ising_energy(observable, offset, bits)
            )

    def test_ground_state_is_the_qubo_optimum(self) -> None:
        instance = QUBOInstance(
            name="toy", num_variables=5,
            linear={0: 1.0, 3: -2.0},
            quadratic={"0,1": -3.0, "1,2": 2.0, "2,3": -1.5, "3,4": 4.0},
        )
        observable, offset = instance.to_ising_observable()
        best_value, best_bits = _brute_force_minimum(instance)

        assert _ising_energy(observable, offset, best_bits) == pytest.approx(best_value)

    def test_offset_is_returned_not_folded_into_an_identity_term(self) -> None:
        """A constant hidden in the observable breaks energy comparisons."""
        instance = QUBOInstance(name="c", num_variables=2, linear={0: 6.0})
        observable, offset = instance.to_ising_observable()

        assert offset == pytest.approx(3.0)
        assert all(term.qubit_indices for term in observable.terms)

    def test_zero_coefficients_produce_no_terms(self) -> None:
        instance = QUBOInstance(name="empty", num_variables=3)
        observable, offset = instance.to_ising_observable()

        assert observable.terms == []
        assert offset == 0.0


# ---------------------------------------------------------------------------
# Parsers, against inline fixtures
# ---------------------------------------------------------------------------

class TestOrlibParser:
    _FIXTURE = "2\n3 4\n1 1 5\n1 2 -3\n2 3 7\n3 3 2\n2 2\n1 2 4\n2 2 -6\n"

    def test_parses_every_bundled_instance(self) -> None:
        instances = _parse_orlib(self._FIXTURE, "bqptest")
        assert [i.name for i in instances] == ["bqptest.1", "bqptest.2"]
        assert [i.num_variables for i in instances] == [3, 2]

    def test_indices_shift_from_one_based_to_zero_based(self) -> None:
        first = _parse_orlib(self._FIXTURE, "bqptest")[0]
        assert set(first.linear) == {0, 2}
        assert set(first.quadratic) == {"0,1", "1,2"}

    def test_published_maximise_form_is_negated_to_minimise(self) -> None:
        first = _parse_orlib(self._FIXTURE, "bqptest")[0]
        assert first.linear[0] == -5.0
        assert first.quadratic["0,1"] == 3.0


class TestMqlibParser:
    _FIXTURE = (
        "# NAME: toy\n# COMMENT: converted\n"
        "4 3\n1 2 10\n2 3 -4\n3 4 7\n"
    )

    def test_comments_are_skipped_and_header_read(self) -> None:
        instance = _parse_mqlib(self._FIXTURE, "toy")
        assert instance.num_variables == 4
        assert instance.quadratic == {"0,1": 10.0, "1,2": -4.0, "2,3": 7.0}

    def test_maxcut_inversion_drops_the_reference_node(self) -> None:
        recovered = _maxcut_to_qubo(_parse_mqlib(self._FIXTURE, "toy"))
        assert recovered.num_variables == 3
        assert recovered.name == "toy.qubo"

    def test_inversion_subtracts_the_row_sum_from_the_diagonal(self) -> None:
        """w_ir = Q_ii + sum_j Q_ij, so the row sum must come back out.

        Node 3 (0-indexed 2) has reference weight 7 and one non-reference edge
        of weight -4, so its diagonal is -(7 + -4) = -3. Reading w_ir alone
        would wrongly give -7.
        """
        recovered = _maxcut_to_qubo(_parse_mqlib(self._FIXTURE, "toy"))
        assert recovered.linear[2] == pytest.approx(-3.0)
        assert recovered.quadratic == {"0,1": 10.0, "1,2": -4.0}


class TestInterchangeFormats:
    def test_qubo_file_indices_stay_zero_based(self, tmp_path) -> None:
        path = tmp_path / "toy.qubo"
        path.write_text(
            "c a comment\np qubo 0 3 2 1\n0 0 1.5\n2 2 -2.0\n0 2 3.0\n",
            encoding="utf-8",
        )
        instance = read_qubo_file(path)

        assert instance.num_variables == 3
        assert instance.linear == {0: 1.5, 2: -2.0}
        assert instance.quadratic == {"0,2": 3.0}

    def test_qubo_file_without_a_program_line_is_rejected(self, tmp_path) -> None:
        path = tmp_path / "bad.qubo"
        path.write_text("0 0 1.0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="program line"):
            read_qubo_file(path)

    def test_bqpjson_boolean_domain_loads(self, tmp_path) -> None:
        path = tmp_path / "toy.json"
        path.write_text(json.dumps({
            "id": "toy-1",
            "variable_domain": "boolean",
            "variable_ids": [10, 20, 30],
            "linear_terms": [{"id": 10, "coeff": 1.0}],
            "quadratic_terms": [{"id_head": 10, "id_tail": 30, "coeff": -2.0}],
        }), encoding="utf-8")
        instance = read_bqpjson(path)

        assert instance.name == "toy-1"
        assert instance.num_variables == 3
        assert instance.linear == {0: 1.0}
        assert instance.quadratic == {"0,2": -2.0}

    def test_bqpjson_spin_domain_is_rejected_not_reinterpreted(self, tmp_path) -> None:
        """A spin instance is an Ising model, not a QUBO."""
        path = tmp_path / "spin.json"
        path.write_text(json.dumps({
            "variable_domain": "spin", "variable_ids": [1],
            "linear_terms": [], "quadratic_terms": [],
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="only 'boolean' is a QUBO"):
            read_bqpjson(path)


# ---------------------------------------------------------------------------
# Real downloads — the tests that actually pin the published formats
# ---------------------------------------------------------------------------

@requires_network
class TestRealLibraries:
    def test_orlib_bqp100_first_instance(self) -> None:
        from qpubench.hamiltonian_sources.qubo import load_orlib

        instance, record = load_orlib("bqp100", index=0)
        assert instance.num_variables == 100
        assert instance.num_terms == 475
        assert record.extras["orlib_sense"] == "maximise"

    def test_mqlib_stores_the_be_family_as_maxcut_on_one_extra_node(self) -> None:
        from qpubench.hamiltonian_sources.qubo import load_mqlib

        maxcut, record = load_mqlib("be100.1")
        assert maxcut.num_variables == 101
        assert record.extras["form"] == "maxcut"

    def test_mqlib_recovery_reproduces_orlib_exactly(self) -> None:
        """The strongest available check: two independent sources must agree.

        be100.1 is bqp100's first instance converted to Max-Cut. Inverting the
        conversion must give back the OR-Library matrix coefficient for
        coefficient — this is what caught the naive inversion that ignored the
        row-sum folding.
        """
        from qpubench.hamiltonian_sources.qubo import load_mqlib, load_orlib

        recovered, _ = load_mqlib("be100.1", recover_qubo=True)
        original, _ = load_orlib("bqp100", index=0)

        assert recovered.num_variables == original.num_variables
        assert recovered.quadratic == original.quadratic
        assert recovered.linear == original.linear

    def test_mqlib_catalogue_lists_every_instance(self) -> None:
        from qpubench.hamiltonian_sources.qubo import list_mqlib_instances

        names = list_mqlib_instances()
        assert len(names) > 3000
        assert "be100.1" in names
