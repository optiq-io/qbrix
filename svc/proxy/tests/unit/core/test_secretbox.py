"""a sealed secret opens only under the key that sealed it, for the tenant,
purpose and row it was sealed for, and never once altered."""

from __future__ import annotations

import pytest

from proxysvc.core.secretbox import SecretBox
from proxysvc.core.secretbox import SecretUnreadableError

pytestmark = pytest.mark.unit

KEY = b"k" * 32
FOR = {"tenant_id": "t1", "purpose": "webhook-secret", "row_id": "r1"}


def test_round_trip_and_shape():
    box = SecretBox(KEY)

    sealed = box.seal("whsec_abc", **FOR)

    version, key_id, _, _ = sealed.split(".")
    assert (version, key_id) == ("v1", box.key_id)
    assert "whsec_abc" not in sealed
    assert box.open(sealed, **FOR) == "whsec_abc"


def test_each_seal_differs():
    box = SecretBox(KEY)

    assert box.seal("same", **FOR) != box.seal("same", **FOR)


def test_another_key_cant_open_it():
    sealed = SecretBox(KEY).seal("whsec_abc", **FOR)

    with pytest.raises(SecretUnreadableError, match="another key"):
        SecretBox(b"x" * 32).open(sealed, **FOR)


@pytest.mark.parametrize(
    "other",
    [
        {"tenant_id": "t2"},
        {"purpose": "github-key"},
        {"row_id": "r2"},
    ],
)
def test_a_value_moved_to_another_row_doesnt_open(other):
    box = SecretBox(KEY)
    sealed = box.seal("whsec_abc", **FOR)

    with pytest.raises(SecretUnreadableError):
        box.open(sealed, **{**FOR, **other})


@pytest.mark.parametrize(
    "tamper",
    [
        lambda s: s[:-2] + ("A" if s[-2] != "A" else "B") + s[-1],
        lambda s: "v2" + s[2:],
        lambda s: s.rsplit(".", 1)[0],
        lambda s: "not sealed",
    ],
)
def test_an_altered_value_doesnt_open(tamper):
    box = SecretBox(KEY)
    sealed = box.seal("whsec_abc", **FOR)

    with pytest.raises(SecretUnreadableError):
        box.open(tamper(sealed), **FOR)
