from datetime import UTC, datetime, timedelta

import pytest

from mcp_vertica.mcp import _is_stale, _qual, _sanitize_ident


def test_sanitize_ident_valid():
    assert _sanitize_ident("valid_name") == "valid_name"
    assert _sanitize_ident("Valid123") == "Valid123"


def test_sanitize_ident_invalid():
    with pytest.raises(ValueError):
        _sanitize_ident("invalid-name")
    with pytest.raises(ValueError):
        _sanitize_ident("123bad")


def test_qualifier_with_schema():
    assert _qual("public", "table") == "public.table"


def test_qualifier_without_schema():
    assert _qual(None, "table") == "table"


def test_is_stale_with_recent_datetime():
    recent = datetime.now(UTC) - timedelta(minutes=30)
    assert not _is_stale(recent)


def test_is_stale_with_old_timestamp():
    old = datetime.now(UTC) - timedelta(hours=2)
    assert _is_stale(old)


def test_is_stale_with_epoch():
    recent = datetime.now(UTC) - timedelta(minutes=10)
    assert not _is_stale(int(recent.timestamp()))


def test_is_stale_with_invalid_string():
    assert _is_stale("not-a-date")
