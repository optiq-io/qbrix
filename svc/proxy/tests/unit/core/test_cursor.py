"""unit tests for page cursors.

invariants verified:
  a cursor round-trips the last row's time and id, a naive time reads as utc,
  and anything a page didn't return is refused.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone

import pytest

from proxysvc.core import cursor
from proxysvc.core.error import InvalidCursorError

AT = datetime(2026, 10, 26, 13, 9, 1, 216000, tzinfo=timezone.utc)


def test_round_trips_the_time_and_id():
    assert cursor.decode(cursor.encode(AT, "abc123")) == (AT, "abc123")


def test_a_naive_time_reads_as_utc():
    naive = AT.replace(tzinfo=None)

    assert cursor.decode(cursor.encode(naive, "abc123")) == (AT, "abc123")


@pytest.mark.parametrize(
    "token",
    ["not-a-cursor", "", "!!!", cursor.encode(AT, "")[:-2], "MjAyNi0xMC0yNg"],
)
def test_anything_a_page_did_not_return_is_refused(token):
    with pytest.raises(InvalidCursorError):
        cursor.decode(token)
