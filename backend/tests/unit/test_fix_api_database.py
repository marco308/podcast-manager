"""Tests for ``get_db`` exception handling (issue #182).

Routine HTTPExceptions (404s and friends) raised inside a request used to be
logged as ERROR "Database transaction failed" with a stack trace. They must
roll back quietly; only genuinely unexpected exceptions warrant the ERROR.
"""

import logging

import pytest
from fastapi import HTTPException

from app.database import get_db


@pytest.mark.asyncio
async def test_http_exception_rolls_back_without_error_log(caplog):
    gen = get_db()
    await anext(gen)
    with caplog.at_level(logging.DEBUG, logger="app.database"), pytest.raises(HTTPException):
        await gen.athrow(HTTPException(status_code=404, detail="Not found"))
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_unexpected_exception_still_logged_as_error(caplog):
    gen = get_db()
    await anext(gen)
    with caplog.at_level(logging.DEBUG, logger="app.database"), pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("boom"))
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("Database transaction failed" in r.getMessage() for r in errors)
