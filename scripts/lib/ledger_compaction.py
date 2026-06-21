"""ledger_compaction — pure compaction logic for the operator-ledger (M29).

Closes the follow-up explicitly deferred in lib/operator_ledger.py:54-56 ("Not in
this module: cron-based weekly compaction. That belongs under the `enable-cron-job`
Mutation gate and lives wherever the other cron entries live"). The operator-ledger
is append-only per (project_id, agent_type): every task invocation appends a record,
so re-running the SAME task (same task_hash) accumulates superseded duplicates whose
only current value is the latest outcome.

Compaction = keep the LATEST record per task_hash; everything else is superseded.
Two records are NEVER dropped: (1) any `human_override` record (operator decisions are
audit-critical), (2) any record without a task_hash (cannot be de-duplicated safely).
Superseded records are not destroyed by this module — the cron consumer ARCHIVES them
to a `.compacted.<ts>` sibling (audit trail, mirroring run_l2_promotion's `.consumed`
discipline), never hard-deletes. This module only computes the plan; it does no IO.
"""
from __future__ import annotations

from dataclasses import dataclass


def _ts_key(rec: dict) -> str:
    """Sort key for 'latest' — ISO-8601 ts strings sort lexicographically by time."""
    return str(rec.get("ts") or "")


@dataclass(frozen=True)
class CompactionPlan:
    kept: tuple[dict, ...]          # records to retain in the live ledger
    superseded: tuple[dict, ...]    # older duplicates to archive (never deleted)

    @property
    def total(self) -> int:
        return len(self.kept) + len(self.superseded)

    @property
    def reclaimed(self) -> int:
        return len(self.superseded)


def compaction_plan(records: list[dict]) -> CompactionPlan:
    """Partition ledger records into (kept, superseded). Pure + deterministic.

    kept = the latest record per task_hash + ALL human_override records + ALL
    records lacking a task_hash. superseded = older duplicates of a task_hash
    (the rows compaction reclaims). Input order is preserved within each partition,
    so re-running on already-compacted input is idempotent (superseded becomes empty).
    """
    # Latest index per task_hash among de-dup-eligible records only.
    latest_idx: dict[str, int] = {}
    for i, r in enumerate(records):
        if not isinstance(r, dict) or r.get("human_override"):
            continue
        th = r.get("task_hash")
        if not th:
            continue
        prev = latest_idx.get(th)
        if prev is None or _ts_key(r) >= _ts_key(records[prev]):
            latest_idx[th] = i
    latest_indices = set(latest_idx.values())

    kept: list[dict] = []
    superseded: list[dict] = []
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            kept.append(r)  # preserve unparsed/foreign rows untouched (never lose data)
        elif r.get("human_override") or not r.get("task_hash"):
            kept.append(r)
        elif i in latest_indices:
            kept.append(r)
        else:
            superseded.append(r)
    return CompactionPlan(kept=tuple(kept), superseded=tuple(superseded))


def redundancy_ratio(records: list[dict]) -> float:
    """Fraction of records that compaction would reclaim (superseded / total)."""
    if not records:
        return 0.0
    return compaction_plan(records).reclaimed / len(records)
