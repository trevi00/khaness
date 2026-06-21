---
name: iso25010-scoring
description: ISO/IEC 25010 기반 28 sub-attribute × 9 카테고리 정량 평가 룰북 — example_project-analysis SCORING-RUBRIC.md 검증된 frame을 보편화. 9 카테고리 평균과 28 sub-attribute 평균의 ±0.5 일관성으로 self-check. 모든 프로젝트의 도메인 평가 / 후보 선정 / 시스템 점수 산출에 적용.
keywords: [iso25010, scoring, sub-attribute, rubric, quality-evaluation, self-check, consistency]
intent: [evaluate, score, prioritize, audit, codify-quality]
phase: review
min_score: 4
---

# ISO 25010 — 28 Sub-Attribute Scoring Framework

> **사용자 비전**: 매 step 후보 선정 + 매 도메인 audit에 정량 점수 활용 ("28 sub-attribute × 9 ISO 25010 카테고리 정량 평가로 최고의 답을 자율 선정").
>
> **본 스킬의 책임**: 28-sub × 9 카테고리 평가 frame + 1/3/5 anchor 정의 + 변환 공식 + 일관성 self-check 제공. 본 frame을 새 프로젝트에 적용할 때 운영자 특성에 맞춰 조정.
>
> **검증 출처**: `/home/user/example_project-analysis/.claude/requirements/SCORING-RUBRIC.md` (15 도메인 × 28 sub × 1913점 / 420셀 = 4.555 시스템 평균, 9 카테고리 view와 ±0.025 consistency). 47-step 동안 매 후보 선정에 28-sub로 자율 평가.

## 핵심 원칙

1. **28 sub-attribute = 직접 평가 셀** (15 도메인 × 28 = 420 셀이 evidence backbone)
2. **9 카테고리 점수 = sub-attribute 산술 평균** (downstream reporting view)
3. **9번 확장성 = derived** (M.응집 + M.결합 + M.모듈 + C.공존 + C.상호 5 sub 평균) — 시스템 평균 산출에서 제외
4. **Anchor 3 단계 (1 / 3 / 5)** — 2/4 는 보간으로 추정 (v1). v2는 1~5 모든 anchor 명시.
5. **일관성 self-check**: 도메인의 9 카테고리 평균과 28 sub 평균의 차이 **±0.5 이내** 필수. 초과 시 evidence 재검토.

## 의사결정 트리

### IF 후보 선정 (Plan)
1. 후보별 5~6 sub-attribute만 평가 (전 28 미평가 OK — 후보 비교용)
2. 평균 ≥ 4.5 후보 자율 선정
3. 회귀 risk 0 후보 우선

### IF 도메인 평가 (Review)
1. 도메인 1개씩 28 sub 모두 평가 (1/3/5 또는 보간 2/4)
2. 9 카테고리 평균 산출 (§3.1 공식)
3. **일관성 self-check** — 카테고리 평균 vs sub 평균 차이 ≥0.5 면 evidence 재검토
4. 9번 확장성 derived 계산
5. 매트릭스 cell에 점수 + evidence 출처 기록

### IF 시스템 점수 산출 (Audit)
1. 모든 도메인 28 sub 점수 누적
2. **시스템 평균** = sum(N 도메인 × 28 sub) / (N × 28) — 9번 확장성 derived 제외
3. 9 카테고리 view = 카테고리별 도메인 평균
4. 두 view 일치 검증 (±0.5 이내)

## 28 Sub-Attribute 카탈로그

본 frame은 ISO/IEC 25010:2011 기반 + 운영자 특성에 맞춰 조정. 운영자 1명 가정 (sub 6→2 축약) — 다중 사용자면 §5.1 조정 포인트 참조.

### 카테고리 1. 기능 적합성 (Functional Suitability)

| Sub | 약어 | 1 (낮음) | 3 (보통) | 5 (높음) |
|---|---|---|---|---|
| 정확성 | F.정확 | 명세-코드 자주 불일치, 회귀 시 발견 못함 | 명세 일부 cover, 일부 추측 | 모든 spec/US-AC 1:1 매핑 + 회귀 테스트 |
| 안정성 (functional safety) | F.안정 | 정상 path만 cover, 에러 path 미명시 | 4분류 (입력/리소스/충돌/인프라) 일부 cover | 4분류 모두 cover + 에러 코드 enum 명시 |

### 카테고리 2. 성능 효율성 (Performance Efficiency)

| Sub | 약어 | 1 | 3 | 5 |
|---|---|---|---|---|
| 시간 (latency) | P.시간 | 정량 baseline 없음 | 일부 정량 (TTL gate 등) | P95/P99 측정 + bounded loop + 명시 budget |
| 자원 (CPU/memory/lock) | P.자원 | lock 자유, lease 무한, panic-on-error | 일부 lease/quarantine 정량 | lease 명시 (900s 등) + RAII Drop + bounded counter |
| 용량 (throughput) | P.용량 | throughput 측정 0, 한도 미정 | cron/batch 한도 명시 | capacity baseline + KPI 측정 + auto-scale |

