"""Generic acknowledgement store for harness advisory signals.

Wave 19 (debate-1777989789-7c3571 converged gen 3): consolidates the
near-identical ack stores previously in cli/debate_doubts.py and
lib/strict_design_ack.py into a single abstraction with REGISTRY
dispatch.

Design contract (locked by Architect verdict, snapshot hash
89f6af6eee69a1f60a57fa4dbbdbe469a1742ee3):

  - Constructor takes ONLY (name, ack_path) plus required `doc` kwarg.
    legacy_paths/key_field/key_field_type/tz_awareness are intentionally
    absent — they are documentation-only metadata for current callers,
    no behavioral branch consumes them. Reintroduce as constructor args
    only if a future advisory's legacy_path diverges from new_path
    (currently both registered advisories use the same physical file,
    so the read-union has trivial input N=1).

  - load() returns set[str] from a single physical file (or empty set on
    missing/unreadable). No copy-forward, no sunset, no migration window.

  - ack()/ack_many() append to ack_path only — never mutate any other
    file. New entries persist as bounded plaintext lines.

  - REGISTRY entries are constructed via _register() which fails fast at
    import time if `doc` is empty — this enforces the adapter shape
    contract without relying on the type system (mypy/pyright treat
    dynamic attrs as Any).

  - resolve(name) is the behavioral dispatch entry point — raises
    KeyError with the known-set in the message on miss, so the failure
    mode is explicit rather than silent dict.get(default).

Backwards compatibility: lib/strict_design_ack.py and cli/debate_doubts.py
expose the SAME public symbols they did before — they now delegate to
the matching REGISTRY entry via the shim/redirect pattern. Caller code
needs no changes; the shim emits DeprecationWarning(stacklevel=2) on
first import to surface the new canonical path.
"""
from __future__ import annotations

from pathlib import Path

from .paths import STATE_DIR


