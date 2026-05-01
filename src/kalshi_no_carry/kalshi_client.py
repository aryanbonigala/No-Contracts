"""Thin Kalshi API client stub — authentication and endpoints are intentionally not implemented."""

from __future__ import annotations

from typing import Any

from kalshi_no_carry.config import Settings, get_settings


class KalshiClient:
    """
    Placeholder for a future Kalshi REST/WebSocket client.

    Design intent (later phases):
    - Load base URL and credentials only from environment or a secrets manager.
    - Separate read-only market data calls from authenticated trading (trading stays out of scope for research v1).
    - Centralize retries, rate limits, and request signing in one place.

    This scaffold does not perform HTTP requests.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def base_url(self) -> str:
        return str(self._settings.kalshi_api_base_url).rstrip("/")

    def fetch_markets(self, **_kwargs: Any) -> None:
        """Reserved: list or search markets (not implemented)."""
        raise NotImplementedError("KalshiClient.fetch_markets is a stub")

    def fetch_orderbook(self, **_kwargs: Any) -> None:
        """Reserved: snapshot order book for a market (not implemented)."""
        raise NotImplementedError("KalshiClient.fetch_orderbook is a stub")
