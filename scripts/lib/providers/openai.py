"""OpenAI (Codex CLI) provider adapter.

Wraps `codex exec <prompt>` for non-interactive Q&A. Requires the `codex`
CLI on PATH (npm: `@openai/codex`). No SDK imports; pure subprocess.

Design:
  - Prompt is passed via stdin to avoid shell-escaping long content.
  - Safe defaults for a pure Q&A use case:
      --skip-git-repo-check  → allow running outside a git repo
      -s read-only           → model-generated shell commands can't mutate
  - Model override via `-m <id>` (simpler than the `-c model="..."` form).
  - Empty request.model defers to Codex CLI's configured default.
  - Windows `.cmd` shim needs shell=True (CreateProcess cannot launch .cmd).
"""
from __future__ import annotations

import shutil
import subprocess

from .base import AskRequest, AskResponse, ProviderBase, ProviderUnavailableError


class OpenAIProvider(ProviderBase):
    name = "openai"
    default_model = ""  # empty → let Codex CLI pick its configured default
    capabilities = ("text", "code")

    def is_available(self) -> bool:
        return shutil.which("codex") is not None

    def ask(self, request: AskRequest) -> AskResponse:
        codex_path = shutil.which("codex")
        if not codex_path:
            raise ProviderUnavailableError("codex CLI not found on PATH")

        model = request.model or self.default_model
        # Minimum flags for a headless Q&A from any cwd, no side effects.
        args: list[str] = ["exec", "--skip-git-repo-check", "-s", "read-only"]
        if model:
            args.extend(["-m", model])

        # Worker-1 M4: codex exec has no separate system-prompt flag, so we
        # inline request.system as a `<system>` block prefix. Honors the
        # ProviderBase contract that AskRequest.system is non-ignorable.
        prompt = request.prompt
        if request.system:
            prompt = (
                f"<system>\n{request.system}\n</system>\n\n"
                f"<user>\n{prompt}\n</user>"
            )

        # Windows batch shims (.cmd/.bat) cannot be launched by CreateProcess
        # directly — Python subprocess needs shell=True to route through cmd.exe.
        # Other platforms (and .exe on Windows) use the normal arg-list path.
        import platform
        is_batch_shim = (
            platform.system() == "Windows"
            and codex_path.lower().endswith((".cmd", ".bat"))
        )

        try:
            if is_batch_shim:
                command_line = subprocess.list2cmdline([codex_path, *args])
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
                    [codex_path, *args],
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=300,
                )
        except subprocess.TimeoutExpired as e:
            raise ProviderUnavailableError("codex exec timeout after 300s") from e

        if proc.returncode != 0:
            raise ProviderUnavailableError(
                f"codex exec exit {proc.returncode}: {proc.stderr[:300]}"
            )

        return AskResponse(
            text=proc.stdout.strip(),
            provider=self.name,
            model=model or "codex-default",
            raw={"stderr_tail": proc.stderr[-200:] if proc.stderr else None},
        )


PROVIDER = OpenAIProvider