### 카테고리 3. 호환성 (Compatibility)

| Sub | 약어 | 1 | 3 | 5 |
|---|---|---|---|---|
| 공존성 | C.공존 | 같은 호스트의 다른 process와 race/lock 충돌 | 일부 isolation (per-server) | WAL/file lock cross-process serialize + clean isolation |
| 상호운용성 | C.상호 | 외부 system과 ad-hoc 통합, 표준 0 | 일부 표준 (JSON/TOML) | 표준 protocol (REST/SSE/agentskills.io v1) + 양방향 |

### 카테고리 4. 사용성 (Usability — 운영자 1명 가정 시 6→2 축약)

| Sub | 약어 | 1 | 3 | 5 |
|---|---|---|---|---|
| 학습성 | U.학습 | 명령/artifact 학습 비용 높음, doc 부재 | 일부 doc + next_command chain | next_command chain + objective_status boolean + drill-down |
| 운영자 보호 | U.보호 | typo/오발 시 mutation 가능, 게이트 0 | 일부 confirm 토큰 (1~3개) | 모든 mutate에 토큰 + reason 강제 + private 채널 격리 |

> 다중 사용자 시: **적합성 인식 / 사용자 오류 보호 / 접근성 / 운영성** 4 sub 추가 (§5.1 참조).

### 카테고리 5. 신뢰성 (Reliability)

| Sub | 약어 | 1 | 3 | 5 |
|---|---|---|---|---|
| 가용성 | R.가용 | uptime 보장 없음, freshness gate 0 | 일부 freshness TTL | 4+ freshness gate (300s/3600s) + cold-handoff |
| 결함허용 | R.결함 | retry 0, fallback 0 | 일부 retry (1회) | 4-tier fallback + retry exp backoff + quarantine |
| 회복성 | R.회복 | 재기동 시 상태 손실, lease 누수 | 일부 cold-resume | durable artifact + AUTOINCREMENT 단조 + lease 회수 |
| 무결성 | R.무결 | idempotent 안 됨, race 시 중복/손상 | 일부 idempotent (upsert) | append-only + idempotent + monotonic + WAL |

### 카테고리 6. 보안 (Security)

| Sub | 약어 | 1 | 3 | 5 |
|---|---|---|---|---|
| 기밀성 | S.기밀 | secret 노출 (env 비검증, 평문 key) | env var only, 일부 검증 | secret scanner + env var only + hardcoded 키 0 |
| 무결성 (tampering) | S.무결 | artifact 위변조 가능, signature 0 | 일부 hash/version | artifact hash + version pinning + audit log |
| 인증 | S.인증 | operator identity 미검증 | 사용자 ID 정도 | token-bound + 채널 격리 + reason 강제 |
| 부인방지 | S.부인 | audit log 0, who-did-what 추적 불가 | 일부 audit (error 시만) | event_log SOT + decided_by + correlation_id |

### 카테고리 7. 유지보수성 (Maintainability — 8 sub, 가장 정밀)

| Sub | 약어 | 1 | 3 | 5 |
|---|---|---|---|---|
| 응집도 | M.응집 | 한 모듈에 여러 책임 (26K 모놀리식) | 부분 분리 | 단일 책임 crate + 명확한 boundary |
| 결합도 | M.결합 | tight coupling, 변경 chain | 일부 trait 추상 | trait + REGISTRY + DI |
| 모듈성 | M.모듈 | file/crate boundary 모호 | 부분 분할 | crate 단위 + members glob + workspace deps |
| 재사용성 | M.재사 | copy-paste, generic 0 | 일부 helper | trait + generic + workspace.dependencies |
| 가독성 | M.가독 | cryptic naming, 주석 부재/잘못 | 일부 주석 + 일관 naming | snake_case + WHY 주석 + RAII pattern |
| 테스트 용이성 | M.시험 | 테스트 0, mock 어려움 | 일부 unit test | 6+ unit + integration + mock parity + clean-env |
| 수정성 | M.수정 | 변경 시 N개 파일 일관 수정 | 부분 OCP | REGISTRY 1줄 + provider 1 파일 + workspace glob |
| 분석성 | M.분석 | log 부재, debug 추측 | 일부 log | typed event_log + correlation_id + payload JSON |

### 카테고리 8. 이식성 (Portability)

