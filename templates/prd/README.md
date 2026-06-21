# PRD 템플릿 사용 가이드

## 구조
```
templates/prd/
├── README.md              ← 이 파일
├── index.md               ← 문서 맵 + 기술 스택 요약
├── context.md             ← 문제 정의, 목표, 페르소나, 범위
├── domain/
│   └── _template.md       ← 도메인별 US + AC 템플릿 (복사해서 사용)
├── nfr.md                 ← 비기능 요구사항 (ISO 25010 8속성)
├── architecture.md        ← 이벤트/캐시/제약/역할 매트릭스
├── risks.md               ← 리스크/의존성/가정/거부된 대안
├── glossary.md            ← 용어 정의
└── changelog.md           ← 변경 이력
```

## 사용법

### 1. 프로젝트에 복사
```bash
cp -r ~/.claude/templates/prd/ <프로젝트>/.claude/requirements/
```

### 2. 도메인 파일 생성
`domain/_template.md`를 도메인별로 복사:
```bash
cd <프로젝트>/.claude/requirements/domain/
cp _template.md user.md
cp _template.md product.md
cp _template.md order.md
# ... 도메인 수만큼 반복
```

### 3. {{플레이스홀더}} 채우기
모든 `{{...}}`를 실제 내용으로 교체. 작성 완료 후 HTML 주석 체크리스트 삭제.

### 4. 검증
doc-verify.md 스킬의 5 Quality Gates로 검증:
- Gate 1: 구조 완성도 (TCPF = 1.0, TBD = 0)
- Gate 2: 언어 품질 (금지어 = 0, Ambiguity Index = 0.0)
- Gate 3: 추적성 (SSOT 일치, 역할 매트릭스 완전)
- Gate 4: 의미 완성도 (Fresh Agent 이진 체크리스트)
- Gate 5: 리뷰 수렴 (DDR < 0.1)

## 설계 원칙

### 검증 에이전트 최적화 구조
이 트리 구조는 Fresh Agent(독립 검증 에이전트)가 체계적으로 검증할 수 있도록 설계됨:

1. **파일 = 검증 단위** — 에이전트가 파일 단위로 Read하며 체크
2. **SSOT 교차 검증** — domain/*.md ↔ architecture.md 대조 (notification.md는 해당 시)
3. **TCPF 매핑** — doc-verify.md의 필수 섹션 10개 = 파일 구조와 1:1 매핑
4. **Grep 자동화** — US-ID, Given/When/Then, TBD 등 패턴 스캔 가능

### 에러 AC 쌍 규칙
모든 성공 AC에는 반드시 대응하는 에러 AC를 함께 작성:
- **400**: 유효성 검증 실패 (빈 필드, 형식 오류)
- **404**: 리소스 미존재 (+ 타인 리소스 접근 정책에 따라)
- **403**: 권한 없음
- **409**: 충돌/중복

### SSOT 분배 규칙
도메인 파일 수정 시 반드시 연쇄 업데이트 확인:
- architecture.md → 이벤트 목록, 동기/비동기 경계, 역할 매트릭스
- notification.md (있는 경우) → 알림 매핑 테이블
- glossary.md → 새 용어 정의
- nfr.md → 새 API 권한/성능 요건

## 참조 구현
이커머스 PRD: `<project>/.claude/requirements/` (참조 구현)
- 10개 도메인, 28개 US, 21차 검증 완료 (v3.8)
- 이 템플릿의 실제 적용 사례
