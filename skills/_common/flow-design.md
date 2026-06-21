---
keywords: 플로우 flow 흐름도 flowchart 시퀀스 sequence 유저플로우 userflow 기능흐름 functional-flow 상태전이 state-transition 머메이드 mermaid 시각화 visualize 기능플로우 기능설계
intent: 플로우차트그려 시퀀스다이어그램해 유저플로우만들어 기능흐름시각화해 상태전이그려 플로우만들어 플로우해 흐름설계해
paths: design/ flows/ .claude/design/flows/
patterns: mermaid flowchart sequenceDiagram stateDiagram-v2
requires: doc-writer context-docs
phase: plan
min_score: 3
---

# 기능 플로우차트 설계 가이드 (파이프라인 3단계)

> 원칙: **PRD의 시각적 검증** — 글로 정리한 요구사항을 다이어그램으로 변환하여 누락/모순 발견
> 템플릿: `~/.claude/templates/flowchart/` (3파일: README, _domain-template, system-overview)
> SSOT: PRD가 원본, 플로우차트는 파생물. 새 요구사항을 플로우차트에 추가하지 않는다.
> 검증: 작성 완료 후 `doc-verify` 스킬로 US/AC ↔ 플로우 크로스 검증

## 의사결정 트리

### IF 새 프로젝트 플로우차트 작성 (Plan)
1. PRD 완성 확인 (doc-verify PASS 필수 — 선행 조건)
2. **Gray Areas 도출** — 각 도메인별 PRD에 명시되지 않은 결정 사항 식별 (아래 Gray Areas 가이드 참고)
3. 시스템 개요 플로우 작성 (system-overview.md)
4. 도메인별 플로우차트 작성 (PRD 도메인 파일 1개 = 플로우 파일 1개)
5. 추적성 매트릭스 완성 (US ID ↔ 플로우 노드)
6. doc-verify 크로스 검증 실행

### IF 기존 플로우차트에 도메인 추가 (Plan)
1. _domain-template.md 복사 → 새 도메인 플로우 파일 생성
2. PRD 도메인 파일 Read → 플로우 작성
3. system-overview.md 업데이트 (도메인 간 연결)
4. 추적성 매트릭스 추가

### IF PRD 수정 후 플로우차트 동기화 (Plan)
1. 변경된 PRD 도메인 파일 Read
2. 대응하는 플로우 파일 수정
3. 추적성 매트릭스 재확인
4. 크로스 검증 재실행

## 다이어그램 3종과 PRD 매핑

| 다이어그램 | PRD 원본 | 변환 규칙 |
|-----------|---------|----------|
| `flowchart` (유저 플로우) | US의 AS/I WANT + AC의 Given/Then | US 1개 = flowchart 1개. 성공 AC → happy path, 에러 AC → 에러 분기 |
| `sequenceDiagram` (시스템 시퀀스) | AC의 When (API 엔드포인트) | API 1개 = sequence 1개. alt/else로 성공+에러 포함 |
| `stateDiagram-v2` (상태 전이) | 도메인의 "상태 전이 규칙" | 텍스트 규칙 → Mermaid 노드. 허용+금지 전이 모두 |

## 작성 순서

```
Phase 1: system-overview.md
  context.md 페르소나 → 역할별 진입 플로우
  architecture.md → 도메인 간 연결 + 시스템 아키텍처 시퀀스
  ※ 전체 조감도. 세부 분기는 포함하지 않는다.

Phase 2: 도메인별 플로우 (의존성 없는 것부터)
  PRD domain/*.md Read → 유저 플로우 + 시스템 시퀀스 + 상태 전이
  추적성 매트릭스 작성
  ※ 도메인 간 의존 관계 = system-overview의 의존성 방향

Phase 3: 크로스 검증
  doc-verify 스킬로 US/AC ↔ 플로우 1:1 대조
```

## 템플릿 사용법

### 1. 프로젝트에 복사
```bash
mkdir -p <프로젝트>/.claude/design/flows/
cp ~/.claude/templates/flowchart/system-overview.md <프로젝트>/.claude/design/flows/00-system-overview.md
```

### 2. 도메인별 파일 생성
```bash
cd <프로젝트>/.claude/design/flows/
cp ~/.claude/templates/flowchart/_domain-template.md user.md
cp ~/.claude/templates/flowchart/_domain-template.md order.md
# PRD 도메인 수만큼 반복
```

### 3. PRD → 플로우 변환 절차

#### 유저 플로우 (flowchart)
```
PRD US:  AS 구매자 I WANT 상품을 장바구니에 담기 SO THAT 나중에 한번에 구매
PRD AC:  Given 로그인 상태 When POST /api/cart Then 201 + 장바구니 아이템
         Given 재고 0 When POST /api/cart Then 400 + "재고 부족"
         Given 미로그인 When POST /api/cart Then 401

변환 →

flowchart TD
    A["상품 상세 페이지"] --> B{"로그인 여부"}
    B -->|"미로그인"| C["401 Unauthorized"]
    B -->|"로그인됨"| D{"재고 확인"}
    D -->|"재고 > 0"| E["장바구니 담기 성공 (201)"]
    D -->|"재고 = 0"| F["400 재고 부족"]
```