| Sub | 약어 | 1 | 3 | 5 |
|---|---|---|---|---|
| 적응성 | T.적응 | OS-specific hard-code, env hard-code | 부분 cross-platform | env var + Optional pattern + cross-platform file lock |
| 설치성 | T.설치 | 수동 다단계, 모호 | 일부 자동화 | `cargo install` (또는 동급) + workspace 단일 + Containerfile |
| 대체성 | T.대체 | vendor lock-in | 일부 trait 추상 | trait abstraction + REGISTRY + Optional<...> 비활성 허용 |

### 카테고리 9. 확장성 (Derived)

```
E.확장 = avg(M.응집 + M.결합 + M.모듈 + C.공존 + C.상호)
```

**이유**: 새 component 추가 시 (1) 응집/결합/모듈성이 좋아야 격리 가능하고, (2) 공존/상호운용성이 좋아야 기존 system과 통합 가능. 두 차원 모두 통과해야 진정한 "확장 가능".

## 변환 공식

### 카테고리 점수 = sub-attribute 산술 평균

| 카테고리 | sub 수 | 공식 |
|---|---|---|
| 1 기능 적합성 | 2 | (F.정확 + F.안정) / 2 |
| 2 성능 효율성 | 3 | (P.시간 + P.자원 + P.용량) / 3 |
| 3 호환성 | 2 | (C.공존 + C.상호) / 2 |
| 4 사용성 | 2 (or 6 다중 사용자) | (U.학습 + U.보호) / 2 |
| 5 신뢰성 | 4 | (R.가용 + R.결함 + R.회복 + R.무결) / 4 |
| 6 보안 | 4 | (S.기밀 + S.무결 + S.인증 + S.부인) / 4 |
| 7 유지보수성 | 8 | (M.응집 + M.결합 + M.모듈 + M.재사 + M.가독 + M.시험 + M.수정 + M.분석) / 8 |
| 8 이식성 | 3 | (T.적응 + T.설치 + T.대체) / 3 |
| 9 확장성 | 5 (derived) | (M.응집 + M.결합 + M.모듈 + C.공존 + C.상호) / 5 |

### 시스템 평균 = 28 sub × N 도메인 직접 평균

```
시스템 평균 = sum(N × 28 cells) / (N × 28)
```

9번 확장성은 derived이므로 **시스템 평균에서 제외**.

### 일관성 self-check

```
|카테고리 평균(9 view) − sub 평균(28 view)| ≤ 0.5  for every domain
```

초과 시 evidence 재검토 (한쪽 view가 잘못 평가됐을 가능성). 본 frame은 0.5 임계가 v1; v2는 0.3로 정밀화 권고.

## 후보 선정 시 단축 평가 (5~6 sub만)

후보 비교용으로 전 28 sub 평가 불필요. 다음 5~6 sub만 평가:

- **F.정확** (1.기능적합성) — 명세 매핑
- **R.무결** (5.신뢰성) — idempotent / monotonic
- **M.응집** (7.유지보수성) — 단일 책임
- **M.시험** (7.유지보수성) — test 용이
- **U.보호** (4.사용성) — operator 안전
- **회귀 risk** (외부 차원) — 0 / low / medium / high

평균 ≥ 4.5 + 회귀 risk 0 → 자율 선정 적합.

## 운영자 / 진입 / 인증 조정 포인트

본 frame은 example_project (운영자 1명 + Discord 진입 + Codex/Claude 분리) 특화. 다른 프로젝트는 다음 조정:

### 5.1 운영자 다중 사용자
- 사용성 카테고리 6 sub로 확장: **학습성 / 운영자 보호 / 적합성 인식 / 접근성 / 사용자 오류 보호 / 운영성**
- 카테고리 4 공식: `(U.학습 + U.보호 + U.인식 + U.접근 + U.오류 + U.운영) / 6`
- 시스템 평균 셀 수 변경: `N × 32` (28 + 4 추가)

### 5.2 진입이 Discord가 아님
- U.학습의 "next_command chain" 가중 다른 표준으로 (CLI prompt / 웹 UI / IDE 등)
- S.인증의 "Discord user ID" 가중 다른 표준으로 (OAuth bind / mTLS / SSO)

### 5.3 인증이 token-bound가 아님
- S.인증 anchor 5 정의 변경: "token-bound + 채널 격리" → "OAuth bind + RBAC" 등
- S.부인의 correlation_id를 SSO session ID로

### 5.4 도메인별 가중치 (v3)
보안 도메인은 S.* sub 가중 2배, 성능 도메인은 P.* 가중 2배. v3에서 도입 권고.

## Sample 평가 (D11 mock-parity, example_project evidence)

```
9 카테고리 점수: 5/5/5/4/5/5/5/5/5 → 평균 4.89
28 sub 합계: 5×26 + 4×2 = 138 / 140 → 평균 4.93
차이: |4.89 - 4.93| = 0.04 (consistency PASS, ≤ 0.5)
E.확장 derived: (5+5+5+5+5)/5 = 5.0
```

