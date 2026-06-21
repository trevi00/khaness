"""HTTP webhook utility for notification handlers and any outbound POST.

Zero external deps (stdlib only). Single responsibility: POST JSON with
bounded exponential backoff. Used by handlers/notification/* (Wave 4).

Public API:
  post_json(url, payload, retries=3, timeout_seconds=10.0, ...) -> (ok, status, err)
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    retries: int = 3,
    timeout_seconds: float = 10.0,
    backoff_seconds: float = 1.0,
    headers: dict[str, str] | None = None,
) -> tuple[bool, int | None, str | None]:
    """POST JSON payload with bounded exponential backoff.

    Returns (ok, status_code, error_message).
    - ok=True iff a 2xx response was received.
    - 4xx (except 429) never retries — client error is deterministic.
    - 5xx and transport errors retry up to `retries` times.
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    last_err: str | None = None
    last_status: int | None = None

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, data=data, headers=req_headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                last_status = resp.status
                if 200 <= last_status < 300:
                    return True, last_status, None
                last_err = f"HTTP {last_status}"
        except urllib.error.HTTPError as e:
            last_status = e.code
            last_err = f"HTTP {e.code}: {e.reason}"
            if 400 <= e.code < 500 and e.code != 429:
                return False, last_status, last_err
        except urllib.error.URLError as e:
            last_err = f"URL error: {e.reason}"
        except Exception as e:
            last_err = f"unexpected: {e!r}"

        if attempt < retries:
            time.sleep(backoff_seconds * (2 ** attempt))

    return False, last_status, last_err
