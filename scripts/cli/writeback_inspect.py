#!/usr/bin/env python3
"""Inspect / dismiss writeback proposals from harness-researcher strikes.

Closes the operator-facing gap left by debate-1778230575-aebdd3 D2 (observe-only
writeback v0): the round-robin advisory in handlers/prompt/debate_trigger.py
surfaces pending proposals but had no CLI for review beyond raw JSONL inspection.

Usage:
    cd ~/.claude/scripts
    python -m cli.writeback_inspect                  # plaintext list of pending
    python -m cli.writeback_inspect --list           # explicit list
    python -m cli.writeback_inspect --show <id>      # full index entry
    python -m cli.writeback_inspect --dismiss <id>   # mark status='rejected'
    python -m cli.writeback_inspect --json           # machine-readable list

Exit codes:
    0  success / list rendered (even when empty)
    1  unknown id (--show / --dismiss)
    2  argument error
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.writeback_parser import (  # noqa: E402
    ParsedProposal, RejectReason, parse_proposal,
)
from lib.writeback_store import (  # noqa: E402
    list_applied, list_pending, mark_applied, mark_status, read_index,
    telemetry_snapshot,
)
from lib.writeback_apply import (  # noqa: E402
    ApplyError, InvalidOperatorContext, apply_edits_to_text,
    validate_operator_context,
)
from lib.writeback_token import (  # noqa: E402
    ConsumeResult, arm as token_arm, consume as token_consume,
)


def _file_sha1(path: Path) -> str | None:
    """sha1 of file bytes, or None if missing/unreadable."""
    import hashlib
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _preimages_dir() -> Path:
    """Lazy STATE_DIR resolution for sidecar storage (D4)."""
    from lib.paths import STATE_DIR
    d = STATE_DIR / "writeback" / "preimages"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _quarantine_dir() -> Path:
    """Lazy STATE_DIR resolution for quarantine artifacts (D5 fallback)."""
    from lib.paths import STATE_DIR
    d = STATE_DIR / "writeback" / "quarantine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _operator_context() -> dict:
    """Build operator_context per D6 contract.

    pid: real os.getpid() (always > 0).
    sid: from ORCH_SID env (autopilot/orchestrator-issued) else 'cli-direct'.
    cwd: os.getcwd().
    user: os.getlogin() with Windows OSError fallback to USERNAME/USER/'<unknown>'.
    """
    import os as _os
    user = "<unknown>"
    try:
        user = _os.getlogin()
    except OSError:
        user = _os.environ.get("USERNAME") or _os.environ.get("USER") or "<unknown>"
    sid = _os.environ.get("ORCH_SID") or "cli-direct"
    return {
        "pid": _os.getpid(),
        "sid": sid,
        "cwd": _os.getcwd(),
        "user": user,
    }


def _resolve_target_abs(target_path: str) -> Path:
    """Resolve a parser-emitted target path to an absolute Path.

    The parser strips 'b/' prefix, leaving a relative path under the
    project tree. For apply, we resolve relative to ~/.claude (the harness
    root) per the skill-tree convention. Operators applying to non-skill
    paths must use the absolute form already.
    """
    p = Path(target_path)
    if p.is_absolute():
        return p
    return (Path.home() / ".claude" / target_path).resolve()


def _atomic_write_bytes(path: Path, data: bytes) -> bool:
    """Atomic write via tempfile + os.replace. Returns True on success."""
    import os as _os
    import tempfile as _tf
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = _tf.mkstemp(dir=str(parent), prefix=path.name + ".",
                                suffix=".tmp")
    try:
        with _os.fdopen(fd, "wb") as f:
            f.write(data)
            try:
                _os.fsync(f.fileno())
            except OSError:
                pass
        _os.replace(tmp_name, str(path))
        tmp_name = ""
        return True
    except OSError:
        return False
    finally:
        if tmp_name and _os.path.exists(tmp_name):
            try:
                _os.unlink(tmp_name)
            except OSError:
                pass


def _strike_artifact_path(fingerprint: str) -> Path:
    """Path to the harness-researcher strike artifact for `fingerprint`.

    Per writeback_parser docstring: state/research/strikes/<fingerprint>.md.
    Lazy STATE_DIR resolution per lib/team_mailbox + lib/autopilot_state +
    lib/writeback_store pattern (test fixtures redirect lib.paths.STATE_DIR
    after import; capturing at module-load misses the override).
    """
    from lib.paths import STATE_DIR
    return STATE_DIR / "research" / "strikes" / f"{fingerprint}.md"


def render_preview(pid: str, entry: dict, parsed) -> str:
    """Plaintext rendering of a parse_proposal result for operator review."""
    fp = entry.get("fingerprint", "?")
    target = entry.get("target_skill_path", "?")
    artifact = _strike_artifact_path(fp)

    if isinstance(parsed, RejectReason):
        return (
            f"Preview for {pid}: REJECTED\n"
            f"  fingerprint  : {fp}\n"
            f"  artifact     : {artifact}\n"
            f"  reject reason: {parsed.value}\n"
            f"  → harness-researcher must regenerate the strike with a "
            f"unified-diff under '## Proposed permanent change'."
        )

    if isinstance(parsed, ParsedProposal):
        edits = parsed.edits
        added = sum(
            sum(1 for ln in e.body_lines if ln.startswith("+") and not ln.startswith("+++"))
            for e in edits
        )
        removed = sum(
            sum(1 for ln in e.body_lines if ln.startswith("-") and not ln.startswith("---"))
            for e in edits
        )
        targets = sorted({e.target_path for e in edits})
        lines = [
            f"Preview for {pid}: PARSED OK",
            f"  fingerprint : {fp}",
            f"  artifact    : {artifact}",
            f"  index target: {target}",
            f"  hunk count  : {len(edits)}",
            f"  +/- lines   : +{added} / -{removed}",
            f"  diff targets: {', '.join(targets) if targets else '(none)'}",
        ]
        if target not in targets and targets:
            lines.append(
                "  ! WARN: index target_skill_path differs from diff target — "
                "registration drift"
            )
        lines.append(
            "  → All targets passed denylist + skills/-only regex (parser "
            "would reject otherwise). --apply not yet implemented; this is "
            "observe-only preview."
        )
        return "\n".join(lines)

    return f"Preview for {pid}: unexpected parser return type: {type(parsed).__name__}"


def _format_age(now: float, created_ts: float) -> str:
    delta = max(0.0, now - created_ts)
    if delta < 60:
        return f"{int(delta)}s"
    if delta < 3600:
        return f"{int(delta / 60)}m"
    if delta < 86400:
        return f"{int(delta / 3600)}h"
    return f"{int(delta / 86400)}d"


def render_list(pending: list[dict], now: float | None = None) -> str:
    """Return plaintext rendering of pending proposals."""
    if not pending:
        return "No pending writeback proposals."
    cur = time.time() if now is None else now
    lines = [f"Pending writeback proposals ({len(pending)}):"]
    for entry in pending:
        pid = entry.get("id", "?")
        fp = entry.get("fingerprint", "?")[:8]
        target = entry.get("target_skill_path", "?")
        created = float(entry.get("created_ts", 0))
        age = _format_age(cur, created) if created else "?"
        lines.append(f"  [{pid}] fp={fp} target={target} age={age}")
    lines.append("")
    lines.append(
        "Inspect: python -m cli.writeback_inspect --show <id>  |  "
        "Dismiss: python -m cli.writeback_inspect --dismiss <id>"
    )
    return "\n".join(lines)


def cmd_list(args: argparse.Namespace) -> int:
    pending = list_pending()
    if args.json:
        print(json.dumps(pending, ensure_ascii=False, sort_keys=True))
    else:
        print(render_list(pending))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    idx = read_index()
    entry = idx.get(args.id)
    if not isinstance(entry, dict):
        print(f"unknown id: {args.id}", file=sys.stderr)
        return 1
    payload = {"id": args.id, **entry}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        for k in sorted(payload.keys()):
            print(f"{k}: {payload[k]}")
    return 0


def cmd_dismiss(args: argparse.Namespace) -> int:
    idx = read_index()
    if args.id not in idx:
        print(f"unknown id: {args.id}", file=sys.stderr)
        return 1
    if not mark_status(args.id, "rejected"):
        print(f"failed to mark {args.id} as rejected", file=sys.stderr)
        return 1
    print(f"dismissed: {args.id}")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    idx = read_index()
    entry = idx.get(args.id)
    if not isinstance(entry, dict):
        print(f"unknown id: {args.id}", file=sys.stderr)
        return 1
    fp = entry.get("fingerprint")
    if not fp:
        print(f"index entry for {args.id} missing fingerprint", file=sys.stderr)
        return 1
    artifact = _strike_artifact_path(fp)
    if not artifact.is_file():
        print(
            f"strike artifact missing: {artifact}\n"
            f"  expected at state/research/strikes/<fingerprint>.md",
            file=sys.stderr,
        )
        return 1
    parsed = parse_proposal(artifact)
    if args.json:
        if isinstance(parsed, RejectReason):
            payload = {"id": args.id, "status": "rejected",
                       "reason": parsed.value, "fingerprint": fp,
                       "artifact": str(artifact)}
        else:
            payload = {
                "id": args.id, "status": "parsed", "fingerprint": fp,
                "artifact": str(artifact),
                "edits": [
                    {"target_path": e.target_path,
                     "hunk_header": e.hunk_header,
                     "body_line_count": len(e.body_lines)}
                    for e in parsed.edits
                ],
            }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(render_preview(args.id, entry, parsed))
    return 0


def cmd_arm(args: argparse.Namespace) -> int:
    """Mint a token bound to (proposal_id, current target sha1).

    Operator runs this first; the token text is printed on stdout for the
    operator to feed into a subsequent --apply --token=<token> invocation.
    """
    idx = read_index()
    entry = idx.get(args.id)
    if not isinstance(entry, dict):
        print(f"unknown id: {args.id}", file=sys.stderr)
        return 1
    fp = entry.get("fingerprint")
    if not fp:
        print(f"index entry for {args.id} missing fingerprint", file=sys.stderr)
        return 1
    artifact = _strike_artifact_path(fp)
    if not artifact.is_file():
        print(f"strike artifact missing: {artifact}", file=sys.stderr)
        return 1
    parsed = parse_proposal(artifact)
    if isinstance(parsed, RejectReason):
        print(f"strike artifact rejected by parser: {parsed.value}",
              file=sys.stderr)
        return 1

    # Compute pre_image_sha1 for FIRST target (token binds to one shape)
    targets = sorted({_resolve_target_abs(e.target_path) for e in parsed.edits})
    if not targets:
        print(f"parsed proposal has no edits", file=sys.stderr)
        return 1
    # Multi-target: pre_image is sha1 of joined sha1s, deterministic
    import hashlib
    h = hashlib.sha1()
    for t in targets:
        sha = _file_sha1(t)
        if sha is None:
            print(f"target missing or unreadable: {t}", file=sys.stderr)
            return 7  # TARGET_MISSING
        h.update(sha.encode("utf-8"))
        h.update(b"\x00")
    pre_image_sha1 = h.hexdigest()

    arm_result = token_arm(args.id, pre_image_sha1)
    if args.json:
        print(json.dumps({
            "id": args.id,
            "token": arm_result.token,
            "pre_image_sha1": pre_image_sha1,
            "targets": [str(t) for t in targets],
            "ttl_seconds_default": 300,
        }, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Armed proposal {args.id}")
        print(f"  token         : {arm_result.token}")
        print(f"  pre_image_sha1: {pre_image_sha1}")
        print(f"  targets       : {len(targets)}")
        for t in targets:
            print(f"    - {t}")
        print(f"  TTL           : 300s default (env WRITEBACK_APPLY_TOKEN_TTL [60,1800])")
        print(f"  apply         : python -m cli.writeback_inspect --apply "
              f"{args.id} --token={arm_result.token}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply a previously-armed proposal.

    Phases per D5 atomicity_model:
      1. validate operator_context (D6 contract)
      2. parse strike artifact (parser already validates denylist + skill regex)
      3. recompute pre_image_sha1; consume token (validates equality + TTL + drift)
      4. read all targets, replay hunks per target → in-memory post_images
      5. write all preimage sidecars (atomic)
      6. sequentially os.replace each target
      7. on partial replace failure: synchronously restore from sidecars;
         if restore fails → quarantine + exit 6
      8. mark_applied(audit record)
    """
    if not args.token:
        print("--apply requires --token=<token> (run --arm <id> first)",
              file=sys.stderr)
        return 2

    idx = read_index()
    entry = idx.get(args.id)
    if not isinstance(entry, dict):
        print(f"unknown id: {args.id}", file=sys.stderr)
        return 1
    fp = entry.get("fingerprint")
    artifact = _strike_artifact_path(fp)
    if not artifact.is_file():
        print(f"strike artifact missing: {artifact}", file=sys.stderr)
        return 1
    parsed = parse_proposal(artifact)
    if isinstance(parsed, RejectReason):
        print(f"strike artifact rejected: {parsed.value}", file=sys.stderr)
        return 1

    # D6 contract validation
    op_ctx = _operator_context()
    try:
        validate_operator_context(op_ctx)
    except InvalidOperatorContext as e:
        print(f"invocation_contract violation: {e}", file=sys.stderr)
        return 9  # contract violated

    # Group edits by target file
    edits_by_target: dict[Path, list[tuple[str, tuple[str, ...]]]] = {}
    for e in parsed.edits:
        t = _resolve_target_abs(e.target_path)
        edits_by_target.setdefault(t, []).append((e.hunk_header, e.body_lines))

    # Verify every target exists pre-apply
    for t in edits_by_target:
        if not t.is_file():
            print(f"target missing: {t}", file=sys.stderr)
            return 7  # TARGET_MISSING

    # Compute current pre_image_sha1
    import hashlib
    h = hashlib.sha1()
    target_sorted = sorted(edits_by_target.keys())
    pre_image_per_target: dict[Path, str] = {}
    # Read each target's bytes EXACTLY ONCE here and reuse them for the apply
    # below, so the sha the token validates and the bytes actually mutated come
    # from the SAME read — closes the TOCTOU between the sha check and the apply
    # (deep-audit pass-2 rank 5). sha1(raw bytes) == _file_sha1 (both hash the raw
    # bytes), so an already-armed token still validates.
    pre_image_bytes_captured: dict[Path, bytes] = {}
    for t in target_sorted:
        try:
            pre_bytes = t.read_bytes()
        except OSError:
            print(f"target unreadable: {t}", file=sys.stderr)
            return 7
        pre_image_bytes_captured[t] = pre_bytes
        sha = hashlib.sha1(pre_bytes).hexdigest()
        pre_image_per_target[t] = sha
        h.update(sha.encode("utf-8"))
        h.update(b"\x00")
    pre_image_sha1 = h.hexdigest()

    # Token consume (D1 gate)
    rc = token_consume(args.id, args.token, pre_image_sha1)
    if rc == ConsumeResult.OK:
        pass
    elif rc == ConsumeResult.TOKEN_INVALID:
        print(f"TOKEN_INVALID: missing or wrong token for {args.id}",
              file=sys.stderr)
        return 2
    elif rc == ConsumeResult.TOKEN_EXPIRED:
        print(f"TOKEN_EXPIRED: re-arm with --arm {args.id}", file=sys.stderr)
        return 2
    elif rc == ConsumeResult.PRE_IMAGE_DRIFT:
        print(f"RACE_DETECTED: target sha1 changed since --arm; re-arm and "
              f"re-review", file=sys.stderr)
        return 4

    # D5: stage all post_images in memory first
    pre_image_bytes_per_target: dict[Path, bytes] = {}
    post_image_text_per_target: dict[Path, str] = {}
    for t in target_sorted:
        try:
            # Reuse the SINGLE authoritative read from above — do NOT re-read
            # (a second t.read_bytes() here is the TOCTOU window; rank 5).
            pre_bytes = pre_image_bytes_captured[t]
            pre_image_bytes_per_target[t] = pre_bytes
            try:
                pre_text = pre_bytes.decode("utf-8")
            except UnicodeDecodeError:
                print(f"target not utf-8: {t}", file=sys.stderr)
                return 5
            try:
                post_text = apply_edits_to_text(
                    pre_text, edits_by_target[t]
                )
            except ApplyError as e:
                print(f"HUNK_MISMATCH for {t}: {e.detail}", file=sys.stderr)
                return 5
            post_image_text_per_target[t] = post_text
        except OSError as e:
            print(f"OSError reading {t}: {e}", file=sys.stderr)
            return 5

    # Mint apply_id from (proposal_id, pre_image_sha1, time)
    applied_ts = time.time()
    apply_id = hashlib.sha1(
        f"{args.id}|{pre_image_sha1}|{applied_ts}".encode("utf-8")
    ).hexdigest()[:16]

    # Write preimage sidecar (joined preimages indexed by relative path)
    sidecar_path = _preimages_dir() / f"{apply_id}.bin"
    # Sidecar format: simple frame "TARGET\t<abspath>\nLEN\t<bytes>\n<bytes>\n"
    sidecar_data = b""
    for t in target_sorted:
        b = pre_image_bytes_per_target[t]
        sidecar_data += f"TARGET\t{t}\nLEN\t{len(b)}\n".encode("utf-8")
        sidecar_data += b
        sidecar_data += b"\n"
    if not _atomic_write_bytes(sidecar_path, sidecar_data):
        print(f"sidecar write failed: {sidecar_path}", file=sys.stderr)
        return 5

    # Sequential os.replace; track which succeeded for partial-recover
    replaced: list[Path] = []
    for t in target_sorted:
        post_bytes = post_image_text_per_target[t].encode("utf-8")
        if not _atomic_write_bytes(t, post_bytes):
            # Partial recover from sidecar
            recover_failed = []
            for done in replaced:
                if not _atomic_write_bytes(done, pre_image_bytes_per_target[done]):
                    recover_failed.append(str(done))
            if recover_failed:
                # Quarantine
                qpath = _quarantine_dir() / f"{apply_id}.json"
                _atomic_write_bytes(qpath, json.dumps({
                    "apply_id": apply_id,
                    "proposal_id": args.id,
                    "phase": "partial_recover_failed",
                    "replaced": [str(p) for p in replaced],
                    "recover_failed": recover_failed,
                    "applied_ts": applied_ts,
                }, ensure_ascii=False, sort_keys=True).encode("utf-8"))
                print(f"QUARANTINED: partial recovery failed; see {qpath}",
                      file=sys.stderr)
                return 6
            print(f"replace failed for {t}; recovered {len(replaced)} targets",
                  file=sys.stderr)
            return 5
        replaced.append(t)

    # Compute post_image_sha1 (joined sha1s of new content)
    h2 = hashlib.sha1()
    for t in target_sorted:
        h2.update(hashlib.sha1(post_image_text_per_target[t].encode("utf-8")).hexdigest().encode("utf-8"))
        h2.update(b"\x00")
    post_image_sha1 = h2.hexdigest()

    # Audit (D3)
    audit_record = {
        "apply_id": apply_id,
        "fingerprint": fp,
        "target_path": "; ".join(str(t) for t in target_sorted),
        "pre_image_sha1": pre_image_sha1,
        "post_image_sha1": post_image_sha1,
        "applied_ts": applied_ts,
        "operator_context": op_ctx,
        "hunk_count": sum(len(v) for v in edits_by_target.values()),
        "hunk_headers": [h for v in edits_by_target.values() for h, _ in v],
        "schema_version": 1,
    }
    if not mark_applied(args.id, audit_record):
        print(f"audit record failed (apply succeeded — manual reconciliation "
              f"needed); apply_id={apply_id}", file=sys.stderr)
        return 5

    if args.json:
        print(json.dumps({
            "status": "applied",
            "apply_id": apply_id,
            "post_image_sha1": post_image_sha1,
            "targets_modified": len(target_sorted),
        }, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Applied proposal {args.id} → apply_id={apply_id}")
        print(f"  targets       : {len(target_sorted)}")
        for t in target_sorted:
            print(f"    - {t}")
        print(f"  post_image    : {post_image_sha1}")
        print(f"  rollback      : python -m cli.writeback_inspect "
              f"--arm-rollback {apply_id}")
    return 0


def cmd_arm_rollback(args: argparse.Namespace) -> int:
    """Mint a rollback token bound to (apply_id, current target sha1)."""
    records = list_applied()
    rec = next((r for r in records if r.get("apply_id") == args.id), None)
    if rec is None:
        print(f"unknown apply_id: {args.id}", file=sys.stderr)
        return 1

    # Recompute current state of all targets
    target_paths_str = rec.get("target_path", "")
    targets = [Path(s) for s in target_paths_str.split("; ") if s]
    if not targets:
        print("audit record has no targets", file=sys.stderr)
        return 1

    import hashlib
    h = hashlib.sha1()
    for t in sorted(targets):
        sha = _file_sha1(t)
        if sha is None:
            print(f"target unreadable: {t}", file=sys.stderr)
            return 7
        h.update(sha.encode("utf-8"))
        h.update(b"\x00")
    current_sha = h.hexdigest()

    arm_result = token_arm(args.id, current_sha)
    if args.json:
        print(json.dumps({
            "apply_id": args.id,
            "token": arm_result.token,
            "current_sha1": current_sha,
            "expected_post_image_sha1": rec.get("post_image_sha1"),
        }, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Armed rollback for {args.id}")
        print(f"  token            : {arm_result.token}")
        print(f"  current_sha1     : {current_sha}")
        print(f"  audit post_image : {rec.get('post_image_sha1')}")
        if current_sha != rec.get("post_image_sha1"):
            print(f"  ! WARN drift detected — rollback will REFUSE")
        print(f"  rollback         : python -m cli.writeback_inspect "
              f"--rollback {args.id} --token={arm_result.token}")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    """Restore preimage sidecar (drift-checked, token-gated)."""
    if not args.token:
        print("--rollback requires --token=<token> (run --arm-rollback first)",
              file=sys.stderr)
        return 2

    records = list_applied()
    rec = next((r for r in records if r.get("apply_id") == args.id), None)
    if rec is None:
        print(f"unknown apply_id: {args.id}", file=sys.stderr)
        return 1

    targets = [Path(s) for s in rec.get("target_path", "").split("; ") if s]

    # Drift check: current sha == recorded post_image_sha1
    import hashlib
    h = hashlib.sha1()
    for t in sorted(targets):
        sha = _file_sha1(t)
        if sha is None:
            print(f"target unreadable: {t}", file=sys.stderr)
            return 7
        h.update(sha.encode("utf-8"))
        h.update(b"\x00")
    current_sha = h.hexdigest()
    if current_sha != rec.get("post_image_sha1"):
        print(f"DRIFT_DETECTED: current sha1 ({current_sha}) != audit "
              f"post_image_sha1 ({rec.get('post_image_sha1')}); REFUSE",
              file=sys.stderr)
        return 8

    # Token consume
    rc = token_consume(args.id, args.token, current_sha)
    if rc != ConsumeResult.OK:
        print(f"token consume failed: {rc.value}", file=sys.stderr)
        return 2

    # Read sidecar
    sidecar_path = _preimages_dir() / f"{args.id}.bin"
    if not sidecar_path.is_file():
        print(f"sidecar missing: {sidecar_path}", file=sys.stderr)
        return 1

    # Parse sidecar frames (TARGET\t<path>\nLEN\t<n>\n<bytes>\n)*
    raw = sidecar_path.read_bytes()
    pos = 0
    pre_images: dict[Path, bytes] = {}
    while pos < len(raw):
        # Read TARGET line
        target_end = raw.index(b"\n", pos)
        target_line = raw[pos:target_end].decode("utf-8")
        if not target_line.startswith("TARGET\t"):
            print(f"sidecar malformed at byte {pos}", file=sys.stderr)
            return 1
        target = Path(target_line[len("TARGET\t"):])
        pos = target_end + 1
        # LEN line
        len_end = raw.index(b"\n", pos)
        len_line = raw[pos:len_end].decode("utf-8")
        if not len_line.startswith("LEN\t"):
            print(f"sidecar malformed LEN at {pos}", file=sys.stderr)
            return 1
        n = int(len_line[len("LEN\t"):])
        pos = len_end + 1
        body = raw[pos:pos + n]
        pos += n + 1  # skip trailing newline
        pre_images[target] = body

    # Atomic restore
    for t in sorted(pre_images.keys()):
        if not _atomic_write_bytes(t, pre_images[t]):
            print(f"restore failed for {t}", file=sys.stderr)
            return 5

    # Append rollback audit record
    op_ctx = _operator_context()
    rollback_id = hashlib.sha1(
        f"rollback|{args.id}|{time.time()}".encode("utf-8")
    ).hexdigest()[:16]
    rollback_record = {
        "apply_id": rollback_id,
        "op": "rollback",
        "rolled_back_apply_id": args.id,
        "fingerprint": rec.get("fingerprint", ""),
        "target_path": rec.get("target_path", ""),
        "pre_image_sha1": rec.get("post_image_sha1"),
        "post_image_sha1": rec.get("pre_image_sha1"),
        "applied_ts": time.time(),
        "operator_context": op_ctx,
        "hunk_count": 0,
        "schema_version": 1,
    }
    # mark_applied with synthetic proposal id "rollback:<original_apply_id>"
    mark_applied(f"rollback:{args.id}", rollback_record)

    if args.json:
        print(json.dumps({
            "status": "rolled_back",
            "rollback_id": rollback_id,
            "rolled_back_apply_id": args.id,
        }, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Rolled back apply_id={args.id}")
        print(f"  rollback_id  : {rollback_id}")
        print(f"  targets      : {len(pre_images)}")
    return 0


def cmd_telemetry(args: argparse.Namespace) -> int:
    snap = telemetry_snapshot()
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, sort_keys=True))
    else:
        if not snap:
            print("(no telemetry counters yet)")
        else:
            for k in sorted(snap.keys()):
                print(f"{k}: {snap[k]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.writeback_inspect",
        description="Inspect / dismiss harness writeback proposals.",
    )
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List pending proposals (default)")

    sp_show = sub.add_parser("show", help="Show one proposal by id")
    sp_show.add_argument("id")

    sp_dismiss = sub.add_parser("dismiss", help="Mark proposal status='rejected'")
    sp_dismiss.add_argument("id")

    sub.add_parser("telemetry", help="Show writeback_store telemetry counters")

    sp_preview = sub.add_parser(
        "preview", help="Parse + render strike artifact (observe-only, no write)"
    )
    sp_preview.add_argument("id")

    sp_arm = sub.add_parser("arm", help="Mint apply token (operator gate)")
    sp_arm.add_argument("id")

    sp_apply = sub.add_parser("apply",
                              help="Apply armed proposal (token-gated, atomic)")
    sp_apply.add_argument("id")
    sp_apply.add_argument("--token", required=True)

    sp_arm_rb = sub.add_parser("arm-rollback",
                               help="Mint rollback token for an apply_id")
    sp_arm_rb.add_argument("id")

    sp_rb = sub.add_parser("rollback",
                           help="Rollback a previously-applied apply_id")
    sp_rb.add_argument("id")
    sp_rb.add_argument("--token", required=True)

    # Backward-compat flags (no subcommand)
    parser.add_argument("--list", dest="flag_list", action="store_true")
    parser.add_argument("--show", dest="flag_show", metavar="ID")
    parser.add_argument("--dismiss", dest="flag_dismiss", metavar="ID")
    parser.add_argument("--telemetry", dest="flag_telemetry", action="store_true")
    parser.add_argument("--preview", dest="flag_preview", metavar="ID")
    parser.add_argument("--arm", dest="flag_arm", metavar="ID")
    parser.add_argument("--apply", dest="flag_apply", metavar="ID")
    parser.add_argument("--arm-rollback", dest="flag_arm_rollback", metavar="ID")
    parser.add_argument("--rollback", dest="flag_rollback", metavar="ID")
    parser.add_argument("--token", dest="token", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Resolve subcommand vs flag form. Flag form takes precedence when present.
    if args.flag_show:
        args.id = args.flag_show
        return cmd_show(args)
    if args.flag_dismiss:
        args.id = args.flag_dismiss
        return cmd_dismiss(args)
    if args.flag_telemetry:
        return cmd_telemetry(args)
    if args.flag_preview:
        args.id = args.flag_preview
        return cmd_preview(args)
    if args.flag_arm:
        args.id = args.flag_arm
        return cmd_arm(args)
    if args.flag_apply:
        args.id = args.flag_apply
        return cmd_apply(args)
    if args.flag_arm_rollback:
        args.id = args.flag_arm_rollback
        return cmd_arm_rollback(args)
    if args.flag_rollback:
        args.id = args.flag_rollback
        return cmd_rollback(args)
    if args.cmd == "show":
        return cmd_show(args)
    if args.cmd == "dismiss":
        return cmd_dismiss(args)
    if args.cmd == "telemetry":
        return cmd_telemetry(args)
    if args.cmd == "preview":
        return cmd_preview(args)
    if args.cmd == "arm":
        return cmd_arm(args)
    if args.cmd == "apply":
        return cmd_apply(args)
    if args.cmd == "arm-rollback":
        return cmd_arm_rollback(args)
    if args.cmd == "rollback":
        return cmd_rollback(args)
    return cmd_list(args)


if __name__ == "__main__":
    sys.exit(main())
