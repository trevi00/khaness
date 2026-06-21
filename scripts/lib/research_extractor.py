"""research_extractor — structured extraction handoff to a cheaper provider.

Per user concern (2026-05-08): Playwright `browser_snapshot` and full-page
WebFetch return blobs of 10K+ tokens (mostly accessibility-tree noise or
boilerplate HTML). Loading those raw into the top-tier reasoning model
(Claude) for "extract title / code blocks / key claims" is a low-reasoning
task at top-tier cost.

Pipeline:
  1. WebFetch / Playwright fetches raw_blob.
  2. extract_structured(raw_blob, source_url, schema) → JSON via OpenAI
     (Codex CLI) provider. Default model is provider-configured (typically
     gpt-4o-mini-class for cheap extraction).
  3. Researcher agent synthesizes from N normalized JSON dicts instead of
     N raw blobs. Claude sees only the structured form.

Schema enumeration (initial set; extend by adding to ResearchSchema enum):
  - GENERIC_TECH_DOC: {title, sections[], code_blocks[], links[]}
  - METHODOLOGY     : {title, methodology_name, principles[], anti_patterns[]}
  - INCIDENT_POSTMORTEM: {title, root_cause, mitigation, lessons[]}
  - REPO_USAGE      : {repo, language, idiomatic_patterns[], example_calls[]}
  - PAPER_ABSTRACT  : {title, claim, method, results, citations[]}

Token-budget gate (BYPASS_THRESHOLD_BYTES): if raw_blob is small enough
to fit in Claude context cheaply, return it AS-IS (no provider call).
Threshold default 8000 bytes (~2K tokens) — env-overridable
RESEARCH_EXTRACTOR_BYPASS_THRESHOLD bounds [1024, 65536].

Graceful degradation: if OpenAIProvider.is_available() False or .ask()
raises ProviderUnavailableError, return raw_blob unchanged with a
warning marker — researcher synthesizes from raw at that point. No
silent failure.

Public surface:
  - ResearchSchema enum
  - ExtractionResult dataclass
  - resolve_bypass_threshold() respects env override
  - extract_structured(raw_blob, source_url, schema, provider=None)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from enum import Enum

from .providers.base import (
    AskRequest, ProviderBase, ProviderUnavailableError,
)


DEFAULT_BYPASS_THRESHOLD_BYTES: int = 8000
MIN_BYPASS_THRESHOLD_BYTES: int = 1024
MAX_BYPASS_THRESHOLD_BYTES: int = 65536

# Extraction model — pinned to gpt-5.5 (cheap/fast tier for structured
# extraction). Override at runtime via RESEARCH_EXTRACTOR_MODEL env, or
# at call site via extract_structured(..., model=<id>).
DEFAULT_EXTRACTION_MODEL: str = "gpt-5.5"


_THRESHOLD_WARN_EMITTED = False


def resolve_extraction_model() -> str:
    """Read RESEARCH_EXTRACTOR_MODEL env override; fallback to default."""
    raw = os.environ.get("RESEARCH_EXTRACTOR_MODEL")
    if raw is None or raw == "":
        return DEFAULT_EXTRACTION_MODEL
    return raw


def resolve_bypass_threshold() -> int:
    """Read RESEARCH_EXTRACTOR_BYPASS_THRESHOLD env override.

    Out-of-bounds or unparseable → DEFAULT + warn-once.
    """
    global _THRESHOLD_WARN_EMITTED
    raw = os.environ.get("RESEARCH_EXTRACTOR_BYPASS_THRESHOLD")
    if raw is None or raw == "":
        return DEFAULT_BYPASS_THRESHOLD_BYTES
    try:
        v = int(raw)
    except (TypeError, ValueError):
        if not _THRESHOLD_WARN_EMITTED:
            print(
                f"RESEARCH_EXTRACTOR_BYPASS_THRESHOLD unparseable "
                f"({raw!r}), using {DEFAULT_BYPASS_THRESHOLD_BYTES}",
                file=sys.stderr,
            )
            _THRESHOLD_WARN_EMITTED = True
        return DEFAULT_BYPASS_THRESHOLD_BYTES
    if v < MIN_BYPASS_THRESHOLD_BYTES or v > MAX_BYPASS_THRESHOLD_BYTES:
        if not _THRESHOLD_WARN_EMITTED:
            print(
                f"RESEARCH_EXTRACTOR_BYPASS_THRESHOLD={v} out of bounds "
                f"[{MIN_BYPASS_THRESHOLD_BYTES}, {MAX_BYPASS_THRESHOLD_BYTES}], "
                f"using {DEFAULT_BYPASS_THRESHOLD_BYTES}",
                file=sys.stderr,
            )
            _THRESHOLD_WARN_EMITTED = True
        return DEFAULT_BYPASS_THRESHOLD_BYTES
    return v


class ResearchSchema(Enum):
    """Structured-extraction schemas. Add new entries by appending here +
    extending _SCHEMA_PROMPTS."""
    GENERIC_TECH_DOC = "generic_tech_doc"
    METHODOLOGY = "methodology"
    INCIDENT_POSTMORTEM = "incident_postmortem"
    REPO_USAGE = "repo_usage"
    PAPER_ABSTRACT = "paper_abstract"


_SCHEMA_PROMPTS: dict[ResearchSchema, str] = {
    ResearchSchema.GENERIC_TECH_DOC: (
        "Extract from the document below into JSON with keys: title (str), "
        "sections (list of {heading, summary}), code_blocks (list of "
        "{lang, body}), links (list of {url, anchor_text}). Only include "
        "what is verbatim present — no invented content."
    ),
    ResearchSchema.METHODOLOGY: (
        "Extract from the document below into JSON with keys: title (str), "
        "methodology_name (str), principles (list of str — verbatim "
        "principle statements), anti_patterns (list of str — explicit "
        "warnings or 'do not' rules). Only verbatim — no inference."
    ),
    ResearchSchema.INCIDENT_POSTMORTEM: (
        "Extract from the postmortem below into JSON with keys: title "
        "(str), root_cause (str — single sentence), mitigation (str), "
        "lessons (list of str). Verbatim only."
    ),
    ResearchSchema.REPO_USAGE: (
        "Extract from the repo source/README below into JSON with keys: "
        "repo (str), language (str), idiomatic_patterns (list of str), "
        "example_calls (list of {fn_name, args_summary}). Verbatim only."
    ),
    ResearchSchema.PAPER_ABSTRACT: (
        "Extract from the paper abstract below into JSON with keys: "
        "title (str), claim (str — single sentence thesis), method (str), "
        "results (str), citations (list of str — bibliographic refs). "
        "Verbatim only."
    ),
}


@dataclass(frozen=True)
class ExtractionResult:
    """One extraction outcome.

    `kind`:
      - 'structured' : `data` is the parsed JSON dict from provider
      - 'bypassed'   : raw was small enough → `data` = {'raw': raw_blob}
      - 'fallback'   : provider unavailable/failed → `data` = {'raw': raw_blob, 'reason': '...'}
    """
    kind: str
    data: dict
    source_url: str
    schema: ResearchSchema
    bytes_input: int
    provider_used: str | None = None
    raw_response_preview: str | None = field(default=None)


def _build_prompt(raw_blob: str, source_url: str,
                  schema: ResearchSchema) -> str:
    schema_prompt = _SCHEMA_PROMPTS[schema]
    return (
        f"{schema_prompt}\n\n"
        f"Source URL: {source_url}\n\n"
        f"Document:\n---\n{raw_blob}\n---\n\n"
        f"Output ONLY a single JSON object. No prose, no code fence."
    )


def _parse_json_response(text: str) -> dict | None:
    """Tolerant JSON parse: strip code fences if present, return None on failure."""
    stripped = text.strip()
    # Handle ```json ... ``` or ``` ... ``` fences
    if stripped.startswith("```"):
        # Find closing fence
        first_newline = stripped.find("\n")
        if first_newline != -1:
            body = stripped[first_newline + 1:]
            if body.endswith("```"):
                body = body[:-3].strip()
            stripped = body
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def extract_structured(raw_blob: str, source_url: str,
                        schema: ResearchSchema,
                        provider: ProviderBase | None = None,
                        bypass_threshold: int | None = None,
                        model: str | None = None,
                        ) -> ExtractionResult:
    """Normalize `raw_blob` into a structured dict per `schema`.

    Behavior:
      - if len(raw_blob_bytes) <= bypass_threshold → return ExtractionResult
        kind='bypassed' (small enough; researcher pulls raw directly).
      - else → call provider.ask() with the schema prompt + raw_blob.
        On success + JSON-parse → kind='structured'. On any failure
        → kind='fallback' with raw_blob preserved.

    `provider` defaults to a fresh OpenAIProvider (via Codex CLI). Tests
    inject a mock implementing ProviderBase.
    """
    if not isinstance(raw_blob, str):
        raise ValueError(f"raw_blob must be str, got {type(raw_blob).__name__}")

    threshold = bypass_threshold if bypass_threshold is not None else resolve_bypass_threshold()
    blob_bytes = len(raw_blob.encode("utf-8"))

    if blob_bytes <= threshold:
        return ExtractionResult(
            kind="bypassed",
            data={"raw": raw_blob},
            source_url=source_url,
            schema=schema,
            bytes_input=blob_bytes,
        )

    if provider is None:
        from .providers.openai import OpenAIProvider
        provider = OpenAIProvider()

    if not provider.is_available():
        return ExtractionResult(
            kind="fallback",
            data={"raw": raw_blob, "reason": f"provider {provider.name} unavailable"},
            source_url=source_url,
            schema=schema,
            bytes_input=blob_bytes,
        )

    prompt = _build_prompt(raw_blob, source_url, schema)
    resolved_model = model if model is not None else resolve_extraction_model()
    try:
        resp = provider.ask(AskRequest(prompt=prompt, model=resolved_model))
    except ProviderUnavailableError as e:
        return ExtractionResult(
            kind="fallback",
            data={"raw": raw_blob, "reason": f"provider raised: {e}"},
            source_url=source_url,
            schema=schema,
            bytes_input=blob_bytes,
        )

    parsed = _parse_json_response(resp.text)
    if parsed is None:
        return ExtractionResult(
            kind="fallback",
            data={"raw": raw_blob, "reason": "provider returned non-JSON"},
            source_url=source_url,
            schema=schema,
            bytes_input=blob_bytes,
            provider_used=resp.provider,
            raw_response_preview=resp.text[:200],
        )

    return ExtractionResult(
        kind="structured",
        data=parsed,
        source_url=source_url,
        schema=schema,
        bytes_input=blob_bytes,
        provider_used=resp.provider,
    )
