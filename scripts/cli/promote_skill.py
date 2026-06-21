"""promote_skill — enable-skill token consumer (Wave 20 architectural gap closure).

Converged design contract: debate-1779507623-8a6f45 (3 gen, 73-field LOCK,
ontology sha1=c150cf125daafcbc261ea094a3ec6b4b0f7894af).

CLAUDE_HOME env honored via lib.paths (CI/test sandboxes must propagate).

Promotes a candidate at ~/.claude/skill-candidates/<cid>.json into a registered
skill at ~/.claude/skills/<name>/SKILL.md via a 4-step atomic commit sequence:

  1. mark_candidate_promoting(candidate_path)
       writes <candidate>.promoting sibling marker; FileExistsError on stale
       marker blocks re-entry after crash.
  2. write tmp file at skills/<name>/.SKILL.md.tmp.<uuid8>
  3. os.replace(tmp, skills/<name>/SKILL.md)  --  atomic in same directory
  4. commit_candidate_promoted(candidate_path, ts_ms)
       renames candidate to .promoted.<ts_ms> (audit trail; never deleted)
  5. advisory_ack.resolve('skill_promotion_completed').ack(f'{ts_ms}:{cid}')

Token gate per CLAUDE.md Mutation 분류 표 row "skill 활성화" — operator must
export HARNESS_MUTATION_TOKEN=enable-skill in same shell as the invocation.

Exit codes (LOCK-fixed scopes):
  0  success
  1  token missing or mismatch
  2  --body-from path missing or file absent
  3  frontmatter shape violation (missing name/description/keywords)
  4  stale .promoting marker (operator must clear before re-promote)
  5  PermissionError (retryable — close editor/indexer handles and rerun)
  6  JSONDecodeError on candidate manifest
  7  UnicodeDecodeError or UnicodeEncodeError
  8  namespace policy violation (--as prefix or _gsd subname shape)
  9  other OSError (non-retryable)

Invocation (operator-CLI only — never from cron/hook/posttooluse/subagent):

  HARNESS_MUTATION_TOKEN=enable-skill \
    python -m cli.promote_skill \
      --candidate skill-bash-repeat-370ecf79 \
      --body-from /path/to/operator/written/skill_body.md \
      --as gsd-bash-repetition-codifier \
      [--candidates-dir /alt/path] \
      [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.advisory_ack import resolve as resolve_advisory  # noqa: E402
from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import SKILLS_DIR, STATE_DIR, CLAUDE_HOME  # noqa: E402


REQUIRED_TOKEN: str = "enable-skill"
TOKEN_ENV: str = "HARNESS_MUTATION_TOKEN"

CANDIDATES_DIR: Path = CLAUDE_HOME / "skill-candidates"

FRONTMATTER_REQUIRED_KEYS: tuple[str, ...] = ("name", "description", "keywords")

# Namespace policy mirrors validators/skill_frontmatter.py:54-80 + :76.
NAMESPACE_FORBIDDEN_TOP = ("harness-",)
NAMESPACE_FORBIDDEN_BARE = ("harness",)
GSD_SUBNAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class TokenMissingError(RuntimeError):
    """env HARNESS_MUTATION_TOKEN != enable-skill."""


class MissingBodyError(RuntimeError):
    """--body-from absent or file does not exist."""


class MalformedBodyError(RuntimeError):
    """parse_frontmatter returned None or required keys missing/empty."""


class NamespaceViolationError(RuntimeError):
    """--as does not satisfy gsd-* / _gsd/<subname> policy."""


def _assert_token() -> None:
    """REFUSE invocation without enable-skill token.

    Strip-then-exact-match parity with cron/run_l2_promotion.py:72.
    """
    actual = os.environ.get(TOKEN_ENV, "").strip()
    if actual != REQUIRED_TOKEN:
        raise TokenMissingError(
            f"promote_skill blocked: env {TOKEN_ENV}={actual!r} != "
            f"{REQUIRED_TOKEN!r}. Operator: set {TOKEN_ENV}={REQUIRED_TOKEN} "
            f"in the same shell as `python -m cli.promote_skill`. "
            f"See CLAUDE.md §Mutation 분류."
        )


def _resolve_namespace(as_name: str) -> tuple[Path, str]:
    """Validate --as and return (target_dir, target_dir_name_for_audit).

    Allowed:
      gsd-<rest>      -> SKILLS_DIR / 'gsd-<rest>' / SKILL.md
      _gsd/<subname>  -> SKILLS_DIR / '_gsd' / '<subname>' / SKILL.md

    Subname rules: regex ^[a-z][a-z0-9_-]{0,31}$, exactly 1 segment.
    """
    s = as_name.strip()
    if not s:
        raise NamespaceViolationError("--as is empty after strip")

    # Forbidden prefixes (harness-* and bare harness, mirroring validator).
    top_seg = s.split("/", 1)[0]
    if top_seg in NAMESPACE_FORBIDDEN_BARE or any(
        top_seg.startswith(p) for p in NAMESPACE_FORBIDDEN_TOP
    ):
        raise NamespaceViolationError(
            f"--as {s!r} top segment {top_seg!r} matches forbidden namespace "
            f"({NAMESPACE_FORBIDDEN_BARE + NAMESPACE_FORBIDDEN_TOP}); use gsd-* "
            f"or _gsd/<subname>."
        )

    if s.startswith("gsd-"):
        if "/" in s:
            raise NamespaceViolationError(
                f"--as {s!r} starts with gsd- but contains '/'; gsd-* must be "
                f"a single segment."
            )
        return SKILLS_DIR / s, s

    if s.startswith("_gsd/"):
        rest = s[len("_gsd/"):]
        if rest in (".", "..", "") or rest.endswith("/"):
            raise NamespaceViolationError(
                f"--as _gsd/{rest!r} subname forbidden (empty / dot / "
                f"trailing slash)."
            )
        if "/" in rest:
            raise NamespaceViolationError(
                f"--as _gsd/{rest!r} has more than one path segment; subname "
                f"must be exactly 1 segment."
            )
        if not GSD_SUBNAME_RE.match(rest):
            raise NamespaceViolationError(
                f"--as _gsd/{rest!r} subname does not match "
                f"{GSD_SUBNAME_RE.pattern}."
            )
        return SKILLS_DIR / "_gsd" / rest, f"_gsd/{rest}"

    raise NamespaceViolationError(
        f"--as {s!r} must start with 'gsd-' or '_gsd/'; got prefix "
        f"{s.split('/', 1)[0]!r}."
    )


def _resolve_candidate_path(cid: str, candidates_dir: Path) -> Path:
    """Return canonical candidate JSON path.

    Accepts either bare cid (e.g. 'skill-bash-repeat-370ecf79') or full
    filename (with .json). Does NOT verify existence here — caller handles
    FileNotFoundError so the error path is auditable.
    """
    if cid.endswith(".json"):
        cid = cid[:-len(".json")]
    if "/" in cid or "\\" in cid:
        raise NamespaceViolationError(
            f"--candidate {cid!r} contains path separators; supply bare id."
        )
    return candidates_dir / f"{cid}.json"


def _load_candidate_manifest(candidate_path: Path) -> dict:
    """Read + json-parse candidate manifest. FileNotFoundError surfaces as OSError."""
    text = candidate_path.read_text(encoding="utf-8")
    return json.loads(text)


def _validate_body(body_path: Path) -> tuple[dict[str, str], str]:
    """parse_frontmatter + required-key non-empty check.

    Raises MalformedBodyError on any failure. Returns (meta, body) on success
    (not strictly used by caller but kept for symmetry with parse_frontmatter).
    """
    result = parse_frontmatter(body_path)
    if result is None:
        raise MalformedBodyError(
            f"--body-from {body_path}: parse_frontmatter returned None "
            f"(no '---' fences or unreadable)."
        )
    meta, body = result
    missing = [
        k for k in FRONTMATTER_REQUIRED_KEYS
        if not (meta.get(k, "").strip())
    ]
    if missing:
        raise MalformedBodyError(
            f"--body-from {body_path}: required frontmatter keys missing or "
            f"empty: {missing}. Required tuple: {FRONTMATTER_REQUIRED_KEYS} "
            f"(per validators/skill_frontmatter.py:41 REQUIRED_FIELDS)."
        )
    return meta, body


def mark_candidate_promoting(candidate_path: Path) -> Path:
    """Write a sibling `.promoting` marker. FileExistsError on stale marker.

    Signature locked by debate ontology: (candidate_path: Path) -> Path.
    """
    marker = candidate_path.with_name(candidate_path.name + ".promoting")
    if marker.exists():
        raise FileExistsError(
            f"stale .promoting marker at {marker}; operator must clear "
            f"manually before re-promote (exit 4)."
        )
    marker.write_text(
        f"promoting:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}\n",
        encoding="utf-8",
    )
    return marker


def commit_candidate_promoted(candidate_path: Path, ts_ms: int) -> Path:
    """Single os.rename of candidate JSON to .promoted.<ts_ms> sibling.

    Signature locked by debate ontology: (candidate_path: Path, ts_ms: int) -> Path.
    Audit trail — NEVER deletes.
    """
    promoted = candidate_path.with_name(
        candidate_path.name + f".promoted.{ts_ms}"
    )
    os.rename(candidate_path, promoted)
    return promoted


def _clear_marker(marker_path: Path) -> None:
    """Best-effort marker cleanup on success path."""
    try:
        marker_path.unlink()
    except FileNotFoundError:
        pass


def promote(
    cid: str,
    body_from: Path,
    as_name: str,
    candidates_dir: Path = CANDIDATES_DIR,
    dry_run: bool = False,
) -> dict:
    """Promote a candidate to a registered skill. See module docstring.

    Returns a dict with keys: {cid, target, marker, promoted, ack_key, dry_run}.
    """
    # Validate body first — fast fail without touching state.
    if not body_from.exists():
        raise MissingBodyError(
            f"--body-from {body_from} does not exist (exit 2)."
        )
    _validate_body(body_from)

    # M21 structure-DEPTH advisory (non-blocking): skill_quality_axes checks section
    # PRESENCE; this surfaces HOLLOW standard sections at promotion time so the operator
    # sees substance gaps before consuming the enable-skill token. Advisory only — does
    # NOT block the promotion (the graduate-validator path is where the bar turns blocking).
    try:
        from lib.skill_structure_depth import structure_depth_gaps
        _depth_gaps = structure_depth_gaps(body_from.read_text(encoding="utf-8"))
        if _depth_gaps:
            sys.stderr.write(
                "[WARN] promote_skill structure-depth: body has hollow standard section(s) — "
                + "; ".join(_depth_gaps[:4]) + ". Consider deepening before promotion.\n"
            )
    except Exception:  # noqa: BLE001 — advisory must never break the promotion path
        pass

    # Validate namespace; resolve target dir.
    target_dir, target_audit_name = _resolve_namespace(as_name)
    target_skill_md = target_dir / "SKILL.md"

    # Resolve candidate.
    candidate_path = _resolve_candidate_path(cid, candidates_dir)
    if not candidate_path.exists():
        raise FileNotFoundError(
            f"candidate manifest not found at {candidate_path}; "
            f"check --candidate id or --candidates-dir."
        )
    # Touch-parse the manifest to surface JSONDecodeError EARLY (before mutation).
    _load_candidate_manifest(candidate_path)

    if dry_run:
        return {
            "cid": cid,
            "target": str(target_skill_md),
            "marker": str(candidate_path.with_name(candidate_path.name + ".promoting")),
            "promoted": str(candidate_path) + ".promoted.<ts_ms>",
            "ack_key": f"<ts_ms>:{cid}",
            "dry_run": True,
            "target_audit_name": target_audit_name,
        }

    # Commit sequence per LOCK: mark -> write -> replace -> commit -> ack.
    marker = mark_candidate_promoting(candidate_path)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = target_dir / f".SKILL.md.tmp.{uuid.uuid4().hex[:8]}"
        body_text = body_from.read_text(encoding="utf-8")
        tmp_path.write_text(body_text, encoding="utf-8")
        os.replace(tmp_path, target_skill_md)

        ts_ms = int(time.time() * 1000)
        promoted = commit_candidate_promoted(candidate_path, ts_ms)
        ack_key = f"{ts_ms}:{cid}"
        resolve_advisory("skill_promotion_completed").ack(ack_key)
    finally:
        _clear_marker(marker)

    return {
        "cid": cid,
        "target": str(target_skill_md),
        "marker": str(marker),
        "promoted": str(promoted),
        "ack_key": ack_key,
        "dry_run": False,
        "target_audit_name": target_audit_name,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="promote_skill",
        description="enable-skill token consumer (Wave 20 gap closure).",
    )
    p.add_argument("--candidate", required=True,
                   help="candidate id (bare, e.g. skill-bash-repeat-370ecf79)")
    p.add_argument("--body-from", required=True, type=Path,
                   help="operator-supplied SKILL.md body file (required keys: "
                        "name, description, keywords)")
    p.add_argument("--as", dest="as_name", required=True,
                   help="target skill name; must startswith 'gsd-' OR be "
                        "'_gsd/<subname>' (single segment)")
    p.add_argument("--candidates-dir", type=Path, default=CANDIDATES_DIR,
                   help=f"candidate source directory (default: {CANDIDATES_DIR})")
    p.add_argument("--dry-run", action="store_true",
                   help="print intended actions without mutating state")
    return p


def main(argv: list[str] | None = None) -> int:
    # LOCK: token gate at main entry line 1.
    try:
        _assert_token()
    except TokenMissingError as e:
        print(f"[error] promote_skill: TokenMissingError: {e}", file=sys.stderr)
        return 1

    args = _build_parser().parse_args(argv)

    try:
        result = promote(
            cid=args.candidate,
            body_from=args.body_from,
            as_name=args.as_name,
            candidates_dir=args.candidates_dir,
            dry_run=args.dry_run,
        )
    except MissingBodyError as e:
        print(f"[error] promote_skill: MissingBodyError: {e}", file=sys.stderr)
        return 2
    except MalformedBodyError as e:
        print(f"[error] promote_skill: MalformedBodyError: {e}", file=sys.stderr)
        return 3
    except FileExistsError as e:
        # mark_candidate_promoting stale marker.
        print(f"[error] promote_skill: FileExistsError: {e}", file=sys.stderr)
        return 4
    except PermissionError as e:
        print(
            f"[error] promote_skill: PermissionError: {e}\n"
            f"advisory: close editor/indexer handles on target SKILL.md "
            f"and rerun.",
            file=sys.stderr,
        )
        return 5
    except json.JSONDecodeError as e:
        print(f"[error] promote_skill: JSONDecodeError: {e}", file=sys.stderr)
        return 6
    except (UnicodeDecodeError, UnicodeEncodeError) as e:
        print(f"[error] promote_skill: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 7
    except NamespaceViolationError as e:
        print(f"[error] promote_skill: NamespaceViolationError: {e}",
              file=sys.stderr)
        return 8
    except OSError as e:
        # FileNotFoundError on missing candidate falls through here (subclass).
        print(f"[error] promote_skill: OSError: {e}", file=sys.stderr)
        return 9

    tag = "[dry-run]" if result["dry_run"] else "[done]"
    print(
        f"{tag} promote_skill: cid={result['cid']} "
        f"target={result['target']} ack_key={result['ack_key']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
