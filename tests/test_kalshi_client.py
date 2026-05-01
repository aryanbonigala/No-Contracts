"""Tests for KalshiClient HTTP wiring, pagination helpers, and orderbook math."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from kalshi_no_carry.config import get_settings, reset_settings_cache
from kalshi_no_carry.kalshi_client import (
    KalshiAuthError,
    KalshiClient,
    derive_executable_prices_from_orderbook,
)


def test_client_joins_base_url_and_path() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"markets": [], "cursor": ""})

    transport = httpx.MockTransport(handler)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        http_client=httpx.Client(transport=transport),
    )
    try:
        client.get_markets(limit=2)
    finally:
        client.close()
    assert calls == ["https://api.elections.kalshi.com/trade-api/v2/markets?limit=2"]


def test_iter_events_pagination() -> None:
    bodies = iter(
        [
            {"events": [{"event_ticker": "E1"}], "cursor": "next"},
            {"events": [{"event_ticker": "E2"}], "cursor": ""},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(bodies))

    transport = httpx.MockTransport(handler)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        http_client=httpx.Client(transport=transport),
    )
    try:
        out = list(client.iter_events(limit=5, max_pages=3))
    finally:
        client.close()
    assert [e["event_ticker"] for e in out] == ["E1", "E2"]


def test_get_events_caps_limit_at_200() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"events": [], "cursor": ""})

    transport = httpx.MockTransport(handler)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        http_client=httpx.Client(transport=transport),
    )
    try:
        client.get_events(limit=5000)
    finally:
        client.close()
    assert "limit=200" in seen[0]


def test_accepts_path_with_or_without_leading_slash() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json={"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})

    transport = httpx.MockTransport(handler)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        http_client=httpx.Client(transport=transport),
    )
    try:
        client.request("GET", "markets/MY-TICKER/orderbook")
        client.request("GET", "/markets/MY-TICKER/orderbook")
    finally:
        client.close()
    assert urls[0] == urls[1]


def test_authenticated_request_raises_without_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        http_client=httpx.Client(transport=transport),
    )
    try:
        with pytest.raises(KalshiAuthError):
            client.request("GET", "/markets", authenticated=True)
    finally:
        client.close()


def test_iter_markets_stops_without_cursor() -> None:
    bodies = [
        {"markets": [{"ticker": "a"}], "cursor": "next"},
        {"markets": [{"ticker": "b"}], "cursor": ""},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=bodies.pop(0))

    transport = httpx.MockTransport(handler)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        http_client=httpx.Client(transport=transport),
    )
    try:
        out = list(client.iter_markets(limit=50))
    finally:
        client.close()
    assert [m["ticker"] for m in out] == ["a", "b"]


def test_iter_markets_respects_max_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"markets": [{"ticker": "x"}], "cursor": "more"})

    transport = httpx.MockTransport(handler)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        http_client=httpx.Client(transport=transport),
    )
    try:
        out = list(client.iter_markets(limit=1, max_pages=2))
    finally:
        client.close()
    assert len(out) == 2


def test_from_settings_uses_resolved_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("KALSHI_ENV", "demo")
    monkeypatch.setenv("KALSHI_DEMO_BASE_URL", "https://demo.example/trade-api/v2")
    monkeypatch.setenv("KALSHI_BASE_URL", "https://prod.example/trade-api/v2")
    reset_settings_cache()
    client = KalshiClient.from_settings(get_settings())
    try:
        assert client._base_url == "https://demo.example/trade-api/v2"
    finally:
        client.close()


def test_derive_executable_both_sides() -> None:
    book: dict[str, Any] = {
        "orderbook_fp": {
            "yes_dollars": [["0.4000", "12"]],
            "no_dollars": [["0.5000", "7"]],
        }
    }
    d = derive_executable_prices_from_orderbook(book)
    assert d["best_yes_bid_cents"] == 40
    assert d["best_no_bid_cents"] == 50
    assert d["best_no_ask_cents"] == 60
    assert d["best_yes_ask_cents"] == 50
    assert d["yes_bid_size"] == "12"
    assert d["no_bid_size"] == "7"
    assert d["no_ask_size"] == "12"
    assert d["yes_ask_size"] == "7"


def test_derive_executable_only_yes_bids() -> None:
    book = {"orderbook_fp": {"yes_dollars": [["0.2000", "3"]], "no_dollars": []}}
    d = derive_executable_prices_from_orderbook(book)
    assert d["best_yes_bid_cents"] == 20
    assert d["best_no_ask_cents"] == 80
    assert d["no_ask_size"] == "3"
    assert d["best_no_bid_cents"] is None
    assert d["best_yes_ask_cents"] is None


def test_derive_executable_only_no_bids() -> None:
    book = {"orderbook_fp": {"yes_dollars": [], "no_dollars": [["0.6500", "9"]]}}
    d = derive_executable_prices_from_orderbook(book)
    assert d["best_no_bid_cents"] == 65
    assert d["best_yes_ask_cents"] == 35
    assert d["yes_ask_size"] == "9"
    assert d["best_yes_bid_cents"] is None
    assert d["best_no_ask_cents"] is None


def test_derive_executable_empty_book() -> None:
    book = {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
    d = derive_executable_prices_from_orderbook(book)
    assert d["best_yes_bid_cents"] is None
    assert d["best_no_bid_cents"] is None
    assert d["best_yes_ask_cents"] is None
    assert d["best_no_ask_cents"] is None
    assert d["yes_bid_size"] is None
    assert d["no_bid_size"] is None


def test_get_multiple_orderbooks_is_stub() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        http_client=httpx.Client(transport=transport),
    )
    try:
        with pytest.raises(NotImplementedError):
            client.get_multiple_orderbooks(["A", "B"])
    finally:
        client.close()
