"""Custom SQLAlchemy column types."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """A DateTime column that always reads back timezone-aware, in UTC.

    Issue #156: every column used a bare ``DateTime`` while every write was
    ``datetime.now(UTC)``. SQLite's DateTime silently drops the offset on
    write and returns a naive value on read, so the codebase grew a scatter
    of ``if x.tzinfo is None: x.replace(tzinfo=UTC)`` fix-ups — and any
    caller that forgot one got a wrong answer or a naive/aware comparison
    ``TypeError``.

    Note that ``DateTime(timezone=True)`` does **not** fix this: on SQLite
    the flag is a no-op and reads still come back naive. Normalising has to
    happen in Python, which is what this type does:

    * **bind** — a naive value is assumed to be UTC; an aware value is
      converted to UTC. Either way it is stored as naive UTC.
    * **result** — the stored value is tagged back as UTC.

    Storing naive UTC keeps the on-disk representation byte-identical to
    what the bare ``DateTime`` columns already wrote, so existing rows read
    back correctly and no data migration is required.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        """Normalise to UTC and strip the offset for storage."""
        if value is None:
            return None
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None:
            # Naive values are UTC by convention throughout this codebase.
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        """Tag the stored value as UTC so callers always get an aware datetime."""
        if value is None:
            return None
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
