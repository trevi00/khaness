#!/usr/bin/env python3
"""Tests for lib/webhook.py — POST JSON with bounded exponential backoff.

Uses Python stdlib http.server to avoid network deps. All tests bind to
127.0.0.1:<random-port> and tear down after each case.
"""
from __future__ import annotations

import http.server
import json
import socket
import sys
import threading
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _free_port() -> int:
    """Bind to port 0 to let OS pick a free port, then close + return number."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _StubHandler(http.server.BaseHTTPRequestHandler):
    """Minimal handler — overridden per test via class attr."""
    response_code: int = 200
    response_body: bytes = b'{"ok": true}'
    received: list[dict[str, Any]] = []

    def do_POST(self):  # noqa: N802 (stdlib API)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"_raw": body.decode("utf-8", "replace")}
        type(self).received.append(payload)
        self.send_response(type(self).response_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).response_body)))
        self.end_headers()
        self.wfile.write(type(self).response_body)

    def log_message(self, format, *args):  # noqa: A002 (silence stderr)
        pass


def _start_server(handler_cls):
    port = _free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def _make_handler(code: int, body: bytes = b'{"ok": true}'):
    """Build a fresh handler subclass per test (received list isolated)."""

    class H(_StubHandler):
        response_code = code
        response_body = body
        received = []  # fresh list per subclass

    return H


def test_post_json_2xx_returns_ok():
    H = _make_handler(200)
    server, port, _ = _start_server(H)
    try:
        from lib.webhook import post_json
        ok, status, err = post_json(
            f"http://127.0.0.1:{port}/", {"x": 1},
            retries=0, timeout_seconds=2.0, backoff_seconds=0.0,
        )
        assert ok is True
        assert status == 200
        assert err is None
        assert H.received == [{"x": 1}]
    finally:
        server.shutdown()


def test_post_json_201_also_ok():
    H = _make_handler(201)
    server, port, _ = _start_server(H)
    try:
        from lib.webhook import post_json
        ok, status, err = post_json(
            f"http://127.0.0.1:{port}/", {},
            retries=0, timeout_seconds=2.0, backoff_seconds=0.0,
        )
        assert ok is True
        assert status == 201
    finally:
        server.shutdown()


def test_post_json_400_does_not_retry():
    H = _make_handler(400, b'{"error": "bad"}')
    server, port, _ = _start_server(H)
    try:
        from lib.webhook import post_json
        ok, status, err = post_json(
            f"http://127.0.0.1:{port}/", {},
            retries=3, timeout_seconds=2.0, backoff_seconds=0.0,
        )
        assert ok is False
        assert status == 400
        assert err is not None and "400" in err
        assert len(H.received) == 1  # client error → no retry
    finally:
        server.shutdown()


def test_post_json_404_does_not_retry():
    H = _make_handler(404)
    server, port, _ = _start_server(H)
    try:
        from lib.webhook import post_json
        ok, status, err = post_json(
            f"http://127.0.0.1:{port}/", {},
            retries=3, timeout_seconds=2.0, backoff_seconds=0.0,
        )
        assert ok is False
        assert status == 404
        assert len(H.received) == 1
    finally:
        server.shutdown()


def test_post_json_500_retries_then_fails():
    H = _make_handler(500)
    server, port, _ = _start_server(H)
    try:
        from lib.webhook import post_json
        ok, status, err = post_json(
            f"http://127.0.0.1:{port}/", {},
            retries=2, timeout_seconds=2.0, backoff_seconds=0.0,
        )
        assert ok is False
        assert status == 500
        assert len(H.received) == 3  # initial + 2 retries
    finally:
        server.shutdown()


def test_post_json_429_retries():
    """429 (rate limit) is the documented exception to client-error no-retry."""
    H = _make_handler(429)
    server, port, _ = _start_server(H)
    try:
        from lib.webhook import post_json
        ok, status, err = post_json(
            f"http://127.0.0.1:{port}/", {},
            retries=2, timeout_seconds=2.0, backoff_seconds=0.0,
        )
        assert ok is False
        assert status == 429
        assert len(H.received) == 3  # initial + 2 retries
    finally:
        server.shutdown()


def test_post_json_unreachable_url():
    """Connection refused → URL error path."""
    port = _free_port()  # nothing listening
    from lib.webhook import post_json
    ok, status, err = post_json(
        f"http://127.0.0.1:{port}/", {},
        retries=1, timeout_seconds=1.0, backoff_seconds=0.0,
    )
    assert ok is False
    assert err is not None


def test_post_json_custom_headers_passed():
    H = _make_handler(200)
    server, port, _ = _start_server(H)
    try:
        from lib.webhook import post_json
        ok, status, _ = post_json(
            f"http://127.0.0.1:{port}/", {"x": 1},
            headers={"X-Test": "marker"},
            retries=0, timeout_seconds=2.0, backoff_seconds=0.0,
        )
        assert ok is True
    finally:
        server.shutdown()


def test_post_json_korean_payload_utf8():
    """ensure_ascii=False — Korean payloads serialize as UTF-8 raw."""
    H = _make_handler(200)
    server, port, _ = _start_server(H)
    try:
        from lib.webhook import post_json
        ok, _, _ = post_json(
            f"http://127.0.0.1:{port}/", {"msg": "안녕"},
            retries=0, timeout_seconds=2.0, backoff_seconds=0.0,
        )
        assert ok is True
        assert H.received == [{"msg": "안녕"}]
    finally:
        server.shutdown()


TESTS = [
    test_post_json_2xx_returns_ok,
    test_post_json_201_also_ok,
    test_post_json_400_does_not_retry,
    test_post_json_404_does_not_retry,
    test_post_json_500_retries_then_fails,
    test_post_json_429_retries,
    test_post_json_unreachable_url,
    test_post_json_custom_headers_passed,
    test_post_json_korean_payload_utf8,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
