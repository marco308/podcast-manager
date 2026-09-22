"""Tests for the UTCDateTime column type (issue #156).

Every DateTime column used to be naive while every write was
``datetime.now(UTC)``. SQLite drops the offset silently, so reads came back
naive and the codebase carried four separate ``if x.tzinfo is None`` fix-ups.

Note ``DateTime(timezone=True)`` does **not** solve this — on SQLite the flag
is a no-op and reads are still naive. These tests pin the behaviour that
actually matters: writes normalise to UTC, reads are always aware, and rows
written by the old bare-DateTime columns still read back correctly.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import Column, Integer, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Session

from app.models.types import UTCDateTime


class Base(DeclarativeBase):
    pass


class Row(Base):
    __tablename__ = "rows"

    id = Column(Integer, primary_key=True)
    at = Column(UTCDateTime, nullable=True)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class TestRoundTrip:
    def test_aware_utc_survives_round_trip(self, session):
        written = datetime(2026, 3, 1, 12, 30, tzinfo=UTC)
        session.add(Row(id=1, at=written))
        session.commit()
        session.expire_all()

        read = session.execute(select(Row)).scalar_one().at

        assert read.tzinfo is not None, "reads must be timezone-aware"
        assert read == written

    def test_non_utc_offset_is_converted_not_truncated(self, session):
        # 09:00 in UTC+2 is 07:00 UTC — the offset must be applied, not dropped.
        written = datetime(2026, 3, 1, 9, 0, tzinfo=timezone(timedelta(hours=2)))
        session.add(Row(id=1, at=written))
        session.commit()
        session.expire_all()

        read = session.execute(select(Row)).scalar_one().at

        assert read == written
        assert read.hour == 7
        assert read.utcoffset() == timedelta(0)

    def test_null_is_preserved(self, session):
        session.add(Row(id=1, at=None))
        session.commit()
        session.expire_all()

        assert session.execute(select(Row)).scalar_one().at is None


class TestBackwardCompatibility:
    """Rows written by the old bare-DateTime columns must still work."""

    def test_existing_naive_rows_read_back_as_utc(self, session):
        # Simulate a pre-migration row: naive UTC, exactly what the old
        # columns wrote. No data migration should be needed.
        session.execute(text("INSERT INTO rows (id, at) VALUES (1, '2026-03-01 12:30:00.000000')"))
        session.commit()

        read = session.execute(select(Row)).scalar_one().at

        assert read == datetime(2026, 3, 1, 12, 30, tzinfo=UTC)

    def test_storage_format_is_unchanged(self, session):
        """On-disk representation must stay naive UTC, so old and new agree."""
        session.add(Row(id=1, at=datetime(2026, 3, 1, 12, 30, tzinfo=UTC)))
        session.commit()

        raw = session.execute(text("SELECT at FROM rows WHERE id = 1")).scalar_one()

        assert raw.startswith("2026-03-01 12:30:00")
        assert "+" not in raw, "an offset in storage would break older readers"


class TestComparisons:
    def test_read_value_compares_with_aware_now_without_error(self, session):
        """The naive/aware TypeError this type exists to prevent."""
        session.add(Row(id=1, at=datetime.now(UTC) - timedelta(hours=1)))
        session.commit()
        session.expire_all()

        read = session.execute(select(Row)).scalar_one().at

        # Would raise TypeError with a bare DateTime column.
        assert (datetime.now(UTC) - read).total_seconds() > 0