#### 시스템 시퀀스 (sequenceDiagram)
```
PRD AC의 When:  POST /api/cart
PRD 기능 상세:  재고 확인 → 장바구니 저장 → 이벤트 발행

변환 →

sequenceDiagram
    actor User
    participant FE as Frontend
    participant BE as Backend
    participant DB as Database

    User->>FE: 장바구니 담기 클릭
    FE->>BE: POST /api/cart
    alt 재고 충분
        BE->>DB: SELECT stock FROM products
        BE->>DB: INSERT INTO cart_items
        BE-->>FE: 201 Created
    else 재고 부족
        BE->>DB: SELECT stock FROM products
        BE-->>FE: 400 Bad Request
    end
```

#### 상태 전이 (stateDiagram-v2)
```
PRD 상태 전이 규칙:
  [*] → PENDING : 주문 생성
  PENDING → PAID : 결제 성공
  금지: CANCELED → PAID

변환 →

stateDiagram-v2
    [*] --> PENDING: 주문 생성
    PENDING --> PAID: 결제 성공

    note right of CANCELED
        금지: CANCELED → PAID (취소 후 결제 불가)
    end note
```

## 파일 구조

```
project/.claude/design/flows/
├── 00-system-overview.md    # 역할별 진입 + 도메인 간 연결
├── user.md                  # 사용자 도메인 (회원가입/로그인/프로필)
├── product.md               # 상품 도메인 (CRUD/검색/카테고리)
├── order.md                 # 주문 도메인 (주문/취소/상태)
├── payment.md               # 결제 도메인 (결제/환불)
└── ...                      # PRD 도메인 수만큼
```

## 렌더링 방법

### 1. GitHub
```mermaid 블록은 GitHub markdown에서 자동 렌더링.

### 2. Playwright MCP (자동 스크린샷)
1. mermaid.live에 코드 로드
2. `browser_take_screenshot`으로 캡처
3. 캡처 이미지를 `.claude/design/screenshots/`에 저장

### 3. VS Code
`Markdown Preview Mermaid Support` 확장 설치 → .md 파일 미리보기.

## Gray Areas 가이드 (GSD discuss 흡수)

플로우차트 작성 전, 각 도메인의 PRD를 읽고 다음을 도출:

### 도출 방법
1. PRD의 각 US/AC를 읽으며 "이것만으로 구현할 수 있는가?" 질문
2. 암묵적 가정 식별 (예: "다중 판매자 주문 분리 여부"가 PRD에 없음)
3. 에러 케이스의 경계 조건 (예: "0원 주문 시 결제 스킵?")
4. 동시성/타이밍 이슈 (예: "타임아웃 취소와 결제 동시 발생")

### 산출물: {도메인}-gray-areas.md
```markdown
| # | 질문 | 추론/가정 | 근거 |
|---|------|----------|------|
| GA-01 | 다중 판매자 주문 분리? | 1주문 1판매자 | OrderCreated sellerId 단수 |
```

### 결정 기록
- 각 Gray Area에 대해 결정(가정)을 기록하고 근거를 명시
- 결정된 사항은 플로우차트에 반영
- 미결정 사항은 Deferred로 표시하여 추후 논의

## Gotchas

### 플로우차트에서 요구사항 추가
PRD에 없는 분기/경로를 플로우차트에 그리면 SSOT 위반. 누락 발견 시 PRD를 먼저 수정.

### 너무 상세한 유저 플로우
모든 에러 케이스를 하나의 flowchart에 넣으면 가독성 저하. US 단위로 분리하고, 복잡한 US는 happy path / error path를 별도 flowchart로 분리.

### API URL 불일치
sequenceDiagram의 API 경로가 PRD AC의 When 절과 다르면 크로스 검증에서 FAIL. PRD의 URL을 그대로 복사.

### 상태 전이 누락
PRD의 금지 전이를 stateDiagram에 안 넣으면 검증 FAIL. note 블록으로 금지 전이도 시각화.

### Mermaid 문법 에러
노드명에 특수문자 → 큰따옴표 감싸기: `A["주문(Order)"]`.
sequenceDiagram participant에 한글 사용 시 alias 패턴: `participant BE as 백엔드`.

## 도구 사용 패턴 (Harness)
- PRD 읽기: `Read`로 도메인 파일 + architecture.md
- 플로우 작성: `Write`로 .md 파일에 Mermaid 블록 작성
- 시각 검증: Playwright MCP로 mermaid.live 렌더링 → 스크린샷
- 크로스 검증: `doc-verify` 스킬 실행 (US/AC ↔ 플로우 대조)

## 에러 복구 패턴 (Harness)
- US 커버리지 누락 → PRD 도메인 파일의 US 목록 전수 조사 → 누락 플로우 추가
- API URL 불일치 → PRD AC의 When 절에서 URL 복사 → sequenceDiagram 수정
- 상태 전이 불일치 → PRD 상태 전이 규칙 원문 대조 → stateDiagram 수정
- 고아 노드 → 추적성 매트릭스에서 US 역추적 불가 노드 제거
