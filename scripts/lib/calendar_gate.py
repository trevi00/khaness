"""calendar_gate — pure lib-tier deadline scanner for residual-norm ledgers.

Path 2 D1 (debate-1779229138-db17ce gen 3 LOCK SHA
c75bfaf403981c1fcd8cb45c0872c83ae564b777). Companion to D2 ledger
(state/residual_norm/*.json) + D6 handlers/stop adapter + D7 dispatcher
pre-check.

## Responsibility

Scan `state_root/residual_norm/*.json` ledger files. For each ledger,
emit an overdue entry when BOTH:
  - `today >= ledger.deadline` (ISO date string comparison; lexicographic
    on YYYY-MM-DD is correct)
  - `ledger.known_defects > 0` (zero-defect ledger is not "overdue" — the
    invariant intent is "deadline passed AND work remains")

Pure function: no I/O outside the requested state_root, no env reads, no
date `today()` calls. `today` is INJECTED by caller (D5 e2e test, D6
handlers adapter). This is the testability invariant from blueprint L5
("e2e integration test — today: date 주입, no freezegun").

## Public surface

- LEDGER_GLOB constant
- ScanResult dataclass (frozen)
- LedgerParseError
- scan_deadlines(state_root, today) -> list[ScanResult]
- read_ledger(path) -> dict (raises LedgerParseError on schema violation)

## Non-goals

- No mutation: caller decides whether to update ledger.last_eval_ts /
  last_verdict (D7 dispatcher pre-check responsibility).
- No Stop-hook emit: D6 handlers/stop/calendar_gate_emitter.py adapts
  scan results to the Stop-hook decision='block' shape.
- No env / clock access: `today` injected, `state_root` injected.

## Cross-references

- D2 ledger schema: state/residual_norm/rlm_gate.json
- D6 adapter: handlers/stop/calendar_gate_emitter.py
- D7 reader: lib/evaluator_dispatcher pre-check
- HANDOFF.md wave 10 (Path 2 implementation entry)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


LEDGER_GLOB: str = "*.json"
"""Glob pattern relative to state_root/residual_norm/."""


class LedgerParseError(ValueError):
    """Raised when a ledger file violates the D2 schema invariants.

    Distinct from generic JSON parse errors — this signals a structural
    contract violation (missing field, wrong type, malformed date string).
    Caller (scan_deadlines) catches per-file and continues with remaining
    ledgers, so a single broken file does not block the scan.
    """


@dataclass(frozen=True)
class ScanResult:
    """One overdue ledger entry returned by scan_deadlines.

    `gate_id` matches the ledger's `gate_id` field (e.g., 'rlm_gate').
    `ledger_path` is the absolute file path for downstream cross-reference.
    `deadline` and `known_defects` are echoed from the ledger for the
    Stop-hook reason message (D6 adapter). `days_overdue` is `today -
    deadline` (positive int when overdue, 0 on the deadline day itself).
    """
    gate_id: str
    ledger_path: Path
    deadline: date
    known_defects: int
    days_overdue: int

    def __post_init__(self) -> None:
        if not isinstance(self.gate_id, str) or not self.gate_id:
            raise LedgerParseError(
                f"gate_id must be non-empty str, got {self.gate_id!r}"
            )
        if not isinstance(self.known_defects, int) or self.known_defects < 0:
            raise LedgerParseError(
                f"known_defects must be non-negative int, "
                f"got {self.known_defects!r}"
            )
        if not isinstance(self.days_overdue, int) or self.days_overdue < 0:
            raise LedgerParseError(
                f"days_overdue must be non-negative int, "
                f"got {self.days_overdue!r}"
            )


def read_ledger(path: Path) -> dict:
    """Read + validate one D2 ledger JSON file.

    Required fields: gate_id (non-empty str), known_defects (int>=0),
    deadline (ISO YYYY-MM-DD or null).
    Optional fields: last_eval_ts, last_verdict, schema_version, notes,
    anchor_debate, anchor_sha1, lock_debate, lock_sha1.

    Returns the raw dict. Caller (scan_deadlines) does the date arithmetic
    + filtering.

    Raises:
      LedgerParseError on missing/malformed required fields.
      OSError / json.JSONDecodeError propagate (caller catches and
      skips with optional logging).
    """
    import json

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise LedgerParseError(
            f"ledger root must be dict, got {type(data).__name__} at {path}"
        )

    gate_id = data.get("gate_id")
    if not isinstance(gate_id, str) or not gate_id:
        raise LedgerParseError(
            f"gate_id missing or non-string at {path}: {gate_id!r}"
        )

    known_defects = data.get("known_defects")
    if not isinstance(known_defects, int) or isinstance(known_defects, bool):
        raise LedgerParseError(
            f"known_defects must be int at {path}, got {known_defects!r}"
        )
    if known_defects < 0:
        raise LedgerParseError(
            f"known_defects must be >=0 at {path}, got {known_defects}"
        )

    deadline_raw = data.get("deadline")
    if deadline_raw is not None:
        if not isinstance(deadline_raw, str):
            raise LedgerParseError(
                f"deadline must be ISO date string or null at {path}, "
                f"got {deadline_raw!r}"
            )
        try:
            date.fromisoformat(deadline_raw)
        except ValueError as e:
            raise LedgerParseError(
                f"deadline not ISO YYYY-MM-DD at {path}: {deadline_raw!r} "
                f"({e})"
            ) from e

    return data


def scan_deadlines(
    state_root: Path | str,
    today: date,
    *,
    on_error: "Iterable[tuple[Path, Exception]] | None" = None,
) -> list[ScanResult]:
    """Scan state_root/residual_norm/*.json for overdue ledger entries.

    Args:
      state_root: directory containing the `residual_norm/` subtree (e.g.,
        Path('~/.claude/state').expanduser()). Path-like.
      today: injected current date (no `date.today()` call inside —
        testability invariant from blueprint L5).
      on_error: optional list-like to which (path, exception) tuples are
        appended for ledger files that failed to parse. None = silent skip.

    Returns:
      list[ScanResult] for ledgers where deadline <= today AND
      known_defects > 0. Empty list when no ledgers exist, no ledgers are
      overdue, or all overdue ledgers have known_defects == 0.

    Behavior:
      - state_root or state_root/residual_norm missing → returns [] (not
        an error; the harness may run before any residual-norm cycle).
      - Per-ledger parse error → captured in `on_error` if provided,
        otherwise silently skipped. Scan continues with remaining files.
      - Ledgers with deadline=null are skipped (no deadline set = no
        overdue evaluation possible).
      - Ledgers with known_defects=0 are skipped EVEN IF overdue (the
        invariant intent is "deadline passed AND work remains").
    """
    if not isinstance(today, date):
        raise TypeError(
            f"today must be datetime.date, got {type(today).__name__}"
        )

    root = Path(state_root)
    rn_dir = root / "residual_norm"
    if not rn_dir.is_dir():
        return []

    results: list[ScanResult] = []
    for ledger_path in sorted(rn_dir.glob(LEDGER_GLOB)):
        try:
            data = read_ledger(ledger_path)
        except (OSError, ValueError) as e:
            # ValueError covers both json.JSONDecodeError and LedgerParseError.
            if on_error is not None:
                try:
                    on_error.append((ledger_path, e))  # type: ignore[attr-defined]
                except Exception:
                    pass
            continue

        deadline_raw = data.get("deadline")
        if deadline_raw is None:
            continue
        deadline_date = date.fromisoformat(deadline_raw)
        known_defects = int(data["known_defects"])

        if known_defects <= 0:
            continue
        if today < deadline_date:
            continue

        days_overdue = (today - deadline_date).days
        results.append(ScanResult(
            gate_id=str(data["gate_id"]),
            ledger_path=ledger_path,
            deadline=deadline_date,
            known_defects=known_defects,
            days_overdue=days_overdue,
        ))

    return results


# ============================================================================
# Embedded self-check (single-file mutation surface invariant)
# ============================================================================


def _self_check() -> int:
    import sys
    import json
    import tempfile

    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    # ---- Case 1: today must be date, not str or datetime ----
    try:
        scan_deadlines("/nonexistent", "2026-05-20")  # type: ignore[arg-type]
        case("today_rejects_str", False, "expected TypeError")
    except TypeError:
        case("today_rejects_str", True)

    try:
        scan_deadlines("/nonexistent", 20260520)  # type: ignore[arg-type]
        case("today_rejects_int", False, "expected TypeError")
    except TypeError:
        case("today_rejects_int", True)

    # ---- Case 2: missing state_root returns [] ----
    results = scan_deadlines("/nonexistent/path/xyz", date(2026, 5, 20))
    case("missing_state_root_empty", results == [])

    # ---- Case 3: missing residual_norm subdir returns [] ----
    with tempfile.TemporaryDirectory() as td:
        results = scan_deadlines(td, date(2026, 5, 20))
        case("missing_residual_norm_empty", results == [])

    # ---- Case 4: empty residual_norm returns [] ----
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "residual_norm").mkdir()
        results = scan_deadlines(td, date(2026, 5, 20))
        case("empty_residual_norm_empty", results == [])

    # ---- Case 5: ledger with deadline in future returns [] ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "future.json").write_text(json.dumps({
            "gate_id": "future_gate", "known_defects": 5,
            "deadline": "2027-01-01",
        }))
        results = scan_deadlines(td, date(2026, 5, 20))
        case("future_deadline_not_overdue", results == [])

    # ---- Case 6: ledger with deadline today AND known_defects>0 returns 1 ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "today.json").write_text(json.dumps({
            "gate_id": "today_gate", "known_defects": 3,
            "deadline": "2026-05-20",
        }))
        results = scan_deadlines(td, date(2026, 5, 20))
        case("deadline_today_overdue_zero_days",
             len(results) == 1 and results[0].days_overdue == 0)
        case("today_gate_id", results and results[0].gate_id == "today_gate")
        case("today_known_defects_echoed",
             results and results[0].known_defects == 3)

    # ---- Case 7: ledger overdue by 30 days returns days_overdue=30 ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "overdue.json").write_text(json.dumps({
            "gate_id": "overdue_gate", "known_defects": 1,
            "deadline": "2026-04-20",
        }))
        results = scan_deadlines(td, date(2026, 5, 20))
        case("deadline_overdue_30_days",
             len(results) == 1 and results[0].days_overdue == 30)

    # ---- Case 8: known_defects=0 NOT overdue even if past deadline ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "clean.json").write_text(json.dumps({
            "gate_id": "clean_gate", "known_defects": 0,
            "deadline": "2026-01-01",
        }))
        results = scan_deadlines(td, date(2026, 5, 20))
        case("zero_defects_skip_even_if_overdue", results == [])

    # ---- Case 9: deadline=null skipped ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "no_deadline.json").write_text(json.dumps({
            "gate_id": "nd_gate", "known_defects": 5,
            "deadline": None,
        }))
        results = scan_deadlines(td, date(2026, 5, 20))
        case("null_deadline_skipped", results == [])

    # ---- Case 10: malformed JSON captured in on_error, scan continues ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "broken.json").write_text("{not valid json")
        (rn / "valid.json").write_text(json.dumps({
            "gate_id": "valid_gate", "known_defects": 1,
            "deadline": "2026-01-01",
        }))
        errors: list = []
        results = scan_deadlines(td, date(2026, 5, 20), on_error=errors)
        case("malformed_continues_scan",
             len(results) == 1 and results[0].gate_id == "valid_gate")
        case("malformed_captured_in_on_error",
             len(errors) == 1 and errors[0][0].name == "broken.json")

    # ---- Case 11: malformed without on_error silently skipped ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "broken.json").write_text("{not valid json")
        results = scan_deadlines(td, date(2026, 5, 20))  # no on_error
        case("malformed_silent_skip_no_crash", results == [])

    # ---- Case 12: read_ledger raises on missing required fields ----
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "missing_gate_id.json"
        p.write_text(json.dumps({"known_defects": 1, "deadline": "2026-01-01"}))
        try:
            read_ledger(p)
            case("read_ledger_missing_gate_id", False,
                 "expected LedgerParseError")
        except LedgerParseError:
            case("read_ledger_missing_gate_id", True)

        p = Path(td) / "bad_defects.json"
        p.write_text(json.dumps({
            "gate_id": "x", "known_defects": "five", "deadline": "2026-01-01"
        }))
        try:
            read_ledger(p)
            case("read_ledger_non_int_defects", False,
                 "expected LedgerParseError")
        except LedgerParseError:
            case("read_ledger_non_int_defects", True)

        p = Path(td) / "negative_defects.json"
        p.write_text(json.dumps({
            "gate_id": "x", "known_defects": -1, "deadline": "2026-01-01"
        }))
        try:
            read_ledger(p)
            case("read_ledger_negative_defects", False,
                 "expected LedgerParseError")
        except LedgerParseError:
            case("read_ledger_negative_defects", True)

        p = Path(td) / "bad_deadline.json"
        p.write_text(json.dumps({
            "gate_id": "x", "known_defects": 1, "deadline": "not-a-date"
        }))
        try:
            read_ledger(p)
            case("read_ledger_malformed_deadline", False,
                 "expected LedgerParseError")
        except LedgerParseError:
            case("read_ledger_malformed_deadline", True)

    # ---- Case 13: read_ledger rejects bool as known_defects (int subclass guard) ----
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bool_defects.json"
        p.write_text(json.dumps({
            "gate_id": "x", "known_defects": True, "deadline": "2026-01-01"
        }))
        try:
            read_ledger(p)
            case("read_ledger_rejects_bool_defects", False,
                 "expected LedgerParseError")
        except LedgerParseError:
            case("read_ledger_rejects_bool_defects", True)

    # ---- Case 14: multiple overdue ledgers returned in sorted glob order ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        for name, gid in [("b.json", "b_gate"), ("a.json", "a_gate"),
                          ("c.json", "c_gate")]:
            (rn / name).write_text(json.dumps({
                "gate_id": gid, "known_defects": 1, "deadline": "2026-01-01"
            }))
        results = scan_deadlines(td, date(2026, 5, 20))
        case("multiple_overdue_sorted",
             [r.gate_id for r in results] == ["a_gate", "b_gate", "c_gate"])

    # ---- Case 15: ScanResult validation ----
    try:
        ScanResult(gate_id="", ledger_path=Path("/x"), deadline=date(2026, 1, 1),
                   known_defects=1, days_overdue=0)
        case("scan_result_rejects_empty_gate_id", False,
             "expected LedgerParseError")
    except LedgerParseError:
        case("scan_result_rejects_empty_gate_id", True)

    try:
        ScanResult(gate_id="x", ledger_path=Path("/x"), deadline=date(2026, 1, 1),
                   known_defects=-1, days_overdue=0)
        case("scan_result_rejects_negative_defects", False,
             "expected LedgerParseError")
    except LedgerParseError:
        case("scan_result_rejects_negative_defects", True)

    try:
        ScanResult(gate_id="x", ledger_path=Path("/x"), deadline=date(2026, 1, 1),
                   known_defects=1, days_overdue=-5)
        case("scan_result_rejects_negative_overdue", False,
             "expected LedgerParseError")
    except LedgerParseError:
        case("scan_result_rejects_negative_overdue", True)

    # ---- report ----
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
    import sys as _sys
    if "--self-check" in _sys.argv:
        _sys.exit(_self_check())
    print("lib.calendar_gate — Path 2 D1 (debate-1779229138-db17ce LOCK c75bfaf4)")
    print(f"  ledger_glob: {LEDGER_GLOB}")
    print(f"  pure function: scan_deadlines(state_root, today: date)")
    print(f"  use --self-check to run embedded smoke test")
    _sys.exit(0)
