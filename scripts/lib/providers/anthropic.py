"""Anthropic (Claude) provider adapter.

Backend discovery order:
  1. `anthropic` Python SDK + ANTHROPIC_API_KEY env var
  2. `claude` CLI on PATH

Claude Code hosts typically have the CLI present, so this adapter is
usable out of the box even without SDK install. Network calls are
performed by the chosen backend; this adapter does not talk HTTP directly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from .base import AskRequest, AskResponse, ProviderBase, ProviderUnavailableError


class AnthropicProvider(ProviderBase):
    name = "anthropic"
    default_model = "claude-sonnet-4-6"
    capabilities = ("text", "json", "long-context", "code")

    def is_available(self) -> bool:
        if self._sdk_ready():
            return True
        return shutil.which("claude") is not None

    def ask(self, request: AskRequest) -> AskResponse:
        if self._sdk_ready():
            return self._ask_sdk(request)
        if shutil.which("claude"):
            return self._ask_cli(request)
        raise ProviderUnavailableError(
            "Neither anthropic SDK (with ANTHROPIC_API_KEY) nor `claude` CLI is available."
        )

    # --- internals ---

    def _sdk_ready(self) -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def _ask_sdk(self, request: AskRequest) -> AskResponse:
        import anthropic  # type: ignore
        client = anthropic.Anthropic()
        model = request.model or self.default_model
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens or 4096,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.system:
            kwargs["system"] = request.system

        # Worker-1 H2: SDK exceptions must surface as ProviderUnavailableError
        # so callers (engine/external_jury) can apply unified failure handling.
        try:
            msg = client.messages.create(**kwargs)
        except Exception as e:
            raise ProviderUnavailableError(
                f"anthropic SDK call failed: {type(e).__name__}: {e}"
            ) from e
        text = "".join(
            getattr(block, "text", "")
            for block in msg.content
            if getattr(block, "type", "") == "text"
        )
        usage = getattr(msg, "usage", None)
        return AskResponse(
            text=text,
            provider=self.name,
            model=model,
            tokens_in=getattr(usage, "input_tokens", None),
            tokens_out=getattr(usage, "output_tokens", None),
            raw={"id": getattr(msg, "id", None)},
        )

    def _ask_cli(self, request: AskRequest) -> AskResponse:
        model = request.model or self.default_model
        cmd = ["claude", "--model", model, "--print"]
        if request.system:
            cmd.extend(["--append-system-prompt", request.system])
        try:
            proc = subprocess.run(
                cmd,
                input=request.prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=180,
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderUnavailableError(
                f"claude CLI timed out after {e.timeout}s"
            ) from e
        except OSError as e:
            raise ProviderUnavailableError(
                f"claude CLI invocation failed: {type(e).__name__}: {e}"
            ) from e
        if proc.returncode != 0:
            raise ProviderUnavailableError(
                f"claude CLI exit {proc.returncode}: {proc.stderr[:200]}"
            )
        return AskResponse(
            text=proc.stdout.strip(),
            provider=self.name,
            model=model,
            raw={"stderr_tail": proc.stderr[-200:] if proc.stderr else None},
        )


PROVIDER = AnthropicProvider
