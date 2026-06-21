---
name: abstraction-first
description: 신규 기능 추가 시 회귀 risk 0을 유지하는 19 변형 카탈로그 — example_project-analysis 103-step에서 51+ 검증된 abstraction-first 패턴. 새 모듈/crate + I/O 격리 + caller 시그니처 보존 + dense unit test로 monolith 진입 risk를 카탈로그 변형 또는 명시적 integration step으로 분류한다. V19 추가 후 design-locked implementation (CLAUDE.md DGE 직속)도 한 변형으로 cover.
keywords: [abstraction-first, pattern-catalog, regression-zero, atomic-save, adapter, helper-delegate, state-machine, homomorphism, monolith-risk, debate-locked-design, dge-workflow]
intent: [design, refactor, plan, regression-safe, codify-variation, dge-implementation]
phase: plan
min_score: 4
---

# Abstraction-First — 19-Variant Catalog

> **사용자 비전 (CLAUDE.md DGE 원칙 직속)**: "신규 기능을 추가할 때는 새 모듈로, 회귀 0으로, 한 세션에 closure로." V19 추가로 *구조적 변경* (모듈 경계 / dep graph)도 `/harness-debate` 4-gen 수렴 후 byte-identical implementation으로 카탈로그 안에 들어옴. 본 스킬은 그 원칙의 19 변형을 명문화한다.
>
> **본 스킬의 책임**: 새 sub-task 시작 시 의사결정 트리로 변형 선정. 적용 후 본 entry의 적용 빈도 갱신 (self-modification). repeat-error-tracker.md (negative space)와 짝.
>
> **검증 출처**: `/home/user/example_project-analysis/.claude/requirements/PATTERNS-CATALOG.md` (19 변형 / 62 applications, 103-step / 회귀 0). 외부 commit SHA가 evidence. V19 (debate-locked design implementation)는 CLAUDE.md DGE 3원칙 직접 코드화.

## 핵심 원칙 (4 조건)

신규 기능을 카탈로그 변형으로 인정받으려면 다음 4 조건 모두 만족:

1. **신규 모듈/crate**: 기존 파일 본문 수정 0. 기존 파일은 `pub mod` 한 줄 또는 `pub use` 추가만.
2. **I/O-free 또는 격리된 I/O**: pure types / pure functions / atomic save (`temp + rename`) / append-only (`Mutex<File>` 직렬화) / in-memory MIRROR.
3. **회귀 0**: 기존 caller 시그니처 변경 0. signature 변경이 필요하면 caller가 0인 경우만 허용.
4. **한 세션 closure**: dense unit test + 전체 회귀 통과 + commit + 분석 폴더 SSOT 갱신을 한 turn에 완료.

4 조건 중 하나라도 깨지면 **integration step** (회귀 risk medium 이상으로 승격). 본 카탈로그는 abstraction-first 변형만 다룬다 — integration step은 repeat-error-tracker.md E1 + Anti-pattern matrix가 owner.

## 의사결정 트리 (적용 순서)

새 sub-task 시작 시 다음 순서로 매칭:

1. **신규 record 단위 저장 필요?**
   - id별 1 파일 + UPSERT 의미 → **V2 atomic save** (이전 V2 적용 있으면 **V16 호모모피즘**)
   - 단조 증가 event log → **V1 append-only**
2. **신규 enum variant 추가 (parser fall-through 가능)?** → **V3 enum extension**
3. **기존 trait 위에 부수 효과 (예: persist after mutation)?** → **V4 adapter wiring**
4. **provider/runtime에 default Store 필요?** → **V5 noop + factory**
5. **기존 메서드의 return을 확장하고 싶음?**
   - 별도 메서드 (caller 0 변경) → **V6 별도 메서드 + pure helper**
   - 같은 메서드 + helper 분리 → **V7 helper + delegate** (byte-identical guard test)
6. **streaming/incremental input fold?** → **V8 stateful event folder** (monotonic max)
7. **상태 머신 (lease / retry / quarantine 등)?** → **V10 state machine** (total transitions + panic 0 + serde round-trip)
8. **외부 event-pipeline subscription 전 contract lock?** → **V11 event contract + pure converter**
9. **scheduler tick loop fire-history tracking?** → **V12 fire-history pure state**
10. **복잡한 알고리즘?**
    - 작은 spec subset만 → **V13 minimal viable pure function**
    - sub-module이 internal dep chain — 한 번에 분리 불가 → **V13a multi-iteration minimal viable** (각 iteration 별 외부 dep 0 fn만 추가)
        - 같은 iter에서 trivial fn (≤ 5 LOC body, 외부 dep 0) 다수 발견 → **V13a-batch batch trivial sub-variation** (single iter에 N fn batch)
        - 분리할 fn이 기존 sub-module의 응집과 무관한 utility (CLI args / paths / hash 등) + 함수명 conflict 0 → **V13a-utility-module utility module 신규 sub-variation** (새 module + use 1 라인만, replace_all 불필요)
        - 분리할 fn 이름이 monolith 내부 다른 함수 (특히 1-arg overload)와 conflict 발생 → **V13a-name-conflict name conflict patch sub-variation** (rename + full-signature replace_all)
    - 외부 crate 회피 필요 + PD reference 존재 → **V14 zero-dep pure rust** (Howard Hinnant 등)
    - 표준 spec이 multi-field matching (POSIX cron(8) 등) → **V15 calendar OR semantics**
11. **silent fail audit gap fix?** → **V9 silent → explicit logging** (시스템 점수 직접 unlock 가능)
12. **구조적 결정 (모듈 경계 / dep graph / naming convention) + ≥ 200 LOC 또는 ≥ 5 functions 영향?** → **V19 debate-locked design implementation** (`/harness-debate` 4-gen 수렴 → byte-identical implementation; CLAUDE.md DGE 3원칙 직속). V13/V13a small-scope과 차이 — large structural scope. debate scope 안에 V13a/V16/V17이 implementation 방식으로 포함될 수 있음
13. **기존 `String` field가 closed-set 의미 + 외부 caller 0 또는 in-workspace N caller (atomic single commit migrate 가능) + legacy wire format 호환 필수?** → **V20 data-shape narrowing** (open String → closed enum + `Unknown(String)` catch-all + custom serde byte-identical). ※ **자동화 hook 완성 + in-workspace multi-caller variant Stage 2 정식 등록 + vanilla 7th PascalCase 첫 evidence (impl-135 + impl-137 + impl-144 + impl-147 + impl-148 + impl-156 + impl-158 7회 evidence ★★★★★, Stage 5 자동 발견 zero-effort 검출 + sub-variation Stage 2 promotion + main lifecycle 보강)**. **Wire format 다양화**: snake_case (impl-135/144/147/148/156) + kebab-case (impl-135 variant) + lowercase 평문 (impl-137) + **PascalCase (impl-158, 기본 serde no rename_all)** — V20 byte-identical 보존 invariant은 wire format에 종속적이지 않음. CLAUDE.md §3 "4회 누적 Stage 5 자동 발견" 도달 + pattern-auto-detector V20 detector path 정식 hook 등록 (`0a71b1f` impl-146) + impl-147 (`f4b3c3e`) zero-effort 검출 first evidence + v14.15 recipe step 1 scope broadening 정식 적용 + **v14.17 in-workspace multi-caller variant 정식 등록** (impl-148 `a1aa7d7`, debate sid `debate-1778844941-40ce06` 4-gen 수렴, DGE 원칙 §1 4번째 실증 ★★★★★, V19 path 결합) + BLOCK 9 sub-branch 등록 (외부 caller ≥ 2일 때 (a) in-workspace atomic → multi-caller variant / (b) cross-crate publisher → V19 / (c) production 외부 → semver-major). V20 lifecycle 완주 (Stage 1~5) + sub-variation Stage 1 lock. **Sub-variation promotion threshold policy**: main lifecycle과 동일. **large structural scope (≥ 5 structs / 3+ crates / ≥ 80 caller sites) 시 V19 path 결합 필수**.
14. **위 중 어느 것도 안 맞고 기존 코드를 수정해야 함** → **integration step** (본 카탈로그 범위 외, repeat-error-tracker E1 적용)

## 패턴 lifecycle protocol (CLAUDE.md self-improvement loop §3 운용 매뉴얼)

> CLAUDE.md `self-improvement loop §3` "1회 evidence는 후보 lock, 2회 누적 시 정식 등록, 3회 누적 시 자동화/hook"의 **실 운용 단계**. V19 / V20 발견 → 정식 승격 → 자동화 hook 승급 evidence (`example_project-analysis` impl-107 / impl-130 / impl-134 / impl-136 / impl-138)로 검증.

### Stage 1 — 후보 lock (1회 evidence)

새로운 abstraction-first 변형으로 보이는 commit이 1회 발화하면:

1. **분석 SSOT (PATTERNS-CATALOG.md)**: V{N} entry 신규 추가, header에 **`(후보 lock)`** 명시 + `> ⚠️ 후보 lock 단계` callout
2. **글로벌 SSOT (본 파일)**: 같은 entry 동기, header `V{N} (후보 lock) ...` 명시
3. **의사결정 트리에 분기 신규** — 단 "후보 lock, 1회" 명시
4. **적용 빈도 매트릭스에 row 추가** (count = 1)
5. **2번째 evidence 후보 정찰 위임** — HANDOFF에 "다음 evidence 후보" 명시 (예: "discord-bridge ChannelKind / DiscordCommand kind / autopilot decision verdict / cron job priority 등")
6. 외부 코드 변경 0 (메타 cycle만, 분석 + 글로벌 commit 2개)

### Stage 2 — 정식 등록 (2회 evidence)

2번째 evidence 발화 (자율 또는 명시 사냥) 시:

1. **분석 SSOT**: V{N} entry header `(후보 lock)` 표시 제거 + `(정식 등록 — 2회 evidence)` 명시 + callout 갱신 (✅ 정식 등록 단계)
2. **글로벌 SSOT**: 같은 entry 동기 + evidence 2 신규 row 추가 (Evidence 1 / Evidence 2 분리 기술)
3. **의사결정 트리에 분기 갱신** — "정식 등록, 2회 누적, 3회 시 자동화 hook 승급" 명시
4. **적용 빈도 매트릭스 row 갱신** (count: 1 → 2, "(정식 등록)" 표기)
5. **shapes 카운트 +1** (후보 lock 단계는 shapes에 미포함, 정식 등록 시 정식 shape 1개로 진입)
6. **3번째 evidence 사냥 위임** — HANDOFF에 "3회 evidence 시 자동화 hook 승급" 명시
7. 외부 코드 변경 0 (메타 cycle만)

### Stage 3 — 자동화 hook 승급 (3회 evidence)

3번째 evidence 발화 시:

1. **`pattern-auto-detector.md`에 V{N} detector path 정식 hook** — UserPromptSubmit 또는 PostToolUse hook에서 자동 detect + 권고 advisory 발화
2. **분석 SSOT**: V{N} entry에 `★ 자동화 hook 승급` 마크 + auto-detect 조건 명시
3. **글로벌 SSOT**: 같은 동기 + `pattern-auto-detector.md` cross-ref 추가
4. **CLAUDE.md self-improvement loop §3 cycle 종결** (해당 패턴의 lifecycle 완성)

### Stage 0 — 정식 등록 후 양산 (4회+ evidence)

