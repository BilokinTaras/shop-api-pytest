"""Minimal HS256 JWT helpers for negative tests (expired, re-signed, alg=none tokens).

Implemented with the standard library on purpose: the tests must control every byte of the token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def decode_unverified(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    header, payload, _ = token.split(".")
    return json.loads(_unb64(header)), json.loads(_unb64(payload))


def sign(payload: dict[str, Any], secret: str, header: dict[str, Any] | None = None) -> str:
    head = _b64(json.dumps(header or {"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(signature)}"


def unsigned(payload: dict[str, Any]) -> str:
    """An ``alg: none`` token with an empty signature."""
    head = _b64(json.dumps({"alg": "none", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{head}.{body}."
