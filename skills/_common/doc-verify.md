---
keywords: 검증 verify verification 리뷰 review 품질 quality 모호성 ambiguity 독립 independent 크로스체크 crosscheck 신선한 fresh 평가 evaluate 완성도 completeness 일관성 consistency 게이트 gate DDR
intent: 문서검증해 PRD리뷰해 명세평가해 완성도체크해 크로스검증해 검증해 문서검증해 확인해
paths: docs/ design/ .claude/ requirements spec
patterns: requirements specification acceptance-criteria user-story checklist verification given-when-then
requires: context-docs doc-writer
phase: plan review
min_score: 3
---

# 독립 에이전트 문서 검증 가이드 (Fresh Agent Verification)

> 원칙: **구현자와 검증자의 분리** — 같은 에이전트가 만들고 검증하지 않는다.
> 품질 표준: IEEE 830 + ISO/IEC/IEEE 29148:2018 + NASA Appendix C
> 핵심 혁신: **주관적 0-10점 → 이진 품질 게이트 (PASS/FAIL)**
> 수렴 판정: Fagan Inspection DDR (Defect Discovery Rate) 기반 리뷰 중단 기준

## 의사결정 트리

### IF 설계 문서 검증 (Plan)
1. 문서 작성 완료
2. **Gate 1-3 자동 검증** 실행 (Grep 기반)
3. **Gate 4 Fresh Agent 검증** 실행 (독립 에이전트)
4. **Gate 5 수렴 판정** — DDR < 0.1이면 리뷰 종료
5. 모든 Gate PASS 시 다음 단계 진행

### IF 구현물 검증 (Review)
1. 구현 완료
2. **명세 대조 검증** 실행 (Spec Verification)
3. 불일치 항목 수정 → 재검증

## 5 Quality Gates (모두 PASS 필수)

주관적 점수(0-10)를 **이진 판정(PASS/FAIL)**으로 대체. 각 게이트의 기준은 측정 가능하며 자동화 가능.

### Gate 1: 구조 완성도 (자동)
| # | 체크 항목 | PASS 기준 | 측정 방법 |
|---|----------|----------|----------|
| G1-1 | 필수 섹션 존재 | TCPF = 1.0 (12개 섹션 전부) | Grep으로 섹션 헤더 존재 확인 |
| G1-2 | TBD 항목 없음 | TBD Count = 0 | `Grep("TBD\|TODO\|미정\|추후")` |
| G1-3 | 모든 US에 고유 ID | 미번호 US = 0 | `Grep("US-[0-9]")` 수 = US 총 수 |
| G1-4 | AS/I WANT/SO THAT | 누락 US = 0 | Grep 패턴 매칭 |
| G1-5 | Given/When/Then AC | 누락 AC = 0 (성공+에러 쌍) | Grep 패턴 매칭 |
| G1-6 | 상태 전이 규칙 | 초기 상태 + 허용 + 금지 전이 | `Grep("\\[\\*\\]")` 도메인 수 일치 |
| G1-7 | Kafka/Redis 명세 | Producer/Consumer/토픽, 키/TTL/무효화 | Grep으로 섹션 존재 확인 |

### Gate 2: 언어 품질 (자동 — 금지어 스캔)
**금지어가 1개라도 있으면 FAIL** (IEEE 830 Unambiguous + NASA Appendix C)

`Ambiguity Index = (금지어 포함 요구사항 수) / (전체 요구사항 수)` → **목표: 0.0**

