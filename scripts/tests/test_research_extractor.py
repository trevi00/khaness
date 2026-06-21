#!/usr/bin/env python3
"""Unit tests for lib/research_extractor.py — structured extraction handoff."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.providers.base import (  # noqa: E402
    AskRequest, AskResponse, ProviderBase, ProviderUnavailableError,
)
from lib.research_extractor import (  # noqa: E402
    DEFAULT_BYPASS_THRESHOLD_BYTES, DEFAULT_EXTRACTION_MODEL,
    ExtractionResult, ResearchSchema,
    _parse_json_response, extract_structured, resolve_bypass_threshold,
    resolve_extraction_model,
)


# ---- bypass threshold env handling ----

def test_resolve_bypass_threshold_default():
    import lib.research_extractor as RE
    os.environ.pop("RESEARCH_EXTRACTOR_BYPASS_THRESHOLD", None)
    RE._THRESHOLD_WARN_EMITTED = False
    assert resolve_bypass_threshold() == DEFAULT_BYPASS_THRESHOLD_BYTES


def test_resolve_bypass_threshold_respects_in_range_env():
    import lib.research_extractor as RE
    os.environ["RESEARCH_EXTRACTOR_BYPASS_THRESHOLD"] = "4096"
    RE._THRESHOLD_WARN_EMITTED = False
    try:
        assert resolve_bypass_threshold() == 4096
    finally:
        os.environ.pop("RESEARCH_EXTRACTOR_BYPASS_THRESHOLD", None)


def test_resolve_bypass_threshold_falls_back_on_out_of_range():
    import lib.research_extractor as RE
    for bad in ("100", "70000"):
        os.environ["RESEARCH_EXTRACTOR_BYPASS_THRESHOLD"] = bad
        RE._THRESHOLD_WARN_EMITTED = False
        try:
            assert resolve_bypass_threshold() == DEFAULT_BYPASS_THRESHOLD_BYTES
        finally:
            os.environ.pop("RESEARCH_EXTRACTOR_BYPASS_THRESHOLD", None)


def test_resolve_bypass_threshold_falls_back_on_unparseable():
    import lib.research_extractor as RE
    os.environ["RESEARCH_EXTRACTOR_BYPASS_THRESHOLD"] = "abc"
    RE._THRESHOLD_WARN_EMITTED = False
    try:
        assert resolve_bypass_threshold() == DEFAULT_BYPASS_THRESHOLD_BYTES
    finally:
        os.environ.pop("RESEARCH_EXTRACTOR_BYPASS_THRESHOLD", None)


# ---- _parse_json_response ----

def test_parse_json_response_plain():
    out = _parse_json_response('{"title": "x", "n": 3}')
    assert out == {"title": "x", "n": 3}


def test_parse_json_response_strips_code_fence():
    text = "```json\n{\"k\": 1}\n```"
    assert _parse_json_response(text) == {"k": 1}


def test_parse_json_response_bare_fence():
    text = "```\n{\"k\": 2}\n```"
    assert _parse_json_response(text) == {"k": 2}


def test_parse_json_response_returns_none_on_garbage():
    assert _parse_json_response("not json {{{") is None


def test_parse_json_response_returns_none_when_top_level_is_array():
    """Schema requires dict; arrays are rejected to keep callers' contract."""
    assert _parse_json_response("[1, 2, 3]") is None


# ---- Mock provider for extract_structured ----

class _FakeProviderOK(ProviderBase):
    name = "fake"
    default_model = "fake-model"

    def __init__(self, response_text: str):
        self._text = response_text
        self.calls: list[AskRequest] = []

    def is_available(self) -> bool:
        return True

    def ask(self, request: AskRequest) -> AskResponse:
        self.calls.append(request)
        return AskResponse(
            text=self._text, provider=self.name, model=self.default_model,
        )


class _FakeProviderUnavailable(ProviderBase):
    name = "fake-down"
    default_model = ""

    def is_available(self) -> bool:
        return False

    def ask(self, request: AskRequest) -> AskResponse:
        raise ProviderUnavailableError("not reachable")


class _FakeProviderRaisesOnAsk(ProviderBase):
    name = "fake-raises"
    default_model = ""

    def is_available(self) -> bool:
        return True

    def ask(self, request: AskRequest) -> AskResponse:
        raise ProviderUnavailableError("backend timed out")


# ---- extract_structured branches ----

def test_extract_structured_bypasses_small_blob():
    blob = "small content"
    provider = _FakeProviderOK('{"should": "not be called"}')
    result = extract_structured(
        blob, "https://example.com", ResearchSchema.GENERIC_TECH_DOC,
        provider=provider,
    )
    assert result.kind == "bypassed"
    assert result.data["raw"] == blob
    # Provider must not have been called
    assert provider.calls == []


def test_extract_structured_calls_provider_when_blob_large():
    blob = "x" * 20000  # 20KB > default 8KB threshold
    structured_response = '{"title":"T","sections":[],"code_blocks":[],"links":[]}'
    provider = _FakeProviderOK(structured_response)
    result = extract_structured(
        blob, "https://example.com", ResearchSchema.GENERIC_TECH_DOC,
        provider=provider,
    )
    assert result.kind == "structured"
    assert result.data["title"] == "T"
    assert result.provider_used == "fake"
    assert len(provider.calls) == 1


