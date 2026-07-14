from __future__ import annotations

import random
import time
from typing import Any

import httpx


RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    attempts: int = 4,
    **kwargs: Any,
) -> tuple[Any, httpx.Response]:
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code in RETRYABLE_STATUS:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = min(30.0, float(retry_after))
                    except ValueError:
                        delay = 0.0
                else:
                    delay = min(12.0, (2 ** (attempt - 1)) + random.random())
                if attempt < attempts:
                    time.sleep(delay)
                    continue
            response.raise_for_status()
            return response.json(), response
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            time.sleep(min(12.0, (2 ** (attempt - 1)) + random.random()))

    raise RuntimeError(str(last_error or "Provider request failed"))


def download_bytes(
    client: httpx.Client,
    url: str,
    *,
    attempts: int = 4,
) -> tuple[bytes, httpx.Response]:
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url)
            if response.status_code in RETRYABLE_STATUS and attempt < attempts:
                time.sleep(min(12.0, (2 ** (attempt - 1)) + random.random()))
                continue
            response.raise_for_status()
            return response.content, response
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            time.sleep(min(12.0, (2 ** (attempt - 1)) + random.random()))

    raise RuntimeError(str(last_error or "Provider download failed"))
