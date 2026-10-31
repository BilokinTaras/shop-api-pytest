"""HTTP client with timeouts, logging, secret masking and a request journal for failure reports."""

from __future__ import annotations

import json
import logging
import os
import re
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Self, TypeVar

import httpx
from pydantic import BaseModel

log = logging.getLogger("shop_api.http")

M = TypeVar("M", bound=BaseModel)

_SECRET_HEADERS = {"authorization", "x-publishable-api-key", "cookie", "set-cookie"}
_TOKEN_IN_BODY = re.compile(r'("(?:token|password)"\s*:\s*")[^"]*(")')


def mask_headers(headers: httpx.Headers) -> dict[str, str]:
    """Keeps the first characters of secrets so two different tokens stay distinguishable in reports."""
    return {
        k: (v[:12] + "…" if k.lower() in _SECRET_HEADERS and len(v) > 12 else v) for k, v in headers.items()
    }


def mask_body(text: str) -> str:
    return _TOKEN_IN_BODY.sub(r"\1***\2", text)


@dataclass(frozen=True)
class Exchange:
    method: str
    url: str
    request_headers: dict[str, str]
    request_body: str
    status: int
    response_body: str
    elapsed_ms: float

    def render(self) -> str:
        return (
            f"{self.method} {self.url}\n{json.dumps(self.request_headers, indent=2)}\n{self.request_body}\n\n"
            f"-> {self.status} in {self.elapsed_ms:.0f} ms\n{self.response_body}"
        )


class Journal:
    """The last N exchanges of the current test; attached to the report when the test fails."""

    def __init__(self, size: int = 20) -> None:
        self.items: deque[Exchange] = deque(maxlen=size)

    def clear(self) -> None:
        self.items.clear()


JOURNAL = Journal()


class ApiError(AssertionError):
    """A call expected to succeed did not."""


class BaseClient:
    def __init__(self, base_url: str, headers: dict[str, str] | None = None, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self._client = httpx.Client(
            base_url=base_url,
            headers=headers or {},
            timeout=httpx.Timeout(timeout, connect=5.0),
            event_hooks={"response": [self._record]},
        )

    def _record(self, response: httpx.Response) -> None:
        response.read()
        request = response.request
        body = request.content.decode("utf-8", "replace") if request.content else ""
        exchange = Exchange(
            method=request.method,
            url=str(request.url),
            request_headers=mask_headers(request.headers),
            request_body=mask_body(body),
            status=response.status_code,
            response_body=mask_body(response.text[:5000]),
            elapsed_ms=response.elapsed.total_seconds() * 1000,
        )
        JOURNAL.items.append(exchange)
        if record_dir := os.environ.get("SHOP_API_RECORD_DIR"):
            # One file per process, so parallel xdist workers never interleave writes.
            with open(os.path.join(record_dir, f"calls-{os.getpid()}.txt"), "a", encoding="utf-8") as fh:
                fh.write(f"{request.method} {request.url.path}\n")
        log.debug(
            "%s %s -> %s (%.0f ms)", exchange.method, exchange.url, exchange.status, exchange.elapsed_ms
        )

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Any call, any status: for negative tests that assert on the response themselves."""
        return self._client.request(method, path, **kwargs)

    def call(self, model: type[M], method: str, path: str, expected: int = 200, **kwargs: Any) -> M:
        """A call expected to succeed: checks the status and parses the body into ``model``."""
        response = self.request(method, path, **kwargs)
        if response.status_code != expected:
            raise ApiError(
                f"{method} {path}: expected {expected}, got {response.status_code}: {response.text[:500]}"
            )
        # parse_float=Decimal: amounts such as 25.4745 must not pass through binary floats.
        return model.model_validate(json.loads(response.text, parse_float=Decimal))

    def with_headers(self, **headers: str) -> Self:
        clone = self.__class__.__new__(self.__class__)
        clone.__dict__.update(self.__dict__)
        clone._client = httpx.Client(
            base_url=self.base_url,
            headers={**self._client.headers, **headers},
            timeout=self._client.timeout,
            event_hooks={"response": [self._record]},
        )
        return clone

    def close(self) -> None:
        self._client.close()
