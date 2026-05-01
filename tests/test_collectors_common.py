"""Tests for collector shared helpers."""

from __future__ import annotations

import httpx

from kalshi_no_carry.collectors.common import CollectorSummary, safe_error_message, utc_now


def test_safe_error_message_httpstatus() -> None:
    req = httpx.Request("GET", "https://secret.example/path")
    resp = httpx.Response(418, request=req)
    exc = httpx.HTTPStatusError("x", request=req, response=resp)
    msg = safe_error_message(exc)
    assert "418" in msg
    assert "secret" not in msg.lower()


def test_collector_summary_public_dict_no_ids() -> None:
    s = CollectorSummary(
        name="n",
        started_at=utc_now(),
        ids_collected=["a", "b", "c"],
    )
    d = s.to_public_dict()
    assert d["ids_collected_count"] == 3
    assert "ids_collected" not in d