class AdvisoryAck:
    """File-backed set-of-strings ack store, one instance per advisory.

    ADAPTER_SHAPE_DOC is the class-level CONTRACT TEMPLATE: every
    concrete REGISTRY entry's `doc` must describe at minimum the
    advisory's key_field, key_field_type, and tz_awareness so future
    contributors know what they are putting on the line. The doc lives
    on the instance via the constructor's required kwarg, not as a
    dynamically attached attribute, so it is visible to type tools.
    """

    ADAPTER_SHAPE_DOC: str = (
        "Each REGISTRY entry's `doc` kwarg must declare:\n"
        "  - key_field: identifier name (e.g., 'session_id', 'ts')\n"
        "  - key_field_type: 'str' | 'iso8601' | 'hash' | other\n"
        "  - tz_awareness: 'naive' | 'aware' | 'n/a'\n"
        "legacy_paths is intentionally not modeled because both current\n"
        "advisories resolve to the same physical file as new_path; if\n"
        "divergence reappears, reintroduce as a behavioral constructor\n"
        "field with a paired read-union test (see Wave 19 verdict)."
    )

    def __init__(self, name: str, ack_path: Path, *, doc: str) -> None:
        if not (doc and doc.strip()):
            raise ValueError(
                f"AdvisoryAck {name!r}: `doc` kwarg must be non-empty "
                f"(see AdvisoryAck.ADAPTER_SHAPE_DOC for required fields)"
            )
        self.name = name
        self.ack_path = ack_path
        self.doc = doc

    def load(self) -> set[str]:
        if not self.ack_path.exists():
            return set()
        try:
            return {
                line.strip()
                for line in self.ack_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        except OSError:
            return set()

    def ack(self, key: str) -> bool:
        """Append key if not already present. Returns True on add."""
        if not key:
            return False
        existing = self.load()
        if key in existing:
            return False
        self.ack_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ack_path.open("a", encoding="utf-8") as f:
            f.write(key + "\n")
        return True

    def ack_many(self, keys) -> int:
        """Bulk-append novel keys. Returns count newly added."""
        existing = self.load()
        new = [k for k in keys if k and k not in existing]
        if not new:
            return 0
        self.ack_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ack_path.open("a", encoding="utf-8") as f:
            for k in new:
                f.write(k + "\n")
        return len(new)


def _register(name: str, ack_path: Path, *, doc: str) -> AdvisoryAck:
    """Factory used at module import — fails fast on missing doc."""
    return AdvisoryAck(name, ack_path, doc=doc)


REGISTRY: dict[str, AdvisoryAck] = {
    "debate_doubts": _register(
        "debate_doubts",
        STATE_DIR / "debate_doubts_acknowledged.txt",
        doc=(
            "key_field=session_id, key_field_type=str, tz_awareness=n/a. "
            "Source: state/debates/<sid>/events.jsonl Architect "
            "self_doubt_note payloads. Producer: harness-debate engine. "
            "Consumer: cli.debate_doubts CLI + SessionStart "
            "<harness-status> [debate-doubts] line."
        ),
    ),
    "strict_design": _register(
        "strict_design",
        STATE_DIR / "strict_design_acknowledged.txt",
        doc=(
            "key_field=ts, key_field_type=iso8601, tz_awareness=naive. "
            "Source: telemetry/debate-triggers.jsonl strict_design=True "
            "records. Producer: handlers/prompt/debate_trigger.py. "
            "Consumer: engine.trigger_summary CLI + SessionStart "
            "<harness-status> [strict-design] line."
        ),
    ),
    "aborted_kha_plan_validator_fail": _register(
        "aborted_kha_plan_validator_fail",
        STATE_DIR / "aborted_kha_plan_validator_fail.txt",
        doc=(
            "key_field=<orch_sid>:<phase>:<plan>[:<sub>], "
            "key_field_type=str, tz_awareness=n/a. "
            "Source: kha↔harness bridge dispatch path "
            "(lib/autopilot_kha_bridge.py). Producer: autopilot Phase 1 "
            "bridge router when ralph would auto-edit a .planning/ file "
            "under bridge_dispatch_active=true, AND orphan-detection "
            "path when kha-executor commits exist with no SUMMARY.md. "
            "Consumer: SessionStart <harness-status> [aborted-kha-plan] line "
            "(BUILT — handlers/session/init.py::_aborted_kha_plan_line, STEP 6 "
            "operator decision 2026-06-04) + autopilot Phase 3 escape advisory render. "
            "Wave 15 (debate-1779314852-338b28 4-LOCK sha1 "
            "dc809a9257f23c472212ce55d426fdccb039624b D6)."
        ),
    ),
    "l2_promotion_completed": _register(
        "l2_promotion_completed",
        STATE_DIR / "l2_promotion_completed.txt",
        doc=(
            "key_field=ts_ms:run_uuid_hex8, "
            "key_field_type=str, tz_awareness=n/a. "
            "Source: cron/run_l2_promotion.py run-completion timestamps. "
            "Producer: L2 promoter on successful promote_all() return. "
            "Consumer: operator forensic grep ONLY — completed-event audit "
            "log, NOT surfaced at SessionStart (STEP 6 operator decision "
            "2026-06-04: completed-promotion counts are low-signal vs the "
            "token-diet; the prior '[l2-promotion] line (future)' is retracted). "
            "Wave 16 S2 L2 (debate-1779328283-9076f2 14-LOCK sha1 "
            "59cc1bab06a1af2019763d414cf345a2db7626df D11). "
            "Per-run uuid_hex8 generated per-INVOCATION via "
            "uuid.uuid4().hex[:8] (SC1: reset on entry, NOT module-level)."
        ),
    ),
    "skill_promotion_completed": _register(
        "skill_promotion_completed",
        STATE_DIR / "skill_promotion_completed.txt",
        doc=(
            "key_field=ts_ms:candidate_id, "
            "key_field_type=str, tz_awareness=n/a. "
            "Source: cli/promote_skill.py promote() commit step. "
            "Producer: operator-invoked promote_skill CLI on successful "
            "os.replace(tmp, SKILL.md) AND commit_candidate_promoted. "
            "Consumer: operator forensic grep ONLY over promoted candidates — "
            "completed-event audit log, NOT surfaced at SessionStart (STEP 6 "
            "operator decision 2026-06-04; prior '[skill-promotion] line "
            "(future)' retracted). Wave 20 (debate-1779507623-8a6f45 73-LOCK "
            "sha1 c150cf125daafcbc261ea094a3ec6b4b0f7894af D6). "
            "candidate_id is the bare cid (e.g. skill-bash-repeat-370ecf79)."
        ),
    ),
    "validator_graduated": _register(
        "validator_graduated",
        STATE_DIR / "validator_graduated.txt",
        doc=(
            "key_field=ts_ms:validator:action, "
            "key_field_type=str, tz_awareness=n/a. "
            "Source: state/graduation-history.jsonl graduate/demote/"
            "circuit_breaker_demote records. Producer: cli/graduate_validator.py "
            "(operator-invoked, graduate-validator/apply-user-preference gated) "
            "AND lib/graduation.tick_validator circuit-breaker auto-demote. "
            "Consumer: operator forensic grep over the graduation audit trail; "
            "the READY signal (not the completed event) is what SessionStart "
            "surfaces via handlers/session/init._graduation_ready_line. "
            "Track 1 (debate-1780722434-e5h19n gen-2, snapshot sha1 "
            "98f0fa4eca228fc36828c610544f765e287aa4cf, D5 graduation_audit)."
        ),
    ),
    "pollution_cleanup_completed": _register(
        "pollution_cleanup_completed",
        STATE_DIR / "pollution_cleanup_completed.txt",
        doc=(
            "key_field=ts_ms:run_uuid_hex8, key_field_type=str, tz_awareness=n/a. "
            "Source: cron/run_pollution_cleanup.py run-completion timestamps. "
            "Producer: insight-index pollution cleanup on successful retract pass "
            "(lib.insight_index.retract of confirmed burst pollution). Consumer: "
            "operator forensic grep ONLY — completed-event audit log, NOT surfaced "
            "at SessionStart. M29 (cron build+stage). Per-run uuid_hex8 generated "
            "per-INVOCATION via uuid.uuid4().hex[:8] (SC1: local var in main())."
        ),
    ),
    "ledger_compaction_completed": _register(
        "ledger_compaction_completed",
        STATE_DIR / "ledger_compaction_completed.txt",
        doc=(
            "key_field=ts_ms:run_uuid_hex8, key_field_type=str, tz_awareness=n/a. "
            "Source: cron/run_ledger_compaction.py run-completion timestamps. "
            "Producer: operator-ledger compaction on successful rewrite (latest-per-"
            "task_hash kept, superseded archived to .compacted.<ts>). Consumer: "
            "operator forensic grep ONLY — completed-event audit log, NOT surfaced "
            "at SessionStart. M29 (cron build+stage; closes operator_ledger.py:54-56 "
            "deferred follow-up). Per-INVOCATION uuid (SC1: local var in main())."
        ),
    ),
    "brain_push_completed": _register(
        "brain_push_completed",
        STATE_DIR / "brain_push_completed.txt",
        doc=(
            "key_field=ts_ms:run_uuid_hex8, key_field_type=str, tz_awareness=n/a. "
            "Source: cron/run_brain_push.py run-completion timestamps. Producer: "
            "deliberate token-gated brain force-save (brain_store.save() bypassing the "
            "900s Stop-hook throttle, e.g. pre-machine-handoff). Does NOT git commit/"
            "push (C5: operator commits brain/ in their normal push flow). Consumer: "
            "operator forensic grep ONLY. M29 (cron build+stage). Per-INVOCATION uuid "
            "(SC1: local var in main())."
        ),
    ),
    "atlas_promotion_completed": _register(
        "atlas_promotion_completed",
        STATE_DIR / "atlas_promotion_completed.txt",
        doc=(
            "key_field=ts_ms:project:domain:note_id, "
            "key_field_type=str, tz_awareness=n/a. "
            "Source: cli/promote_atlas_note.py promote() commit step. "
            "Producer: operator-invoked promote_atlas_note CLI on "
            "successful os.replace(tmp, Core/<domain>/<type>/<id>.md) "
            "AND audit log append. Consumer: operator forensic grep + "
            "99-archive/promoted-log.md cross-ref ONLY — completed-event audit "
            "log, NOT surfaced at SessionStart (STEP 6 operator decision "
            "2026-06-04; prior '[atlas-promotion] line (future)' retracted). "
            "P5 (atlas-system "
            "domain, promotion-policy.md sub→core gate). project is the "
            "sub-brain repo basename (e.g. example_project-analysis); "
            "domain is the Core registry domain; note_id matches the "
            "source frontmatter `id:` field."
        ),
    ),
}


def resolve(name: str) -> AdvisoryAck:
    """Behavioral dispatch — raises KeyError with known-set on miss."""
    if name not in REGISTRY:
        raise KeyError(
            f"unknown advisory {name!r}; registered: {sorted(REGISTRY)}"
        )
    return REGISTRY[name]
