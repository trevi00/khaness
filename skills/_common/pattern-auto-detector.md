---
name: pattern-auto-detector
description: "분리 후보 함수가 주어지면 ≤30초 안에 추천 패턴 + 분리 전략을 lock. V13a 7 iter / V16-V18 trichotomy / 안티패턴 매트릭스를 의사결정 트리로 자동 매칭."
keywords: pattern, abstraction, monolith, separation, sub-variation, V13a, V16, V17, V18, 호모모피즘, 분리, 추출
phase: plan implement review
---

# Pattern Auto-Detector (호모모피즘/V13a sub-variation 자동 추천)

> 원칙: **분리 후보 함수가 주어지면 ≤30초 안에 추천 패턴 + 분리 전략을 lock**. V13a 7 iter / V16-V18 trichotomy / 안티패턴 매트릭스를 의사결정 트리로 자동 매칭.
> 입력: monolith 파일 경로 + 분리 후보 함수명 (또는 함수 리스트)
> 출력: 추천 sub-variation + 분리 위치 (sub-module 경로) + 호출처 변경 패턴 + risk 평가 + estimated cost
> 짝 스킬: `abstraction-first.md` (catalog SSOT) / `repeat-error-tracker.md` (안티패턴 회피)

## 진입점 — 6 질문에 답하면 패턴 lock

분리 후보에 대해 순차적으로 6 질문에 답하면 자동으로 sub-variation 결정.

```
Q1: 후보 fn 의미 카테고리?
    (a) 도메인-specific helper (refresh / objective / business logic)  → Q2로
    (b) 언어-무관 utility (CLI args / paths / hash / OS string)        → V13a-utility-module 고정

Q2: 기존 sub-module에 같은 카테고리 helper 있는가?
    (a) 있음 + 1+ fn 존재                                              → Q3로
    (b) 없음 (sub-module 자체가 신규)                                  → V13a 표준 iter 1 (skeleton + 1 fn)

Q3: 분리 후보 fn 수?
    (a) 1개                                                            → Q4로
    (b) 2+ trivial (≤ 5 LOC body each, 외부 dep 0, primitive only)     → V13a-batch
    (c) 2+ 비-trivial                                                  → 분할: 첫 fn V13a 표준, 나머지 다음 iter

Q4: 함수명이 monolith 내부 다른 fn과 conflict 발생?
    (a) Yes (특히 1-arg overload 존재)                                 → V13a-name-conflict
    (b) No                                                              → Q5로

Q5: 분리할 fn의 dep 분석 (sub-module 호출 OR struct dep 둘 다)
    Q5a: 다른 sub-module의 fn을 호출?
        (a) Yes (sub-module A → sub-module B 의존성)                   → V13a 표준 (cross-module dep variant) → Q5b로
        (b) No                                                          → Q5b로
    Q5b: 인자/return 타입의 struct가 target crate 내부에 정의?         ★ impl-87 강화
        (a) Yes (struct도 target crate 내부)                            → Q5c로
        (b) No (struct가 monolith-internal 또는 다른 외부 crate)        → BLOCK 6 (cross-crate struct dep, 아래 참조)
    Q5c: 분리할 fn body가 호출하는 모든 fn이 target crate 내부?         ★ impl-93 신규
        (a) Yes (모든 호출 fn이 same crate 안 또는 std/외부 dep)         → Q6로
        (b) No (1+ 호출이 monolith-internal로 target crate에 없음)      → BLOCK 7 (cross-crate function call dep, 아래 참조)

Q6: 시그니처 ergonomic 개선 여지?
    (a) `&str` 인자가 caller에서 String/&str 둘 다 받는 경우           → V13a 표준 + `impl Into<String>` (ergonomic builder)
    (b) Default                                                         → V13a 표준 pure single fn
```

## 호모모피즘 detector (별도 path)

분리 작업이 *이전 sub-task와 동일 invariant*를 가진 경우 V16/V17/V18 매칭:

```
이전 sub-task의 V1~V15 중 하나가 동일 invariant?
├── (Yes, full shape 동형 — frontmatter / 시그니처 / file diff 모두 매칭 가능)
│       → V16 full 호모모피즘 (commit message에 "homomorphic to <prev_commit>" 명시)
├── (Yes, partial — template/data shape으로 frontmatter 생략 등 shape-specific 차이)
│       → V17 partial 호모모피즘
└── (No, 다른 branch에 작성된 self-contained crate를 통합 필요)
        → V18 branch cherry-pick 통합
```

## V19 detector path (DGE workflow — 구조적 결정 사전 lock) ★ impl-105 신규

분리 작업이 *구조적 결정* (모듈 경계 / dep graph / naming convention) 또는 *≥ 200 LOC 또는 ≥ 5 functions 영향*인 경우 Q1~Q6 진입 전에 사전 매칭:

```
Q0 (V19 사전 분기): 변경의 nature가 구조적 결정인가?
├── (a) module 경계 변경 / dep graph (new crate / new submodule / cross-crate dep)
├── (b) naming convention 일괄 변경 (prefix 제거 / module path encoding)
├── (c) ≥ 200 LOC 또는 ≥ 5 functions 영향 + Critic이 attack할 명시적 hypothesis 존재
│       → V19 debate-locked design implementation 권고
│         · 1단계: /harness-debate <topic> 호출 → 4-gen 수렴 (Planner/Critic/Architect)
│         · 2단계: ontology_snapshot 확정 후 atomic commit으로 byte-identical 구현
│         · 3단계: commit message footer에 D1/.../Dn 1:1 trace + debate sid + rollback 인용
│         · BLOCK 8 (아래) — debate 사전 lock 없이 V19 후보 진입 차단
└── (d) 위 모두 NO → Q1 (V13a sub-variation detector)로 진입
```

V19 적용 후에도 본문 implementation 안에서 V13a (sub-module 분리) / V16 (이전 sub-task 동형) / V17 (partial 동형)이 *방식*으로 채용될 수 있음 — V19는 "design lock + decisions[] 1:1 trace + atomic commit" abstraction layer, V13a/V16/V17은 본문 implementation 방식.

**Evidence**: impl-105 (`a119680`, 2026-05-14) — PR-2 step 1b. debate sid `debate-1778727952-3db746` 4-gen flow (gen 1 rejected `kha-core` → gen 2 conditional `bridgectl-internal submodule` pivot → gen 3 approved D1/D2/D4/D6 + 9 fns orchestrator 검증 → gen 4 byte-identical converged). 9 fns relocated (4 allows + 5 materialize), main.rs -228 LOC, bridgectl 169/169 + operator-hud 38/38 + kha-core 95/95 회귀 0. **CLAUDE.md DGE 원칙 첫 실증** (Designer=debate, Generator=atomic commit, Evaluator=cascade test). 메타 cycle 20회 발화 + 양방향 vision 14차 cycle.

## V20 detector path (data-shape narrowing — open string → closed enum + Unknown catch-all) ★★★★★ impl-147 자동 발견 zero-effort 검출 first evidence (Stage 5 lifecycle 완주) + v14.15 recipe step 1 scope broadening 정식 적용 (visibility-agnostic) + v14.17 BLOCK 9 sub-branch + in-workspace multi-caller variant Stage 3 자동화 hook 후보 promotion (impl-148 1st + impl-156 2nd + impl-164 3rd, v14.23 cycle) + cross-binary parallel struct sub-variation 1st realized evidence (impl-168, v14.25 cycle) + cross-struct enum 재사용 sub-variation Stage 2 promotion (impl-162 1st + impl-170 2nd, v14.26 cycle)

