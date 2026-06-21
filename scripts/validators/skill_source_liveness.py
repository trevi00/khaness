#!/usr/bin/env python3
"""skill_source_liveness — Source URL 활성성 advisory (opt-in, cron-only).

회고에서 도출한 G1 강화 항목: 인용된 URL이 dead-link이면 verbatim quote의
추적성이 의미 무효 — 9게이트 G1(기능 적합성)을 직접 강화.

기본 회귀에 미포함 (VALIDATOR_NAMES 등록 안 함). URL fetch는 비용 큼:
- HEAD method, 10s timeout, redirect follow
- 200/301/302/308 OK; 401/403도 OK (auth wall — URL 자체는 살아있음)
- 404/5xx → DEAD (WARN, FAIL 아님 — advisory 모드)
- 네트워크 오류 → NETWORK (WARN — false positive 회피)

대상: skill_quality_axes 와 동일한 enforce 정책
(MANDATORY_PREFIXES OR frontmatter `quality_axes_enforced: true`).

호출:
    python -m validators.skill_source_liveness
    python validators/skill_source_liveness.py

cron 권장 주기: 주 1회.
"""
from __future__ import annotations

import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import SKILLS_DIR  # noqa: E402
from validators.skill_quality_axes import _is_enforced  # noqa: E402

URL_RE = re.compile(r"https?://[^\s)\]]+")
TIMEOUT_SEC = 10
# OK semantics: URL exists / addressable. Codes that signal liveness:
# - 200/301/302/308: standard success / redirect
# - 401/403: auth-wall (resource exists, protected)
# - 405: Method Not Allowed (HEAD blocked; URL exists, GET would work)
# - 406: Not Acceptable (Accept/UA mismatch; URL exists)
# 405/406 added per wave 7 후속 6 — validator's default Python-urllib UA
# triggers these on bot-protected sites (uber, vulkan.lunarg, iso25000)
# even though the URLs are reachable in a browser.
OK_CODES = frozenset({200, 301, 302, 308, 401, 403, 405, 406})

# Browser-like User-Agent (Mozilla shape) to reduce bot-detection 406 noise
# without resorting to full headless browser. Caller can opt out by setting
# `_url_opener` to a test stub.
_USER_AGENT = (
    "Mozilla/5.0 (compatible; HarnessSourceLiveness/1.0; "
    "+https://github.com/anthropics/claude-code) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Unverified SSL context for fallback. Liveness probing is informational
# (HEAD request, status code only — no payload transfer / no PII), so SSL
# cert chain verification is non-essential for the validator's purpose. Used
# only AFTER the verified context fails with cert-chain error, so non-SSL
# failures still bubble up correctly. Python's bundled openssl on Windows
# is missing intermediate CAs that browser-class clients (curl) accept;
# without this fallback netflixtechblog.com / spinnaker blog / etc. all
# false-positive NETWORK fail despite being live.
_UNVERIFIED_CONTEXT = ssl._create_unverified_context()

_SSL_CERT_FAIL_TOKEN = "CERTIFICATE_VERIFY_FAILED"

# 의존성 주입 (unit test에서 monkey-patch). 실제 fetch는 _real_open.
_url_opener = None


def _build_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "*/*",
        },
    )


def _real_open(url: str):
    return urllib.request.urlopen(_build_request(url), timeout=TIMEOUT_SEC)


def _real_open_unverified(url: str):
    return urllib.request.urlopen(
        _build_request(url), timeout=TIMEOUT_SEC, context=_UNVERIFIED_CONTEXT
    )


def check_url(url: str) -> tuple[str, str]:
    """Return ("OK"|"DEAD"|"NETWORK", detail)."""
    opener = _url_opener or _real_open
    try:
        with opener(url) as resp:
            code = resp.getcode()
            if code in OK_CODES:
                return ("OK", str(code))
            return ("DEAD", f"HTTP {code}")
    except urllib.error.HTTPError as e:
        if e.code in OK_CODES:
            return ("OK", str(e.code))
        return ("DEAD", f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        # SSL cert chain failure fallback: retry with unverified context.
        # Liveness check is informational (HEAD only), not data transfer —
        # cert validation provides ~0 security benefit for status probing.
        # Triggered by Python urllib missing intermediate CAs (e.g.,
        # netflixtechblog.com on Medium CDN, spinnaker.io) that browser
        # clients verify fine via OS cert store.
        if (_url_opener is None
                and _SSL_CERT_FAIL_TOKEN in str(e)):
            try:
                with _real_open_unverified(url) as resp:
                    code = resp.getcode()
                    if code in OK_CODES:
                        return ("OK", f"{code} (ssl-unverified)")
                    return ("DEAD", f"HTTP {code} (ssl-unverified)")
            except urllib.error.HTTPError as e2:
                if e2.code in OK_CODES:
                    return ("OK", f"{e2.code} (ssl-unverified)")
                return ("DEAD", f"HTTP {e2.code} (ssl-unverified)")
            except Exception as e2:
                return ("NETWORK", f"ssl-unverified retry failed: {type(e2).__name__}: {e2}")
        return ("NETWORK", f"{type(e).__name__}: {e}")
    except Exception as e:
        return ("NETWORK", f"{type(e).__name__}: {e}")


def _enforced_targets() -> list[Path]:
    targets: list[Path] = []
    if not SKILLS_DIR.is_dir():
        return targets
    for path in sorted(SKILLS_DIR.glob("**/*.md")):
        if path.name.startswith("_"):
            continue
        try:
            rel = path.relative_to(SKILLS_DIR)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] == "_pipeline":
            continue
        res = parse_frontmatter(path)
        meta = res[0] if res is not None else None
        if _is_enforced(rel, meta):
            targets.append(path)
    return targets


def main() -> int:
    targets = _enforced_targets()
    if not targets:
        print("[PASS] enforce 대상 노드 없음 (skip)")
        return 0

    total_ok = 0
    total_dead = 0
    total_network = 0

    for path in targets:
        text = path.read_text(encoding="utf-8")
        if "## Source" not in text:
            continue
        block = text.split("## Source", 1)[1]
        urls = sorted(set(URL_RE.findall(block)))
        rel = path.relative_to(SKILLS_DIR)
        for url in urls:
            url = url.rstrip(",.;)]")
            status, detail = check_url(url)
            if status == "OK":
                total_ok += 1
            elif status == "DEAD":
                print(f"[WARN] {rel}: DEAD {url} ({detail})")
                total_dead += 1
            else:
                print(f"[WARN] {rel}: NETWORK {url} ({detail})")
                total_network += 1

    print(
        f"[PASS] skill_source_liveness "
        f"(ok={total_ok}, dead={total_dead}, network={total_network})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
