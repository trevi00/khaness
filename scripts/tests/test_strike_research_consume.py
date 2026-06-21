#!/usr/bin/env python3
"""Tests for cli.strike_research_consume + the M18 skill_candidate_detector clobber-guard.

Covers the deterministic seam (debate-1781594208-53fee4): consume routing (stage / escalate /
forensic / fail-closed / idempotent), decide_dispatch (skip / fire), and the D3 co-tenancy
collision_policy + artifact-surfacing. Auto-discovered by run_units.py via main() -> int.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
for _p in (str(_SCRIPTS), str(_SCRIPTS / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cli.strike_research_consume as cli  # noqa: E402
import skill_candidate_detector as scd  # noqa: E402

_FP = "a1b2c3d4e5f60718"  # 16-hex, matches extract_error_fingerprint digest shape


def _artifact(verdict: str, change_type: str, root_extra: str = "") -> str:
    return (
        f"# Strike {_FP} — Bash schema mismatch on migration\n"
        f"**Tool**: Bash\n**Attempts**: 2\n"
        f"## Root cause\nMigration assumes column ordering that <X> changed. {root_extra}\n"
        f"## Sources\n- local file — establishes it\n"
        f"## Proposed permanent change\n"
        f"- {change_type}: append to skills/_common/db.md Gotchas — pin column order explicitly.\n"
        f"## Why this prevents recurrence\nPins the order.\n"
        f"## Verdict\n- {verdict}\n"
    )


def _env(td: Path):
    """Patch the consume CLI + detector to a temp filesystem; return (sid, ctx-managers)."""
    orch = td / "orchestrator"
    strikes = td / "research" / "strikes"
    cands = td / "cands"
    sid = "orch-test"
    (orch / sid).mkdir(parents=True)
    strikes.mkdir(parents=True)
    return sid, orch, strikes, cands


def test_skill_gotcha_accepted_deterministic_stages():
    with tempfile.TemporaryDirectory() as td:
        sid, orch, strikes, cands = _env(Path(td))
        with mock.patch.object(cli, "_ORCH_DIR", orch), \
                mock.patch.object(cli, "_STRIKES_DIR", strikes), \
                mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            (strikes / f"{_FP}.md").write_text(_artifact("accepted_change", "skill_gotcha"), encoding="utf-8")
            res, code = cli.consume_artifact(sid, _FP)
            assert code == cli.EXIT_CLEAN and res["staged"] is True, res
            assert res["candidate_id"] == f"skill-wonder-{_FP}"
            cj = cands / f"skill-wonder-{_FP}.json"
            assert cj.exists()
            data = json.loads(cj.read_text(encoding="utf-8"))
            assert data["manifest"]["metadata"]["source"] == "strike_research"
            assert data["manifest"]["activation"]["confirm_token"] == "enable-skill"


def test_consume_idempotent_replay():
    with tempfile.TemporaryDirectory() as td:
        sid, orch, strikes, cands = _env(Path(td))
        with mock.patch.object(cli, "_ORCH_DIR", orch), \
                mock.patch.object(cli, "_STRIKES_DIR", strikes), \
                mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            (strikes / f"{_FP}.md").write_text(_artifact("accepted_change", "skill_gotcha"), encoding="utf-8")
            cli.consume_artifact(sid, _FP)
            res2, code2 = cli.consume_artifact(sid, _FP)
            assert code2 == cli.EXIT_CLEAN and res2["deduped"] is True


def test_hook_rule_is_escalation_only_no_candidate():
    fp = "b" * 16
    with tempfile.TemporaryDirectory() as td:
        sid, orch, strikes, cands = _env(Path(td))
        with mock.patch.object(cli, "_ORCH_DIR", orch), \
                mock.patch.object(cli, "_STRIKES_DIR", strikes), \
                mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            (strikes / f"{fp}.md").write_text(_artifact("accepted_change", "hook_rule"), encoding="utf-8")
            res, code = cli.consume_artifact(sid, fp)
            assert code == cli.EXIT_CLEAN and res["escalated"] is True and res["staged"] is False
            assert (strikes / f"{fp}.escalation.json").exists()
            assert not (cands / f"skill-wonder-{fp}.json").exists(), "hook_rule must NOT stage a candidate"


def test_settings_change_is_escalation_only():
    fp = "c" * 16
    with tempfile.TemporaryDirectory() as td:
        sid, orch, strikes, cands = _env(Path(td))
        with mock.patch.object(cli, "_ORCH_DIR", orch), \
                mock.patch.object(cli, "_STRIKES_DIR", strikes), \
                mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            (strikes / f"{fp}.md").write_text(_artifact("accepted_change", "settings_change"), encoding="utf-8")
            res, code = cli.consume_artifact(sid, fp)
            assert res["escalated"] is True and res["staged"] is False


def test_transient_fingerprint_escalates_not_silent_failclosed():
    fp = "d" * 16
    with tempfile.TemporaryDirectory() as td:
        sid, orch, strikes, cands = _env(Path(td))
        with mock.patch.object(cli, "_ORCH_DIR", orch), \
                mock.patch.object(cli, "_STRIKES_DIR", strikes), \
                mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            art = _artifact("accepted_change", "skill_gotcha", root_extra="HTTP <X> Forbidden cloudflare timeout")
            (strikes / f"{fp}.md").write_text(art, encoding="utf-8")
            res, code = cli.consume_artifact(sid, fp)
            assert code == cli.EXIT_CLEAN and res["escalated"] is True and res["staged"] is False, res
            assert "B6" in res["reason"] or "operator-escalation" in res["reason"]


def test_no_research_available_is_forensic_only():
    fp = "e" * 16
    with tempfile.TemporaryDirectory() as td:
        sid, orch, strikes, cands = _env(Path(td))
        with mock.patch.object(cli, "_ORCH_DIR", orch), \
                mock.patch.object(cli, "_STRIKES_DIR", strikes), \
                mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            (strikes / f"{fp}.md").write_text(_artifact("no_research_available", "skill_gotcha"), encoding="utf-8")
            res, code = cli.consume_artifact(sid, fp)
            assert code == cli.EXIT_CLEAN and res["staged"] is False and res["escalated"] is False


def test_missing_artifact_fails_closed():
    with tempfile.TemporaryDirectory() as td:
        sid, orch, strikes, cands = _env(Path(td))
        with mock.patch.object(cli, "_ORCH_DIR", orch), \
                mock.patch.object(cli, "_STRIKES_DIR", strikes), \
                mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            res, code = cli.consume_artifact(sid, "f" * 16)
            assert code == cli.EXIT_ERROR and res["staged"] is False and res["error"]


def test_decide_dispatch_standalone_skips():
    with tempfile.TemporaryDirectory() as td:
        sid, orch, strikes, cands = _env(Path(td))
        with mock.patch.object(cli, "_ORCH_DIR", orch):
            res, code = cli.decide_dispatch("orch-does-not-exist", _FP,
                                            strike_count=2, tool_name="Bash", error_excerpt="x")
            assert code == cli.EXIT_CLEAN and res["action"] == "skip"


def test_decide_dispatch_fires_with_payload():
    with tempfile.TemporaryDirectory() as td:
        sid, orch, strikes, cands = _env(Path(td))
        import lib.paths as paths
        with mock.patch.object(cli, "_ORCH_DIR", orch), mock.patch.object(paths, "STATE_DIR", Path(td)):
            res, code = cli.decide_dispatch(sid, "f0f0f0f0f0f0f0f0",
                                            strike_count=2, tool_name="Bash", error_excerpt="boom")
            assert code == cli.EXIT_FIRE and res["action"] == "dispatch"
            assert res["payload"]["subagent_type"] == "harness-researcher"
            assert res["payload"]["fingerprint"] == "f0f0f0f0f0f0f0f0"


def test_collision_guard_wonder_cannot_clobber_strike():
    import dataclasses
    with tempfile.TemporaryDirectory() as td:
        cands = Path(td) / "cands"
        with mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            strike = scd._build_candidate_from_strike("a" * 16, "pin order", "skills/_common/x.md", "/strikes/a.md")
            strike = dataclasses.replace(strike, secret_scan_clean=True)
            assert scd._write_candidate(strike, collision_policy="priority") == "written"
            # wonder (lower priority) attempts same cid -> skipped, strike survives
            wman = json.loads(json.dumps(strike.manifest))
            wman["metadata"]["source"] = "wonder_reflection"
            wonder = scd.SkillCandidate(id=strike.id, schema=strike.schema, manifest=wman,
                                        trace_md="wonder body", secret_scan_clean=True)
            assert scd._write_candidate(wonder, collision_policy="priority") == "skipped_lower_priority"
            disk = json.loads((cands / f"{strike.id}.json").read_text(encoding="utf-8"))
            assert disk["manifest"]["metadata"]["source"] == "strike_research"


def test_collision_guard_strike_overwrites_wonder_reverse_order():
    import dataclasses
    cid = "skill-wonder-" + ("b" * 16)
    with tempfile.TemporaryDirectory() as td:
        cands = Path(td) / "cands"
        with mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            wman = {"name": cid, "metadata": {"source": "wonder_reflection"},
                    "activation": {"confirm_token": "enable-skill"}}
            wonder = scd.SkillCandidate(id=cid, schema="agentskills.io/v1", manifest=wman,
                                        trace_md="wb", secret_scan_clean=True)
            assert scd._write_candidate(wonder, collision_policy="priority") == "written"
            sman = {"name": cid, "metadata": {"source": "strike_research"},
                    "activation": {"confirm_token": "enable-skill"}}
            strike = scd.SkillCandidate(id=cid, schema="agentskills.io/v1", manifest=sman,
                                        trace_md="sb", secret_scan_clean=True)
            assert scd._write_candidate(strike, collision_policy="priority") == "written"
            disk = json.loads((cands / f"{cid}.json").read_text(encoding="utf-8"))
            assert disk["manifest"]["metadata"]["source"] == "strike_research"


def test_surface_strike_artifact_idempotent():
    cid = "skill-wonder-" + ("c" * 16)
    with tempfile.TemporaryDirectory() as td:
        cands = Path(td) / "cands"
        with mock.patch.object(scd, "_CANDIDATES_ROOT", cands):
            man = {"name": cid, "metadata": {"source": "wonder_reflection"}}
            c = scd.SkillCandidate(id=cid, schema="agentskills.io/v1", manifest=man,
                                   trace_md="b", secret_scan_clean=True)
            scd._write_candidate(c, collision_policy="priority")
            assert scd._surface_strike_artifact(cid, "/strikes/c.md") is True
            assert scd._surface_strike_artifact(cid, "/strikes/c.md") is False
            disk = json.loads((cands / f"{cid}.json").read_text(encoding="utf-8"))
            assert disk["manifest"]["metadata"]["strike_research_artifact"] == "/strikes/c.md"


def test_build_candidate_from_strike_rejects_bad_fingerprint():
    assert scd._build_candidate_from_strike("nothex", "body", None, "/p") is None
    assert scd._build_candidate_from_strike("a" * 16, "  ", None, "/p") is None
    assert scd._build_candidate_from_strike("a" * 15, "body", None, "/p") is None


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