자동화 hook 승급 후 추가 evidence는 적용 빈도 매트릭스에만 row count +1 (별도 stage 발화 없음). 단 anti-pattern 신규 발견 시 entry의 Anti-pattern section에 추가.

### Sub-variation lifecycle policy (v14.17 정식 등록, impl-148 trigger)

> 메인 패턴 V{N}이 Stage 5 자동 발견 zero-effort 검출에 도달한 이후, 적용 조건 완화 또는 scope 확장으로 새 sub-variation이 발견되는 경우의 promotion threshold policy.

**원칙**: Sub-variation은 main lifecycle (Stage 1~5)과 **동일한 promotion threshold policy** 채택. main lifecycle을 통과한 패턴이라도, sub-variation은 독립적으로 1회 lock → 2회 정식 등록 → 3회 자동화 hook 후보 → 4회 zero-effort 검출 단계를 거친다.

**이유**:
1. Sub-variation은 main의 적용 조건 (일부) 완화이므로, **새로운 회귀 risk 축**이 등장 (예: in-workspace multi-caller는 atomic commit / orphan rules / dep graph acyclic forward 같은 새 invariant 발화). 1회 evidence만으로 main 수준 자동 hook 권고는 위험.
2. Sub-variation 누적 evidence가 main의 byte-equivalent template를 그대로 재사용하는지 (impl-148이 impl-135/137/144/147 byte-equivalent로 6 trait impls + 6 unit tests + Unknown(String) catch-all 재사용함을 확인) — main lifecycle 안의 stage progression이 sub-variation의 progression과 분리되어야 trace 가능.
3. **Main shape vs sub-variation shape**: sub-variation은 main shape 내부의 적용 조건 완화이므로 shapes 카운트에 별도 추가하지 않는다 (main shape는 sub-variation을 invariant-preserving 확장으로 포함). 단 자동화 hook 등록 시 detector path BLOCK 분기 sub-branch (예: BLOCK 9 sub-branch) 등록 필수.

**Sub-variation 등록 의무**:
1. **PATTERNS-CATALOG.md (분석 SSOT)** V{N} entry에 Evidence M entry + sub-variation 명시 row 추가
2. **abstraction-first.md (글로벌 SSOT)** V{N} entry에 evidence entry + sub-variation 적용 조건 sub-section 추가 (visible bullet list)
3. **pattern-auto-detector.md (글로벌 SSOT)** V{N} detector path BLOCK 분기 sub-branch 등록 (현재 BLOCK이 cover 못 하는 경계 case 명시) + 적용 조건 완화 명시 + Auto-detect Grep recipes에 sub-variation 분기 추가 (필요 시)
4. **자기-개선 loop trigger 갱신**: sub-variation 추가 evidence를 trigger 항목에 추가

**Evidence**: V20 in-workspace multi-caller variant — main V20 (Stage 5 완주 `f4b3c3e` impl-147) 이후 sub-variation 3회 누적 자동화 hook 후보 promotion 도달:
- **1st evidence (Stage 1 후보 lock)**: impl-148 (`a1aa7d7` `kha-core::UnattendedHealthStatus`, debate sid `debate-1778844941-40ce06` V19 path 결합 large scope: 5 structs / 3 crates / ~80 caller sites)
- **2nd evidence (Stage 2 정식 등록 promotion)**: impl-156 (`8f25798` `kha-core::WorkerStageStatus`, V20-only path mid scope: 3 crates with boundary conversion / 2 internal struct fields / ~9 caller sites + 6 test fixtures, operator-hud는 `as_wire_str().to_string()`로 unchanged)
- **3rd evidence (Stage 3 자동화 hook 후보 promotion)**: impl-164 (`95c9a20` `kha-core::WorkerCircuitBreakerDecision`, V20-only path smallest scope to date: 2 binaries (bridgectl + discord-bridge) + kha-core boundary / 2 internal struct fields / ~5 caller sites / 0 test fixture changes — Unknown(String) absorbs PascalCase legacy sentinel `"ReviewRequired"` byte-identical via raw-pointer reuse)

적용 조건 (3) "외부 caller 0 또는 in-workspace 1 binary" → "외부 caller 0 또는 in-workspace **N** binary (atomic single commit migrate 가능)" 완화. 새 invariant 5종 (atomic commit / orphan rules / dep graph acyclic / tolerant-comparison audit / **empty-string byte-identical preservation via `Unknown(String::new())` init**) 등장. **세 path 분기 (v14.23 자동화 hook 후보 promotion)**: large structural scope (≥ 5 structs OR 3+ crates OR ≥ 80 caller sites) → V19 path 결합 필수 (impl-148); mid scope (3 crates / ~10 caller sites) → V20-only 가능 (impl-156); smallest scope (2 binaries + kha-core boundary / ~5 caller sites / D2 audit clean) → V20-only with minimal scaffolding (impl-164). **Stage 4 zero-effort 검출 trigger**: 다음 4th evidence는 detector path가 multi-caller variant를 zero-effort 자동 매칭하는 시나리오 검증 — pattern-auto-detector BLOCK 9 sub-branch (a)에 Grep recipe sub-step 추가 권고 (`Grep "String type field" in apps/*/src/main.rs → cross-reference gateway-hub::pub(crate) enum same name`).

## Lifecycle 의무 cross-ref

- 본 lifecycle protocol을 따르지 않으면 evidence 누적이 자동화 hook으로 못 가서 자기-개선 loop이 끊긴다 (메타 cycle 가치 0).
- `example_project-analysis` evidence: impl-107 (V19 Stage 1) → impl-130 + impl-134 (V19 Stage 2 도달 후 추가 evidence) / impl-136 (V20 Stage 1) → impl-138 (V20 Stage 2 도달).
- 3회 evidence 도달 시 반드시 Stage 3 진입 — 잊으면 자동화 가치 망실.

## 변형 카탈로그 (V1 ~ V19)

### V1 Append-only I/O 격리
- **시그니처**: `struct Store { file: Mutex<File>, mirror: Vec<T> }` + `append(&self, record: &T)`
- **적용 조건**: 단조 증가만 하는 record 스트림 (token usage event log 등)
- **회귀 risk**: 0 (신규 모듈)
- **재사용 cost**: ~200 LOC + 8 tests
- **핵심 invariant**: append-only — 기존 line 변경 0, file lock으로 동시 write 직렬화
- **evidence**: `532ccf5` JsonlTokenUsageStore (PR-4 step 2)