**금지어 카탈로그**:
| 카테고리 | 금지어 (한국어) | 금지어 (영어) |
|---------|---------------|--------------|
| 모호한 정도 | 적절한, 충분한, 일반적으로, 가능하면, 필요시, 등 | adequate, sufficient, typically, as appropriate, if necessary, etc. |
| 측정 불가 성능 | 빠르게, 효율적으로, 쉽게, 적시에 | fast, efficient, easy, timely, prompt |
| 약한 동사 | 처리한다, 관리한다, 지원한다, 제공한다 | handle, manage, support, provide, process |
| 약한 조동사 | ~할 수 있다, ~일 수도, ~해야 할 것 | should, could, might, may, possibly |
| 모호한 수량 | 일부, 여러, 많은, 약, 대략 | some, several, many, about, approximately |
| 불완전 열거 | 등, 기타, 및/또는 | etc., and/or, but not limited to |
| 모호한 대명사 | 이것, 그것, 저것 (지시 대상 불명확) | it, this, that, they (without clear antecedent) |

**예외**: AC의 Given/When/Then 내부 조건문에서 사용되는 "~할 수 있다"는 허용 (능력 기술). 금지어가 **요구사항 본문**(기능 상세, 비기능 요구사항)에 있는 경우만 FAIL.

### Gate 3: 추적성 (반자동)
| # | 체크 항목 | PASS 기준 | 측정 방법 |
|---|----------|----------|----------|
| G3-1 | 고아 요구사항 없음 | Orphan Ratio = 0.0 | 각 US가 상위(context.md 기능) + 하위(AC) 연결 |
| G3-2 | SSOT 일관성 | 불일치 쌍 = 0 | 이벤트 매핑: domain/*.md ↔ architecture.md (그리고 프로젝트가 notification.md를 채택했다면 ↔ notification.md). notification.md 미채택 프로젝트는 architecture.md만 검사. |
| G3-3 | 역할 매트릭스 완전 | 누락 엔드포인트 = 0 | 각 US의 API ↔ architecture.md 역할 매트릭스 대조 |
| G3-4 | 용어집 완전 | 미정의 용어 = 0 | 본문 전문 용어 ↔ glossary.md 대조 |
| G3-5 | 에러 코드 통일 | 형식 불일치 = 0 | 모든 에러 AC에 `{ status, code, message }` 구조 |

### Gate 4: 의미 완성도 (수동 — Fresh Agent)
독립 에이전트가 문서만 읽고 **이진 체크리스트**로 검증:

| # | 체크 항목 | PASS 기준 |
|---|----------|----------|
| G4-1 | CRUD 시나리오 완전 | 모든 역할의 모든 리소스에 CRUD + 목록(정렬/필터/페이징) |
| G4-2 | 상태 전이 완전 | 모든 도메인의 초기 + 허용 + 금지 + 전이 조건 |
| G4-3 | 에러 AC 쌍 완전 | 모든 성공 AC에 대응하는 에러 AC (404/400/403/409) |
| G4-4 | 동시성 제어 정의 | 재고/쿠폰/결제/장바구니 등 경합 자원에 제어 전략 명시 |
| G4-5 | 도메인 간 흐름 완전 | 주문→결제→배송→알림 경로에 끊김 없음 |
| G4-6 | 권한 정책 통일 | 타인 리소스 접근 정책 일관 (404 vs 403) |
| G4-7 | 스코프 제외 문서화 | 미지원 기능에 제외 항목 + 사유 + 재검토 트리거 |
| G4-8 | 모순 쌍 없음 | 문서 간 상충하는 진술 = 0 |

### Gate 5: 리뷰 수렴 (DDR 기반 종료 판정)
**Defect Discovery Rate (DDR)** — 리뷰를 언제 멈출지 결정하는 수학적 기준.

```
DDR(n) = (라운드 n에서 발견된 새 이슈 수) / (라운드 n-1에서 발견된 새 이슈 수)
```

| DDR 값 | 판정 | 행동 |
|--------|------|------|
| DDR ≥ 0.5 | 초기 단계 | 계속 리뷰 (아직 많이 남음) |
| 0.1 ≤ DDR < 0.5 | 수렴 중 | 계속 리뷰 (감소 추세) |
| **DDR < 0.1** | **수렴 완료** | **리뷰 종료** — 추가 리뷰의 ROI 부족 |
| DDR = 0.0 | 완전 수렴 | 새 이슈 0개, 즉시 종료 |

**실전 예시**:
```
라운드 1: 20개 이슈 발견 (DDR = N/A, 첫 라운드)
라운드 2:  8개 새 이슈 (DDR = 8/20 = 0.40 → 계속)
라운드 3:  3개 새 이슈 (DDR = 3/8  = 0.38 → 계속)
라운드 4:  1개 새 이슈 (DDR = 1/3  = 0.33 → 계속)
라운드 5:  0개 새 이슈 (DDR = 0/1  = 0.00 → 종료)
```

**중요**: DDR이 비단조적(3→5→2)인 경우 = 수정이 새 이슈를 생성함. 이 경우 SSOT 분배 누락이 원인. 수정 시 연쇄 파일 업데이트 필수.

## 모드 분기 — Forward (신규) vs Reverse (역설계)

본 스킬은 두 종류의 PRD를 검증한다. 검증 기준은 동일하지만 일부 Gate의 평가 방식이 다르다.

| 모드 | 대상 | 활성화 조건 |
|------|------|-----------|
| **Forward (default)** | 신규 시스템 설계 PRD — `kha-new-project`, `harness-debate` 산출물 | 본 섹션의 별도 활성화 표기 없음. **기본값**. |
| **Reverse** | 역설계 분석 PRD — `harness-reverse-prd` 산출물 (예: `<프로젝트>-analysis/`) | PRD 루트 `README.md` 또는 `index.md`에 `mode: reverse-engineering` 메타 라인 명시, **또는** `> ⚠️ 역설계 추정` 블록과 GitHub 피닝 커밋 링크가 모두 ≥3건 발견되면 자동 감지 |

### Reverse 모드의 Gate 1 예외

역설계 PRD는 원본 코드의 **미구현/예약된 자리**를 정확히 묘사한다. 이를 PRD 자체의 미작성으로 잘못 판정하지 않도록 G1-2에 예외 규칙 적용.

**G1-2 예외 (Reverse 모드 한정)**:

다음 패턴은 TBD 카운트에서 **제외**한다 (원본 코드 상태 인용이지 PRD의 미정이 아님):

| 패턴 | 의미 | 예시 위치 |
|------|------|----------|
| `(현재 트리거 없음 — 자리만 정의)` | enum/포트만 정의되고 호출 코드 부재 | `architecture.md` 매트릭스 셀 |
| `enum 미정의` / `미정의 action` | 원본 코드에서 명시되지 않은 식별자 | 도메인 PRD 에러 AC |
| `(미구현)` / `빈 응답만 리턴` | 원본 service 메서드가 placeholder | 도메인 PRD 동시성 표 |
| `**Then (예정)**: ...` | 향후 구현 흐름 추정 (현재 흐름과 한 쌍) | 도메인 AC Given/When/Then |
| `1-C에서 작성` / `1-B에서 반영` | 릴리즈 단위 점진 작성 체크포인트 | 연관 문서 갱신 체크 |
| 코드 인용 백틱 안의 `// TODO: ...` | 원본 코드 주석 인용 | study 노트, 도메인 PRD 본문 |

**G1-2 FAIL 조건 (Reverse 모드)**: 위 패턴 외의 TBD/TODO/미정/추후가 발견되면 PRD 자체의 미작성으로 판정.

자동 측정 방법:
```
total_tbd = Grep("TBD|TODO|미정|추후") 매칭 수
excluded = 위 6 패턴 매칭 수 (whitelist)
fail_count = total_tbd - excluded
PASS 기준: fail_count == 0
```

### Reverse 모드의 Gate 4 예외

#### G4-1 변형 — "외부 인터페이스 커버리지"

Forward 모드: "모든 역할의 모든 리소스에 CRUD + 목록(정렬/필터/페이징)"

Reverse 모드: "모든 외부 인터페이스(HTTP endpoint + WebSocket action + 이벤트 토픽)가 도메인 US에 매핑됨". CRUD 패턴이 적용되지 않는 도메인(라우터/게이트웨이/스트림 처리)이 있으면 인터페이스 커버리지로 평가.

#### G4-3 변형 — "(예정)" AC 패턴 인식

Forward 모드: 모든 성공 AC에 대응하는 에러 AC (404/400/403/409)

Reverse 모드: 다음 패턴을 1쌍 AC로 인정한다:
```
**Success (예정) — AC-XXX-S01**
  Given ... When ... Then (예정): 향후 흐름
  Then (현재): 현재 빈 응답

**Error (입력) — AC-XXX-E01**
  Given ... When ... Then ...
```

"예정/현재" 한 쌍은 미구현 비즈니스 로직과 현재 동작을 함께 명시한 형태이며 에러 AC는 별도로 존재해야 한다. "(예정)"만 있고 에러 AC가 없으면 FAIL.

### Reverse 모드의 활성화 메타 라인

PRD 루트에 다음 형식으로 명시 (권장):

```yaml
# 또는 README.md 첫 섹션 표에:
| 모드 | reverse-engineering |
| 원본 레포 | https://github.com/{org}/{repo} |
| 피닝 커밋 | <40-char SHA> |
```

검증 에이전트는 이 메타 라인을 보고 Gate 1/4의 평가 기준을 분기한다.

### Reverse 모드 검증 보고서

`DOC-VERIFY-REPORT.md`에 모드 명시 + Forward 대비 변형된 Gate 항목을 표기. 예시: `<프로젝트>-analysis/DOC-VERIFY-REPORT.md` (Round 1 11/11 PASS, DDR 0.0).

## PRD 필수 섹션 (TCPF 체크리스트)

> **템플릿**: `~/.claude/templates/prd/` — 새 프로젝트는 이 템플릿을 복사하여 시작
> **참조 구현**: `ecommerce/.claude/requirements/` — 10도메인/28 US/21차 검증 완료

| # | 섹션 | 템플릿 파일 | PASS 기준 |
|---|------|-----------|----------|
| 1 | Problem Statement | context.md §1 | 문제 정의 + 데이터 근거 + 해결 방향 |
| 2 | Goals & Metrics | context.md §2 | 정량적 KPI + 선행/후행 지표 + 기준선 + 벤치마크 |
| 3 | Personas | context.md §3 | 역할별 니즈/페인포인트 + 대표 프로필 (모든 역할) |
| 4 | Scope | context.md §4 | In-Scope + Non-Goals(사유) + Rejected Alternatives(사유 + 재검토 트리거) |
| 5 | User Stories + AC | domain/_template.md | AS/I WANT/SO THAT + Given/When/Then (성공 + 에러 쌍) |
| 6 | NFRs | nfr.md | ISO 25010 8개 속성 + 측정 수치 + 측정 주기 |
| 7 | Architecture | architecture.md | 이벤트 흐름 + 캐시 전략 + 동기/비동기 분리 + 역할 매트릭스 |
| 8 | Risks | risks.md | 리스크 매트릭스(확률%×영향) + 완화 전략 + 잔여 위험 |
| 9 | Glossary | glossary.md | 비즈니스 + 기술 용어 정의 |
| 10 | Changelog | changelog.md | 버전 + 날짜 + 변경 내용 |

## Fresh Agent 검증 프로토콜

### 핵심 원칙
- 검증 에이전트는 **작성 과정의 컨텍스트를 일절 모른다**
- 오직 **문서 자체**와 **검증 기준**만 제공받는다
- 검증 에이전트의 혼란/질문 = 문서의 모호성

### 실행 방법 (트리 구조 문서용)

```
Agent(subagent_type="general-purpose", prompt="""
당신은 독립 검증 에이전트입니다. 이전 대화의 맥락을 전혀 모릅니다.
아래 문서들을 순서대로 전부 읽은 뒤, 체크리스트 항목별로 PASS/FAIL 판정하세요.

## 검증 대상 (트리 구조 — 모두 Read)
1. [root]/index.md ~ 16. [root]/changelog.md

## 체크리스트 (모든 항목 PASS 필수)

### Gate 1: 구조 완성도
- [ ] G1-1: 필수 섹션 10개 전부 존재
- [ ] G1-2: TBD/TODO/미정/추후 = 0개
- [ ] G1-3: 모든 US에 고유 ID (US-XXX)
- [ ] G1-4: 모든 US에 AS/I WANT/SO THAT
- [ ] G1-5: 모든 US에 Given/When/Then AC (성공+에러 쌍)
- [ ] G1-6: 상태 있는 모든 도메인에 초기 상태([*]→) + 허용/금지 전이
- [ ] G1-7: Kafka 이벤트에 Producer/Consumer/토픽, Redis에 키/TTL/무효화

### Gate 3: 추적성
- [ ] G3-1: 모든 US가 상위 기능과 연결 (고아 없음)
- [ ] G3-2: domain/*.md 이벤트 ↔ architecture.md 일치 (그리고 프로젝트가 notification.md를 채택했다면 ↔ notification.md도 일치)
- [ ] G3-3: 모든 API 엔드포인트가 역할 매트릭스에 존재
- [ ] G3-4: 본문 전문 용어가 glossary.md에 정의됨
- [ ] G3-5: 모든 에러 AC가 { status, code, message } 구조

### Gate 4: 의미 완성도
- [ ] G4-1: 모든 역할의 모든 리소스에 CRUD + 목록(정렬/필터/페이징)
- [ ] G4-2: 모든 상태 전이에 초기 + 허용 + 금지 + 전이 조건
- [ ] G4-3: 모든 성공 AC에 대응하는 에러 AC (404/400/403/409)
- [ ] G4-4: 경합 자원(재고/쿠폰/결제/장바구니)에 동시성 제어 전략
- [ ] G4-5: 주문→결제→배송→알림 흐름에 끊김 없음
- [ ] G4-6: 타인 리소스 접근 정책 일관 (전 도메인 통일)
- [ ] G4-7: 미지원 기능에 제외 항목 + 사유 + 재검토 트리거
- [ ] G4-8: 문서 간 상충하는 진술 = 0

## 출력 형식

### 판정 결과
G1-1: PASS/FAIL — (근거 1줄)
...
G4-8: PASS/FAIL — (근거 1줄)

### 요약
- PASS 항목: XX/20
- FAIL 항목: XX/20 (목록)
- 발견된 이슈 (FAIL인 항목별 구체적 위치와 내용, 최대 10개)
""")
```

### 통과 기준
| 기준 | 행동 |
|------|------|
| 20/20 PASS + DDR < 0.1 | **통과** — 다음 단계 진행 |
| FAIL 항목 존재 | 이슈 수정 후 재검증 |
| DDR ≥ 0.1 | 추가 리뷰 라운드 실행 |

### 자동화 루프
```
issues_prev = ∞
round = 0

WHILE True:
  round += 1
  1. Gate 1-3 자동 검증 (Grep 기반)
  2. FAIL 있으면 수정 → SSOT 연쇄 업데이트 → GOTO 1
  3. Gate 4 Fresh Agent 검증
  4. issues_new = 발견된 이슈 수
  5. DDR = issues_new / issues_prev
  6. IF DDR < 0.1 AND 모든 Gate PASS: BREAK (리뷰 종료)
  7. 이슈 수정 → issues_prev = issues_new → GOTO 1
```

## PRD 작성 체크리스트 (반복 FAIL 방지)

### 1. 에러 AC는 성공 AC와 동시 작성
- **모든 AC는 성공/실패 쌍으로 작성**: 404, 403, 400, 409
- 예: `POST /api/orders` 성공 AC 작성 시 → 빈 items(400), 재고 부족(400), 타인 리소스(404) 에러 AC도 같이

### 2. SSOT 분배 — 한 파일 수정 시 관련 파일 모두 업데이트
DDR이 비단조적인 핵심 원인. 수정 시 반드시 확인:
- **architecture.md**: 새 API/이벤트/동기 호출 반영? (always)
- **notification.md**: 새 이벤트 추가 시 알림 매핑 테이블 반영? (**only if** 프로젝트가 notification.md를 채택했을 때)
- **glossary.md**: 새 용어 정의? (always)
- **nfr.md**: 새 API 권한/성능 요건? (always)

### 3. "v1.0 스코프 외" 3종 세트
- **제외 항목 명시**: 무엇이 빠졌는지
- **제외 사유**: 왜 빠졌는지
- **재검토 트리거**: 어떤 조건에서 재검토하는지 (정량적)

### 4. 도메인 문서 6대 체크포인트
| # | 체크포인트 | FAIL 조건 |
|---|-----------|----------|
| 1 | 정렬/필터/페이징 | 목록 API에 정렬 기준 미명시 |
| 2 | 에러 AC 쌍 | 성공 AC에 대응 에러 AC 없음 |
| 3 | 상태 전이 규칙 | 초기/허용/금지 전이 누락 |
| 4 | 동시성 제어 | 경합 자원에 제어 전략 없음 |
| 5 | 이벤트 교차 참조 | SSOT 불일치 |
| 6 | 스코프 제외 문서화 | 3종 세트 미비 |

## 크로스 검증 (문서 간 대조)
| 대조 쌍 | PASS 기준 |
|---------|----------|
| 요구사항 ↔ 플로우차트 | 모든 US가 플로우에 반영 (F1-F7 전항 PASS) |
| 플로우차트 ↔ ERD | 모든 데이터가 엔티티로 존재 (D1-D2) |
| ERD ↔ 클래스 다이어그램 ↔ DDL | 3자 대조 1:1 매핑 (D5-D9) |
| 클래스 다이어그램 ↔ 코드 | 실제 코드와 일치 |
| PRD 상태 전이 ↔ enum CHECK 값 | 모든 상태값 1:1 (D4) |
| domain/*.md ↔ architecture.md (↔ notification.md if 채택) | 이벤트 SSOT 완전 일치 — notification.md 미채택 프로젝트는 architecture.md만 검사 |

### 플로우차트 크로스 검증 프로토콜 (파이프라인 3단계)

PRD와 플로우차트 간 1:1 추적성을 검증한다. 플로우차트 템플릿: `~/.claude/templates/flowchart/`

#### 검증 기준 (모두 PASS 필수)

| # | 체크 항목 | PASS 기준 | 측정 방법 |
|---|----------|----------|----------|
| F1 | US 커버리지 | 모든 US가 최소 1개 유저 플로우에 반영 | 추적성 매트릭스에서 유저 플로우 열 빈칸 = 0 |
| F2 | 성공 경로 커버리지 | 모든 성공 AC의 happy path 존재 | AC의 Then(2XX) → flowchart 결과 노드 대조 |
| F3 | 에러 경로 커버리지 | 모든 에러 AC(400/404/403/409)가 분기 노드로 존재 | AC의 Then(4XX) → flowchart 에러 분기 대조 |
| F4 | 상태 전이 일치 | PRD 텍스트 상태 전이 = stateDiagram 노드 | 허용 전이 + 금지 전이 모두 포함 |
| F5 | API URL 일치 | sequenceDiagram의 API 경로 = PRD AC의 When 절 | URL 패턴 정확히 일치 |
| F6 | 고아 노드 없음 | 모든 플로우 노드가 US에 역추적 가능 | 추적성 매트릭스에서 역매핑 확인 |
| F7 | 도메인 간 연결 | system-overview의 도메인 간 흐름에 끊김 없음 | 도메인 목록 = PRD index.md 도메인 목록 |

#### 실행 방법 (Fresh Agent)

```
Agent(subagent_type="general-purpose", prompt="""
당신은 독립 검증 에이전트입니다. PRD 문서와 플로우차트 문서를 비교하여 일치 여부를 검증합니다.

## 검증 대상
1. PRD: [root]/requirements/ (전체 도메인 파일)
2. 플로우차트: [root]/.claude/design/flows/ (전체 도메인 플로우 파일)

## 검증 절차
1. PRD 도메인 파일에서 US ID 전체 목록 추출
2. 플로우차트 추적성 매트릭스에서 US ID 목록 추출
3. 아래 7개 항목 각각 PASS/FAIL 판정

## 체크리스트
- [ ] F1: 모든 US ID가 플로우차트 추적성 매트릭스에 존재
- [ ] F2: 모든 성공 AC(2XX)에 대응하는 flowchart happy path 존재
- [ ] F3: 모든 에러 AC(4XX)에 대응하는 flowchart 에러 분기 존재
- [ ] F4: PRD 상태 전이 텍스트 규칙 = stateDiagram 노드 (허용+금지)
- [ ] F5: sequenceDiagram API URL = PRD AC의 When 절 URL
- [ ] F6: 플로우차트의 모든 노드가 US에 역추적 가능 (고아 없음)
- [ ] F7: system-overview 도메인 목록 = PRD index.md 도메인 목록

## 출력 형식
F1: PASS/FAIL — (근거 1줄)
...
F7: PASS/FAIL — (근거 1줄)

요약:
- PASS: XX/7
- FAIL 항목 목록 + 구체적 위치와 내용
""")
```

## Spec Verification (명세 대조 검증)

구현 완료 후, 명세의 각 AC를 코드에서 검증:
```
각 US의 AC를 assertion으로 변환:
  US-001 "이메일 중복 체크"
  → Grep("email.*exist|duplicate.*email|findByEmail")
  → 존재하면 PASS, 없으면 FAIL
```

## Gotchas

### 검증 에이전트에 컨텍스트 유출
검증 프롬프트에 "이전에 논의한 대로" 같은 표현 금지. 오직 문서 경로와 체크리스트만 제공.

### DDR 비단조 현상
수정 후 이슈가 오히려 늘어나는 것은 SSOT 분배 누락이 원인. 수정 시 연쇄 파일 업데이트 체크리스트 활용.

### 금지어 오탐
AC 내부 Given/When/Then 조건문의 "~할 수 있다"는 허용 (능력 기술). 요구사항 본문의 금지어만 FAIL 처리.

### 과도한 상세화
이슈가 "구현 시 혼란을 주는가"를 기준으로 판단. 가독성 훼손 = 역효과.

### SSOT 분배 누락
도메인 파일 수정 후 notification.md/architecture.md 업데이트 누락이 반복 FAIL의 90% 원인.

## 도구 사용 패턴 (Harness)
- Gate 1-3 자동 검증: `Grep`으로 패턴 매칭 (TBD 카운트, US ID, 금지어 스캔)
- Gate 4 Fresh Agent: `Agent(subagent_type="general-purpose")` — 격리된 컨텍스트
- 크로스 검증: `Read`로 두 문서를 동시에 읽고 대조
- 명세 대조: `Grep`으로 AC 키워드를 코드에서 검색
- DDR 추적: 각 라운드 이슈 수를 기록하여 수렴 판정

## 에러 복구 패턴 (Harness)
- FAIL 항목 → 해당 파일 `Read` → `Edit` 수정 → **SSOT 연쇄 파일 확인** → 재검증
- DDR ≥ 0.1 반복 → 이슈 패턴 분석 (SSOT? 에러 AC? 상태 전이?) → 유형별 일괄 수정
- DDR 비단조 → SSOT 분배 체크리스트 실행 후 재검증
