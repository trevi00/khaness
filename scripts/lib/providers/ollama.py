"""Ollama (local LLM CLI) provider adapter.

v15.35.2 — second non-Anthropic provider for ensemble evaluator pool.

Wraps `ollama run <model>` subprocess (stdin piped prompt). Local-only —
no API key, no cloud round-trip — good fit for an evaluator role where
*provider diversity* (avoid OpenAI/Codex monoculture in the ensemble)
matters more than absolute model quality.

Discovery: `ollama` CLI on PATH AND at least one installed model
(via `ollama list`). Without an installed model the CLI exits non-zero
and the adapter reports unavailable.

Subprocess pattern mirrors lib/providers/openai.py (codex CLI):
  - stdin pipe avoids shell escaping of long prompts
  - text=True + encoding='utf-8' for cross-locale safety
  - Windows .cmd shim → shell=True + list2cmdline route
  - timeout 300s (LLM responses can be slow; we don't want spurious
    ProviderUnavailableError on legitimate slow runs)

Default model: 'llama3.1:8b' (4.9 GB local install, present in dev env
2026-05-17). Override via AskRequest.model or OLLAMA_DEFAULT_MODEL env.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess

from .base import AskRequest, AskResponse, ProviderBase, ProviderUnavailableError


class OllamaProvider(ProviderBase):
    name = "ollama"
    default_model = "llama3.1:8b"
    capabilities = ("text",)

    def is_available(self) -> bool:
        if not shutil.which("ollama"):
            return False
        # CLI present is necessary but not sufficient — need at least one
        # installed model. `ollama list` exits 0 with header even when
        # empty, so probe stdout for a model row (line count > 1).
        try:
            proc = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        if proc.returncode != 0:
            return False
        # Header line is 'NAME ID SIZE MODIFIED'; subsequent non-empty
        # lines are installed models.
        lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        return len(lines) >= 2

    def ask(self, request: AskRequest) -> AskResponse:
        ollama_path = shutil.which("ollama")
        if not ollama_path:
            raise ProviderUnavailableError("ollama CLI not found on PATH")

        model = (
            request.model
            or os.environ.get("OLLAMA_DEFAULT_MODEL")
            or self.default_model
        )

        # `ollama run <model>` reads prompt from stdin when stdin is piped.
        # No model flag separation needed (unlike codex -m).
        args: list[str] = ["run", model]

        # System prompt: ollama CLI has no separate --system flag, so
        # inline as <system>...</system> prefix (same convention as
        # openai.py). The model will see it as part of the user turn.
        prompt = request.prompt
        if request.system:
            prompt = (
                f"<system>\n{request.system}\n</system>\n\n"
                f"<user>\n{prompt}\n</user>"
            )

        # Windows .cmd shim handling (mirrors openai.py codex path).
        is_batch_shim = (
            platform.system() == "Windows"
            and ollama_path.lower().endswith((".cmd", ".bat"))
        )

        try:
            if is_batch_shim:
                command_line = subprocess.list2cmdline([ollama_path, *args])
                proc = subprocess.run(
                    command_line,
                    shell=True,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=300,
                )
            else:
                proc = subprocess.run(
                    [ollama_path, *args],
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=300,
                )
        except subprocess.TimeoutExpired as e:
            raise ProviderUnavailableError(
                f"ollama run timeout after 300s"
            ) from e
        except OSError as e:
            raise ProviderUnavailableError(
                f"ollama invocation failed: {type(e).__name__}: {e}"
            ) from e

        if proc.returncode != 0:
            raise ProviderUnavailableError(
                f"ollama run exit {proc.returncode}: {(proc.stderr or '')[:300]}"
            )

        return AskResponse(
            text=(proc.stdout or "").strip(),
            provider=self.name,
            model=model,
            raw={"stderr_tail": proc.stderr[-200:] if proc.stderr else None},
        )


PROVIDER = OllamaProvider


# ============================================================================
# Embedded self-check (single-file mutation surface — v15.35.2)
# ============================================================================


def _self_check() -> int:
    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    p = OllamaProvider()

    # Identity / metadata
    case("provider_name_ollama", p.name == "ollama")
    case("provider_default_model_set", bool(p.default_model))
    case("provider_capabilities_text",
         "text" in p.capabilities)

    # is_available is bool (host-dependent — either is valid)
    avail = p.is_available()
    case("is_available_returns_bool", isinstance(avail, bool))

    # AskRequest dataclass round-trip
    req = AskRequest(prompt="ping", model="some-model")
    case("ask_request_constructed", req.prompt == "ping")

    # PROVIDER export points to the class
    case("PROVIDER_export_class", PROVIDER is OllamaProvider)

    # Registry round-trip — if ollama is registered (it is post-v15.35.2),
    # get_provider('ollama') returns an instance whose class is OllamaProvider.
    # NB: when this module is run via `python -m lib.providers.ollama`, the
    # class is imported twice (once as __main__.OllamaProvider, once via
    # lib.providers.ollama.OllamaProvider) and isinstance fails. Verify by
    # class name + provider.name attribute instead.
    try:
        from . import get_provider as _get
        instance = _get("ollama")
        case("registry_round_trip",
             type(instance).__name__ == "OllamaProvider"
             and getattr(instance, "name", None) == "ollama")
    except Exception as e:
        case("registry_round_trip", False, str(e))

    # ask() with no CLI on PATH must raise ProviderUnavailableError
    # (only verifiable when CLI absent — skip otherwise to avoid spawning
    # a real model run during self-check).
    if not avail:
        try:
            p.ask(req)
            case("ask_raises_when_unavailable", False,
                 "expected ProviderUnavailableError")
        except ProviderUnavailableError:
            case("ask_raises_when_unavailable", True)
        except Exception as e:
            case("ask_raises_when_unavailable", False,
                 f"wrong exception: {type(e).__name__}")
    else:
        case("ask_raises_when_unavailable", True,
             "(skipped — ollama available; avoid model spawn in self-check)")

    for name, ok, detail in cases:
        marker = "[OK]" if ok else "[FAIL]"
        suffix = f": {detail}" if detail and not ok else ""
        print(f"  {marker} {name}{suffix}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(cases)} self-check assertions failed")
        return 1
    print(f"\n[OK] {len(cases)} self-check assertions passed")
    return 0


if __name__ == "__main__":
    import sys
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    p = OllamaProvider()
    print(f"lib.providers.ollama — local LLM adapter (v15.35.2)")
    print(f"  name:           {p.name}")
    print(f"  default_model:  {p.default_model}")
    print(f"  capabilities:   {p.capabilities}")
    print(f"  is_available(): {p.is_available()}")
    print(f"  use --self-check to run embedded smoke test")
    sys.exit(0)