def test_extract_structured_falls_back_when_provider_unavailable():
    blob = "x" * 20000
    provider = _FakeProviderUnavailable()
    result = extract_structured(
        blob, "https://example.com", ResearchSchema.GENERIC_TECH_DOC,
        provider=provider,
    )
    assert result.kind == "fallback"
    assert "unavailable" in result.data["reason"]
    assert result.data["raw"] == blob


def test_extract_structured_falls_back_on_provider_exception():
    blob = "x" * 20000
    provider = _FakeProviderRaisesOnAsk()
    result = extract_structured(
        blob, "https://example.com", ResearchSchema.GENERIC_TECH_DOC,
        provider=provider,
    )
    assert result.kind == "fallback"
    assert "raised" in result.data["reason"]


def test_extract_structured_falls_back_on_non_json_response():
    blob = "x" * 20000
    provider = _FakeProviderOK("This is prose, not JSON.")
    result = extract_structured(
        blob, "https://example.com", ResearchSchema.GENERIC_TECH_DOC,
        provider=provider,
    )
    assert result.kind == "fallback"
    assert "non-JSON" in result.data["reason"]
    assert result.raw_response_preview is not None


def test_extract_structured_uses_schema_specific_prompt():
    """Different schemas should produce different prompt contents."""
    blob = "x" * 20000
    provider = _FakeProviderOK('{"k":1}')
    extract_structured(
        blob, "https://x", ResearchSchema.METHODOLOGY,
        provider=provider,
    )
    assert "methodology_name" in provider.calls[0].prompt


def test_extract_structured_rejects_non_str_blob():
    provider = _FakeProviderOK('{}')
    try:
        extract_structured(
            12345, "https://x", ResearchSchema.GENERIC_TECH_DOC,  # type: ignore[arg-type]
            provider=provider,
        )
    except ValueError:
        return
    raise AssertionError("expected ValueError on non-str raw_blob")


def test_extract_structured_explicit_bypass_threshold_zero_forces_provider():
    """bypass_threshold=0 forces provider call even on tiny blobs."""
    blob = "tiny"
    provider = _FakeProviderOK('{"ok":true}')
    result = extract_structured(
        blob, "https://x", ResearchSchema.GENERIC_TECH_DOC,
        provider=provider, bypass_threshold=0,
    )
    assert result.kind == "structured"
    assert len(provider.calls) == 1


# ---- model selection (gpt-5.5 default) ----

def test_default_extraction_model_is_gpt_5_5():
    assert DEFAULT_EXTRACTION_MODEL == "gpt-5.5"


def test_resolve_extraction_model_default_when_env_unset():
    os.environ.pop("RESEARCH_EXTRACTOR_MODEL", None)
    assert resolve_extraction_model() == "gpt-5.5"


def test_resolve_extraction_model_respects_env_override():
    os.environ["RESEARCH_EXTRACTOR_MODEL"] = "gpt-4o-mini"
    try:
        assert resolve_extraction_model() == "gpt-4o-mini"
    finally:
        os.environ.pop("RESEARCH_EXTRACTOR_MODEL", None)


def test_extract_structured_passes_default_model_to_provider():
    """extract_structured should hand the resolved model into AskRequest."""
    blob = "x" * 20000
    provider = _FakeProviderOK('{"ok":true}')
    os.environ.pop("RESEARCH_EXTRACTOR_MODEL", None)
    extract_structured(
        blob, "https://x", ResearchSchema.GENERIC_TECH_DOC, provider=provider,
    )
    assert provider.calls[0].model == "gpt-5.5"


def test_extract_structured_call_site_model_overrides_env():
    """Explicit model arg wins over env."""
    blob = "x" * 20000
    provider = _FakeProviderOK('{"ok":true}')
    os.environ["RESEARCH_EXTRACTOR_MODEL"] = "gpt-4o-mini"
    try:
        extract_structured(
            blob, "https://x", ResearchSchema.GENERIC_TECH_DOC,
            provider=provider, model="o3-mini",
        )
        assert provider.calls[0].model == "o3-mini"
    finally:
        os.environ.pop("RESEARCH_EXTRACTOR_MODEL", None)


TESTS = [
    test_resolve_bypass_threshold_default,
    test_resolve_bypass_threshold_respects_in_range_env,
    test_resolve_bypass_threshold_falls_back_on_out_of_range,
    test_resolve_bypass_threshold_falls_back_on_unparseable,
    test_parse_json_response_plain,
    test_parse_json_response_strips_code_fence,
    test_parse_json_response_bare_fence,
    test_parse_json_response_returns_none_on_garbage,
    test_parse_json_response_returns_none_when_top_level_is_array,
    test_extract_structured_bypasses_small_blob,
    test_extract_structured_calls_provider_when_blob_large,
    test_extract_structured_falls_back_when_provider_unavailable,
    test_extract_structured_falls_back_on_provider_exception,
    test_extract_structured_falls_back_on_non_json_response,
    test_extract_structured_uses_schema_specific_prompt,
    test_extract_structured_rejects_non_str_blob,
    test_extract_structured_explicit_bypass_threshold_zero_forces_provider,
    test_default_extraction_model_is_gpt_5_5,
    test_resolve_extraction_model_default_when_env_unset,
    test_resolve_extraction_model_respects_env_override,
    test_extract_structured_passes_default_model_to_provider,
    test_extract_structured_call_site_model_overrides_env,
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
