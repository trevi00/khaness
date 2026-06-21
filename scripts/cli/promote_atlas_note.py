"""promote_atlas_note — promote-to-core token consumer (P5 atlas-system).

Per _meta/promotion-policy.md (sub-Atlas → Core Atlas).

Promotes a sub-brain note at `<project>/atlas/<domain>/<type>/<id>.md`
to Core Atlas at `~/.claude/atlas/<domain>/<type>/<id>.md` via a
3-step atomic commit sequence:

  1. validate (token + source + Core domain registered + target absent)
  2. write tmp file at <core-target-dir>/.<id>.md.tmp.<uuid8>
  3. os.replace(tmp, core-target)  --  atomic in same directory
  4. append audit log to ~/.claude/atlas/99-archive/promoted-log.md
  5. advisory_ack.resolve('atlas_promotion_completed').ack(<key>)

Token gate per CLAUDE.md Mutation 분류 표 row "atlas-promotion" (P5):
operator must export HARNESS_MUTATION_TOKEN=promote-to-core in same
shell as the invocation.

3-axes promotion criteria (per _meta/promotion-policy.md) are
OPERATOR-VERIFIED and not enforced by the CLI (external knowledge):
  A. ≥3 distinct projects' sub Atlas cite same pattern
  B. /harness-debate Architect approved
  C. ≥30일 무변경 (no supersedes, not deprecated)

The CLI's `--axes-met` flag is REQUIRED — operator passes a 3-char
string like 'ABC' (all met) or 'AB' (2 met → exit 11, rejection
trigger). Pass-through audit only; not a substitute for actual
verification.

Exit codes:
  0   success
  1   token missing or mismatch
  2   --from path missing or file absent
  3   source frontmatter shape violation (missing id/type)
  4   target already exists in Core (refuse overwrite)
  5   PermissionError (retryable)
  6   FrontmatterParseError (no fences / unreadable)
  7   UnicodeDecodeError or UnicodeEncodeError
  8   domain not in Core registry
  9   other OSError
  10  invalid --axes-met format (must be subset of 'ABC')
  11  fewer than 3 axes met (rejection — record at source, do not promote)

Invocation (operator-CLI only — never from cron/hook/posttooluse/subagent):

  HARNESS_MUTATION_TOKEN=promote-to-core \\
    python -m cli.promote_atlas_note \\
      --from /path/to/project/atlas/debate-engine/concepts/foo.md \\
      --project example_project-analysis \\
      --axes-met ABC \\
      [--update-frontmatter] \\
      [--dry-run]

target path is derived from --from: domain = source path component after
'atlas/', type = next component, filename = same basename.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.advisory_ack import resolve as resolve_advisory  # noqa: E402
from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import ATLAS_DIR  # noqa: E402


REQUIRED_TOKEN: str = "promote-to-core"
TOKEN_ENV: str = "HARNESS_MUTATION_TOKEN"

SOURCE_FRONTMATTER_REQUIRED_KEYS: tuple[str, ...] = ("id", "type")
AXES_VALID = frozenset("ABC")
AXES_MIN_FOR_PROMOTE = 3

_DOMAIN_REGISTRY_HEADER_RE = re.compile(
    r"^###\s+\d+\.\s+`([a-z][a-z0-9_-]*)/`", re.MULTILINE
)


class TokenMissingError(RuntimeError):
    """env HARNESS_MUTATION_TOKEN != promote-to-core."""


class MissingSourceError(RuntimeError):
    """--from absent or file does not exist."""


class MalformedSourceError(RuntimeError):
    """parse_frontmatter returned None or required keys missing."""


class TargetExistsError(RuntimeError):
    """Core already has a note at the derived target path."""


class DomainNotRegisteredError(RuntimeError):
    """Source domain (path component after atlas/) is not in Core registry."""


class AxesFormatError(RuntimeError):
    """--axes-met contains chars outside {A,B,C} or is duplicated."""


class InsufficientAxesError(RuntimeError):
    """Fewer than 3 axes met — promote rejected."""


def _assert_token() -> None:
    actual = os.environ.get(TOKEN_ENV, "").strip()
    if actual != REQUIRED_TOKEN:
        raise TokenMissingError(
            f"promote_atlas_note blocked: env {TOKEN_ENV}={actual!r} != "
            f"{REQUIRED_TOKEN!r}. Operator: set {TOKEN_ENV}={REQUIRED_TOKEN} "
            f"in the same shell as `python -m cli.promote_atlas_note`. "
            f"See CLAUDE.md §Mutation 분류 (P5 row) and "
            f"~/.claude/atlas/_meta/promotion-policy.md."
        )


def _core_registered_domains() -> set[str]:
    registry = ATLAS_DIR / "_meta" / "domain-registry.md"
    if not registry.is_file():
        return set()
    try:
        text = registry.read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(_DOMAIN_REGISTRY_HEADER_RE.findall(text))


def _parse_axes_met(s: str) -> set[str]:
    s = s.strip().upper()
    if not s:
        return set()
    chars = set(s)
    if not chars.issubset(AXES_VALID):
        raise AxesFormatError(
            f"--axes-met={s!r} contains invalid chars. "
            f"Allowed: {sorted(AXES_VALID)} (any subset)."
        )
    if len(chars) != len(s):
        raise AxesFormatError(f"--axes-met={s!r} has duplicate chars.")
    return chars


def _derive_target(source_path: Path) -> tuple[str, str, Path]:
    """From source path, derive (domain, type, core_target_path).

    Source path pattern expected:
      .../atlas/<domain>/<type>/<filename>.md
    where <type> ∈ {concepts, decisions, artifacts, journal} OR top-level
    README.md (handled as domain MOC — but MOCs typically aren't promoted).
    """
    parts = source_path.resolve().parts
    try:
        atlas_idx = parts.index("atlas")
    except ValueError as e:
        raise MalformedSourceError(
            f"source path {source_path} has no 'atlas' component; "
            f"expected .../atlas/<domain>/<type>/<file>.md"
        ) from e
    rest = parts[atlas_idx + 1:]
    if len(rest) < 3:
        raise MalformedSourceError(
            f"source path {source_path} after 'atlas/' has < 3 components "
            f"({rest}); expected <domain>/<type>/<file>.md"
        )
    domain, type_, filename = rest[0], rest[1], rest[-1]
    if not filename.endswith(".md"):
        raise MalformedSourceError(
            f"source filename {filename!r} does not end in .md"
        )
    core_target = ATLAS_DIR / domain / type_ / filename
    return domain, type_, core_target


def _validate_source_frontmatter(source_path: Path) -> dict[str, str]:
    result = parse_frontmatter(source_path)
    if result is None:
        raise MalformedSourceError(
            f"source {source_path}: parse_frontmatter returned None "
            f"(no '---' fences or unreadable)."
        )
    meta, _body = result
    missing = [
        k for k in SOURCE_FRONTMATTER_REQUIRED_KEYS
        if not (meta.get(k, "").strip())
    ]
    if missing:
        raise MalformedSourceError(
            f"source {source_path}: required frontmatter keys missing or "
            f"empty: {missing}. Required: {SOURCE_FRONTMATTER_REQUIRED_KEYS}."
        )
    return meta


def _append_audit_log(domain: str, type_: str, note_id: str,
                      project: str, axes: set[str], ts_ms: int) -> Path:
    """Append one row to 99-archive/promoted-log.md (creating if absent)."""
    log_dir = ATLAS_DIR / "99-archive"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "promoted-log.md"
    if not log_path.exists():
        log_path.write_text(
            "# Promoted Notes Audit Log\n\n"
            "> Append-only ledger of sub-Atlas → Core Atlas promotions "
            "via `cli/promote_atlas_note.py` (promote-to-core token).\n\n"
            "| ts_ms | project | domain | type | note_id | axes |\n"
            "|-------|---------|--------|------|---------|------|\n",
            encoding="utf-8",
        )
    axes_str = "".join(sorted(axes))
    row = f"| {ts_ms} | {project} | {domain} | {type_} | {note_id} | {axes_str} |\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(row)
    return log_path


def _update_source_frontmatter(source_path: Path, core_target: Path,
                               today: str) -> None:
    """Add `promoted_to:` + `promoted_at:` to source frontmatter (best-effort).

    Writes in-place via atomic tmp + os.replace. Idempotent — if keys
    already present, the line is replaced rather than duplicated.
    """
    text = source_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return
    end_fence = text.find("\n---\n", 4)
    if end_fence < 0:
        return
    fm_block = text[4:end_fence]
    rest = text[end_fence + 5:]
    promoted_to_line = f"promoted_to: {core_target.as_posix()}\n"
    promoted_at_line = f"promoted_at: {today}\n"
    new_lines = []
    saw_promoted_to = False
    saw_promoted_at = False
    for line in fm_block.splitlines(keepends=True):
        if line.startswith("promoted_to:"):
            new_lines.append(promoted_to_line)
            saw_promoted_to = True
        elif line.startswith("promoted_at:"):
            new_lines.append(promoted_at_line)
            saw_promoted_at = True
        else:
            new_lines.append(line)
    if not saw_promoted_to:
        new_lines.append(promoted_to_line)
    if not saw_promoted_at:
        new_lines.append(promoted_at_line)
    new_fm = "".join(new_lines)
    new_text = f"---\n{new_fm}---\n{rest}"
    tmp = source_path.with_name(f".{source_path.name}.tmp.{uuid.uuid4().hex[:8]}")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, source_path)


def promote(
    source_path: Path,
    project: str,
    axes_met: set[str],
    update_frontmatter: bool = False,
    dry_run: bool = False,
) -> dict:
    """Promote source note to Core. See module docstring."""
    # Fast fails first.
    if not source_path.exists():
        raise MissingSourceError(
            f"--from {source_path} does not exist (exit 2)."
        )
    meta = _validate_source_frontmatter(source_path)
    note_id = meta["id"].strip()

    domain, type_, core_target = _derive_target(source_path)

    registered = _core_registered_domains()
    if registered and domain not in registered:
        raise DomainNotRegisteredError(
            f"source domain {domain!r} not in Core registry "
            f"({sorted(registered)}); register first or correct source path."
        )

    if core_target.exists():
        raise TargetExistsError(
            f"Core target {core_target} already exists; would overwrite. "
            f"Operator must explicitly archive existing Core note before "
            f"re-promote (no in-place update via this CLI)."
        )

    if len(axes_met) < AXES_MIN_FOR_PROMOTE:
        raise InsufficientAxesError(
            f"--axes-met has {len(axes_met)} axes ({sorted(axes_met)}); "
            f"need ≥{AXES_MIN_FOR_PROMOTE}. Per promotion-policy.md: "
            f"A=distinct projects ≥3, B=debate-validated, C=≥30일 무변경. "
            f"Operator: record rejection at source via "
            f"`rejected_at: YYYY-MM-DD` + `rejected_reason:` frontmatter."
        )

    today = time.strftime("%Y-%m-%d")
    ts_ms = int(time.time() * 1000)
    ack_key = f"{ts_ms}:{project}:{domain}:{note_id}"

    if dry_run:
        return {
            "source": str(source_path),
            "target": str(core_target),
            "domain": domain,
            "type": type_,
            "note_id": note_id,
            "project": project,
            "axes_met": sorted(axes_met),
            "ack_key": ack_key,
            "dry_run": True,
            "today": today,
        }

    # Commit sequence: write tmp -> replace -> audit log -> ack.
    core_target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = core_target.parent / f".{core_target.name}.tmp.{uuid.uuid4().hex[:8]}"
    body_text = source_path.read_text(encoding="utf-8")
    tmp_path.write_text(body_text, encoding="utf-8")
    os.replace(tmp_path, core_target)

    log_path = _append_audit_log(domain, type_, note_id, project, axes_met, ts_ms)

    if update_frontmatter:
        _update_source_frontmatter(source_path, core_target, today)

    resolve_advisory("atlas_promotion_completed").ack(ack_key)

    return {
        "source": str(source_path),
        "target": str(core_target),
        "domain": domain,
        "type": type_,
        "note_id": note_id,
        "project": project,
        "axes_met": sorted(axes_met),
        "audit_log": str(log_path),
        "ack_key": ack_key,
        "dry_run": False,
        "today": today,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="promote_atlas_note",
        description="promote-to-core token consumer (P5).",
    )
    p.add_argument("--from", dest="from_path", required=True, type=Path,
                   help="source note path (must be inside .../atlas/<domain>/<type>/)")
    p.add_argument("--project", required=True,
                   help="sub-brain project name (e.g. example_project-analysis); "
                        "audit log + ack key field")
    p.add_argument("--axes-met", required=True,
                   help="3-axes verification (operator-attested): any subset of "
                        "{A,B,C}. A=≥3 projects cite, B=debate-validated, "
                        "C=≥30일 무변경. Must contain all 3 for promote.")
    p.add_argument("--update-frontmatter", action="store_true",
                   help="atomically add `promoted_to:` + `promoted_at:` to "
                        "source frontmatter after successful promote")
    p.add_argument("--dry-run", action="store_true",
                   help="print intended actions without mutating state")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        _assert_token()
    except TokenMissingError as e:
        print(f"[error] promote_atlas_note: TokenMissingError: {e}",
              file=sys.stderr)
        return 1

    args = _build_parser().parse_args(argv)

    try:
        axes = _parse_axes_met(args.axes_met)
    except AxesFormatError as e:
        print(f"[error] promote_atlas_note: AxesFormatError: {e}",
              file=sys.stderr)
        return 10

    try:
        result = promote(
            source_path=args.from_path,
            project=args.project,
            axes_met=axes,
            update_frontmatter=args.update_frontmatter,
            dry_run=args.dry_run,
        )
    except MissingSourceError as e:
        print(f"[error] promote_atlas_note: MissingSourceError: {e}",
              file=sys.stderr)
        return 2
    except MalformedSourceError as e:
        print(f"[error] promote_atlas_note: MalformedSourceError: {e}",
              file=sys.stderr)
        return 3
    except TargetExistsError as e:
        print(f"[error] promote_atlas_note: TargetExistsError: {e}",
              file=sys.stderr)
        return 4
    except PermissionError as e:
        print(
            f"[error] promote_atlas_note: PermissionError: {e}\n"
            f"advisory: close editor/indexer handles on target note "
            f"and rerun.",
            file=sys.stderr,
        )
        return 5
    except (UnicodeDecodeError, UnicodeEncodeError) as e:
        print(f"[error] promote_atlas_note: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 7
    except DomainNotRegisteredError as e:
        print(f"[error] promote_atlas_note: DomainNotRegisteredError: {e}",
              file=sys.stderr)
        return 8
    except InsufficientAxesError as e:
        print(f"[error] promote_atlas_note: InsufficientAxesError: {e}",
              file=sys.stderr)
        return 11
    except OSError as e:
        print(f"[error] promote_atlas_note: OSError: {e}", file=sys.stderr)
        return 9

    tag = "[dry-run]" if result["dry_run"] else "[done]"
    print(
        f"{tag} promote_atlas_note: project={result['project']} "
        f"domain={result['domain']} type={result['type']} "
        f"note_id={result['note_id']} target={result['target']} "
        f"ack_key={result['ack_key']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
