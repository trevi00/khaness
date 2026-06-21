---
name: skill-distillation-pipeline
description: 채용 시그널/외부 docs를 9축 강제 스킬로 추출하는 5단계 파이프라인 — research level 결정, frontmatter 표준, 게이트 회귀
keywords: skill-distillation extraction research-augmented frontmatter quality-gates verbatim citation 9-axis
intent: extract-skill-from-source choose-research-level apply-9-gates plan-distillation-pipeline replicate-for-other-companies
paths:
patterns: harness-document-specialist quality_axes_enforced MANDATORY_PREFIXES skill_quality_axes
requires: doc-writer code-quality
phase: plan implement review
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Skill Distillation Pipeline

> 핵심: 채용공고/공식 docs를 스킬로 추출할 때 정확성·이식성·확장성을 동시 만족하려면 **5단계 결정론적 파이프라인** + **3 research level 분기** + **9게이트 강제**가 필요. 이 스킬 자체가 같은 절차를 따라 작성되어 자기증명한다.

## 의사결정 트리

### IF 새 시그널 소스 추출 시작 (Plan)
1. **Source 분류** — 채용공고/공식 docs/RFC/blog 중 어느 카테고리?
2. **Volatility 판정** — 6개월 내 변경 가능한가?
   - 안정 spec (RFC, ANSI SQL) → **L1 직접**
   - 빠른 변화 (Flink/OTel/벤더 fork) → **L2 research-augmented**
   - 아키텍처 분기 (트레이드오프 큰 결정) → **L3 debate engine**
3. **위치 결정** — 새 도메인이면 신규 디렉토리, 기존 도메인 보강이면 그 디렉토리
4. **enforce 결정** — 신규 디렉토리는 `MANDATORY_PREFIXES`에 추가 또는 frontmatter `quality_axes_enforced: true`

### IF 5단계 파이프라인 실행 (Implement)
```
[1] Source crawl     — WebFetch / WebSearch로 채용공고/docs 수집
[2] Verbatim 추출    — 정확한 quote + URL + 조회 날짜 기록 (LLM 환각 차단)
[3] 정규화           — 산업 표준명 매핑 ("MvRx" → "unidirectional-arch")
[4] 그래프 매핑      — 기존 노드 보강 vs 신규 노드 추가 결정
[5] Frontmatter stub — 9축 게이트 자동 만족 형태로 생성
```
각 단계 산출물은 다음 단계 입력 — 단계 건너뛰기 금지.

### IF Research Level 분기 결정 (Plan)
| Level | 적용 조건 | 도구 | 비용 |
|---|---|---|---|
| **L1 직접** | RFC/ANSI/장기 안정 spec, 잘 알려진 패턴 | 직접 작성 + URL 인용 | 0 |
| **L2 research** | 6개월 내 변경 가능, 멀티 벤더 분기, fork 식별 필요 | `harness-document-specialist` agent 1회 | 중 (~30k token, ~90s) |
| **L3 debate** | 아키텍처 결정, 팀 합의 필요, 비용 비대칭 큼 | `/harness-debate` Planner-Critic-Architect | 고 |

### IF 그래프 매핑 결정 (Plan)
- 기존 노드 부분 보강 → `Edit`으로 절 추가 (legacy frontmatter 안 건드림)
- 신규 도메인 → 새 디렉토리 + `_index.md` + 화이트리스트 prefix 등록
- 중간 (기존 도메인에 새 측면) → 신규 노드 + `requires:`로 기존 노드 cross-ref

### IF 회귀 검증 실패 (Debug)
1. `python tests/test_skill_quality_axes.py` 9 unit test 먼저 — validator 자체 회귀 차단
2. `run_validator('skill_quality_axes')` 출력에서 게이트 식별
3. 가장 흔한 fail: **G7 axes-table missing label** (한국어 라벨 단축형 vs main label 혼용)

## 5단계 파이프라인 상세

**P1 Crawl** — WebFetch 우선, JS-heavy 페이지는 aggregator 미러(himalayas.app/echojobs.io). 본문 비면(`job_description: ""`) 다른 미러로 fallback. 직군 lane별 ≥ 3개로 패턴 식별.

**P2 Verbatim** — 형식 `"<exact quote>" — <https URL> (조회 YYYY-MM-DD)`. LLM paraphrase 차단. 같은 사실은 2 출처 cross-validation. http는 G6 자동 차단.

**P3 정규화** — 회사 내부 명칭 → 산업 표준명: `MvRx/Circuit→unidirectional-arch`, `Titus→k8s-runtime`, `Atlas→metrics-backend`, `Stripe Workflow→durable-execution`. 다른 회사 시그널 재사용 가능.

