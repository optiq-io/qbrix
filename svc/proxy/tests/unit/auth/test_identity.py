"""the rules for names and slugs users choose, shared by every transport."""

from __future__ import annotations

import pytest

from proxysvc.core.error import InvalidIdentityError
from proxysvc.mod.auth.identity import clean_name
from proxysvc.mod.auth.identity import clean_slug
from proxysvc.mod.auth.identity import slug_from


class TestCleanName:
    @pytest.mark.parametrize(
        "value",
        [
            "Ada Lovelace",
            "María José O'Neil",
            "Acme Inc.",
            "Acme.io",
            "A/B team",
            "v1.0/beta",
            "研究チーム",
            "x" * 64,
        ],
    )
    def test_ordinary_names_pass(self, value):
        assert clean_name(value, "name") == value

    def test_surrounding_whitespace_is_trimmed(self):
        assert clean_name("  Ada  ", "name") == "Ada"

    def test_absent_stays_absent(self):
        assert clean_name(None, "name") is None

    @pytest.mark.parametrize(
        "value",
        [
            "https://casino.example",
            "ftp://x",
            "go to www.casino.example",
            "WWW.CASINO.EXAMPLE",
            "bit.ly/4q9lhYM",
            "⚡TTam 70.000 TL bonus bit.ly/4q9lhYM⚡",
            "sub.domain.example/path",
            "ｗｗｗ．casino．example",
            "bit．ly／abc",
        ],
    )
    def test_links_are_refused(self, value):
        with pytest.raises(InvalidIdentityError, match="must not contain a link"):
            clean_name(value, "name")

    def test_overlong_is_refused(self):
        with pytest.raises(InvalidIdentityError, match="at most 64"):
            clean_name("x" * 65, "workspace name")

    @pytest.mark.parametrize("value", ["a\nb", "a\rb", "a\tb", "a\x00b"])
    def test_control_characters_are_refused(self, value):
        with pytest.raises(InvalidIdentityError, match="control characters"):
            clean_name(value, "name")

    def test_the_error_names_the_field(self):
        with pytest.raises(InvalidIdentityError, match="^workspace name "):
            clean_name("x" * 65, "workspace name")


class TestCleanSlug:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("acme", "acme"),
            ("acme-inc", "acme-inc"),
            (" Acme-Inc ", "acme-inc"),
            ("acme-", "acme"),
            ("a" * 64, "a" * 64),
        ],
    )
    def test_valid_slugs_are_normalised(self, value, expected):
        assert clean_slug(value) == expected

    @pytest.mark.parametrize(
        "value", ["", "-", "acme inc", "acme--inc", "acme_inc", "açme", "a" * 65]
    )
    def test_malformed_slugs_are_refused(self, value):
        with pytest.raises(InvalidIdentityError):
            clean_slug(value)


class TestSlugFrom:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("first.last", "first-last"),
            ("First.Last+tag", "first-last-tag"),
            ("__x__", "x"),
            ("+++", "workspace"),
            ("a" * 70, "a" * 64),
        ],
    )
    def test_always_yields_a_valid_slug(self, text, expected):
        slug = slug_from(text)

        assert slug == expected
        assert clean_slug(slug) == slug
