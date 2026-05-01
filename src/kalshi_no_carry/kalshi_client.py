"""
Read-only Kalshi Trade API v2 HTTP client (RSA-PSS auth; no order placement).

This module implements market data GETs, exchange status, signing helpers, and
executable bid/ask derivation from Kalshi order books (bids-only with reciprocal quotes).
"""

from __future__ import annotations

import base64
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote, urljoin, urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from kalshi_no_carry.config import Settings, get_settings

logger = logging.getLogger(__name__)


class KalshiAuthError(RuntimeError):
    """Raised when authenticated access is requested without credentials."""


class KalshiClient:
    """
    Minimal read-only client. Orders, portfolio, and trading flows are out of scope.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key_id: str | None = None,
        private_key_path: str | Path | None = None,
        timeout_seconds: float = 20.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = str(base_url).rstrip("/")
        self._api_key_id = api_key_id
        self._private_key_path = Path(private_key_path) if private_key_path else None
        self._timeout_seconds = float(timeout_seconds)
        self._private_key: rsa.RSAPrivateKey | None = None
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(self._timeout_seconds),
            follow_redirects=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> KalshiClient:
        s = settings or get_settings()
        key_path = s.kalshi_private_key_path
        return cls(
            s.resolved_kalshi_base_url(),
            api_key_id=s.kalshi_api_key_id,
            private_key_path=str(key_path) if key_path is not None else None,
            timeout_seconds=s.kalshi_request_timeout_seconds,
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> KalshiClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _normalize_path(self, path: str) -> str:
        p = path.strip()
        if not p.startswith("/"):
            p = "/" + p
        return p

    def _full_url(self, path: str) -> str:
        rel = self._normalize_path(path).lstrip("/")
        return urljoin(self._base_url + "/", rel)

    def _sign_path_from_url(self, full_url: str) -> str:
        parsed = urlparse(full_url)
        sign_path = parsed.path or "/"
        return sign_path.split("?")[0]

    def _load_private_key(self) -> rsa.RSAPrivateKey:
        if self._private_key is not None:
            return self._private_key
        if self._private_key_path is None:
            raise KalshiAuthError(
                "Private key path is not configured; set KALSHI_PRIVATE_KEY_PATH for authenticated requests."
            )
        pem = self._private_key_path.read_bytes()
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise KalshiAuthError("Kalshi private key must be an RSA key in PEM format.")
        self._private_key = key
        return key

    def _timestamp_ms(self) -> int:
        return int(time.time() * 1000)

    def _sign(self, method: str, path_for_signing: str, timestamp_ms: int) -> str:
        path_clean = path_for_signing.split("?")[0]
        message = f"{timestamp_ms}{method.upper()}{path_clean}".encode("utf-8")
        signature = self._load_private_key().sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("ascii")

    def _auth_headers(self, method: str, path_for_signing: str) -> dict[str, str]:
        if not self._api_key_id:
            raise KalshiAuthError(
                "API key id is not configured; set KALSHI_API_KEY_ID for authenticated requests."
            )
        _ = self._load_private_key()  # fail fast if key path missing/unreadable
        ts = self._timestamp_ms()
        sig = self._sign(method, path_for_signing, ts)
        return {
            "KALSHI-ACCESS-KEY": self._api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": str(ts),
            "KALSHI-ACCESS-SIGNATURE": sig,
        }

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        """
        Perform an HTTP request and parse a JSON object response.

        :param path: Path relative to ``base_url``, with or without a leading slash.
        :param params: Query parameters (excluded from the RSA-PSS signing path).
        :param authenticated: When True, attach Kalshi signing headers (requires key material).
        """
        full_url = self._full_url(path)
        sign_path = self._sign_path_from_url(full_url)
        headers: dict[str, str] = {}
        if authenticated:
            headers.update(self._auth_headers(method, sign_path))
        try:
            response = self._http.request(method.upper(), full_url, params=params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("Kalshi HTTP error for %s %s", method.upper(), sign_path, exc_info=True)
            raise

        data = response.json()
        if not isinstance(data, dict):
            raise TypeError(f"Expected JSON object from Kalshi, got {type(data).__name__}")
        return data

    def get_exchange_status(self) -> dict[str, Any]:
        """GET /exchange/status (public)."""
        return self.request("GET", "/exchange/status")

    def get_markets(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        status: str | None = None,
        event_ticker: str | None = None,
        series_ticker: str | None = None,
        authenticated: bool = False,
        **extra_query: Any,
    ) -> dict[str, Any]:
        """GET /markets (paginated; public by default)."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if status is not None:
            params["status"] = status
        if event_ticker is not None:
            params["event_ticker"] = event_ticker
        if series_ticker is not None:
            params["series_ticker"] = series_ticker
        for key, value in extra_query.items():
            if value is not None:
                params[key] = value
        return self.request("GET", "/markets", params=params, authenticated=authenticated)

    def iter_markets(
        self,
        *,
        limit: int = 100,
        max_pages: int | None = None,
        authenticated: bool = False,
        **filters: Any,
    ) -> Iterator[dict[str, Any]]:
        """Yield markets from paginated /markets until cursor is empty or ``max_pages`` is reached."""
        cursor: str | None = None
        pages = 0
        while True:
            if max_pages is not None and pages >= max_pages:
                break
            page = self.get_markets(
                limit=limit,
                cursor=cursor,
                authenticated=authenticated,
                **filters,
            )
            markets = page.get("markets") or []
            if not isinstance(markets, list):
                raise TypeError("markets page must contain a list under 'markets'")
            for row in markets:
                if isinstance(row, dict):
                    yield row
            cursor = page.get("cursor")
            if not cursor:
                break
            pages += 1

    def get_market(self, ticker: str, *, authenticated: bool = False) -> dict[str, Any]:
        """GET /markets/{ticker}."""
        t = ticker.strip()
        if not t:
            raise ValueError("ticker must be non-empty")
        enc = quote(t, safe="-_.~")
        return self.request("GET", f"/markets/{enc}", authenticated=authenticated)

    def get_orderbook(
        self,
        ticker: str,
        depth: int | None = None,
        *,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        """GET /markets/{ticker}/orderbook."""
        t = ticker.strip()
        if not t:
            raise ValueError("ticker must be non-empty")
        params: dict[str, Any] = {}
        if depth is not None:
            params["depth"] = depth
        enc = quote(t, safe="-_.~")
        return self.request(
            "GET",
            f"/markets/{enc}/orderbook",
            params=params or None,
            authenticated=authenticated,
        )

    def get_multiple_orderbooks(
        self,
        tickers: list[str],
        depth: int | None = None,
        *,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        """
        Bulk order books are not implemented in v0.2.

        Kalshi exposes a separate multi-market orderbook route that may require authentication;
        use :meth:`get_orderbook` per ticker for now.
        """
        raise NotImplementedError(
            "get_multiple_orderbooks is not implemented in v0.2; call get_orderbook per ticker."
        )


def dollars_str_to_cents(value: str) -> int:
    """Convert a Kalshi fixed-point dollars string (e.g. ``\"0.6500\"``) to integer cents."""
    quanta = (Decimal(value.strip()) * Decimal(100)).quantize(Decimal("1"))
    return int(quanta)


def derive_executable_prices_from_orderbook(orderbook_json: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a Kalshi GetMarketOrderbook-style JSON payload into best bid/ask cent prices.

    Kalshi returns only YES bids and NO bids. Equivalent asks follow reciprocal quoting:

    - Best NO ask cents = 100 - best YES bid cents (same size as the YES bid level).
    - Best YES ask cents = 100 - best NO bid cents (same size as the NO bid level).

    ``orderbook_json`` may be either the full response (with ``orderbook_fp``) or the inner book.
    """
    ob = orderbook_json.get("orderbook_fp", orderbook_json)
    yes_levels = ob.get("yes_dollars") or []
    no_levels = ob.get("no_dollars") or []

    best_yes = yes_levels[0] if yes_levels else None
    best_no = no_levels[0] if no_levels else None

    best_yes_bid_cents: int | None = None
    best_no_bid_cents: int | None = None
    yes_bid_size: str | None = None
    no_bid_size: str | None = None
    best_yes_ask_cents: int | None = None
    best_no_ask_cents: int | None = None
    yes_ask_size: str | None = None
    no_ask_size: str | None = None

    if best_yes is not None and isinstance(best_yes, (list, tuple)) and len(best_yes) >= 2:
        best_yes_bid_cents = dollars_str_to_cents(str(best_yes[0]))
        yes_bid_size = str(best_yes[1])
        best_no_ask_cents = 100 - best_yes_bid_cents
        no_ask_size = yes_bid_size

    if best_no is not None and isinstance(best_no, (list, tuple)) and len(best_no) >= 2:
        best_no_bid_cents = dollars_str_to_cents(str(best_no[0]))
        no_bid_size = str(best_no[1])
        best_yes_ask_cents = 100 - best_no_bid_cents
        yes_ask_size = no_bid_size

    return {
        "best_yes_bid_cents": best_yes_bid_cents,
        "best_no_bid_cents": best_no_bid_cents,
        "best_yes_ask_cents": best_yes_ask_cents,
        "best_no_ask_cents": best_no_ask_cents,
        "yes_bid_size": yes_bid_size,
        "no_bid_size": no_bid_size,
        "yes_ask_size": yes_ask_size,
        "no_ask_size": no_ask_size,
    }
