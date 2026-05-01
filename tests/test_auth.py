"""Tests for Kalshi RSA-PSS signing and auth header construction."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from kalshi_no_carry.kalshi_client import KalshiAuthError, KalshiClient


def _write_temp_key(tmp_path: Path) -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    p = tmp_path / "kalshi-test-key.pem"
    p.write_bytes(pem)
    return p


def test_authenticated_request_requires_key_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_path = _write_temp_key(tmp_path)
    client = KalshiClient("https://api.elections.kalshi.com/trade-api/v2", private_key_path=key_path)
    monkeypatch.setattr(client, "_timestamp_ms", lambda: 1)
    with pytest.raises(KalshiAuthError):
        client._auth_headers("GET", "/trade-api/v2/markets")


def test_authenticated_request_requires_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        api_key_id="test-key-id",
        private_key_path=None,
    )
    monkeypatch.setattr(client, "_timestamp_ms", lambda: 1)
    with pytest.raises(KalshiAuthError):
        client._auth_headers("GET", "/trade-api/v2/markets")


def test_auth_headers_include_kalshi_header_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_path = _write_temp_key(tmp_path)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        api_key_id="test-key-id",
        private_key_path=key_path,
    )
    monkeypatch.setattr(client, "_timestamp_ms", lambda: 123456789)
    headers = client._auth_headers("get", "/trade-api/v2/markets")
    assert headers["KALSHI-ACCESS-KEY"] == "test-key-id"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "123456789"
    assert headers["KALSHI-ACCESS-SIGNATURE"]
    assert set(headers.keys()) == {"KALSHI-ACCESS-KEY", "KALSHI-ACCESS-TIMESTAMP", "KALSHI-ACCESS-SIGNATURE"}


def test_signing_verifies_with_rsa_public_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(pem)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        api_key_id="id",
        private_key_path=key_path,
    )
    ts = 1700000000000
    monkeypatch.setattr(client, "_timestamp_ms", lambda: ts)
    path = "/trade-api/v2/markets"
    sig_b64 = client._sign("get", path, ts)
    message = f"{ts}GET{path}".encode("utf-8")
    signature = base64.b64decode(sig_b64)
    key.public_key().verify(
        signature,
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_sign_path_ignores_query_for_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(pem)
    client = KalshiClient(
        "https://api.elections.kalshi.com/trade-api/v2",
        api_key_id="id",
        private_key_path=key_path,
    )
    ts = 99
    monkeypatch.setattr(client, "_timestamp_ms", lambda: ts)
    sig1 = client._sign("GET", "/trade-api/v2/markets", ts)
    sig2 = client._sign("GET", "/trade-api/v2/markets?limit=5", ts)
    message = f"{ts}GET/trade-api/v2/markets".encode("utf-8")
    pub = key.public_key()
    for sig_b64 in (sig1, sig2):
        sig = base64.b64decode(sig_b64)
        pub.verify(
            sig,
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