**P4 그래프 매핑** — `Grep` 또는 frontmatter `name:` 인덱스로 기존 노드 검색. 보강은 작은 PR, 신규는 `_index.md` + 4-7개 묶음(1개짜리 디렉토리 금지).

**P5 Frontmatter stub** — 10필드 + opt-in flag:
```yaml
name: <kebab-case>
description: <한 문장 matcher 신호>
keywords: <공백 구분>
intent: <verb-noun>
requires: <기존 name 또는 stem>
phase: plan implement review
tech-stack: any
min_score: 2
quality_axes_enforced: true   # _common/ 위치 시 명시
```

## 가이드

- L2 research agent는 `harness-document-specialist`가 default — 외부 docs 인용 + 출처 명시 + 환각 회피 가이드 내장.
- 표본은 직군 lane당 3-5개로 충분. 16개 → 30개 늘려도 한계효용 떨어짐 (Netflix 케이스에서 실증).
- `_common/`은 항상 로드되므로 토큰 예산 가장 보수적 (≤ 8KB) — 도메인별 디렉토리는 stack 매칭 시만 로드.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | verbatim quote + URL + 날짜 3종으로 사실 정합성 추적 |
| 성능 효율성 | 250 lines / 8KB 예산으로 토큰 비용 통제 |
| 호환성 | 신규 노드 wear-down 정책으로 기존 80+ legacy 영향 0 |
| 사용성 | 5단계 파이프라인 명문화로 누구나 동일 절차 재현 |
| 신뢰성 | 9 unit test + validator 회귀로 추가 시점에 게이트 자동 작동 |
| 보안 | https only Source + 시크릿 패턴 grep 차단 |
| 유지보수성 | 기존 schema 100% 준수 (frontmatter 락) — 호환 깨지지 않음 |
| 이식성 | Stripe/Uber/Airbnb 등 다른 회사 채용 시그널에 동일 절차 즉시 적용 |
| 확장성 | 새 enforce 영역은 prefix 1줄 또는 frontmatter flag 1줄로 추가 |

## Gotchas

### 직접 작성(L1) 후 환각 발견
빠르게 변하는 영역(Flink 2.0, Trino 480, Karpenter v1)을 L1으로 쓰면 옛 docs 기반 잘못된 default 값 인용 위험. Volatility 판정에서 6개월 변동 의심되면 **L2 강제**.

### Verbatim quote 형식 누락
Source 절에 URL만 있고 quote 없으면 G1 통과해도 **추적성 깨짐** — 다음 검증자가 quote 위치 못 찾음. `"<exact quote>" — <URL> (조회 YYYY-MM-DD)` 형식 강제.

### `_common/` 추가 시 quality_axes_enforced 누락
`_common/`은 MANDATORY_PREFIXES 외라 game enforce 안 됨. 신규 추출 노드는 frontmatter `quality_axes_enforced: true` 명시 안 하면 9게이트 보호 못 받음.

### 회사 내부 명칭을 그대로 keyword로
"netflix-titus" 같은 keyword는 다른 회사 사용 시 매칭 실패. Phase 3 정규화에서 산업 표준명("k8s-runtime")으로 변환.

### 1개짜리 디렉토리 신설
`infra/spinnaker-pipeline.md` 하나만 두고 디렉토리 만들면 매칭 점수 분산. 4-7개 묶음 형성 후 디렉토리 만든다 (도메인 cohesion).

### legacy 노드 손대기
80+ legacy `_common/` 노드의 frontmatter나 본문 절을 수정하면 wear-down 정책 깨짐 — 다른 매칭 회귀 위험. 신규 노드만 추가, legacy는 grandfathered.

## Source

- https://iso25000.com/index.php/en/iso-25000-standards/iso-25010 — ISO/IEC 25010 9 quality characteristics 정의 (functional suitability, performance efficiency, compatibility, usability, reliability, security, maintainability, portability, extensibility), 조회 2026-05-10
- https://himalayas.app/companies/netflix/jobs — Netflix 직군 lane 카탈로그, Phase 1 source crawl 사례, 조회 2026-05-10
- https://docs.anthropic.com/en/docs/agents-and-tools/agent-sdk — Agent SDK 패턴 (research-augmented 분기 근거), 조회 2026-05-10
- file:////home/user/.claude/scripts/validators/skill_quality_axes.py — 9게이트 validator 본 환경 구현 (이 스킬과 동기화), 조회 2026-05-10
- file:////home/user/.claude/skills/_common/_template.md — frontmatter schema lock (locked schema, fixplan-meta debate Gen4 W13), 조회 2026-05-10
