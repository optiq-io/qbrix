"""Unit tests for engine specs, versions and the registry."""

import pytest

from qbrixcore.engine import ENGINES
from qbrixcore.engine import EngineError
from qbrixcore.engine import EngineRegistry
from qbrixcore.engine import EngineSpec
from qbrixcore.engine import EngineVersion
from qbrixcore.engine import Leibniz
from qbrixcore.engine import Spinoza
from qbrixcore.engine.spec import ACCEPTED_FORMS


class SpinozaOneOne(Spinoza):
    version = EngineVersion(1, 1)


class TestEngineSpec:
    @pytest.mark.parametrize(
        "text, spec",
        [
            ("spinoza", EngineSpec("spinoza")),
            ("spinoza:1", EngineSpec("spinoza", 1)),
            ("spinoza:1.0", EngineSpec("spinoza", 1, 0)),
            ("spinoza:1.13", EngineSpec("spinoza", 1, 13)),
        ],
    )
    def test_accepted_forms_parse_and_round_trip(self, text, spec):
        assert EngineSpec.parse(text) == spec
        assert str(spec) == text

    @pytest.mark.parametrize(
        "text",
        [
            "spinoza:x",
            "Spinoza",
            "spinoza:",
            "spinoza:1.",
            "spinoza:-1",
            "",
            "spinoza 1",
        ],
    )
    def test_malformed_spec_is_refused_naming_the_accepted_forms(self, text):
        with pytest.raises(EngineError, match=ACCEPTED_FORMS):
            EngineSpec.parse(text)

    def test_minor_without_major_is_refused(self):
        with pytest.raises(EngineError):
            EngineSpec("spinoza", minor=1)

    def test_versions_order_by_major_then_minor(self):
        assert EngineVersion(1, 9) < EngineVersion(1, 10) < EngineVersion(2, 0)
        assert str(EngineVersion(1, 3)) == "1.3"


class TestEngineRegistry:
    def test_ships_spinoza_leibniz_and_buridan_at_one_zero(self):
        assert ENGINES.names == ["buridan", "leibniz", "spinoza"]
        for name in ENGINES.names:
            assert ENGINES.get(name).version == EngineVersion(1, 0)

    def test_default_is_spinoza(self):
        assert ENGINES.get(ENGINES.DEFAULT) is Spinoza

    @pytest.mark.parametrize("text", ["spinoza", "spinoza:1", "spinoza:1.0"])
    def test_every_accepted_form_resolves(self, text):
        assert ENGINES.get(text) is Spinoza

    def test_accepts_a_parsed_spec(self):
        assert ENGINES.get(EngineSpec("leibniz", 1)) is Leibniz

    @pytest.mark.parametrize(
        "text, message",
        [
            ("plato", "unknown engine 'plato'"),
            ("spinoza:2", "spinoza has no major 2"),
            ("spinoza:1.9", "spinoza 1 has no minor 9"),
        ],
    )
    def test_unknown_engine_major_or_minor_is_refused(self, text, message):
        with pytest.raises(EngineError, match=message) as e:
            ENGINES.get(text)

        assert ACCEPTED_FORMS in str(e.value)

    def test_name_and_major_follow_the_latest_minor(self):
        registry = EngineRegistry([SpinozaOneOne, Spinoza])

        assert registry.get("spinoza") is SpinozaOneOne
        assert registry.get("spinoza:1") is SpinozaOneOne
        assert registry.get("spinoza:1.0") is Spinoza

    @pytest.mark.parametrize(
        "text, pin",
        [
            ("spinoza", "spinoza:1"),
            ("spinoza:1", "spinoza:1"),
            ("spinoza:1.0", "spinoza:1.0"),
        ],
    )
    def test_pin_keeps_the_major_unless_a_minor_was_chosen(self, text, pin):
        assert str(ENGINES.pin(text)) == pin

    def test_duplicate_version_is_refused(self):
        with pytest.raises(ValueError, match="registered twice"):
            EngineRegistry([Spinoza, Spinoza])
