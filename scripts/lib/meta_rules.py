"""meta_rules — versioned registry for harness meta-rules (v15.34).

메타-vision 세 번째 building block. v15.32 sensor_anomaly가 sensor incompleteness,
v15.33 action_evolver가 actuator incompleteness를 다뤘다면, 본 모듈은 *meta-loop
incompleteness*를 다룬다 — 메타-룰을 versioned 1급 시민으로 코드화.

현재 메타-룰들은 prose 형태로 CLAUDE.md L0 / W19.1.x amendments / debate ontology
snapshots에 분산. 본 registry는 그것들을 dataclass로 추출 + lineage 추적 → 미래
cycle에서 *메타-룰 자체*를 query/diff/version-bump 가능하게 만든다.

이는 본질적 잔여 (Goedel/Halting 회귀) 자체를 *해결하지 않는다* — 본질적 한계는
정의상 unresolvable. 그러나 메타-룰을 *추적 가능한 객체*로 만들면 그 한계 내에서
최대한 명시적 reasoning이 가능해진다. 면역계 비유의 마지막 piece: B-cell (v15.32)
+ T-cell (v15.33 actuator pattern) + memory (본 v15.34 versioned registry).

Public API:
- MetaRule dataclass (rule_id, version, introduced_in, source_debate, description,
  enforce_layer, status, supersedes, rationale)
- REGISTRY: tuple[MetaRule, ...] (frozen seed, 본 cycle 시점 active set)
- current_rules() → list[MetaRule]  (status='active' only)
- rule_by_id(rule_id) → MetaRule | None
- rule_history(rule_id) → list[MetaRule]  (모든 version 시간순)
- supersession_chain(rule_id) → list[str]  (rule_id가 supersede한 rule_ids 재귀)
- diff_versions(rule_id, v1, v2) → dict  (version 간 field diff)
- coverage_report() → dict  (enforce_layer 분포, status 분포 등)

Versioning convention:
- vMAJOR.MINOR (semver-like)
- MAJOR bump = breaking semantic 변경 (예: paradox_guard 조건 추가)
- MINOR bump = clarification/refinement (예: prose 보강)

Single-file mutation surface (v15.34 D5 gate precedent 유지).

NOT included in this cycle (deferred to future):
- runtime enforcement hook (현재는 query/audit only)
- rule update mechanism via debate (메타-룰이 메타-룰을 수정하는 mechanism)
- 외부 storage backend (현재 frozen Python tuple, runtime mutate 불가 — invariant)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class EnforceLayer(str, Enum):
    """Where the rule is enforced.

    - CODE: enforced by Python invariant (e.g., orchestrator.evaluate_completion)
    - PROSE: documented in CLAUDE.md / HANDOFF, agent prompt 차원
    - OPERATOR: runtime policy mutation token-gated (e.g., settings.json edits)
    - DEBATE: 새 결정 시 debate 게이트 필수 (D-DECISIONS class)
    """
    CODE = "code"
    PROSE = "prose"
    OPERATOR = "operator"
    DEBATE = "debate"


class RuleStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"   # 폐기 (예: W19.1 메타 룰 → W19.1.2 retreat)
    SUPERSEDED = "superseded"   # 다른 룰이 대체


@dataclass(frozen=True)
class MetaRule:
    rule_id: str                  # snake_case, immutable identifier
    version: str                  # "vMAJOR.MINOR" e.g., "v1.0" / "v1.1" / "v2.0"
    introduced_in: str            # cycle id (e.g., "v15.10") or commit SHA
    description: str              # 1-line summary
    enforce_layer: EnforceLayer
    status: RuleStatus = RuleStatus.ACTIVE
    source_debate: str | None = None      # debate sid where rule was formalized
    supersedes: tuple[str, ...] = ()      # rule_ids this one replaces
    rationale: str = ""                   # 1-paragraph why-this-exists


# ============================================================================
# REGISTRY — initial seed (v15.34 lift): 10 메타-룰 from CLAUDE.md L0 + W19.1.x +
# debate ontologies. Frozen Python tuple — runtime mutate 불가 (invariant).
# Future cycles add entries here via PR + debate gate.
# ============================================================================

REGISTRY: tuple[MetaRule, ...] = (
    MetaRule(
        rule_id="dge_three_principles",
        version="v1.0",
        introduced_in="v15.0",
        description="Designer-Generator-Evaluator 3-stage invariant: 설계 → 생성 → 검증",
        enforce_layer=EnforceLayer.PROSE,
        rationale="CLAUDE.md L0 #1. 모든 cycle은 D→G→E 분리 + judge-generator provider 분리 (Evaluator는 OpenAIProvider/codex, Generator는 claude-code Anthropic context).",
    ),
    MetaRule(
        rule_id="self_improvement_loop",
        version="v1.0",
        introduced_in="v15.0",
        description="문제 발견 → 해결 → 교훈을 스킬/훅에 영구 반영",
        enforce_layer=EnforceLayer.PROSE,
        rationale="CLAUDE.md L0 #2. 동일 실수가 두 번 발생하지 않도록 매 cycle 학습을 코드화.",
    ),
    MetaRule(
        rule_id="two_strike_rule",
        version="v1.0",
        introduced_in="v15.0",
        description="같은 유형 문제 2회 발생 → 스킬 Gotcha 또는 훅 규칙으로 영구 코드화",
        enforce_layer=EnforceLayer.CODE,
        rationale="CLAUDE.md L0 #3. v15.26 W (Wonder)가 이를 코드 enforce: evaluator verdict='iterate' 같은 fingerprint 2회 연속 → Wonder strategic re-think trigger.",
    ),
    MetaRule(
        rule_id="quantitative_residual_norm",
        version="v1.2",
        introduced_in="v15.W19.1.2",
        description="완료 주장 시 알려진 결함 수 N + 자동 회귀 X/Y + 잔여 위험 비-제로 인정",
        enforce_layer=EnforceLayer.PROSE,
        source_debate="debate-1778232757-24f9e3",
        supersedes=("w19_1_meta_rule_absolute_assertion_ban",),
        rationale="W19.1.2 γ-retreat. W19.1 절대 단언 금지 + self-validation trigger는 self-referential noise generator로 판명. 명시적 결함 카운트로 대체. ⚠️ enforce_layer 정정 (deep-audit rank 3): orchestrator.evaluate_completion(→completion_gate.decide_completion 위임)은 validators/tests/evaluator/iterations만 게이트하고 known_defects/잔여-노름 파라미터가 없다 → 본 룰은 CODE-enforce가 아니라 PROSE(에이전트 규율). 유일한 부분 게이트 calendar_gate_emitter는 settings.json Stop 훅에 미등록 + overdue ledger에만 발동.",
    ),
    MetaRule(
        rule_id="w19_1_meta_rule_absolute_assertion_ban",
        version="v1.0",
        introduced_in="v15.W19.1",
        description="(폐기) 절대 단언 금지 + self-validation trigger",
        enforce_layer=EnforceLayer.PROSE,
        status=RuleStatus.DEPRECATED,
        rationale="W19.1.2 γ-retreat (debate-1778232757-24f9e3 gen 2)에 의해 폐기. self-referential noise generator. quantitative_residual_norm으로 대체.",
    ),
    MetaRule(
        rule_id="phase_tree_convention",
        version="v1.1",
        introduced_in="v15.W19.1.1",
        description="long-running 작업은 HANDOFF Current Phase Block sub_phases 트리. step ≥5 + 자식 ≥3 sub_step → 자식 phase로 promotion",
        enforce_layer=EnforceLayer.PROSE,
        rationale="CLAUDE.md L0 #5. HANDOFF.md 차원 컨벤션, v15.26 D-AC-PHASE-1TO1로 AC tree와 1:1 매핑됨.",
    ),
    MetaRule(
        rule_id="paradox_guard",
        version="v1.1",
        introduced_in="v15.W19.1.1",
        description="evaluator verdict='approved' 조건: test_pass=True AND research_citation_count≥3 AND ontology_match=True",
        enforce_layer=EnforceLayer.CODE,
        source_debate="debate-1778248254-0b7092",
        rationale="W19.1.1 amendment. Self-validation paradox 회피 — 3-조건 strict boolean. 위반 시 LLM/subagent timeout fallback (구 E2 fallback: validators + run_units).",
    ),
    MetaRule(
        rule_id="five_axis_advisory_plus_completeness_gate",
        version="v1.1",
        introduced_in="v15.26",
        description="5축(응집·결합·확장·안정·사용) advisory 1-5 score + 1 boolean axis (completeness) strict GATE",
        enforce_layer=EnforceLayer.CODE,
        source_debate="debate-1778987814-41b475",
        rationale="v15.26 D2 (Critic-driven redesign). GateLeaf + AdvisoryLeaf split, isinstance aggregation, __post_init__ guards 통해 typo bypass 차단. ISO 25010 strict subset + Functional Suitability를 boolean gate로 흡수.",
    ),
    MetaRule(
        rule_id="mutation_classification",
        version="v1.0",
        introduced_in="v15.0",
        description="자동 OK (skill 후보/memory 추가/cron 등록/sub-Atlas 노트 작성) vs 토큰 게이트 (skill 활성화 enable-skill/user preference apply/cron 실행/critic policy 변경/sub→core promotion promote-to-core/validator advisory→blocking graduation graduate-validator) vs NEVER 자동 (runtime policy mutation, settings.json/permissions/hooks 등록)",
        enforce_layer=EnforceLayer.OPERATOR,
        rationale="CLAUDE.md L0 Mutation 분류 표. example_project invariant runtime_policy_mutated_by_command=false 흡수. v15.20+v15.24 operator 후속 2건이 이 invariant 준수 사례.",
    ),
    MetaRule(
        rule_id="single_file_mutation_surface",
        version="v1.0",
        introduced_in="v15.27",
        description="cycle별 mutation surface = 1 file (신규 또는 수정). atomic revert 단위 최소화 + closure timing 명확화",
        enforce_layer=EnforceLayer.PROSE,
        source_debate="debate-1778990144-679cb8",
        rationale="v15.27→33 sequential cycles에서 채택. 각 cycle 1 mutation surface + run_units green + validators 100% + known_defects_in_scope=0 strict gate. 별도 test file 추가 회피 → embedded --self-check 패턴.",
    ),
)


# ============================================================================
# Public Query API
# ============================================================================


def current_rules() -> list[MetaRule]:
    """Return all rules with status=ACTIVE."""
    return [r for r in REGISTRY if r.status == RuleStatus.ACTIVE]


def rule_by_id(rule_id: str) -> MetaRule | None:
    """Return the latest (active or most-recent) rule with given rule_id."""
    if not isinstance(rule_id, str) or not rule_id:
        return None
    matches = [r for r in REGISTRY if r.rule_id == rule_id]
    if not matches:
        return None
    # Prefer ACTIVE; else most-recent by version string
    active = [r for r in matches if r.status == RuleStatus.ACTIVE]
    if active:
        return active[0]
    return sorted(matches, key=lambda r: r.version, reverse=True)[0]


def rule_history(rule_id: str) -> list[MetaRule]:
    """Return all versions of a rule_id, chronologically by version."""
    if not isinstance(rule_id, str) or not rule_id:
        return []
    matches = [r for r in REGISTRY if r.rule_id == rule_id]
    return sorted(matches, key=lambda r: r.version)


def supersession_chain(rule_id: str) -> list[str]:
    """Return rule_ids that `rule_id` supersedes, recursively (deduped)."""
    if not isinstance(rule_id, str) or not rule_id:
        return []
    seen: set[str] = set()
    out: list[str] = []
    queue: list[str] = [rule_id]
    while queue:
        current = queue.pop(0)
        rule = rule_by_id(current)
        if rule is None:
            continue
        for sup in rule.supersedes:
            if sup not in seen:
                seen.add(sup)
                out.append(sup)
                queue.append(sup)
    return out


def diff_versions(rule_id: str, v1: str, v2: str) -> dict:
    """Return per-field diff between two versions of a rule_id.

    Output: {field_name: {"v1": value_at_v1, "v2": value_at_v2}}
    Missing field on either side means version not found.
    """
    history = rule_history(rule_id)
    r1 = next((r for r in history if r.version == v1), None)
    r2 = next((r for r in history if r.version == v2), None)
    if r1 is None or r2 is None:
        return {"_error": f"version not found: v1={v1 if r1 else 'MISSING'} v2={v2 if r2 else 'MISSING'}"}
    diffs: dict = {}
    for fld in ("description", "enforce_layer", "status", "introduced_in",
                "source_debate", "supersedes", "rationale"):
        a = getattr(r1, fld)
        b = getattr(r2, fld)
        if a != b:
            diffs[fld] = {"v1": str(a), "v2": str(b)}
    return diffs


def coverage_report() -> dict:
    """Return distribution: total / by_status / by_enforce_layer / supersession_count."""
    total = len(REGISTRY)
    by_status: dict[str, int] = {}
    by_layer: dict[str, int] = {}
    superseded_count = 0
    for r in REGISTRY:
        by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        by_layer[r.enforce_layer.value] = by_layer.get(r.enforce_layer.value, 0) + 1
        if r.supersedes:
            superseded_count += len(r.supersedes)
    return {
        "total_rules": total,
        "by_status": by_status,
        "by_enforce_layer": by_layer,
        "supersession_count": superseded_count,
        "active_rule_ids": sorted(r.rule_id for r in current_rules()),
    }


# ============================================================================
# Embedded self-check (single-file mutation surface invariant — v15.34)
# ============================================================================


def _self_check() -> int:
    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    # Case 1: registry non-empty + immutable dataclass
    case("registry_non_empty", len(REGISTRY) >= 10)
    case("registry_is_tuple", isinstance(REGISTRY, tuple))
    try:
        # Attempt regular attribute assignment on frozen dataclass — should raise
        REGISTRY[0].rule_id = "hacked"  # type: ignore[misc]
        case("rule_frozen_dataclass", False, "frozen=True breach")
    except Exception:
        case("rule_frozen_dataclass", True)

    # Case 2: current_rules excludes deprecated
    actives = current_rules()
    case("current_rules_excludes_deprecated",
         not any(r.status != RuleStatus.ACTIVE for r in actives))
    case("current_rules_at_least_8", len(actives) >= 8)

    # Case 3: rule_by_id lookup
    paradox = rule_by_id("paradox_guard")
    case("rule_by_id_finds_paradox", paradox is not None and paradox.version == "v1.1")
    case("rule_by_id_missing_returns_none", rule_by_id("nonexistent_rule_xyz") is None)
    case("rule_by_id_empty_returns_none", rule_by_id("") is None)

    # Case 4: rule_history sorted by version
    qrn_history = rule_history("quantitative_residual_norm")
    case("rule_history_qrn_exists", len(qrn_history) == 1)
    w19_history = rule_history("w19_1_meta_rule_absolute_assertion_ban")
    case("deprecated_rule_history_findable", len(w19_history) == 1)
    case("deprecated_rule_status", w19_history[0].status == RuleStatus.DEPRECATED)

    # Case 5: supersession chain
    chain = supersession_chain("quantitative_residual_norm")
    case("supersession_finds_w19_1",
         "w19_1_meta_rule_absolute_assertion_ban" in chain)
    empty_chain = supersession_chain("dge_three_principles")
    case("no_supersession_empty_chain", empty_chain == [])

    # Case 6: diff_versions (single-version rules → empty diff or error)
    diff = diff_versions("paradox_guard", "v1.0", "v1.1")
    case("diff_missing_version_returns_error", "_error" in diff)

    # Case 7: coverage_report
    report = coverage_report()
    case("coverage_total_matches", report["total_rules"] == len(REGISTRY))
    case("coverage_has_status_distribution", "active" in report["by_status"])
    case("coverage_has_layer_distribution",
         any(layer in report["by_enforce_layer"] for layer in ("code", "prose", "operator")))
    case("coverage_supersession_at_least_one", report["supersession_count"] >= 1)

    # Case 8: enforce_layer enum integrity
    case("enforce_layer_values_consistent",
         all(r.enforce_layer in EnforceLayer for r in REGISTRY))
    case("status_values_consistent",
         all(r.status in RuleStatus for r in REGISTRY))

    # Case 9: version strings well-formed (vMAJOR.MINOR or similar)
    for r in REGISTRY:
        if not (r.version.startswith("v") and "." in r.version):
            case(f"version_wellformed_{r.rule_id}", False, f"version={r.version}")
            break
    else:
        case("version_wellformed_all", True)

    # Case 10: rule_id is snake_case
    import re as _re
    snake_re = _re.compile(r"^[a-z][a-z0-9_]*$")
    for r in REGISTRY:
        if not snake_re.match(r.rule_id):
            case(f"rule_id_snake_case_{r.rule_id}", False, f"id={r.rule_id}")
            break
    else:
        case("rule_id_snake_case_all", True)

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
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    print("lib.meta_rules — versioned registry of harness meta-rules (v15.34)")
    print(f"  active rules: {len(current_rules())} / total: {len(REGISTRY)}")
    print(f"  use --self-check to run embedded smoke test")
    sys.exit(0)
