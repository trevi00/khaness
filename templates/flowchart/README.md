# 기능 플로우차트 템플릿

> 파이프라인 3단계: PRD의 US/AC를 시각적 다이어그램으로 변환하여 누락/모순을 잡아낸다.
> Generator: `flow-design` 스킬 | Evaluator: `doc-verify` 스킬 (크로스 검증)

## 설계 원칙

1. **PRD가 SSOT** — 플로우차트는 PRD의 시각적 표현이지, 새로운 요구사항을 추가하는 곳이 아니다
2. **1:1 추적성** — 모든 US는 최소 1개 플로우 경로에, 모든 AC는 분기/결과 노드에 반영
3. **도메인별 분리** — PRD 도메인 파일 1개 = 플로우차트 파일 1개
4. **에러 경로 필수** — 성공 경로(happy path)만 그리지 않는다. 에러 AC도 분기 노드로 시각화

## 템플릿 파일

| 파일 | 용도 |
|------|------|
| `_domain-template.md` | 도메인별 플로우차트 (US → 유저플로우 + 시스템시퀀스 + 상태전이) |
| `system-overview.md` | 시스템 전체 흐름 (도메인 간 연결 개요) |

## 사용법

### 1. 프로젝트에 복사
```bash
mkdir -p <프로젝트>/.claude/design/flows/
cp ~/.claude/templates/flowchart/system-overview.md <프로젝트>/.claude/design/flows/00-system-overview.md
```

### 2. 도메인별 파일 생성
```bash
cd <프로젝트>/.claude/design/flows/
cp ~/.claude/templates/flowchart/_domain-template.md user.md
cp ~/.claude/templates/flowchart/_domain-template.md product.md
cp ~/.claude/templates/flowchart/_domain-template.md order.md
# PRD 도메인 수만큼 반복
```

### 3. PRD → 플로우차트 변환
1. PRD 도메인 파일 Read
2. US 목록 추출 → 유저 플로우 flowchart 작성
3. AC의 API 엔드포인트 추출 → 시스템 시퀀스 sequenceDiagram 작성
4. 상태 전이 규칙 추출 → stateDiagram-v2 작성
5. 추적성 매트릭스 작성 (US ID ↔ 플로우 노드)

### 4. 검증
- `doc-verify` 스킬의 플로우차트 크로스 검증 프로토콜 실행
- US 커버리지 100% + 에러 경로 100% + API URL 일치 + 상태 전이 일치

## 산출물 구조
```
project/.claude/design/flows/
├── 00-system-overview.md    # 시스템 전체: 역할별 진입 → 도메인 간 흐름
├── user.md                  # 사용자 도메인 플로우
├── product.md               # 상품 도메인 플로우
├── order.md                 # 주문 도메인 플로우
├── payment.md               # 결제 도메인 플로우
└── ...                      # PRD 도메인 수만큼
```

## Mermaid 문법 주의사항
- 노드명에 특수문자(`(`, `)`, `[`, `]`) → 큰따옴표 감싸기: `A["주문(Order)"]`
- 한글 노드명 사용 가능하나, 공백 포함 시 큰따옴표 필수
- sequenceDiagram의 participant 이름은 영문 권장 (한글 alias 가능)
- stateDiagram-v2 사용 (v1 대비 note, fork/join 지원)