분리 작업이 *기존 `String` field의 type 좁히기* (closed-set semantics + legacy wire 호환)인 경우 Q1~Q6 진입 전에 사전 매칭:

```
Q0' (V20 사전 분기): 변경의 nature가 data-shape narrowing인가?
├── (a) `pub field: String` (open wire format) + closed-set 의미 (typo/drift 위험)
├── (b) 사전 Grep corpus lock 가능 (N종 wire 값 enumeration; N ≥ 3 권장)
├── (c) 외부 crate caller 0 또는 **in-workspace 1 binary caller** ★ impl-144 완화 또는 **in-workspace N binary caller (atomic single commit으로 모두 migrate 가능)** ★★ impl-148 sub-variation
├── (d) legacy wire-format 호환 필수 (event-log / persistence / config / discord token 등)
│       → V20 data-shape narrowing 권고
│         · 1단계: Grep "<field_name>" + caller corpus 정찰 (N종 wire 값 lock)
│         · 2단계: 외부 caller 정찰 (`Grep("use <crate>::<Type>", path=workspace)`) — 0 또는 in-workspace 1 binary 또는 in-workspace N binary atomic migrate 가능 시 통과 (multi-caller variant — BLOCK 9 sub-branch 참조)
│         · 3단계: enum + `Unknown(String)` catch-all + custom Serialize/Deserialize (byte-identical) + 6 trait impls (`as_wire_str` / `from_wire_str` / `Display` / `FromStr<Err=Infallible>` / `From<&str>` / `From<String>`) + `is_known()` predicate + 6 unit tests (impl-135 / impl-137 / impl-144 / impl-147 / impl-148 byte-equivalent template)
│         · 4단계 ★ NEW (multi-caller variant 시): 2 binary 이상 caller migrate 필요 + large structural scope (≥ 5 structs 또는 ≥ 80 caller sites)인 경우 → **V19 path 결합 필수** (`/harness-debate` 4-gen 수렴 후 byte-identical implementation; impl-148 evidence)
│         · BLOCK 9 (아래) — 외부 crate caller ≥ 2일 때 sub-branch 분기 (in-workspace atomic → multi-caller variant / external production client → 차단)
│         · BLOCK 10 (아래) — tagged-enum wrapper 또는 strict enum (no Unknown) 시도 차단
└── (e) 위 모두 NO → Q0 (V19 사전 분기)로 진입
```

**Auto-detect Grep recipes** (V20 후보 발견 자동화):

```
1. 후보 field 발견 (Serialize-derived struct 안 wire-exposed field — `pub` 강제 X) ★ broadening v14.15:

   Step 1a (사전 정찰 — Serialize-derived struct 식별):
       Grep("#\\[derive\\([^)]*Serialize", path=target_crate, type=rust, -A=8)
       → Serialize 또는 Deserialize derive struct (custom Serialize impl block은 별도 사전 정찰 — `impl Serialize for <Type>` Grep)
       → wire-exposed struct enumeration (private struct도 포함 — file-internal serialize는 여전히 wire format)

   Step 1b (필드 발견 — pub 키워드 optional):
       Grep("^\\s*(pub\\s+)?\\w+:\\s+String\\s*,", path=<Serialize-derived struct 본문>, type=rust)
       - `pub` 키워드 optional — private 필드도 Serialize-derived struct 안이면 wire-exposed
       - Filter: 위 step 1a로 식별한 struct 본문 내부만 (struct 정의 시작 라인 + `}` 종료 사이)

   Step 1c (Filter — field name semantic indicator):
       field name ∈ {status, kind, verdict, severity, priority, state, category, scope, level, class, tier, mode, outcome, phase, stage, origin, source, action, signal, trigger, reason}

   **broadening 이유 (v14.15 정식 적용)**: impl-137 (`dee9967` `ReviewLaneOutcome.verdict`, private struct + private field) + impl-147 (`f4b3c3e` `DiscordRoundtripEvidence.kind`, private struct + private field) 모두 V20 정상 적용 case이나, `pub` 강제 regex는 두 case 모두 miss. Serialize-derived struct 안 field는 visibility와 무관하게 wire-exposed.

2. closed-set 의미 검증 — wire 값 corpus 정찰:
   Grep("<field_name>\\s*=\\s*\"|<field_name>:\\s*\"", path=workspace, type=rust)
   - 결과 distinct string 값 N종 corpus lock
   - N ≥ 3 권장 (closed-set 의미 신뢰도)
   - N == 1 → corpus 부족, 후보 강도 낮음 (deferred)

3. 외부 caller 정찰:
   Grep("use <crate>::<Type>", path=workspace, type=rust)
   - 결과 = 0 → 통과 (file-internal only)
   - 결과 = 1 + caller가 in-workspace binary → 통과 (impl-144 완화)
   - 결과 ≥ 2 → BLOCK 9 sub-branch 분기 (아래)
     (a) caller가 모두 in-workspace + 같은 atomic commit 안에서 migrate 가능 → **V20 in-workspace multi-caller variant** (impl-148 sub-variation 1st evidence). large structural scope (≥ 5 structs 또는 ≥ 80 caller sites) 시 V19 path 결합 권고
     (b) caller가 cross-crate publisher API → V19 territory (debate 호출 필수)
     (c) caller가 production 외부 client → V20 차단, semver-major release 필요

4. legacy wire 호환 필수성 검증:
   Grep("(json|toml|yaml).*deserialize|serde_json::from_str|persist_.*\\(.*<field_owner>", path=workspace)
   - 1+ hit → legacy 호환 필수 (V20 적용 조건 (d) 통과)
   - 0 hit → 호환 부담 0 (V20 oversized, V3 enum extension으로 충분)

5. ★ NEW (v14.24 recipe broadening, Stage 4 zero-effort 자동매칭 보강) — cross-binary parallel struct 패턴:
   Step 5a: 같은 struct 이름이 ≥ 2 in-workspace binaries에 정의되어 있는지 검증:
       Grep("^struct <StructName>\\b", path=apps, type=rust)
       - hits ≥ 2 across distinct binaries → cross-binary parallel struct 후보

   Step 5b: 같은 field가 하나의 binary에서는 enum, 다른 binary에서는 String인지 검증:
       binary A: `<field>: <SomeEnum>` (already migrated)
       binary B: `<field>: String` (not yet migrated)
       → V20 multi-caller promotion 후보 (kha-core으로 enum 승격 후 양쪽 import)

   Step 5c: enum 정의 위치 확인 (orphan rule 회피 계획):
       - binary A의 file-internal enum → kha-core 이동 필요 (parallel definition vs promotion 결정)
       - enum이 cross-crate type에 대한 `From<ForeignType>` impl을 가지면 promotion 시 orphan rule 위반 → caller-site explicit 변환 또는 binary-local newtype wrapper로 대체

   **이유 (v14.24 retroactive evidence)**: `bridgectl::DiscordRoundtripEvidence.kind: String` (L1476) ↔ `discord-bridge::DiscordRoundtripEvidence.kind: DiscordRoundtripKind` (L2321, impl-147 정의 file-internal enum) — gateway-hub 우물 고갈 후 발견된 다음 패턴. recipe step 3 (외부 caller 정찰)이 file-internal enum (kha-core이 아닌 binary-local)을 cross-reference 못함. step 5 추가로 cross-binary parallel struct 패턴 zero-effort 자동매칭 가능.

   **현재 인식 후보 (v14.24 scouting 결과)**: DiscordRoundtripKind (kha-core 승격 candidate, orphan rule 회피 필요). 4th evidence 적용 시 multi-caller variant Stage 3 → Stage 4 zero-effort 검출 trigger 도달 가능.

   **v14.25 first realized evidence (impl-168 `693cc6f`)**: DiscordRoundtripKind kha-core 승격 완료 (cross-binary parallel struct sub-variation 1st realized). discord-bridge writer + bridgectl reader pair unified into kha-core `DiscordRoundtripKind`. **Orphan-rule avoidance**: pre-existing `impl From<DiscordOutboundKind> for DiscordRoundtripKind` trait impl removed → discord-bridge binary-local free fn `outbound_kind_to_roundtrip(DiscordOutboundKind) -> DiscordRoundtripKind` (kha-core does NOT depend on channel-discord, preserving acyclic forward dep graph). Step 5c recommendation (b) "caller-site explicit 변환 또는 binary-local newtype wrapper로 대체" validated — free fn 1 site + 1 boundary helper, ~10 LOC vs full trait impl. 864/864 PASS [+7 V20], 회귀 0. Cross-binary parallel struct sub-variation **Stage 1 후보 lock** (sub-variation lifecycle policy 적용: 1회 lock → 2회 정식 등록 → 3회 자동화 hook → 4회 zero-effort 검출). 다음 2nd evidence 후보: cross-binary writer/reader pair scouting — Grep("^struct <Same>\\b", path=apps) ≥ 2 distinct binaries hit + step 5b enum/String type asymmetry 검증.

6. ★ NEW (v14.27 recipe broadening, D2 tolerant-comparison audit FAIL anti-pattern 자동매칭) — V19/V20 분기 결정 자동화:
   Step 6a: D2 mandatory tolerant-comparison audit (사전 정찰):
       Grep("<field_name>(\\.[a-z_]+)?\\.(eq_ignore_ascii_case|to_ascii_lowercase\\(\\)\\.|to_lowercase\\(\\)\\.)", path=workspace, type=rust)
       추가:
       Grep("matches!\\(<field_name>(\\.[a-z_]+)?\\.(as_str\\(\\)|to_ascii_lowercase\\(\\)\\.as_str\\(\\))", path=workspace)
       - 0 hits → V20 적용 안전 (`is_known() Unknown(_) → false` 안전 확정)
       - ≥1 hit → V20 안티패턴 — V19 territory (debate 필요) 또는 `is_ok_tolerant()` 추가 method 검토 필요

   Step 6b: Strict equality vs tolerant comparison 분기 결정:
       - 모든 caller가 `==`/`!=` literal 문자열 (no case-folding) → V20 strict 안전
       - 모든 caller가 Display-only (format!/println!/to_string) → V20 strict 안전
       - 1+ caller에 `eq_ignore_ascii_case` / `to_ascii_lowercase().as_str()` / `to_lowercase()` / `matches!(..to_ascii_lowercase().as_str(), ...)` → V19 territory

   Step 6c: Production wire schema 확인 (tolerant caller가 dead defensive code인지 판단):
       - publisher가 `#[serde(rename_all = "snake_case")]` 강제 → tolerant code는 over-defensive
       - 다만 legacy JSON artefact 존재 가능성 → `is_ok_tolerant()` method 추가하여 V20 + tolerant 양립 가능
       - V19 debate 호출 시 candidate 분석에 포함

   **이유 (v14.27 retroactive evidence)**: v14.27 정찰에서 발견한 D2 audit FAIL 케이스 모음:
   - bridgectl `WorkerSupervisorQueueStage.status: String` L13696 — caller L13662 `stage.status.to_ascii_lowercase().as_str()` + `matches!("succeeded" | "skipped")` (defensive case-folding)
   - bridgectl `WorkerMergeDecisionHudRecord.action: String` L1652 — caller L13682 + L16157 `decision.action.eq_ignore_ascii_case("reject")` (strict V19 territory per HANDOFF v14.24)

   현재 detector path step 3 (외부 caller 정찰)이 caller 수만 카운트할 뿐 caller convention (tolerant vs strict)을 분류하지 않음. Step 6 추가로 D2 audit를 자동매칭 단계로 격상.

   **현재 인식 후보 (v14.27 scouting 결과)**: WorkerSupervisorQueueStage.status (tolerant) / WorkerMergeDecisionHudRecord.action (tolerant strict V19 territory). 이 두 후보는 V20 차단, V19 debate-locked design implementation candidate.
