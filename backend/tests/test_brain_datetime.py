from datetime import datetime, timezone

from brain import _as_utc_datetime


def test_as_utc_datetime_normalizes_naive_sqlite_timestamp():
    naive = datetime(2026, 7, 9, 17, 25, 47)

    normalized = _as_utc_datetime(naive)

    assert normalized.tzinfo == timezone.utc
    assert (datetime.now(timezone.utc) - normalized).total_seconds()