evidence는 SCORING-RUBRIC.md §4 (mock-parity 28 sub × evidence 1:1 매핑).

## Self-improvement loop

본 frame은 **living rubric**. 발견 시:

1. **새 anchor 정밀화** (v2: 2/4 anchor 명시) — `Edit` 본 파일에 단계별 anchor 추가
2. **도메인 가중치** (v3) — `Edit` §5.4 확장
3. **자동 점수 산출** (v4) — clippy / cargo metrics / test coverage 통합

### 새 sub-attribute 추가 절차

운영자 특성이 본 frame과 다를 때 (§5 조정 포인트):

```markdown
| Sub | 약어 | 1 | 3 | 5 |
|---|---|---|---|---|
| <새 sub> | <약어> | <설명> | <설명> | <설명> |
```

본 frame에 추가 + 카테고리 공식 갱신 + 시스템 평균 셀 수 명시.

## Gotchas

### 9 → 28 view 불일치를 무시
일관성 check ±0.5 초과를 "노이즈"로 처리하면 안 됨. evidence 한쪽이 잘못 평가됐다는 신호. 둘 중 어느 view가 정확한지 evidence path를 따라가서 재산출.

### 9번 확장성을 시스템 평균에 포함
9번은 derived. 포함하면 5 sub (M.응집 + M.결합 + M.모듈 + C.공존 + C.상호)이 double-count. 시스템 평균은 항상 28 sub × N 도메인.

### 보간 anchor 추정의 비일관성
2/4는 v1에서 보간. 두 평가자가 같은 도메인을 2와 4로 다르게 매기면 frame v1의 한계. v2 (1/2/3/4/5 모든 anchor 명시)까지는 평가자 캘리브레이션 필요.

### 단축 평가 (5~6 sub)를 도메인 점수로 오인
단축 평가는 **후보 비교용**. 도메인 점수 산출은 항상 전 28 sub 필요.

### 사용성 sub를 운영자 1명 → 다중 사용자로 옮길 때 시스템 평균 분모 미갱신
sub 28 → 32 변경 시 `N × 32`로 분모 갱신 안 하면 시스템 평균이 인플레이션. 분모 변경 시 모든 도메인 sub 누락 채우기 필수.

## 짝 스킬 (peer)

- **abstraction-first.md** (H2) — 신규 기능 추가 시 본 rubric으로 28-sub 평가 → V1~V16 변형 선정
- **repeat-error-tracker.md** (H1) — 회피 패턴이 본 rubric 점수에 직접 반영 (E1 monolith 회피 → M.응집 +1 unlock 등)
- **verification-before-completion.md** (기존) — 본 rubric 점수가 completion gate의 정량 기준
- **doc-verify.md** (기존) — 본 rubric 점수가 문서 품질 gate

## 도구 사용 패턴 (Harness)

- 후보 선정 시: `Read /home/user/.claude/skills/_common/iso25010-scoring.md` (본 파일) — 단축 평가 5~6 sub
- 도메인 평가 시: 28 sub 모두 평가 + 9 카테고리 view + 일관성 check
- 시스템 점수 산출: `N × 28` 셀 매트릭스 → 평균 + 9 view + 일관성 ±0.5
- 새 anchor 정밀화: `Edit` 본 파일 §28 sub 테이블에 단계 추가

## 에러 복구 패턴 (Harness)

- 일관성 check FAIL (Δ > 0.5) → 두 view 중 어느 evidence가 부정확한지 확인 → 한쪽 점수 재산출
- 평가자 캘리브레이션 불일치 → 같은 도메인 두 평가자가 사용 anchor 인용 비교
- sub 누락 발견 → 누락 sub만 채워서 도메인 점수 재산출 (다른 sub 영향 0)

## 출처 인용

본 스킬의 28 sub-attribute + 9 카테고리 + 변환 공식 + 일관성 check는 다음 evidence:

| 출처 | 위치 |
|---|---|
| 분석 폴더 SCORING-RUBRIC | `/home/user/example_project-analysis/.claude/requirements/SCORING-RUBRIC.md` (312 LOC, v1) |
| VERIFICATION §9 매트릭스 | `.claude/requirements/VERIFICATION.md` §9 (15 × 28 = 420 셀 산출 결과) |
| 시스템 점수 evidence | 9 카테고리 평균 4.53 + 28 sub 평균 4.555 (Δ +0.025, ±0.5 일관성 통과) |
| 적용 횟수 | 47-step 동안 매 후보 선정에 단축 평가 활용 (~50회) + 15 도메인 audit (×28 = 420 셀) |
| AUTOPILOT-PLAN §3 H3 | `synthesis/AUTOPILOT-PLAN.md` (본 스킬의 의도 lock) |
| ISO/IEC 25010:2011 표준 | https://www.iso.org/standard/35733.html (base spec — 본 frame은 사용자 정의 변형) |