```

**Template scaffolding** (impl-135 / impl-137 / impl-144 byte-equivalent):

```rust
/// Closed-set <field-domain> field. Wire-format은 평문 string (kebab/snake/lowercase) —
/// Unknown(String) catch-all로 legacy historic JSON round-trip preserve.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FieldName {
    Variant1,  // wire: "variant_1"
    // ... N known
    Unknown(String),  // catch-all (NEVER omit)
}

impl FieldName {
    pub fn as_wire_str(&self) -> &str {
        match self {
            Self::Variant1 => "variant_1",
            // ... N arms
            Self::Unknown(raw) => raw.as_str(),
        }
    }

    pub fn from_wire_str(value: &str) -> Self {
        match value {
            "variant_1" => Self::Variant1,
            // ... N arms
            other => Self::Unknown(other.to_string()),
        }
    }

    pub fn is_known(&self) -> bool {
        !matches!(self, Self::Unknown(_))
    }
}

impl std::fmt::Display for FieldName { fn fmt(&self, f) { f.write_str(self.as_wire_str()) } }
impl std::str::FromStr for FieldName {
    type Err = std::convert::Infallible;
    fn from_str(s: &str) -> Result<Self, Self::Err> { Ok(Self::from_wire_str(s)) }
}
impl From<&str> for FieldName { ... }
impl From<String> for FieldName {
    // CRITICAL: Unknown arm reuses owned allocation (no extra to_string())
    fn from(value: String) -> Self {
        match value.as_str() {
            "variant_1" => Self::Variant1,
            // ...
            _ => Self::Unknown(value),  // value moved, not cloned
        }
    }
}

impl Serialize for FieldName {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_wire_str())
    }
}