### V2 Atomic save (temp + rename) ★ 3회 적용
- **시그니처**: `trait Store { save(&self, &record); load_all() -> Vec<T> }` + `JsonStore` + `InMemoryStore` impls
- **적용 조건**: UPSERT 의미의 record (id별 1 파일, 부분 write 회피 필수)
- **회귀 risk**: 0 (신규 모듈)
- **재사용 cost**: 250~430 LOC + 13~18 tests
- **핵심 invariant**:
  - `std::fs::write(temp); std::fs::rename(temp, final)` 원자성 (Windows ReplaceFileW 2018+로 overwrite 안전)
  - path-traversal 4 패턴 (`/`, `\`, `..`, `MAIN_SEPARATOR`) + empty 거부
  - envelope v1 + `schema_version != 1` reject
- **evidence**: `4ba59d1` JsonLearningsStore, `3ad8c7e` JsonCandidateStore, `b01812b` JsonJobStore

### V3 Enum variant 확장 (parser fall-through)
- **시그니처**: 기존 enum에 신규 variant + 신규 parser branch — 기존 match arm 영향 0
- **적용 조건**: parser fall-through 가능 구조 (regex 우선순위 / peg ordered alternatives)
- **회귀 risk**: 0 (기존 match exhaustive 유지)
- **재사용 cost**: ~89 LOC + 18 tests
- **핵심 invariant**: 기존 variant serde 표현 변경 0; 신규의 single-value 케이스는 기존 variant로 collapse
- **evidence**: `fe5f04f` Range/List + monthly + 12-hour (PR-8 step 2)

### V4 Adapter wiring (compose 2 traits)
- **시그니처**: `struct Adapter<A, B> { inner: A, side: B }` + `impl A_trait for Adapter` (delegates + side-effect)
- **적용 조건**: 기존 trait 구현 위에 best-effort 부수 효과 (예: 모든 mutation 후 save)
- **회귀 risk**: 0 (caller가 inner trait spec을 그대로 받음)
- **재사용 cost**: ~313 LOC + 6 tests
- **핵심 invariant**: side error는 inner 결과를 막지 않음 (best-effort); inner의 모든 메서드 명시적 delegate
- **evidence**: `a6b620c` PersistingPreferenceObserver (PR-9 step 3b)

### V5 Noop default + factory selector
- **시그니처**: `enum FactoryError`, `struct NoopStore` (do-nothing impl), `fn resolve_store(opt: Option<&str>) -> Arc<dyn Store>`
- **적용 조건**: provider/runtime이 store를 require하지만 impl 존재 여부와 분리된 경우
- **회귀 risk**: 0 (default = NoopStore로 caller 영향 0)
- **재사용 cost**: ~305 LOC + 12 tests
- **핵심 invariant**: NoopStore는 모든 메서드를 `Ok(())` 또는 `Ok(Vec::new())`로; factory가 unsafe env mutation 없이 path 결정
- **evidence**: `571a4c6` NoopTokenUsageStore + token_usage_factory (PR-4 step 2.5)

### V6 별도 메서드 추가 + pure helper 모듈
- **시그니처**: 기존 `fn old(&self, ...)` 그대로 + 신규 `fn new_with_capture(&self, ...) -> NewResult` 별도 메서드 + helper 모듈 분리
- **적용 조건**: 기존 메서드 return type을 확장하고 싶지만 caller breakage 없이
- **회귀 risk**: 0 (기존 메서드 unchanged)
- **재사용 cost**: ~190 LOC + 6 tests + caller 0 변경
- **핵심 invariant**: 신규 메서드만 추가 정보 반환; 기존 메서드는 신규의 fall-back에 위임 가능 (또는 독립 path 유지)
- **evidence**: `b0cb71e` send_message_with_usage_capture + make_usage_record (PR-4 step 3)

### V7 Helper 분리 + delegate refactor
- **시그니처**: 기존 `fn original(&Body) -> Record`을 `fn from_parts(field1, field2, ...) -> Record`으로 분리 + 기존 함수는 위임
- **적용 조건**: helper에 streaming/incremental 입력을 보내야 할 때 (기존 single-shot 호출자도 보존)
- **회귀 risk**: 0 (byte-identical equivalence guard test로 검증)
- **재사용 cost**: ~100 LOC delta + 1 byte-identical guard test
- **핵심 invariant**: guard test `from_parts(unpack(body)) == original(&body)` 모든 케이스
- **evidence**: `5bbebfc` make_usage_record_from_parts (PR-4 step 4a)

### V8 Stateful event folder (monotonic max)
- **시그니처**: `struct Accumulator { ... }` + `fn observe(&mut self, event)` + `fn snapshot(&self) -> Option<Record>`
- **적용 조건**: event stream을 누적 record로 fold — duplicate event 안전 (max merge)
- **회귀 risk**: 0 (신규 모듈, fold logic은 byte-identical to from_parts)
- **재사용 cost**: ~340 LOC + 8 tests
- **핵심 invariant**: monotonic max merge — 동일 token에 대한 두 번째 event는 `max(prev, new)` 적용 (proxy resend 안전)
- **evidence**: `831f713` StreamUsageAccumulator (PR-4 step 4a-bridge)

### V9 Silent → explicit logging
- **시그니처**: 기존 loop을 `for (i, item) in enumerated()` + `match outcome { Ok => ..., Err => eprintln!("..."); }`; pure types만 신규 모듈
- **적용 조건**: 기존 silent fail이 system metric에 outlier로 반영 (audit gap fix)
- **회귀 risk**: low (기존 동작 표면 변화: stderr line 추가만 — STDOUT 그대로)
- **재사용 cost**: ~85 LOC pure types + 5 tests + main.rs 2 small Edit
- **핵심 invariant**: pure types만 신규; main.rs 변경은 reversible. **시스템 점수 직접 unlock 가능** (검증 점수에 silent fail이 outlier로 잡혀있을 때)
- **evidence**: `3acb3bb` ChunkSendProgress + main.rs 2 site (D1 fix, 시스템 점수 4.555 → 4.557)

### V10 State machine (total transitions)
- **시그니처**: `enum State`, `enum Outcome`, `impl State { fn transition_a(&mut self, ...) -> Result<_, Error>; ... }` — 모든 `(state, event)` defined
- **적용 조건**: 상태 머신을 운영해야 하나 panic 0을 보장하고 싶음 (lease/retry/quarantine 등)
- **회귀 risk**: 0 (신규 모듈)
- **재사용 cost**: ~340 LOC + 17 tests
- **핵심 invariant**: total transitions (panic 0); monotonic clamp for backwards-time; serde round-trip 명시
- **evidence**: `989cf2e` JobLease + JobState + 4 transitions (PR-8 step 3 sub-task)

### V11 Event contract + pure converter ★ 2회 적용
- **시그니처**: `struct Event { ... N 카테고리 denormalized Option 필드 }` + `fn extract_evidence(&self) -> Vec<Evidence>` + `fn apply_to_observer(event, &dyn Trait) -> Result<usize, Error>`
- **적용 조건**: 외부 event-pipeline subscription 전 payload contract + matching rule lock; 또는 pretty-print multi-line JSON parse (best-effort)
- **회귀 risk**: 0 (caller 0)
- **재사용 cost**: ~345 LOC + 15 tests
- **핵심 invariant**: denormalized N-slot `Option<_>` 필드 — 컴파일러가 missing category 발견; deterministic transform; best-effort glue (first error → early return + 부분 적용 보존)
- **evidence**: `e968d1a` SessionUpsertedEvent (D6 contract lock), `7f577fa` SessionEventBuilder + AllsolutionDigest (안티패턴 회피 변형), `a6c1c2b` parse_apply_user_preference_output (multi-line JSON best-effort)

### V12 Fire-history pure state
- **시그니처**: `struct State { last_at: Option<u64>, planned_next: Option<u64>, count: u64, missed: u64 }` + `Self → Self` transitions + 3 query methods
- **적용 조건**: scheduler tick loop이 fire history를 tracking — backwards 시계 안전 + saturating counters
- **회귀 risk**: 0 (신규 모듈, lease와 독립 pair)
- **재사용 cost**: ~250 LOC + 18 tests
- **핵심 invariant**: monotonic-max clamp; saturating_add/sub로 overflow + panic 0; idle 정의 unambiguous (never fired AND no plan)
- **evidence**: `28ac4a1` TickerState (PR-8 step 3 sub-task 2)

### V13 Minimal viable pure function
- **시그니처**: `fn evaluate(input: &Input, after: u64, horizon: u64) -> Option<u64>` + brute-force minute scan + `checked_add` overflow safety
- **적용 조건**: full implementation이 큰 dependency 또는 복잡한 알고리즘 필요할 때 — minimal viable로 lock하고 후속에서 확장
- **회귀 risk**: 0 (caller 0)
- **재사용 cost**: ~320 LOC + 20 tests
- **핵심 invariant**: strict-after semantics (exact-on input은 skip — supervisor loop 무한 회피); near-`u64::MAX` overflow safe; `Step(0)` modulo-by-zero panic 0
- **evidence**: `340f33d` next_fire_within UTC minimal (PR-8 step 3 sub-task 3)

### V13a Multi-iteration minimal viable (점진 sub-module 성장)
- **시그니처**: sub-module skeleton + **외부 dep 0 pure fn 1개로 시작** → 의존하는 다른 sub-module 분리 후 차례로 fn 추가 (multi-pass refinement)
- **적용 조건**: helper 그룹이 internal dep chain을 가져 한 번에 분리 불가 — 점진적 sub-module 성장
- **회귀 risk**: 0 (각 iteration 별 회귀 0)
- **재사용 cost**: 첫 iteration ~40 LOC + 6 tests, 후속 iteration 별 ~50~150 LOC 추가
- **핵심 invariant**: 각 iteration 별 (1) cargo build PASS (2) cargo test 회귀 0 (3) 외부 dep 명시적으로 surface
- **V13과 차이**: V13은 single-pass minimal viable, V13a는 **multi-pass refinement** (sub-module 점진 성장 패턴)
- **evidence**: iter 1 (`8288fcd` refresh.rs pure 38 LOC) / iter 2 (`3a315a3` objective.rs 220 LOC) / iter 3 (`e5cdf83` refresh cross-module 45 LOC ★) / iter 4 (`5a98363` objective batch trivial 2 fn 5 LOC body ★) / iter 5 (`a77d706` objective ergonomic builder 17 LOC `impl Into<String>`) / iter 6 (`149813a` cli_args utility-module 신규 3 LOC ★) / iter 7 (`0823d29` cli_args name-conflict patch 10 LOC ★) / iter 8 (`61bec96` autopilot.rs 도메인 sub-module 신규 15 LOC ★) / iter 9 (`13cafef` autopilot.rs V16 동형 22 LOC — same-module 호모모피즘 첫 ★) / iter 10 (`824ea42` commands.rs batch + category mix builder+classifier — 신규 skeleton + V13a-batch 2번째 ★) / iter 11 (`a73ce49` cli_args utility batch command_arg + append_command_flag 14 LOC — V13a-batch 3번째 + V13a-utility-module 2번째 + BLOCK 7 unblock 첫 evidence ★) / iter 13 (`b0cf8d1` autopilot.rs `materialize_handoff_branch` 15 LOC — same-module 도메인 성장 3번째 fn, BLOCK 7 chain dep 추가 감쇄 ★) — iter 12는 impl-100 정찰 BLOCK 6 발화로 skip

### V13a-batch Batch trivial sub-variation (impl-75 등록)
- **시그니처**: V13a iteration 안에서 여러 trivial fn (≤ 5 LOC body, 외부 dep 0, primitive only)을 single iter에 batch 분리
- **적용 조건**: sub-module에 이미 1개 이상 fn 있음 + 새 fn들이 모두 trivial + dep chain unblock 발생 안 함
- **회귀 risk**: 0 (trivial이므로 단위 검증 불필요, 컴파일 PASS = 정확성 보장)
- **재사용 cost**: iter 1 비용의 ~10% (skeleton 재사용, 단순 fn append)
- **핵심 invariant**: fn 본문 ≤ 5 LOC body each + 외부 dep 0 + cfg(test) tests 신규 추가 선택 (trivial은 compile-time 검증만으로 충분)
- **V13a과 차이**: V13a 표준 1 fn/iter, **V13a-batch N fn/iter** (trivial 경우만)
- **anti-pattern**: trivial이 아닌 fn (≥ 30 LOC, 외부 dep 있음)을 batch에 포함하면 V13a 표준으로 회귀 — 별도 iter로 분리
- **evidence**: `5a98363` operator-hud::objective batch iter 4 (top_level_ready + is_monitor_command, PR-2 step 1c-5)

### V13a-utility-module Utility module 신규 sub-variation (impl-79 등록)
- **시그니처**: 분리할 함수가 기존 crate의 어느 sub-module에도 자연스럽게 속하지 않는 **언어 무관 utility (CLI args / OsString / path 등)**일 때 **새 module을 crate에 신규로 만들고** pub fn 1개로 시작
- **적용 조건**: (1) 분리할 fn이 기존 sub-module의 의미적 응집과 무관 (2) 외부 dep 0 또는 std only (3) 함수명을 분리 후에도 그대로 사용 가능 (rename 불필요)
- **회귀 risk**: 0 (신규 module, caller 0 변경 — 함수명 동일 시 use 1 라인만 추가하면 호출처 전체 cover)
- **재사용 cost**: ~10 LOC (skeleton + 1 fn) + 1-2 cfg(test) tests + caller 0
- **핵심 invariant**: 새 module이 의미적으로 응집된 utility 카테고리 (cli_args, paths, hash 등) + 함수명 conflict 0 + use 갱신 외 모든 호출 코드 byte-identical
- **V13a과 차이**: V13a 표준은 기존 sub-module에 fn 추가, **V13a-utility-module은 새 module 신규** (응집과 무관한 utility). replace_all 불필요 (use 1 라인만)
- **anti-pattern**: utility가 아닌 비즈니스 로직 (도메인 의미가 있는 helper)을 utility module에 두면 응집 깨짐 — 기존 sub-module에 V13a 표준으로 분리
- **evidence**: `149813a` operator-hud `cli_args` module 신규 + `push_workspace_arg` 3 LOC pure utility, 21 호출처 byte-identical (PR-2 step 1c-8)

### V13a-name-conflict Name conflict patch sub-variation (impl-80 등록)
- **시그니처**: 분리할 함수명이 monolith 내부 다른 함수 (특히 1-arg overload)와 conflict 발생 → 분리 함수를 의미가 더 구체적인 새 이름으로 rename + replace_all pattern을 **full call signature** (인자 첫 문자 포함)로 구성하여 1-arg overload 호출과 정확히 구분
- **적용 조건**: monolith가 같은 함수명을 다른 시그니처로 이미 사용 (e.g., 1-arg overload 존재) + 분리할 fn은 2-arg / 다른 시그니처
- **회귀 risk**: 0 (rename + full-signature replace_all — overload 호출 영향 0)
- **재사용 cost**: ~15 LOC (rename 1 fn + replace_all N 사이트) + 정찰-fix 1회 turnaround (1차 컴파일 fail → rename)
- **핵심 invariant**: (1) rename 후 새 이름은 의미적으로 더 구체적 (예: `command_arg` → `flag_value` — 인자 `flag`를 받아 `value`를 반환) (2) replace_all pattern을 **full call signature `name(arg_first_chars,`** 으로 잡아 overload와 정확히 구분 (3) 1차 컴파일 fail은 정찰-fix 1회 turnaround로 정정 (rollback 불필요)
- **V13a-utility-module과 차이**: V13a-utility-module은 함수명 conflict 0, **V13a-name-conflict는 함수명 conflict 발생** → rename + full-signature replace_all
- **anti-pattern**: placeholder rename (`_*_removed` 같은 임시 이름으로 함수 정의 유지) — V13a 컨벤션은 full deletion이 정석. placeholder는 즉시 정정
- **evidence**: `0823d29` operator-hud cli_args `command_arg` → `flag_value` rename, replace_all pattern `command_arg(command,` full signature로 26 사이트 갱신, bridgectl 1-arg `command_arg(value)` 영향 0 (PR-2 step 1c-10)

### V14 Zero-dep pure rust algorithm
- **시그니처**: 외부 crate 없이 std arithmetic만 사용하는 ~30-60 LOC core function (Howard Hinnant 등 PD reference)
- **적용 조건**: chrono/regex 같은 큰 crate가 과도할 때, public-domain 알고리즘이 존재하는 경우
- **회귀 risk**: 0 (caller 0)
- **재사용 cost**: ~175 LOC + 16 tests (property-based round-trip 포함)
- **핵심 invariant**: std arithmetic only (no `f64`, no panic, no I/O); license = PD (출처 명시 필수); property test로 algorithm 정확성 강한 보장
- **evidence**: `7276e21` civil_date + days_from_civil + civil_from_days + weekday_from_days (PR-8 step 3 sub-task 3.5)

### V15 Calendar OR semantics
- **시그니처**: `fn calendar_matches(expr, dom, month, dow) -> bool` + dom + dow 모두 restricted면 OR, 둘 중 하나 Star이면 다른 쪽만 평가
- **적용 조건**: POSIX cron(8)처럼 표준 spec이 OR semantics를 요구하는 multi-field matching
- **회귀 risk**: 0 (caller 0)
- **재사용 cost**: ~30 LOC delta + 5 신규 calendar tests
- **핵심 invariant**: spec 인용 명시 (cron(8) man page); 모든 4 조합 (dom_star + dow_star, dom_star + dow_restricted, dom_restricted + dow_star, both restricted)을 explicitly 분기
- **evidence**: `7276e21` next_fire_within extension (PR-8 step 3 sub-task 3.5)

### V16 검증된 패턴 의도적 동형 재사용 (full 호모모피즘) ★ 5회 적용
- **시그니처**: 이전 sub-task의 V1~V15 중 하나를 새 도메인에 file-diff로 검증 가능한 정도로 동형 적용 (shape 완전 일치 — code-to-code, frontmatter + 시그니처 + 본문 모두 동형). V19 (debate-locked design implementation)에서도 implementation 방식으로 채용 가능
- **적용 조건**: 새 도메인이 이전 sub-task와 동일한 invariant 요구 (예: id-keyed atomic save, 같은 submodule 확장) — reviewer가 file-diff로 "same approach" 검증 가능
- **회귀 risk**: 0 (신규 모듈 또는 기존 submodule 확장 + 검증된 shape)
- **재사용 cost**: 80~430 LOC + 0~18 tests (이전 sub-task의 80~90% 코드 재사용; submodule 확장 변형은 더 저렴)
- **핵심 invariant**: 의도적 동형 — commit message에 "homomorphic to previous" 명시; envelope versioning은 evolution risk에 비례하여 borrow/skip 결정
- **evidence**: `3ad8c7e` JsonCandidateStore (V2 2번째), `b01812b` JsonJobStore (V2 3번째), `408296b` D4c reset-user-model (D4b 4-site shape homomorphism), `13cafef` autopilot.rs `materialize_failure_learning_decision` (iter 8 ↔ iter 9 same-module 호모모피즘 첫 in-module), `1d86a57` autopilot_prevention.rs +6 fns extension (impl-108 V19-followup, impl-105 a119680 동형: 같은 파일/같은 naming convention/같은 visibility pub(crate)/같은 dep graph/같은 atomic commit shape, main.rs -82 LOC + 169/169+38/38+95/95 회귀 0)

### V17 Partial 호모모피즘 (template / data shape) ★ 4회 적용
- **시그니처**: 이전 sub-task의 V1~V16 패턴 중 본문 구조 / 출처 인용 / 짝 스킬 cross-reference만 동형 채용하고 frontmatter / 시그니처 prefix 등 shape-specific 부분은 생략한 partial 동형
- **적용 조건**: shape-specific 제약 (template은 frontmatter 없음, data는 markdown 아닌 JSON 등)으로 full V16 동형 불가하나 본문 구조 / 출처 / cross-reference 동형은 가능한 경우
- **회귀 risk**: 0 (template/data 파일 — 코드 caller 0)
- **재사용 cost**: 500~800 LOC (template 본문 채우기 + 짝 스킬 link만) + 0 tests
- **핵심 invariant**: partial 동형 — commit message에 동형 요소 명시 ("본문 구조 동형 + frontmatter 생략" 등). V16의 분화 변형 — 의사결정 트리에서 V16과 함께 매칭
- **evidence**: `a224262` H4 verification template + `1f32c6c` D14-WIRING-SPEC + `275d904` D13 5a-impl + `150c595` D13 5b-wire (4회 누적)

### V18 Branch cherry-pick 통합
- **시그니처**: 다른 branch에 작성된 self-contained crate를 `git checkout <other-branch> -- <crate-path>`로 현재 working tree에 통합 + workspace glob auto-discover + 빌드/테스트 검증
- **적용 조건**: 다른 branch에 작성된 crate가 self-contained이고 현재 branch가 그 crate를 후속 integration step에서 사용해야 할 때
- **회귀 risk**: 0 (workspace 내부 path dep + 외부 dep 0 + 기존 branch 코드 0 변경)
- **재사용 cost**: ~5분 (cherry-pick + cargo build + cargo test 회귀 0 확인)
- **핵심 invariant**: workspace glob auto-discover (workspace.members 작업 0) + 외부 dep 0 + cherry-pick 후 기존 branch tests 100% pass + Cargo.lock 자동 갱신
- **V16과 차이**: V16은 *코드 shape* 동형 (file-diff 검증); V18은 *branch boundary* 통합 (cross-branch dependency 흡수)
- **evidence**: `c80bf8f` D14 nl-cron-parser prereq + `3951aa9` D13 skill-extractor prereq (2회 누적)

### V19 Debate-locked design implementation (DGE workflow, impl-105 등록) ★ NEW
- **시그니처**: 구조적 결정 (모듈 경계 / dep graph / naming)을 `/harness-debate` 3-agent 토론 엔진 (Planner/Critic/Architect)으로 lock → ontology_snapshot 수렴 (2 consecutive approved + byte-identical hash) → 본문 implementation에서 **decisions[] byte-identical 1:1 trace** + atomic single commit + commit message에 debate sid 인용
- **적용 조건**: (1) 변경이 단순 implementation 아닌 **구조적 결정** (모듈 경계 / dep graph / naming) (2) 1+ open question 또는 1+ trade-off 존재 (3) ≥ 200 LOC 또는 ≥ 5 functions 영향 (4) Critic이 attack할 명시적 hypothesis 존재
- **회귀 risk**: 0 (design locked + atomic commit + byte-identical → 표면 변화 0; rollback = `git revert <SHA>`)
- **재사용 cost**: debate 4-gen ~70분 (engine 1회) + implementation atomic commit (대상 변경 비용 그대로) + commit message 1:1 매핑 footer ~5분
- **핵심 invariant**:
  - decisions[] 1:1 trace — commit message footer에 D1/.../Dn enumerated + 각 decision 코드 위치 인용 가능
  - byte-identical to debate snapshot — 마지막 gen의 ontology_snapshot.fields ↔ commit diff 1:1 매칭
  - atomic single commit (debate scope strict — scope 밖은 별도 commit)
  - commit message debate sid 인용 (`Design lock: ... debate-XXXXXXXXXX-XXXXXX gen N converged`)
  - rollback 명시 (`Rollback: git revert <SHA>`)
- **V13/V13a와 차이**: V13/V13a는 small-medium scope minimal viable. **V19는 large structural scope** — implementation 진입 전 architecture 합의가 정의적 invariant
- **V16/V17과 차이**: V16/V17은 *이전 sub-task 패턴 재사용* (code-to-code shape). **V19는 *debate decisions[] 재현* (decision-to-code shape)** — 한 단계 위 abstraction. V19 implementation 안에 V13a/V16/V17이 본문 방식으로 포함될 수 있음
- **anti-pattern**:
  - debate scope 외 변경을 같은 commit에 묶기 (byte-identical 가드 위반)
  - debate sid 인용 없이 implementation 진행 (rollback context 손실)
  - 작은 변경 (< 200 LOC / < 5 functions)에 debate 강제 (4-gen ~70분 overhead 과잉) — V13/V13a/V16/V17/V18로 충분
  - gen 1 즉시 approved fast-path = V19 적용 조건 미달의 신호 (Critic이 attack할 hypothesis 부재) → V13a로 재분류
- **evidence**: `a119680` PR-2 step 1b autopilot_prevention.rs — debate sid `debate-1778727952-3db746` 4-gen 수렴 (gen 1 rejected `kha-core` 제안 → gen 2 conditional `bridgectl-internal submodule` pivot → gen 3 approved D1/D2/D4/D6 + orchestrator 9 fns 검증 → gen 4 byte-identical converged). 9 fns relocated (4 allows + 5 materialize), 312 LOC 신규 + main.rs -228 LOC, bridgectl 169/169 + operator-hud 38/38 + kha-core 95/95 회귀 0. **DGE 원칙 첫 실증 ★★★★** (Designer=debate, Generator=implementation, Evaluator=cascade test + cargo test + commit message 1:1 trace)
- **cross-reference**: CLAUDE.md DGE 3원칙 §1 (Designer/Generator/Evaluator 분리, 중요 설계 결정 시 `/harness-debate` 필수) + 분석 폴더 PATTERNS-CATALOG.md V19 entry + `pattern-auto-detector.md` V19 detector path

### V20 Data-shape narrowing (자동화 hook 완성 + multi-caller Stage 3 자동화 hook 후보 promotion + cross-binary parallel struct 1st realized + cross-struct enum 재사용 Stage 2 promotion + vanilla 7th PascalCase + vanilla 11th — impl-135 + impl-137 + impl-144 + impl-147 + impl-148 + impl-156 + impl-158 + impl-162 + impl-164 + impl-168 + impl-170 11회 evidence + Stage 5 자동 발견 + sub-variation Stage 3 + cross-binary parallel struct Stage 1 + cross-struct enum 재사용 Stage 2 + main lifecycle 보강 ×3) ★★★★★

> ✅ **자동화 hook 완성 단계 (Stage 5 도달, V20 lifecycle 완주)** — CLAUDE.md self-improvement loop §3 "1회 후보 lock → 2회 정식 등록 → 3회 자동화 hook 후보 → 4회 자동 발견 zero-effort 검출" 규칙의 Stage 5 도달 ★★★★. impl-147 (`f4b3c3e` discord-bridge `DiscordRoundtripKind`)이 `pattern-auto-detector.md` V20 detector path (`0a71b1f` impl-146)가 정찰 + Q0' 사전 분기 + Auto-detect Grep recipes 4단계를 zero-effort로 자동 매칭 검증한 first evidence. 동시에 recipe step 1 scope broadening 첫 evidence — `pub field: String` → `serde-exposed field (Serialize-derived struct 안 private 필드 포함)`로 확장한 application.

> ✅ **In-workspace multi-caller variant Stage 3 자동화 hook 후보 promotion (impl-148 1st + impl-156 2nd + impl-164 3rd, sub-variation Stage 3 promotion ★★★★★)** — V20 main lifecycle 완주 이후 sub-variation 3회 누적으로 자동화 hook 후보 진입 도달. impl-148 (`a1aa7d7` `kha-core::UnattendedHealthStatus`, debate sid `debate-1778844941-40ce06` 4-gen 수렴, V19 path 결합 large scope) + impl-156 (`8f25798` `kha-core::WorkerStageStatus`, V20-only path mid scope, 3 crates with boundary conversion) + impl-164 (`95c9a20` `kha-core::WorkerCircuitBreakerDecision`, V20-only path smallest scope to date, 2 binaries + kha-core boundary). V20 적용 조건 (3) "외부 caller 0 또는 in-workspace 1 binary"를 "외부 caller 0 또는 in-workspace **N** binary (atomic single commit 모두 migrate 가능)"로 확장. **세 path 분기**: large structural scope (≥ 5 structs / 3+ crates / ≥ 80 caller sites)이면 V19 path 결합 필수 — impl-148 evidence. mid scope이면 V20-only 가능 — impl-156 evidence (3 crates with boundary conversion: kha-core 정의 + bridgectl + discord-bridge, operator-hud는 `as_wire_str().to_string()`로 unchanged). smallest scope (2 binaries + kha-core boundary / ~5 caller sites / 0 test fixture changes) → V20-only with minimal scaffolding — impl-164 evidence (Unknown(String) absorbs legacy PascalCase sentinel `"ReviewRequired"` byte-identical via raw-pointer reuse). **Sub-variation promotion threshold policy**: main V20 lifecycle과 동일 (1회 후보 lock → 2회 정식 등록 → 3회 자동화 hook 후보 → 4회 zero-effort 검출). 현재 **3rd evidence (Stage 3 자동화 hook 후보 promotion)** — pattern-auto-detector BLOCK 9 sub-branch (a)에 Grep recipe sub-step 추가 권고 (`Grep "String type field" in apps/*/src/main.rs → cross-reference gateway-hub::pub(crate) enum same name`). 다음 4th evidence → Stage 4 zero-effort 검출 trigger.

#### In-workspace multi-caller variant 적용 조건 (sub-section)

- (1) 외부 crate caller ≥ 2 + 모두 in-workspace binary (publisher API 아님, production 외부 client 아님)
- (2) 모든 caller가 **같은 atomic single commit 안에서 migrate 가능** (의존 그래프 acyclic forward 유지)
- (3) Rust orphan rules 준수 — binary-local `From<&LocalStruct> for ForeignEnum` impls (reference target local) 가능
- (4) large structural scope (≥ 5 structs 또는 3+ crates 또는 ≥ 80 caller sites) 시 V19 path (`/harness-debate` 4-gen 수렴) 결합 필수
- (5) D2 mandatory pre-implementation audit — tolerant-comparison callers (`eq_ignore_ascii_case` / `matches!` / bound-variable rebinding) 전수 정찰. 0건 확정 시 `is_known() Unknown(_) → false` 안전, 1+건 시 `is_ok_tolerant()` 추가 검토

- **시그니처**: `pub field: String` (open wire) → `pub field: Enum` (closed set + `Unknown(String)` catch-all) + **custom `Serialize`/`Deserialize`로 wire-format byte-identical 보존** + `as_wire_str`/`from_wire_str`/`Display`/`FromStr<Err=Infallible>`/`From<&str>`/`From<String>` (Unknown arm owned-alloc 재활용) + caller migration (in-file caller만)
- **적용 조건**: (1) field가 closed-set 의미 + type system 상 `String` (typo/drift 위험) (2) 사전 정찰 (`Grep field_name corpus`)로 실제 사용 값 N종 lock 가능 (3) **외부 crate caller 0** 또는 in-workspace 1 binary 또는 **in-workspace N binary (atomic single commit migrate 가능)** ★ impl-148 sub-variation — production 외부 client 또는 cross-crate publisher API면 V19 lane (debate 필수) (4) legacy wire-format 호환 필수 (event-log/persistence/discord token 등) — Unknown(String) catch-all로 lossless preserve
- **회귀 risk**: low — caller 0 ~ in-file caller만 + wire byte-identical + Unknown fall-through로 legacy deserialize fail 0
- **재사용 cost**: ~80~250 LOC (enum + serde + impl 6~8 trait + 5~6 unit tests + caller migration); 사전 정찰 5분 + cargo test 5분
- **핵심 invariant**:
  - wire-format byte-identical — JSON byte 단위 동일 (no tagged-enum wrapper, 평문 string)
  - legacy migration lossless — historic string은 `Unknown(String)`로 round-trip
  - catch-all 무차별 수용 — `FromStr` Infallible / `From<&str>` infallible (parser fail 0)
  - owned allocation reuse — `From<String>`의 Unknown arm은 입력 String 그대로 재활용
  - 외부 crate caller 0 검증 (`Grep use crate::path::Type` empty)
- **V3과 차이**: V3은 *기존 enum에 variant 추가* (이미 typed). **V20은 *String → enum narrowing* (open → closed type 전환)**
- **V11과 차이**: V11은 *event contract + pure converter* (신규 contract). **V20은 *기존 field type 좁히기* (자가-개선)**
- **anti-pattern**:
  - 외부 caller 있는데 V20 적용 (medium 회귀, V19 territory로 escalation 필요)
  - Unknown fall-through 생략 + strict enum만 → legacy event-log deserialize fail
  - `#[serde(rename_all = "kebab-case")]` derive + `#[serde(other)] Unknown` unit variant 시도 → `Unknown(String)` value capture 불가, custom impl 필수
  - wire format을 tagged-enum (`{"type": "X"}`)로 변경 → byte-identical 가드 위반
- **evidence 1 (impl-135 `499b298`)**: `runtime::LaneOwnership.workflow_scope: String → WorkflowScope` 5 known variants `{ClawCodeDogfood, TestSuite, ExternalGitMaintenance, InfraHealth, ManualOperator}` + `Unknown(String)`. 사전 Grep 5종 wire 값 corpus lock. 외부 caller 0 검증. 6 unit tests (known round-trip 5종 + Unknown 보존 + legacy → known deserialize + FromStr infallible + From<String> owned reuse + LaneOwnership JSON byte-identical guard). 616/616 PASS 회귀 0. **Hermes 결정 2 D6 정밀화 evidence**.
- **evidence 2 (impl-137 `dee9967`)**: `tools::ReviewLaneOutcome.verdict: String → ReviewVerdict` 3 known variants `{Approve, Reject, Blocked}` + `Unknown(String)` (from `REVIEW_VERDICTS` corpus). `ReviewLaneOutcome`는 file-internal private struct (no `pub`). caller scope = file 내 only (3 사이트: clone / construct / JSON assertion line 8053). 외부 crate caller 0 확정 (`tools` dependency = `rusty-claude-cli` + `compat-harness`만, 둘 다 ReviewLaneOutcome 직접 import 0). custom Serialize/Deserialize 평문 lowercase wire `reviewVerdict: "approve"` byte-identical preserve. 6 unit tests (known round-trip 3종 + Unknown 보존 `"draft"` round-trip + legacy wire deserialize 3종 + FromStr infallibility + From<String> Unknown arm owned-alloc raw pointer 동일성 + extract_review_outcome end-to-end Option<String> vs Option<ReviewVerdict> JSON byte-identical guard). tools 91 passed; 11 failed (pre-existing Windows path failures baseline 동일; +6 신규 모두 PASS); baseline set bridgectl 169 + gateway-hub 132 + 8 baseline crates 573/573 PASS. impl-135 byte-equivalent shape 재사용 evidence — **D-tools 정밀화 evidence + V20 정식 승격 trigger** (CLAUDE.md §3 "2회 누적 정식 등록" 도달 ★★).
- **evidence 3 (impl-144 `82c50d0`) ★★★ NEW — 자동화 hook 후보 진입 (Stage 3)**: `kha-core::RunMilestoneState.status: String → RunMilestoneStatus` 9 known variants `{Idle, Running, Planned, Checkpointed, Verified, Repaired, RolledBack, Quarantined, Failed}` + `Unknown(String)` (corpus = bootstrap default 1 + literal in-flight 1 + `job_status_label(JobStatus)` 매핑 8 합집합 - 중복 "running" = 9). `RunMilestoneState`는 publicly-exported struct from kha-core, **하지만 외부 crate writer caller는 kha-cli 단일 (in-workspace binary)** — V20 적용 조건 (3)을 "외부 caller 0 또는 in-workspace 1 caller"로 완화한 첫 evidence. caller scope = kha-core 정의 + kha-cli 4 사이트 (bootstrap default + literal "running" + `from_wire_str(job_status_label(...))` 매핑 + `as_wire_str()` for `update_planning_state_markdown` `&str` 호환). custom Serialize/Deserialize 평문 lowercase + snake_case wire `{"status":"rolled_back"}` byte-identical preserve. 6 unit tests (known round-trip **9종 — 가장 큰 corpus** + Unknown 보존 `"draft"` round-trip + legacy wire deserialize 9종 [`rolled_back` snake_case 호환] + FromStr infallibility + From<String> Unknown arm owned-alloc raw pointer 동일성 + **RunMilestoneState end-to-end JSON byte-identical guard 10 값** [9 known + 1 operator-custom Unknown]). 기존 assertion (`assert_eq!(state.status, "idle")`) → `RunMilestoneStatus::Idle` 타이트닝 + `as_wire_str() == "idle"` guard 추가. kha-core 95 → **101 passed** (+6 V20); baseline set bridgectl 169 + gateway-hub 132 + operator-hud 38 + nl-cron-parser 116 + session-store 10 + event-log 1 + llm-summarizer-* 12 + kha-cli 11 = **490/490 PASS** in this verification cycle; discord-bridge 238 unaffected. impl-135 + impl-137 byte-equivalent shape 재사용 evidence — **D-kha-core 정밀화 evidence + V20 자동화 hook 후보 진입 trigger** (CLAUDE.md §3 "3회 누적 자동화" 도달 ★★★).
- **evidence 4 (impl-147 `f4b3c3e`) ★★★★ NEW — Stage 5 자동 발견 zero-effort 검출 first evidence**: `discord-bridge::DiscordRoundtripEvidence.kind: String → DiscordRoundtripKind` 5 known variants `{Plan, RuntimeResult, WorkerAlert, UnattendedHealthAlert, Error}` + `Unknown(String)` (corpus = `discord_outbound_kind_label(DiscordOutboundKind) -> &'static str` match block 5 wire 값 = `plan`/`runtime_result`/`worker_alert`/`unattended_health_alert`/`error`, `channel_discord::DiscordOutboundKind` `#[serde(rename_all = "snake_case")]`과 wire identical). `DiscordRoundtripEvidence`는 private struct (`struct`, no `pub`), file-internal only, `#[derive(Serialize)]` 단방향 wire (no Deserialize derive on parent struct — Unknown catch-all은 future Deserialize forward-compat 목적). 외부 caller 0 확정 (private struct이므로 외부 crate import 불가). custom Serialize/Deserialize 평문 snake_case wire byte-identical preserve. 메서드 family: `as_wire_str` / `from_wire_str` / `Display` / `FromStr<Err=Infallible>` / `From<&str>` / `From<String>` (Unknown arm owned-alloc reuse) + bonus `From<DiscordOutboundKind>` for clean direct conversion at builder + `is_known()` predicate. **orphan helper 흡수**: 기존 `discord_outbound_kind_label(kind: DiscordOutboundKind) -> &'static str` (10 LOC match) → `DiscordRoundtripKind::as_wire_str` + `From<DiscordOutboundKind>` impl로 흡수 후 helper 삭제. 6 신규 unit tests (known round-trip 5종 + Unknown 보존 `"operator-defined"` + legacy wire deserialize 5종 + FromStr infallibility + From<String> Unknown arm raw-pointer reuse + 5 known + 1 Unknown + From<DiscordOutboundKind> equivalence end-to-end). 기존 `discord_roundtrip_evidence_persists_latest_artifacts` 테스트에 `assert_eq!(persisted["kind"], "runtime_result")` byte-identical guard 추가. discord-bridge 238 → **244 passed** (+6 V20); baseline set bridgectl 169 + gateway-hub 132 + kha-core 101 + operator-hud 38 + nl-cron-parser 116 + session-store 10 + event-log 1 + llm-summarizer-* 12 + kha-cli 11 = **590/590 PASS**, 합계 **834/834 PASS**. impl-135 / impl-137 / impl-144 byte-equivalent shape 재사용 evidence — **D-discord-bridge 정밀화 evidence + V20 자동 발견 zero-effort 검출 first evidence + detector recipe scope broadening 첫 evidence** (pub field → serde-exposed field 확장) + **CLAUDE.md §3 "4회 누적 Stage 5 자동 발견" 도달 ★★★★ + V20 lifecycle 완주 (Stage 1~5)**.
- **evidence 5 (impl-148 `a1aa7d7`) ★★★★★ NEW — In-workspace multi-caller variant 1st evidence (sub-variation 정식 등록 Stage 1) + DGE 원칙 §1 4번째 실증 + V19 path 결합**: `kha-core::UnattendedHealthStatus` 5 known variants `{Healthy, IdleStopped, NotRunning, GateBlocked, Error}` + `Unknown(String)` (corpus from bridgectl helper `supervisor_unattended_health_status(...)` 5-arm match at main.rs:18003). **In-workspace 2 binary caller atomic migrate** — kha-core (2 pub struct fields, definition crate persisted JSON) + bridgectl (3 internal struct fields, ~50 caller sites) + discord-bridge (5 internal struct fields, ~30 caller sites) + 2 helper fn return type migration + 2 binary-local `From<&...>` impls (Rust orphan rules: reference target local). 사전 정찰 D2 mandatory audit — expanded regex (`eq_ignore_ascii_case` / `matches!` / bound-variable rebinding 포함) → **0 tolerant-comparison callers** across 3 crates, `is_ok()` Unknown(_) → false 안전 확정. custom Serialize (`serialize_str(as_wire_str())`) + custom Deserialize (`visit_str` allocates + `visit_string` 통한 From<String> raw-pointer reuse — serde Visitor `visit_str` does NOT borrow source bytes, raw-pointer scope는 From<String> only로 한정). 7 신규 unit tests (impl-135/137/144/147 byte-equivalent template + `is_ok()` semantics-preservation guard [matches `Healthy | IdleStopped` legacy 보존] + parent struct end-to-end JSON byte-identical 6-case). debate sid `debate-1778844941-40ce06` 4-gen 수렴 canonical hash `8be7d91cc4a2` (3/3 citations validated: Rust orphan rules + serde Visitor + proptest). cargo check 9 crates 27.48s + cargo test **841/841 PASS** [+7 V20, baseline 834], 회귀 0. analysis SSOT `~/.claude/state/analysis/v20-enum-hardening.md` (200+ LOC). **V20 lifecycle Stage 5 완주 + sub-variation Stage 1 후보 lock + DGE 원칙 §1 4번째 실증 ★★★★★ + V19 path 결합 첫 evidence**.
- **evidence 6 (impl-156 `8f25798`) ★★★★★ NEW — In-workspace multi-caller variant 2nd evidence (sub-variation Stage 2 promotion, V20-only path)**: `kha-core::WorkerStageStatus` 6 known variants `{Pending, Running, Succeeded, Failed, Quarantined, Skipped}` + `Unknown(String)` (corpus from gateway-hub `pub(crate) enum WorkerStageStatus` `#[serde(rename_all = "snake_case")]`, gateway-hub/src/worker.rs:43). **In-workspace 2 binary caller atomic migrate** — kha-core (1 new pub enum, definition crate) + bridgectl (`WorkerStatusHudStage.status` private field, 7 caller sites + 4 test fixtures) + discord-bridge (`WorkerStatusStage.status` private field, 2 caller sites + 2 test fixtures + 1 assert). 사전 정찰 D2 mandatory audit → 0 tolerant-comparison callers across 3 crates → `is_known()` Unknown(_) → false 안전 확정. custom Serialize/Deserialize byte-identical (lowercase snake_case 평문, untagged). 6 trait impls + `is_known()` + **`is_blocked()`** (matches caller convention `failed | quarantined` — bridgectl + discord-bridge 2 inline `matches!` 패턴 흡수). 7 신규 unit tests (impl-135/137/144/147/148 byte-equivalent + `is_blocked()` semantics + parent struct 6 known + 1 Unknown end-to-end). **operator-hud `OperatorHudWorkerBlockedStage.status: String` unchanged** — boundary conversion via `as_wire_str().to_string()` preserves publicly-exported String shape. cargo test full baseline **849/849 PASS** [+7 V20, baseline 842 from v14.18], 회귀 0. **V20-only path** (V19 debate 미사용, scope: 3 crates with boundary conversion / 2 internal struct fields / ~9 caller sites / 6 test fixtures, V19 threshold ≥5 structs OR ≥80 caller sites 미달). impl-148 byte-equivalent shape 재사용 + 6-value corpus (impl-144 9 다음으로 두 번째 큰). **Sub-variation Stage 2 정식 등록 promotion** (CLAUDE.md self-improvement loop §3 "2회 누적 정식 등록" 도달, sub-variation).
- **evidence 7 (impl-158 `5cb7d36`) ★★★★★ NEW — V20 vanilla 7th evidence (main lifecycle 보강, PascalCase wire 첫 evidence, single-binary bridgectl-local scope)**: `bridgectl::WorkerExecuteHandlerStatus` 3 known variants `{Deferred, Succeeded, Failed}` + `Unknown(String)` (corpus from gateway-hub `pub(crate) enum WorkerStageHandlerStatus`, gateway-hub/src/worker.rs:543, **기본 serde — PascalCase wire format**, no `rename_all`). single-binary scope: `WorkerExecuteHandlerHudRecord.status: String → WorkerExecuteHandlerStatus` (L1656, bridgectl-internal struct file-internal only) + 2 caller sites migrated. 사전 D2 mandatory audit → 0 tolerant-comparison callers (all callers strict `==/!= "Deferred"`). 6 trait impls + `is_known()` `#[allow(dead_code)]` (impl-148-followup precedent). bridgectl-local inline enum (no kha-core 변경, impl-137 pattern과 유사 — tools-local ReviewVerdict). custom Serialize/Deserialize byte-identical **PascalCase wire** — V20 lineage 첫 PascalCase evidence (impl-135~157 모두 snake_case/kebab-case/lowercase 평문). cargo test full baseline **849/849 PASS** unchanged (V20 enum dead_code warning silenced), 회귀 0. impl-148/156 byte-equivalent shape 재사용 + PascalCase wire 첫 적용. **Main lifecycle 보강 evidence** (sub-variation 2회 누적과 별개 카운트, 7회 누적 V20 total).
- **evidence 8 (impl-162 `ff163cd`) ★★★★★ NEW — V20 vanilla 8th evidence (cross-struct enum 재사용 첫 evidence, single-binary scope)**: `bridgectl::WorkerSupervisorJsonAlert.status: String → WorkerStageStatus` (impl-156 kha-core enum 재사용, **no new enum 정의**). kha-core::WorkerStageStatus (impl-156 정의)가 여러 deserialize sink (WorkerStatusHudStage + WorkerSupervisorJsonAlert)를 동시 커버. 같은 wire format (snake_case from gateway-hub `pub(crate) enum WorkerStageStatus`) 공유. 1 caller site (`worker_supervisor_alert_is_running` L13627) + 4 test fixtures 마이그레이트. 사전 D2 audit → 0 tolerant-comparison callers. cargo test 850/850 PASS unchanged (no new tests — impl-156 unit tests via shared enum 자동 커버), 회귀 0. **Cross-struct enum 재사용 첫 evidence** — V20 enum의 cross-struct applicability 검증, 단일 enum 정의가 여러 sink 마이그레이션 비용 절감. Main lifecycle 추가 보강 (sub-variation 2회 누적과 별개 카운트, 8회 누적 V20 total).
- **evidence 11 (impl-170 `d3d1b4c`) ★★★★★ NEW — V20 vanilla 11th + cross-struct enum 재사용 sub-variation Stage 2 정식 등록 promotion (impl-162 was 1st on bridgectl, impl-170 is 2nd mirror on discord-bridge)**: `discord-bridge::WorkerSupervisorAlert.status: String → WorkerStageStatus` (impl-156 kha-core enum 재사용, **no new enum**). discord-bridge-internal struct file-internal scope. Same wire (snake_case) and same corpus (6 known) as impl-156. 2 caller sites Display-only (`worker_alert_key` format!, `render_worker_alert_outbound` format!), 0 tolerant-comparison callers. 2 test fixtures migrated from PascalCase string literals (`"Quarantined"`, `"Failed"`) to proper enum variants — PascalCase fixtures never valid gateway-hub wire (production snake_case). **Cross-struct enum 재사용 sub-variation lineage**: impl-162 was 1st (bridgectl::WorkerSupervisorJsonAlert.status), impl-170 is **2nd evidence** (discord-bridge::WorkerSupervisorAlert.status on OTHER binary). Both reuse impl-156 kha-core::WorkerStageStatus single enum across distinct binaries and struct types. **Sub-variation Stage 2 정식 등록 promotion** (CLAUDE.md self-improvement loop §3 "2회 누적 정식 등록" 도달, cross-struct enum 재사용 sub-variation). atomic single commit +3/-3 LOC (smallest V20 commit to date). regression 0 (discord-bridge 244 unchanged, total 864/864 PASS unchanged from v14.25 — kha-core::WorkerStageStatus unit tests via shared enum auto-cover new consumer).
- **evidence 10 (impl-168 `693cc6f`) ★★★★★ NEW — V20 cross-binary parallel struct sub-variation 1st realized evidence (cross-binary writer/reader unification, V20-only path)**: `kha-core::DiscordRoundtripKind` 5 known variants `{Plan, RuntimeResult, WorkerAlert, UnattendedHealthAlert, Error}` + `Unknown(String)` (corpus from `channel_discord::DiscordOutboundKind` `#[serde(rename_all = "snake_case")]`). **Cross-binary parallel struct sub-variation** — different from in-workspace multi-caller variant (impl-148/156/164: multiple readers of same publisher's wire). Here **discord-bridge is the writer + bridgectl is the reader**, both serialize/deserialize the same `.factory/discord-roundtrip/latest.json` artefact with parallel struct definitions. Pre-promotion: discord-bridge file-internal `enum DiscordRoundtripKind` (impl-147) + bridgectl `DiscordRoundtripEvidence.kind: String` parallel field. Post-promotion: kha-core single source-of-truth. **Orphan-rule avoidance**: kha-core does NOT depend on channel-discord. Pre-existing `impl From<DiscordOutboundKind> for DiscordRoundtripKind` trait impl removed → discord-bridge binary-local free fn `outbound_kind_to_roundtrip(DiscordOutboundKind) -> DiscordRoundtripKind`. atomic single commit 4 files (+317/-119 LOC, net -118 LOC) — local enum removal saves ~110 LOC, free fn adds ~10 LOC, kha-core gains 273 LOC. 사전 D2 mandatory audit → 0 tolerant-comparison callers: bridgectl `kind` field parsed-but-never-read (Deserialize-only consumer), discord-bridge writer Serialize-only. 7 신규 kha-core unit tests (impl-148/156/164 byte-equivalent + Display matches wire_str). 1 discord-bridge test refactored to call free fn instead of `.into()`. cargo test full baseline **864/864 PASS** [+7 V20, baseline 857 from v14.23], 회귀 0 (kha-core 124 → 131 [+7 V20]; bridgectl 169 + discord-bridge 244 unchanged). **V20-only path** (debate 미사용) — scope: 3 crates / 2 internal struct fields / 1 writer caller + 1 boundary helper / 1 test refactor, V19 threshold 미달. v14.24 detector recipe Step 5 (impl-166) retroactive identification → impl-168 first execution. **Sub-variation lifecycle policy**: main V20 lifecycle과 동일 (1회 후보 lock → 2회 정식 등록 → 3회 자동화 hook → 4회 zero-effort 검출). 현재 cross-binary parallel struct sub-variation **Stage 1 후보 lock** (1st realized evidence) — 다음 2nd evidence 시 Stage 2 정식 등록 promotion 도달 예정.
- **evidence 9 (impl-164 `95c9a20`) ★★★★★ NEW — V20 in-workspace multi-caller variant 3rd evidence (sub-variation Stage 3 자동화 hook 후보 promotion, smallest multi-caller scope to date, V20-only path)**: `kha-core::WorkerCircuitBreakerDecision` 3 known variants `{None, RepairContractIssued, OperatorDecisionRequired}` + `Unknown(String)` (corpus from gateway-hub `pub(crate) enum WorkerCircuitBreakerDecision` `#[serde(rename_all = "snake_case")]`, gateway-hub/src/worker.rs:551 — smallest corpus to date for V20 multi-caller). **In-workspace 2 binary caller atomic migrate** — kha-core (1 new pub enum, definition crate) + bridgectl (`WorkerFailureLearningStatusCommandResult.circuit_breaker` private field L641 + init L7756 + parse L7788) + discord-bridge (`WorkerFailureLearningStatusJsonResult.circuit_breaker` private field L2907, Serialize+Deserialize both honoured). 사전 D2 mandatory audit → 0 tolerant-comparison callers across both binaries (only `println!`/`format!` Display formatting at bridgectl L8600 + discord-bridge L12016). custom Serialize/Deserialize byte-identical (lowercase snake_case 평문, untagged). 6 trait impls + `is_known()`. 7 신규 unit tests (impl-148/156 byte-equivalent template + **empty-string → Unknown invariant for byte-identical missing-artefact wire** + parent struct end-to-end JSON byte-identical 5-case [3 known + 2 Unknown including empty + ReviewRequired sentinel]). **No test fixture changes** — V20 Unknown(String) absorbs PascalCase legacy sentinel `"ReviewRequired"` (5 bridgectl + 1 discord-bridge test fixtures) byte-identical via raw-pointer reuse in `From<String>`. **smallest multi-caller scope to date**: 3 crates / 2 internal struct fields / ~5 caller sites / 4 files (+289/-6 LOC), V19 threshold (≥5 structs OR ≥80 caller sites) 미달 → V20-only path. cargo test full baseline **857/857 PASS** [+7 V20, baseline 850 from v14.22], 회귀 0 (kha-core 117 → 124 passed; bridgectl 169 + discord-bridge 244 unchanged). impl-148/156 byte-equivalent shape 재사용 + 3-value corpus (smallest multi-caller). **Sub-variation Stage 3 자동화 hook 후보 promotion trigger** (CLAUDE.md self-improvement loop §3 "3회 누적 자동화 hook 후보 promotion" 도달, sub-variation). 다음 4th evidence → Stage 4 zero-effort 검출 trigger 후보.
- **cross-reference**: 분석 폴더 PATTERNS-CATALOG.md V20 Evidence 4/5/6/7/8/9/10/11 entry + Hermes 결정 2 §86 D6 정밀화 + CLAUDE.md self-improvement loop §3 "4회 누적 Stage 5 자동 발견" 도달 + DGE 원칙 §1 4번째 실증 + `pattern-auto-detector.md` V20 detector path **정식 hook 등록 + Stage 5 검증 + v14.15 recipe step 1 scope broadening 정식 적용 + v14.17 BLOCK 9 sub-branch + v14.19 in-workspace multi-caller variant Stage 2 정식 등록 promotion (impl-156) + v14.20 vanilla 7th PascalCase wire 첫 evidence (impl-158) + v14.22 vanilla 8th cross-struct enum 재사용 첫 evidence (impl-162) + v14.23 multi-caller Stage 3 자동화 hook 후보 promotion (impl-164) + v14.25 cross-binary parallel struct 1st realized (impl-168) + v14.26 cross-struct enum 재사용 Stage 2 promotion (impl-170) + v14.27 Step 6 D2 tolerant-comparison audit FAIL anti-pattern 자동매칭 (메타 cycle 38회, impl-172, 외부 코드 변경 0)** (`0a71b1f` impl-146 등록 → `f4b3c3e` impl-147 first zero-effort 검출 검증 → v14.15 recipe step 1 visibility-agnostic broadening — `pub field: String` 강제 regex → `(pub\\s+)?` optional + Serialize-derived struct filter 사전 정찰; impl-137 / impl-147 private struct private field case retroactive 흡수 → **v14.17 impl-148 BLOCK 9 sub-branch + multi-caller variant 정식 등록 → v14.23 impl-164 Stage 3 promotion + BLOCK 9 sub-branch (a) Grep recipe sub-step 추가 권고**) + analysis SSOT `~/.claude/state/analysis/v20-enum-hardening.md` (200+ LOC)

## 적용 빈도 매트릭스

| 변형 | 적용 횟수 | commit |
|------|---------|--------|
| V1 Append-only I/O | 1 | `532ccf5` |
| **V2 Atomic save** | **3 ★** | `4ba59d1`, `3ad8c7e`, `b01812b` |
| V3 Enum variant 확장 | 1 | `fe5f04f` |
| V4 Adapter wiring | 1 | `a6b620c` |
| V5 Noop + factory | **2** | `571a4c6` (PR-4 step 2.5) + `8fdc844` (nl-cron-parser `select_summarizer` + Noop fallback + claude-cli adapter id 상수, LLM-SUMMARY-CRON-SPEC 16b — **첫 cross-domain 적용 D7→D14+D6 ★**) |
| V6 별도 메서드 + helper | 1 | `b0cb71e` |
| V7 Helper 분리 + delegate | 1 | `5bbebfc` |
| V8 Stateful event folder | 1 | `831f713` |
| V9 Silent → explicit | 1 | `3acb3bb` (시스템 점수 unlock) |
| V10 State machine | 1 | `989cf2e` |
| **V11 Event contract converter** | **3** | `e968d1a`, `7f577fa`, `a6c1c2b` |
| V12 Fire-history pure state | 1 | `28ac4a1` |
| V13 Minimal viable pure function | 1 | `340f33d` |
| V13a Multi-iteration minimal viable | **15 ★** | `8288fcd` iter 1 + `3a315a3` iter 2 + `e5cdf83` iter 3 cross-module + `5a98363` iter 4 batch + `a77d706` iter 5 ergonomic builder + `149813a` iter 6 utility-module + `0823d29` iter 7 name-conflict + `61bec96` iter 8 autopilot 도메인 sub-module + `13cafef` iter 9 autopilot V16 동형 + `824ea42` iter 10 commands batch + category mix + `a73ce49` iter 11 cli_args utility batch + BLOCK 7 unblock + `b0cf8d1` iter 13 autopilot 도메인 성장 3rd fn + `5fc728b` iter 14 policy sub-module + 5 fns batch + cross-crate forward dep (kha-core) + `1be17b8` iter 15 mini policy extractor (module 책임 확장 classifier→classifier+extractor) + `b73b936` iter 16 nl-cron-parser summarizer 첫 외부 crate 적용 (LLM-SUMMARY-CRON-SPEC §2 foundational + V18-noop variant, 10 unit tests) ★ — iter 12는 impl-100 BLOCK 6 skip |
| V13a-batch Batch trivial sub-variation | **4 ★** | `5a98363` (objective 동일 카테고리 batch) + `824ea42` (commands category mix builder+classifier ★) + `a73ce49` (cli_args utility batch + same-module call dep ★) + `5fc728b` (policy 신규 skeleton + 5 fns batch + cross-crate dep 추가 ★) |
| V13a-utility-module Utility module 신규 sub-variation | **2 ★** | `149813a` (cli_args 신규 push_workspace_arg) + `a73ce49` (cli_args 확장 command_arg + append_command_flag — 같은 module 추가 application ★) |
| V13a-name-conflict Name conflict patch sub-variation | 1 | `0823d29` (operator-hud cli_args::flag_value rename) |
| V14 Zero-dep pure rust algorithm | 1 | `7276e21` |
| V15 Calendar OR semantics | 1 | `7276e21` |
| **V16 호모모피즘 (full)** | **7 ★** | `3ad8c7e`, `b01812b`, `408296b`, `13cafef` (autopilot.rs same-module 첫 호모모피즘) + `1d86a57` (autopilot_prevention.rs 확장, impl-108 V19-followup — impl-105 동형) + `b6c240f` (WAL subset, impl-112 — branch boundary 호모모피즘 첫 ★) + `64f829a` (WAL superset, impl-114 — 2-step layered application 첫 evidence ★★) |
| **V17 Partial 호모모피즘** | **7 ★** | `a224262`, `1f32c6c`, `275d904`, `150c595`, `d197737` (PR-2-WIRING-SPEC), `f8e4c97` (operator-hud lib.rs), `LLM-SUMMARY-CRON-SPEC` (cross-domain spec lock — D14+D6+LLM, V17 7번째) |
| **V18 Branch cherry-pick** | **2** | `c80bf8f`, `3951aa9` |
| **V19 Debate-locked design implementation** ★ NEW | **3** | `a119680` (PR-2 step 1b — debate sid `debate-1778727952-3db746` 4-gen 수렴, **DGE 원칙 첫 실증 ★★★★**) + `609a253` (LLM-SUMMARY-CRON-SPEC 16c — debate sid `debate-1778766841-f3bbf5` **gen 1 fast-path 수렴 ★★** 7/7 decisions, 446/446 PASS) + `f2d509a` (impl-134 mock arm wire — debate sid `debate-1778807207-6718fe` **gen 2 converged ★★** ontology hash `a11b9ee04efc` impl-130 successor, 7 decisions, Critic 3 blockers all addressed, 616/616 PASS) |
| **V20 Data-shape narrowing** ★★★★★ **자동화 hook 완성 + multi-caller Stage 3 자동화 hook 후보 promotion + cross-binary parallel struct 1st realized + cross-struct enum 재사용 Stage 2 promotion + vanilla 7th PascalCase + vanilla 11th (11회 evidence, Stage 5 + sub-variation Stage 3 + cross-binary parallel struct Stage 1 + cross-struct enum 재사용 Stage 2 + main lifecycle 보강 ×3)** | **11** | `499b298` (impl-135 `runtime::LaneOwnership.workflow_scope: String → WorkflowScope` 5+Unknown, 6 unit tests, 616/616 PASS — D6 정밀화) + `dee9967` (impl-137 `tools::ReviewLaneOutcome.verdict: String → ReviewVerdict` 3+Unknown, 6 unit tests, 573/573 baseline set PASS — D-tools 정밀화) + `82c50d0` (impl-144 `kha-core::RunMilestoneState.status: String → RunMilestoneStatus` 9+Unknown, 6 unit tests + 9-value JSON byte-identical guard, kha-core 95 → 101 [+6], 490/490 baseline set PASS — **D-kha-core 정밀화 + Stage 3 자동화 hook 후보 ★★★**) + **`f4b3c3e`** (impl-147 `discord-bridge::DiscordRoundtripEvidence.kind: String → DiscordRoundtripKind` 5+Unknown, 6 unit tests + From<DiscordOutboundKind> bonus + orphan helper 흡수, discord-bridge 238 → 244, 합계 834/834 PASS — **V20 자동 발견 zero-effort 검출 first evidence + V20 lifecycle 완주 ★★★★**) + **`a1aa7d7`** (impl-148 `kha-core::UnattendedHealthStatus` 5+Unknown, 7 unit tests, **in-workspace 2 binary atomic migrate** (kha-core + bridgectl + discord-bridge + ~80 caller sites), debate sid `debate-1778844941-40ce06` 4-gen 수렴, 합계 **841/841 PASS** [+7 V20] — **In-workspace multi-caller variant 1st evidence + DGE 원칙 §1 4번째 실증 + V19 path 결합 ★★★★★**) + `8f25798` (impl-156 `kha-core::WorkerStageStatus` 6+Unknown, V20-only mid scope, 3 crates with boundary, 7 unit tests + `is_blocked()`, 849/849 PASS [+7 V20] — **multi-caller variant 2nd evidence (Stage 2 정식 등록)**) + `5cb7d36` (impl-158 `bridgectl::WorkerExecuteHandlerStatus` 3+Unknown, single-binary PascalCase wire 첫 evidence, 849/849 PASS unchanged — **main lifecycle 보강 + V20 vanilla 7th**) + `ff163cd` (impl-162 `bridgectl::WorkerSupervisorJsonAlert.status: String → WorkerStageStatus` impl-156 enum 재사용 no new enum, 850/850 PASS unchanged — **cross-struct enum 재사용 첫 evidence + V20 vanilla 8th**) + **`95c9a20`** (impl-164 `kha-core::WorkerCircuitBreakerDecision` 3+Unknown `{None, RepairContractIssued, OperatorDecisionRequired}`, V20-only smallest multi-caller scope to date — 2 binaries + kha-core boundary / ~5 caller sites / 0 test fixture changes (Unknown absorbs PascalCase `ReviewRequired` sentinel byte-identical via raw-pointer reuse), 7 unit tests + empty-string Unknown invariant guard + parent struct end-to-end 5-case, 합계 **857/857 PASS** [+7 V20], 회귀 0 — **In-workspace multi-caller variant 3rd evidence (sub-variation Stage 3 자동화 hook 후보 promotion trigger ★★★★★)**) |

**총 72 applications** (V20 11번째 = +1 from 71, impl-170 시점 — `discord-bridge::WorkerSupervisorAlert.status: String → WorkerStageStatus` cross-struct enum 재사용 sub-variation **Stage 2 정식 등록 promotion** (impl-162 1st bridgectl + impl-170 2nd discord-bridge, kha-core single enum 정의 WorkerStageStatus가 3 distinct sinks 동시 커버). V20 main lifecycle 완주 (Stage 1~5) + in-workspace multi-caller variant Stage 3 자동화 hook 후보 + cross-binary parallel struct sub-variation Stage 1 (impl-168) + **cross-struct enum 재사용 sub-variation Stage 2 정식 등록 promotion (impl-170)** + main lifecycle 보강 ×3 (impl-158 PascalCase 첫 + impl-162 enum 재사용 첫 + impl-170 vanilla 11th). atomic commit +3/-3 LOC (smallest V20 commit to date — cross-struct enum 재사용 비용 절감 evidence). abstraction-first 41 + integration 28 + 메타 59 = 128 step과 별도 카운트).

## 안티패턴 (integration step으로 승격)

다음 상황은 abstraction-first 변형이 아닌 **integration step** — `repeat-error-tracker.md` E1 + Anti-pattern matrix가 owner. 본 카탈로그가 적용 안 되는 회귀 risk medium+ 케이스:

| 안티패턴 | 회귀 risk | 감쇄 패턴 |
|---|---|---|
| 26K LOC monolith 내부 함수 수정 | medium~high → low | 변경 < 0.5% + helper 분리 + cfg(test) (`04516e3`, `a6c1c2b`, `82299b1`, `408296b` 7회 무회귀) |
| 기존 caller 시그니처 변경 (caller ≥ 1) | medium | 신규 메서드 추가 (V6) + delegate refactor (V7) |
| 기존 모듈 본문 logic 변경 (re-export 외) | medium | helper 분리 + byte-identical equivalence test |
| 신규 외부 production dep | low~medium | workspace 내부 crate path dep (chrono → Howard Hinnant V14) |
| 의도된 contract 깨기 (동기→비동기 등) | high | 사용자 확인 필수 |

## Self-improvement loop (CLAUDE.md 2원칙 직속)

본 카탈로그는 **living catalog**. 새 변형 발견 시:

1. 본 entry에 V17, V18, ... 추가
2. 본 의사결정 트리에 해당 분기 추가
3. evidence (commit SHA + 적용 횟수) 명시
4. 적용 빈도 매트릭스 갱신

### 새 변형 추가 절차

```markdown
### V{N} <한 줄 요약>
- **시그니처**: <Rust/언어 비종속 시그니처>
- **적용 조건**: <상황>
- **회귀 risk**: <0 / low / medium / high>
- **재사용 cost**: <LOC + tests>
- **핵심 invariant**: <unit test 도출용 체크리스트>
- **evidence**: <commit SHA(s)>
```

## Gotchas

### V16 호모모피즘 명시 부재
이전 V1~V15을 동형 적용하면서 commit message에 "homomorphic to previous" 인용 없으면 reviewer가 발견 못 함. 의도적 동형은 반드시 commit message + 본 카탈로그 evidence 양쪽에 SHA 인용.

### V11 multi-purpose 혼동
V11 "event contract + converter"는 두 가지로 쓰임: (1) 외부 subscription 전 contract lock, (2) pretty-print multi-line JSON best-effort parse. 두 use case 모두 `Vec<Evidence>` 또는 `Result<T, BridgeError>` 형태 — 혼동 없도록 commit message에 use case 명시.

### V13 minimal viable의 후속 확장 약속
V13은 "minimal viable로 lock하고 후속에서 확장"이 전제. 후속 확장이 안 들어오면 minimal-viable이 production-stuck. 본 카탈로그에 적용 후 후속 확장 commit SHA를 함께 evidence로 기록.

### Anti-pattern이 본 카탈로그를 가린다
"V16 호모모피즘으로 26K monolith 수정도 회귀 0이지!"는 잘못된 추론. V16은 신규 모듈에만 적용. monolith 진입은 integration step (E1).

### 카탈로그 자체의 회귀
본 스킬에 변형을 추가했는데 evidence 출처 commit이 revert되면 카탈로그 자체가 stale. 변형 추가 후 evidence SHA는 ≥30일 stable해야 함.

### Cross-crate dep BLOCK (pattern-auto-detector enforcement)

본 카탈로그가 다루는 변형은 모두 분리 후보가 target crate 안에서 self-contained 가능할 때 적용. 외부 dep이 있으면 detector가 BLOCK으로 차단.

| BLOCK | axis | trigger | Evidence | enforcer Q |
|---|---|---|---|---|
| BLOCK 6 ★ | struct (type) | 인자/return type이 target crate 외부 monolith-internal struct | impl-87 `unattended_can_start(&SupervisorUnattendedCommandResult)` | Q5b |
| BLOCK 7 ★ | function call | body가 호출하는 1+ fn이 target crate 외부 monolith-internal | impl-93 `prevention_chain_command` body 4 cross-crate calls | Q5c |

**동형 self-갱신 패턴**: 둘 다 first-pass 정찰에서 detector 자체 누락 발견 → 즉시 self-갱신. axis만 다름 (struct ↔ function call). 양방향 vision 3차 cycle (impl-87) ↔ 9차 cycle (impl-93)에서 longtail 효과 검증. 새 axis 발견 시 본 표에 BLOCK [N] entry 추가 + pattern-auto-detector.md Q5d/Q5e 분기 추가.

## 짝 스킬 (peer)

- **pattern-auto-detector.md** ★ — 본 카탈로그를 의사결정 트리 자동 매칭으로 활용. 분리 후보 fn이 주어지면 6 질문에 답하여 V13a sub-variation 또는 V16~V18 호모모피즘을 ≤30초 안에 추천. 본 스킬은 카탈로그 SSOT, detector는 SSOT를 사용하는 enforcer. evidence 누적 시 (V19+ 또는 V13a iter 8+ 발견) **양 스킬을 동시 갱신** (메타 cycle 발화).
- **repeat-error-tracker.md** — 본 스킬이 "positive space" (해야 할 것). repeat-error-tracker는 "negative space" (안 해야 할 것). 같은 사례를 다룰 수도 있지만 관점이 다름.
- **testing-anti-patterns.md** — unit test 관점의 안티패턴 (본 스킬 V1~V16의 dense test 부분이 본 스킬 영역, mock 사용 등은 testing-anti-patterns 영역).
- **verification-before-completion.md** — 본 스킬 변형 적용 후 completion gate.

## 도구 사용 패턴 (Harness)

- 새 sub-task 시작 시: `Read /home/user/.claude/skills/_common/abstraction-first.md` (본 파일) — 의사결정 트리로 변형 선정
- 적용 후 commit message: `feat: <변경> (V{N} <변형명>, homomorphic to <prev SHA>)` 형식 권고
- 적용 빈도 매트릭스 갱신: `Edit` 본 파일에 적용 횟수 +1 + commit SHA 추가
- 새 변형 발견: `Edit` 본 파일에 V17, V18, ... 추가 + 의사결정 트리 분기 추가

## 에러 복구 패턴 (Harness)

- 변형 매칭이 모호 → 의사결정 트리 1~12 순서대로 매칭 시도. 모든 분기 미스 시 integration step (12번)
- V16 호모모피즘이 떠올랐지만 file-diff 동형이 어색 → 이전 sub-task SHA를 다시 read해서 shape 비교. 다르면 V16 아니라 신규 변형
- 적용 후 회귀 발견 → 본 카탈로그 변형 부적합 의심. integration step으로 재분류 + repeat-error-tracker E1 적용

## 출처 인용

본 스킬의 16 변형 + 의사결정 트리 + 안티패턴 matrix는 다음 evidence에서 추출:

| 출처 | 위치 |
|---|---|
| 분석 폴더 PATTERNS-CATALOG | `/home/user/example_project-analysis/.claude/requirements/PATTERNS-CATALOG.md` (16 변형 / 23 applications) |
| VERIFICATION backbone | `.claude/requirements/VERIFICATION.md` (3-tier living, 5 Gates + §11 + §12) |
| 누적 changelog | `.claude/requirements/changelog.md` (impl-1 ~ impl-48) |
| 외부 commit (33 application) | `/home/user/example_project/` (5 branch / 37 commit / 9600 LOC / 384/384 tests / 회귀 0) |
| AUTOPILOT-PLAN §3 H2 | `synthesis/AUTOPILOT-PLAN.md` (본 스킬의 의도 lock) |