impl<'de> Deserialize<'de> for FieldName {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error> {
        let raw = String::deserialize(deserializer)?;
        Ok(Self::from(raw))
    }
}
```

**Required 6 unit tests** (impl-135 / impl-137 / impl-144 byte-equivalent):

1. **known-variant JSON round-trip** (N variants): `serde_json::to_string` → `from_str` → `assert_eq` + `is_known() == true`
2. **Unknown arm preserves raw wire**: `from_wire_str("draft")` → `Unknown("draft")` round-trip + `is_known() == false`
3. **legacy wire deserialize → known**: `serde_json::from_str(r#""variant_1""#)` → `Variant1` (kebab/snake/lowercase 보존)
4. **FromStr<Err=Infallible> infallibility**: `FromStr::from_str("operator-defined").unwrap()` → `Unknown(...)` 정상
5. **From<String> Unknown arm raw-pointer reuse**: `String::from("custom")` → `From::from(s)` → Unknown arm의 `as_ptr() == original_ptr` (allocation 재활용)
6. **parent struct end-to-end JSON byte-identical guard**: legacy `{"field":"variant_1"}` ↔ 새 enum shape JSON 동일 (N + 1 Unknown = N+1 values 전수 검증)

**Evidence**:
- impl-135 (`499b298`, 2026-05-14) — `runtime::LaneOwnership.workflow_scope: String → WorkflowScope` 5 known `{ClawCodeDogfood, TestSuite, ExternalGitMaintenance, InfraHealth, ManualOperator}` + Unknown(String). 사전 Grep 5종 wire 값 corpus lock. 외부 caller 0 검증. 6 unit tests + 회귀 0. **V20 1st evidence (후보 lock Stage 1)**.
- impl-137 (`dee9967`, 2026-05-15) — `tools::ReviewLaneOutcome.verdict: String → ReviewVerdict` 3 known `{Approve, Reject, Blocked}` + Unknown(String). **file-internal private struct + private field** (`struct ReviewLaneOutcome`, no `pub`; `verdict: String`, no `pub`). 외부 caller 0. 6 unit tests + 회귀 0. **V20 2nd evidence (정식 등록 Stage 2)**. **broadening retroactive evidence ★** — recipe step 1 `pub field: String` 강제 regex로는 본 case miss (private struct private field이나 `#[derive(Serialize, Deserialize)]`로 wire-exposed). v14.15 broadening 정식 적용 후 본 case Grep recipe로 zero-effort 자동 발견 가능.
- impl-144 (`82c50d0`, 2026-05-15) — `kha-core::RunMilestoneState.status: String → RunMilestoneStatus` 9 known `{Idle, Running, Planned, Checkpointed, Verified, Repaired, RolledBack, Quarantined, Failed}` + Unknown(String). publicly-exported struct, writer caller = kha-cli single in-workspace binary. **V20 적용 조건 완화 첫 evidence** ("외부 caller 0" → "외부 caller 0 또는 in-workspace 1 binary caller"). 9-value 가장 큰 corpus + 6 unit tests + 회귀 0. **V20 3rd evidence (자동화 hook 후보 Stage 3) ★★★** + 본 detector path 등록 trigger.
- impl-147 (`f4b3c3e`, 2026-05-15) — `discord-bridge::DiscordRoundtripEvidence.kind: String → DiscordRoundtripKind` 5 known `{Plan, RuntimeResult, WorkerAlert, UnattendedHealthAlert, Error}` + Unknown(String). **file-internal private struct + private field** (`struct DiscordRoundtripEvidence`, no `pub`; `kind: String`, no `pub`). 외부 caller 0 (struct privacy로 import 불가). corpus = `discord_outbound_kind_label(DiscordOutboundKind)` match block 5 wire 값. `#[derive(Serialize)]` 단방향 wire (no Deserialize on parent struct — Unknown catch-all은 forward-compat 목적). bonus `From<DiscordOutboundKind>` impl로 caller `.to_string()` 변환 제거 + orphan `discord_outbound_kind_label` helper 흡수. 6 unit tests + 기존 test에 `kind` byte-identical guard 추가 + 회귀 0 (discord-bridge 238 → 244 [+6], 합계 834/834 PASS). **V20 4th evidence (자동 발견 zero-effort 검출 Stage 5 first evidence) ★★★★** — 본 detector path를 통해 zero-effort로 자동 매칭한 첫 검증 cycle. **V20 lifecycle 완주 (Stage 1~5)**. **detector recipe scope broadening 첫 evidence** — recipe step 1 `pub field: String` 제약은 `serde-exposed field including private fields in Serialize-derived struct`로 broadening 권고 (impl-137은 retroactive하게 같은 case이지만 본 evidence가 명시적으로 트리거).
- impl-148 (`a1aa7d7`, 2026-05-15) — `kha-core::UnattendedHealthStatus` 5 known `{Healthy, IdleStopped, NotRunning, GateBlocked, Error}` + Unknown(String). **In-workspace 2 binary caller atomic migrate** — kha-core (2 pub struct fields, definition crate) + bridgectl (3 internal struct fields, ~50 caller sites) + discord-bridge (5 internal struct fields, ~30 caller sites) + 2 helper return type migration + 2 binary-local `From<&...>` impls (Rust orphan rules: reference target local). 5-corpus from `supervisor_unattended_health_status` 5-arm match (bridgectl/main.rs:18003). 사전 정찰 (D2 mandatory audit, expanded regex with `eq_ignore_ascii_case` / `matches!` / bound-variable rebinding) — **0 tolerant-comparison callers** across 3 crates → `is_ok()` Unknown(_) → false 안전 확정. custom Serialize (`serialize_str(as_wire_str())`) + custom Deserialize (`visit_str` allocates + `visit_string` 통한 From<String> raw-pointer reuse — serde Visitor visit_str does NOT borrow source bytes, D4 scoped to From<String> only). 7 신규 unit tests (impl-135/137/144/147 byte-equivalent + `is_ok()` semantics-preservation guard + parent struct 6-case end-to-end). debate sid `debate-1778844941-40ce06` 4-gen 수렴 canonical hash `8be7d91cc4a2` (3/3 citations validated: Rust orphan rules + serde Visitor + proptest). cargo check 9 crates 27.48s + cargo test **841/841 PASS** [+7 V20, baseline 834], 회귀 0. **V20 5th evidence (in-workspace multi-caller variant 1st evidence, sub-variation 정식 등록 Stage 1) ★★★★★ + DGE 원칙 §1 4번째 실증 ★★★★★ + V19 path 결합 (debate-locked design implementation, large structural scope: 5 structs / 3 crates / ~80 caller sites)**. analysis SSOT `~/.claude/state/analysis/v20-enum-hardening.md` (200+ LOC).
- impl-156 (`8f25798`, 2026-05-15) — `kha-core::WorkerStageStatus` 6 known `{Pending, Running, Succeeded, Failed, Quarantined, Skipped}` + Unknown(String). **In-workspace 2 binary caller atomic migrate, V20-only path (no V19 debate)** — kha-core (1 new pub enum, definition crate) + bridgectl (`WorkerStatusHudStage.status` private field, 7 caller sites + 4 test fixtures) + discord-bridge (`WorkerStatusStage.status` private field, 2 caller sites + 2 test fixtures + 1 assert). 6-corpus from `gateway-hub::worker::WorkerStageStatus` `pub(crate) #[serde(rename_all = "snake_case")]` (gateway-hub/src/worker.rs:43). 사전 정찰 D2 mandatory audit — **0 tolerant-comparison callers** on the two target struct fields → `is_known()` Unknown(_) → false 안전 확정. custom Serialize/Deserialize byte-identical (lowercase snake_case 평문, untagged). 6 trait impls + `is_known()` + **`is_blocked()`** (matches caller convention `failed | quarantined` from bridgectl + discord-bridge, replaces 2 inline `matches!` patterns). 7 신규 unit tests (impl-135/137/144/147/148 byte-equivalent + `is_blocked()` semantics + parent struct 6 known + 1 Unknown end-to-end). **operator-hud `OperatorHudWorkerBlockedStage.status: String` unchanged** — boundary conversion via `as_wire_str().to_string()` preserves publicly-exported String shape. cargo test full baseline **849/849 PASS** [+7 V20, baseline 842 from v14.18], 회귀 0. **V20 6th evidence (in-workspace multi-caller variant 2nd evidence, sub-variation Stage 2 정식 등록 promotion) ★★★★★ + V20-only path (small scope: 3 crates / 2 internal struct fields / ~9 caller sites / 6 test fixtures, below V19 threshold)**. impl-148 byte-equivalent shape 재사용 + 6-value corpus (impl-144 9 다음으로 두 번째 큰 corpus).
- impl-158 (`5cb7d36`, 2026-05-15) — `bridgectl::WorkerExecuteHandlerStatus` 3 known `{Deferred, Succeeded, Failed}` + Unknown(String). **V20 vanilla 7th evidence (main lifecycle 보강, PascalCase wire 첫 evidence)** — single-binary bridgectl-local scope (multi-caller variant 아님). corpus from `gateway-hub::worker::WorkerStageHandlerStatus` (gateway-hub/src/worker.rs:543, 기본 serde 사용으로 **PascalCase wire format** — `rename_all = "snake_case"` 없음). bridgectl-local inline enum (no kha-core 변경) — bridgectl/main.rs:1654~1762 inline definition. `WorkerExecuteHandlerHudRecord.status: String → WorkerExecuteHandlerStatus` (L1656) + 2 caller sites migrated. 사전 D2 mandatory audit → 0 tolerant-comparison callers. 6 trait impls + `is_known()` `#[allow(dead_code)]` guard (impl-148-followup precedent). custom Serialize/Deserialize byte-identical **PascalCase wire** — V20 lineage 첫 PascalCase evidence (impl-135~157 모두 snake_case/kebab-case/lowercase 평문). cargo test **849/849 PASS** unchanged, 회귀 0. impl-148/156 byte-equivalent shape 재사용 + PascalCase wire 첫 적용. **Main lifecycle 보강 evidence** (sub-variation 진행과 별개 카운트).
- impl-162 (`ff163cd`, 2026-05-16) — `bridgectl::WorkerSupervisorJsonAlert.status: String → WorkerStageStatus` (impl-156 kha-core enum 재사용, **no new enum 정의**). **V20 vanilla 8th evidence (cross-struct enum 재사용 첫 evidence, single-binary scope)** — kha-core::WorkerStageStatus (impl-156 정의)가 여러 deserialize sink (WorkerStatusHudStage impl-156 + WorkerSupervisorJsonAlert impl-162)를 동시 커버. 같은 wire format (snake_case from gateway-hub `pub(crate) enum WorkerStageStatus`) 공유. 1 caller site + 4 test fixtures. 사전 D2 audit → 0 tolerant-comparison callers. cargo test 850/850 PASS unchanged (no new tests — impl-156 unit tests via shared enum 자동 커버), 회귀 0. **Cross-struct enum 재사용 첫 evidence** — V20 enum의 cross-struct applicability 검증, 단일 enum 정의가 cross-sink 마이그레이션 비용 절감.
- impl-164 (`95c9a20`, 2026-05-16) — `kha-core::WorkerCircuitBreakerDecision` 3 known `{None, RepairContractIssued, OperatorDecisionRequired}` + Unknown(String). **In-workspace 2 binary caller atomic migrate, V20-only path (no V19 debate), smallest multi-caller scope to date** — kha-core (1 new pub enum, definition crate) + bridgectl (`WorkerFailureLearningStatusCommandResult.circuit_breaker` private field L641 + init L7756 + parse L7788) + discord-bridge (`WorkerFailureLearningStatusJsonResult.circuit_breaker` private field L2907, Serialize+Deserialize both honoured). 3-corpus from `gateway-hub::worker::WorkerCircuitBreakerDecision` `pub(crate) #[serde(rename_all = "snake_case")]` (gateway-hub/src/worker.rs:551 — **smallest multi-caller corpus to date**, impl-148=5, impl-156=6, impl-164=3). 사전 정찰 D2 mandatory audit → **0 tolerant-comparison callers** across both binaries (only `println!`/`format!` Display formatting at bridgectl L8600 + discord-bridge L12016). custom Serialize/Deserialize byte-identical (lowercase snake_case 평문, untagged). 6 trait impls + `is_known()`. 7 신규 unit tests (impl-148/156 byte-equivalent + **empty-string → Unknown invariant for byte-identical missing-artefact wire** + parent struct end-to-end JSON byte-identical 5-case [3 known + 2 Unknown including empty + `"ReviewRequired"` legacy sentinel]). **No test fixture changes** — V20 Unknown(String) absorbs PascalCase legacy sentinel `"ReviewRequired"` (5 bridgectl + 1 discord-bridge test fixtures) byte-identical via raw-pointer reuse in `From<String>`. **smallest multi-caller scope to date**: 3 crates / 2 internal struct fields / ~5 caller sites / 4 files (+289/-6 LOC). cargo test full baseline **857/857 PASS** [+7 V20, baseline 850 from v14.22], 회귀 0. **V20 9th evidence (in-workspace multi-caller variant 3rd evidence, sub-variation Stage 3 자동화 hook 후보 promotion trigger) ★★★★★ + V20-only path (smallest scope: 3 crates / 2 internal struct fields / ~5 caller sites / 0 test fixture changes, well below V19 threshold)**. impl-148/156 byte-equivalent shape 재사용 + 3-value corpus (smallest multi-caller). **Stage 3 자동화 hook 후보 promotion**: BLOCK 9 sub-branch (a)에 Grep recipe sub-step 추가 권고 (`Grep "String type field" in apps/*/src/main.rs → cross-reference gateway-hub::pub(crate) enum same name`).

**Recipe broadening 정식 적용 완료 (v14.15 cycle, impl-147 trigger → 정식 반영)** ★★:
- **이전 recipe step 1 (v14.13 ~ v14.14)**: `Grep("^\\s*pub\\s+\\w+:\\s+String\\s*,", ...)` — `pub` 키워드 강제 → impl-137 / impl-147 같은 private struct private field 케이스 miss
- **현재 recipe step 1 (v14.15+)**: Step 1a (`#[derive(Serialize...)]` Grep으로 wire-exposed struct enumeration) → Step 1b (`(pub\\s+)?` optional regex로 visibility-agnostic 필드 발견) → Step 1c (semantic indicator filter) — 위 "Auto-detect Grep recipes" step 1 본문 참조
- **retroactive evidence**: impl-137 (`dee9967` `ReviewLaneOutcome.verdict`, private struct private field) + impl-147 (`f4b3c3e` `DiscordRoundtripEvidence.kind`, private struct private field) — 두 case 모두 broadening 후 zero-effort 자동 발견 가능
- **이유**: Serialize-derived struct 안 field는 visibility (pub vs private)와 무관하게 wire-exposed. V20 적용 invariant (wire-format byte-identical + closed-set semantics)는 visibility와 직교.

## 출력 형식 (자동 추천 카드)

질문 답 받으면 다음 형식으로 추천:

```
=== Pattern Auto-Detector 추천 ===

후보: <fn_name(s)> in <monolith_path>

추천 sub-variation: <V13a / V13a-batch / V13a-utility-module / V13a-name-conflict / V16 / V17 / V18>

분리 위치:
- 파일: <crate_path>/<sub_module>.rs (or 신규 module)
- pub fn 시그니처: <signature>

호출처 변경 패턴:
- replace_all: <old_pattern> → <new_pattern>
- 또는 use 1 라인만: <import statement>

Risk 평가: <0 / low / medium / high>
- 회귀 가능성: <근거>
- 정찰-fix turnaround 예상: <0 / 1회 / 2회+>

Estimated cost:
- LOC delta: <add/remove>
- tests 추가: <count>
- 호출처 갱신: <count>

검증 invariant (commit 전 필수):
- [ ] cargo build PASS
- [ ] cargo test 회귀 0
- [ ] cfg(test) tests N개 PASS
- [ ] 외부 dep 명시적으로 surface
```

## V13a iter naming convention

```
iter 1: pure single fn                  (pure I/O-free)
iter 2: pure single fn (큰)              (≥ 100 LOC, 호출처 20+)
iter 3: cross-module dep                (sub-module A → B 의존 첫 검증)
iter 4: batch trivial                   (V13a-batch, 2+ trivial fn)
iter 5: ergonomic builder               (impl Into<String> / generic 변형)
iter 6: utility module 신규             (V13a-utility-module)
iter 7: name conflict patch             (V13a-name-conflict)
iter 8: domain sub-module 신규          (V13a 표준 — utility 아닌 도메인 helper, BLOCK 5 회피) ★ impl-88
iter 9: V16 동형 (same-module)          (V13a 표준 + V16 — autopilot.rs 안 첫 호모모피즘 fn) ★ impl-89
iter 10: 신규 skeleton + batch + category mix (V13a 표준 + V13a-batch 2번째 — 신규 commands.rs + builder/classifier mix) ★ impl-91
iter 11: 기존 utility module 확장 + same-module call dep (V13a-batch 3번째 + V13a-utility-module 2번째 + BLOCK 7 unblock 첫 evidence — cli_args 확장 command_arg + append_command_flag) ★ impl-96
iter 12: SKIP — allows_autopilot_prevention_* 3 fn 정찰 시 BLOCK 6 (struct dep WorkerFailureLearningConfig) 발화 ★ impl-100
iter 13: 도메인 sub-module 성장 3rd fn (autopilot.rs same-module 안정성 검증 — iter 8/9에 이어 materialize_handoff_branch 15 LOC pure 추가, BLOCK 7 chain dep prevention_handoff 4→3 추가 감쇄) ★ impl-101
iter 14 (분기점): V13a sequence 종결 후 V19 첫 적용 ★ impl-105 (debate sid `debate-1778727952-3db746` 4-gen 수렴) → **V13a iter 14 재진입** ★ impl-118 `5fc728b` (policy 신규 sub-module + 5 trivial classifiers batch + cross-crate forward dep 추가 kha-core 첫 evidence). V13a iter 14가 두 lane 모두 cover — multi-fn structural lane (V19, impl-105) ↔ V13a-friendly small lane (V13a-batch 4번째, impl-118). 두 lane은 mutually exclusive 아닌 complementary.
iter 15+: (미발견, V13a-friendly 잔여 후보 또는 V19 second application)
```

다음 iter 발견 시 본 카탈로그를 자기-갱신 (메타 cycle 발화).

## 의사결정 트리 — 분리 작업 즉시 가이드

새 분리 task에서:

```
1. monolith 정찰 (Grep + Read) → 후보 fn list 구성
2. 각 fn에 대해 Q1~Q6 답변 → sub-variation 결정
3. 분리 위치 (file path / 신규 module 여부) 결정
4. 호출처 변경 pattern 결정 (replace_all vs use 1 라인)
5. risk 평가 + estimated cost 계산
6. 사용자 confirm 또는 자율 진행
```

## 안티패턴 회피 (자동 가드)

다음 경우 추천을 BLOCK + 사용자 컨펌 요구:

```
BLOCK 1: monolith 0.5%+ 변경 + cfg(test) 미동반
  → "PATTERNS-CATALOG monolith 안티패턴 (E1). cfg(test) + file 끝 isolated로 회피 권고"

BLOCK 2: 기존 caller 시그니처 변경
  → "caller 0 신규 method + delegate (V7) 권고"

BLOCK 3: 신규 외부 production dep
  → "workspace 내부 crate path dep 또는 zero-dep pure rust (V14) 권고"

BLOCK 4: 함수명 conflict 미확인 분리
  → "V13a-name-conflict로 분류 + rename + full-signature replace_all 권고"

BLOCK 5: utility 아닌 도메인 helper를 utility module에 배치
  → "V13a 표준으로 기존 sub-module에 추가 권고"

BLOCK 6: cross-crate struct dep (분리할 fn이 target crate 외부의 struct에 의존)  ★ impl-87
  → "분리 후보 fn이 target crate (예: operator-hud) 외부의 monolith-internal struct (예: bridgectl-internal SupervisorUnattendedCommandResult)를 인자로 받는 경우. target crate가 monolith를 역방향 의존할 수 없음 (workspace dep graph 역행 금지). 권고:
       (a) struct도 함께 target crate로 옮기기 (ops chain dep 분리 비용 평가 필요, PR-2 step 1b territory)
       (b) target crate에 trait 정의 + monolith struct가 trait impl (큰 변경)
       (c) 분리 후보 변경 — cross-crate struct dep 없는 다른 fn 우선"
  → Q5 정찰 시 struct 정의 위치 추가 검사 필수 (단순 'sub-module 호출 여부'만이 아니라 'struct 정의가 target crate 내부인가' 확인)

BLOCK 7: cross-crate function call dep (분리할 fn body가 target crate 외부의 monolith-internal fn을 호출)  ★ impl-93
  → "분리 후보 fn 시그니처는 primitive only (BLOCK 6 통과)지만 body가 호출하는 N+1개 fn 중 1+ 호출이 monolith-internal로 target crate 안에 분리되어 있지 않은 경우. chain된 monolith-internal fn 호출 = target crate가 monolith로 역방향 fn-call → workspace dep graph 위반. BLOCK 6 (struct dep)와 axis 다른 동형 케이스. 권고:
       (a) 호출되는 모든 sub-fn을 먼저 target crate로 옮기기 (chain 전체 이동 = bottom-up V13a multi-iteration 권장)
       (b) chain의 head fn만 분리 + 분리 안 된 sub-fn은 trait/callback으로 injection (큰 변경)
       (c) 분리 후보 변경 — chain head 미분리 fn 우선 처리 (1+ pure sub-fn 먼저)"
  → Q5c 정찰 시 body 안의 fn 호출 list 전수 조사 필수 (Grep `fn_name(` for each callee), target crate 안 또는 std/외부 dep으로 모두 cover 가능한지 확인

BLOCK 8: V19 후보 (구조적 결정 / ≥ 200 LOC / ≥ 5 functions) 진입 시 debate 사전 lock 누락  ★ impl-105
  → "후보가 module 경계 변경 / dep graph / naming convention / ≥ 200 LOC / ≥ 5 functions 영향이면서 `/harness-debate` 4-gen 수렴 (ontology_snapshot byte-identical) 없이 implementation 시도. CLAUDE.md DGE 3원칙 §1 위반 (Designer phase 건너뜀). 권고:
       (a) `/harness-debate <topic>` 호출 → Planner/Critic/Architect 4-gen 수렴 후 byte-identical implementation (V19 표준 path)
       (b) 변경이 V19 적용 조건 미달 (Critic이 attack할 hypothesis 없음, < 200 LOC, < 5 functions)이면 V13/V13a/V16/V17/V18로 재분류
       (c) 사용자가 명시적으로 debate 생략 결정 시 — commit message에 'debate-skip-rationale' 인용 필수 (audit gap 회피)"
  → Q0 (V19 사전 분기) 정찰 시 변경 nature 분석 필수 (module 경계 / dep graph / naming / LOC delta / function count). 일치 시 debate 사전 권고.

BLOCK 9: V20 후보의 외부 crate caller ≥ 2 (data-shape narrowing 적용 조건 위반)  ★ impl-144 / ★★ impl-148 sub-branch 정식 등록 (v14.17) / ★★★ impl-156 Stage 2 promotion (v14.19) / ★★★★ impl-164 Stage 3 자동화 hook 후보 promotion (v14.23)
  → "후보가 `pub field: String` + closed-set semantics이나 외부 crate caller ≥ 2 (in-workspace binary 1 초과). 모든 caller에 enum migration 강제 → medium 회귀 + caller signature drift 위험. **Sub-branch 분기 (v14.17 정식 등록 + v14.19 Stage 2 promotion + v14.23 Stage 3 자동화 hook 후보 promotion, impl-148 + impl-156 + impl-164 3회 evidence)**:
       (a) **V20 in-workspace multi-caller variant (sub-variation Stage 3 자동화 hook 후보 promotion, impl-148 1st + impl-156 2nd + impl-164 3rd)** — caller가 모두 in-workspace binary + 같은 atomic single commit 안에서 모두 migrate 가능 + workspace dep graph acyclic forward 유지 (orphan rule: binary-local `From<&LocalStruct>` for foreign enum) 시 V20 적용 가능. **세 path**:
          - **large structural scope (≥ 5 structs OR 3+ crates OR ≥ 80 caller sites)** → V19 path (`/harness-debate` 4-gen 수렴) 결합 필수 — impl-148 evidence (debate sid `debate-1778844941-40ce06`, canonical hash `8be7d91cc4a2`)
          - **mid scope (3 crates with boundary conversion + < 5 structs + < 80 caller sites)** → V20-only 가능 (V19 미사용) — impl-156 evidence (`8f25798` WorkerStageStatus, 3 crates: kha-core 정의 + bridgectl + discord-bridge / 2 internal struct fields / ~9 caller sites / 6 test fixtures; operator-hud는 boundary conversion `as_wire_str().to_string()`로 unchanged)
          - **smallest scope (2 binaries + kha-core boundary + ~5 caller sites + 0 test fixture changes)** → V20-only with minimal scaffolding — impl-164 evidence (`95c9a20` WorkerCircuitBreakerDecision, kha-core 정의 + bridgectl + discord-bridge, 2 internal struct fields, ~5 caller sites Display-only, V20 Unknown(String) absorbs PascalCase legacy sentinel `"ReviewRequired"` byte-identical via raw-pointer reuse — no test fixture changes needed)
          **Auto-detect Grep recipe sub-step (v14.23 Stage 3 promotion 권고)**: `Grep "circuit_breaker|status|verdict|kind|category|severity|priority|stage|phase|action|outcome|signal|trigger|reason|class|tier|mode|state|level|origin|source: String," in apps/*/src/main.rs` → struct field hits → cross-reference with `gateway-hub::pub(crate) enum SameName` (or kha-core public enum) for snake_case wire format → D2 audit (`Grep "\\.field_name\\b.*(==|!=|matches!|eq_ignore_ascii_case)"`) → if D2 clean and ≥2 in-workspace binaries hit, V20 multi-caller variant candidate.
          Sub-variation promotion threshold policy: main V20 lifecycle과 동일 (1회 후보 lock → 2회 정식 등록 → 3회 자동화 hook 후보 → 4회 zero-effort 검출). **현재 Stage 3 자동화 hook 후보 promotion (impl-148 + impl-156 + impl-164 3회 evidence)**. 4th evidence → Stage 4 zero-effort 검출 trigger.
       (b) caller가 cross-crate publisher API (workspace 외부에 노출되는 library struct) → V19 territory (debate 호출 필수, structural decision)
       (c) caller가 production 외부 client (workspace 밖) → V20 차단, semver-major release 필요 (별도 cycle)"
  → Q0' (V20 사전 분기) 정찰 시 외부 caller 정찰 필수 (`Grep("use <crate>::<Type>", path=workspace)`). 결과 0 또는 in-workspace 1 binary 또는 in-workspace N binary atomic migrate 가능 시 통과.

BLOCK 10: V20 후보에 strict enum (no Unknown) 또는 tagged-enum wrapper 시도  ★ impl-144
  → "후보가 `pub field: String` 변환이나 (a) `Unknown(String)` catch-all 생략하고 strict enum만 — legacy historic JSON deserialize fail 위험 (event-log/persistence corruption) (b) wire format을 tagged-enum (`{\"type\":\"Variant1\"}` 또는 `#[serde(tag = \"...\")]`)로 변경 — byte-identical 가드 위반, 모든 historic artifacts re-serialize 필요. 권고:
       (a) Unknown(String) catch-all + `From<String>` Unknown arm은 owned allocation 재활용 (raw-pointer 동일성 검증 test 필수)
       (b) custom Serialize/Deserialize 작성 — `serialize_str(self.as_wire_str())` + `String::deserialize` → `Self::from(raw)` 패턴 (impl-135/137/144 byte-equivalent)
       (c) 6 unit tests 전수 — 그 중 'parent struct end-to-end JSON byte-identical guard' (legacy String shape vs 새 enum shape 동일 wire) 필수"
  → V20 적용 시 template scaffolding 1:1 따르기. impl-135/impl-137/impl-144 commit에서 enum body + 6 trait impl + 6 tests pattern 복제.
```

**Evidence**:
- impl-87 (2026-05-13, BLOCK 6) — PR-2 step 1c-9 first-test 시 발견. `operator_hud_unattended_can_start(unattended: &SupervisorUnattendedCommandResult) -> bool`에서 struct가 bridgectl-internal로 확인 → 분리 BLOCK. 양방향 vision 3차 cycle의 첫 검증 결과 — detector self-test가 자체 BLOCK 누락을 발견하고 self-갱신 (메타 cycle 13회 ★).
- impl-93 (2026-05-14, BLOCK 7) — PR-2 step 1c-15 정찰 시 발견. `operator_hud_materialize_autopilot_prevention_chain_command(command, workspace_root, 5 bool)`는 primitive only 시그니처 (BLOCK 6 통과)지만 body가 4 cross-crate fn 호출 (`operator_hud_materialize_autopilot_prevention_{plan,handoff,promote,enable}` 모두 bridgectl-internal RepoLayout/WorkerFailureLearningConfig dep). 5 sub-call 중 1 (`materialize_failure_learning_decision`)만 operator-hud::autopilot으로 분리됨 → mixed-dep delegate. 분리 BLOCK. 양방향 vision 9차 cycle 검증 — detector self-test가 BLOCK 6의 axis-different 변형 (struct → function call)을 발견하고 self-갱신 (메타 cycle 16회 ★★).
- impl-105 (2026-05-14, BLOCK 8 + V19 entry) — PR-2 step 1b first-test 시 발견. RepoLayout/WorkerFailureLearningConfig + 9 prevention fns 한꺼번에 분리 후보로 등장 — 단일 V13a iter가 아닌 9 fns × 2 struct × cross-crate 결정 (kha-core vs bridgectl-internal vs operator-hud target 선택). debate scope = "PR-2 step 1b 분리 strategy", 4-gen 수렴 결과 D1=bridgectl-internal submodule (NOT kha-core, NOT operator-hud) — Critic gen 2 reframe ("external_caller_count=0 → shared crate inclusion test fail"). BLOCK 8 (debate 사전 lock 누락 시 V19 후보 차단)을 detector 자체에 추가 — 본 detector가 미래에 V19-적격 후보를 만나면 Q0 분기로 debate 권고. 양방향 vision 14차 cycle 검증 — detector self-test가 V19 abstraction layer 자체를 BLOCK matrix에 흡수 (메타 cycle 20회 ★★★).

## 자기-개선 loop

새 iter 발견 시 본 detector + abstraction-first.md catalog 동시 갱신 (메타 cycle 발화).

```
trigger: V13a iter ≥8 또는 V20+ 신규 변형 발견 또는 BLOCK 11+ 신규 발견 또는 V19/V20 추가 application 또는 V20 sub-variation (in-workspace multi-caller variant 등) 추가 evidence
action:
  1. PATTERNS-CATALOG.md에 새 entry 추가 (분석 폴더)
  2. abstraction-first.md skill 동기 (글로벌)
  3. 본 detector decision tree에 새 분기 추가
  4. evidence commit (메타 cycle ++)
```

V20 main lifecycle Stage 5 완주 (impl-147) + v14.15 recipe broadening 정식 적용 + v14.17 in-workspace multi-caller variant 정식 등록 (impl-148 1st) + v14.19 Stage 2 promotion (impl-156 2nd) + v14.23 Stage 3 자동화 hook 후보 promotion (impl-164 3rd, smallest multi-caller scope to date) 후 다음 cycle 후보:
- **V20 in-workspace multi-caller variant 4th evidence (Stage 3 → Stage 4 zero-effort 검출 trigger)**: impl-148 / impl-156 / impl-164 byte-equivalent template로 또 다른 in-workspace 2+ binary caller atomic migrate case 발견. v14.23 BLOCK 9 sub-branch (a)에 추가된 Grep recipe sub-step을 zero-effort 자동 매칭으로 검증할 첫 cycle 목표. 후보 priors: gateway-hub의 다른 wire 노출 enum (WorkerCodexGateVerdict N=2 약함, WorkerStageOperatorAction N=2 약함, WorkerMergeDecisionAction N=2 약함) 또는 bridgectl/discord-bridge 다른 status/kind/category field 정찰 — N≥3 corpus + 2+ binary 일치 필요.
- **V20 vanilla 10th evidence** (main lifecycle 추가 보강): v14.15 broadening 후 private struct private field 정찰 대상 포함 — discord-bridge / bridgectl / kha-core file-internal `#[derive(Serialize)]` struct 안 String field 정찰. 단일 binary scope만 가능 (multi-caller은 (a) sub-branch로 분리).
- V19 4th+ application: 또 다른 구조적 결정 발생 시 동일 path 적용. 적용 빈도 매트릭스 +1.
- BLOCK 11 후보 (미발견): V20 자동 발견 hook의 false positive — 의미 indicator 매칭 (status/kind/category 등)이지만 actual free-form 문자열 (open-set, event-log category 패턴). corpus 정찰 (Grep wire 값 distinct N) 결과 N ≥ 10 + prefix grouping (`gateway.worker.*` 등) 발견 → open-set 확정 → V20 차단

## Gotchas

### Q4 (name conflict)는 정찰 후 확인 필수
1차 시도에서 컴파일 fail → rename 정정. impl-80 패턴. 사전 정찰 권고:
```
Grep("fn <fn_name>\\b") → 같은 이름 fn 다수 발견 시 BLOCK
```

### Q1 (utility vs domain) 경계 모호 시
도메인 의미를 가진 helper (예: `parse_workspace_path`)는 utility처럼 보이지만 V13a 표준이 옳음. 판단 기준:
- utility: caller 어디서나 동일 의미로 사용 가능 (CLI args / paths / hash)
- domain: 특정 도메인 컨텍스트 필요 (workspace 정의가 도메인-specific)

### V13a-batch에 비-trivial 1개라도 끼면 무효
2 trivial + 1 비-trivial인 경우 분할: 2개는 V13a-batch, 1개는 V13a 표준 별도 iter.

### V16/V17/V18 매칭은 1차 fn 분리 시 무관
호모모피즘은 *2+번째* 동일 invariant sub-task에서 발화. 첫 번째 fn 분리는 V13a로 시작 후 두 번째에서 V16 호모모피즘 적용 가능.

## 도구 사용 패턴 (Harness)

- 후보 fn 정찰: `Grep("fn <pattern>", monolith.rs)` + `Read` 시그니처
- 같은 이름 fn conflict 확인: `Grep("fn <name>\\b", monolith.rs, count)` ≥ 2면 V13a-name-conflict
- 호출처 카운트: `Grep("<fn_name>\\(", monolith.rs, count)` → estimated cost
- 분리 후 검증: `Bash("cargo build && cargo test -p <crate>")` 회귀 0

## 짝 스킬 cross-reference

- `abstraction-first.md`: 변형 카탈로그 SSOT — 본 detector의 추천은 카탈로그 entry와 1:1 매칭
- `repeat-error-tracker.md`: E1 안티패턴 (monolith 내부 수정) + E8 (hook false positive) 회피 룰
- `iso25010-scoring.md`: 추천 후 28-sub 평가에 사용

## 미커밋 후보 (다음 iter 발견 시 추가)

- V13a iter 10 (미발견): generic trait extraction? lifetime-annotated borrow split? — 후보 lock 안 됨, 발견 시 본 detector 갱신
- V13a-dataclass-extract sub-variation: struct 분리 (현재는 V13a 표준에 포함, 별도 변형으로 등록할지 evidence 누적 후 결정)
- V19+ 신규 변형: 비-Rust 컨텍스트 (Python / TypeScript)에서 적용 시 발화 가능

## Evidence: iter 8/9/10 (impl-88/89/91, V13a 표준의 세 보조 lane)

iter 8 (`61bec96`) — 도메인 sub-module 신규: `materialize_promote_command`를 autopilot.rs 신규 module에 분리. V13a-utility-module과의 차이는 BLOCK 5 (utility 아닌 도메인 helper) — autopilot은 의미 컨텍스트 필요, cli_args는 언어-무관 utility.

iter 9 (`13cafef`) — same-module V16 호모모피즘 첫 적용: `materialize_failure_learning_decision`를 autopilot.rs에 추가, iter 8과 file shape / 시그니처 `(command: &str, allow: bool) -> String` / body pattern (`if condition then replace, else passthrough`) 완전 동형. V16의 일반 적용 (cross-module 또는 cross-sub-task)과 차이는 same module 안 (sub-task 동일 module 안 추가 fn) — 첫 검증.

iter 10 (`824ea42`) — 신규 skeleton + V13a-batch + category mix: `command_with_team` (builder) + `is_promote_renewal_command` (classifier) 2 trivial pure fn을 commands.rs 신규 sub-module에 batch. impl-73 (objective batch, 동일 카테고리 classifier 2개) 과 차이: **신규 skeleton + builder/classifier category mix**. V13a-batch 응집 조건이 (trivial + 외부 dep 0) 만으로 충분하고 의미 카테고리 동일은 필수 아님을 검증.

양방향 vision 4-7차 cycle: iter 8/9/10 = **3 consecutive first-pass clearance** (impl-87 detector self-갱신 후). detector longtail 효과 세 번 실증. 미발견 후보 (V13a-delegate-mixed) 다음 cycle 정찰 예정.
