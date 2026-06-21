# 5 Gates — 자가-감사 검증 명세

> 본 파일은 verification template의 Gate 명세부. README.md에서 호출된다.
> 검증 출처: `example_project-analysis/.claude/requirements/VERIFICATION.md` Gate 1~5 + 자체 grep + manual cross-reference.

각 Gate는 **PASS / FLAG / FAIL** 3 단계. FAIL은 즉시 fix 필수. FLAG은 다음 release 전 해결 권고. PASS만 release-ready.

---

## Gate 1 — 금지어 검사

**목적**: 모호한 표현이 spec에 들어가지 않도록 차단. 구체적 수치 / 동사 / 필수-금지 명시로 교체.

### 1.1 카탈로그 (doc-writer.md `금지어 회피` 표 인용)

| 금지어 | 대체 표현 |
|---|---|
| 적절한 / 충분한 | 구체적 수치 (예: "5개 이상", "200ms 이내") |
| 빠르게 / 효율적으로 | P99 ≤ 1초 / 캐시 히트율 ≥ 80% |
| 처리한다 / 관리한다 | 구체적 동사 (생성 / 삭제 / 조회 / 변경 / 차감 / 복구) |
| ~할 수 있다 | ~한다 (필수), ~하지 않는다 (금지) |
| 등 / 기타 | 완전한 열거 ("(N종)" + 모두 나열) |

### 1.2 grep 패턴

```bash
# 금지어 9 패턴 전수 검사
rg -n "적절한|충분한|빠르게|효율적으로|처리한다|관리한다|할 수 있다|등|기타" \
   .claude/requirements/ \
   --type md --glob '!CHANGELOG.md'
```

### 1.3 면제 조건

- 코드 인용 내부 ("`enum FooKind { Bar, Etc }`")의 `등`/`기타`는 면제 — meta-text로 인정
- AC 내부 Given/When/Then 조건문의 "~할 수 있다" (능력 기술)는 면제 — 요구사항 본문만 차단

### 1.4 판정

- 위반 0 → **PASS**
- 위반 1~3 (sub-section 1개 이내) → **FLAG**
- 위반 4+ 또는 sub-section 2+ → **FAIL**

---

## Gate 2 — 페르소나 ↔ US `AS` 역할 추적성

**목적**: 모든 US의 `AS <역할>`이 `context.md` §페르소나에 명시 정의된 역할과 일치. alias 또는 외부 페르소나는 명시 등록.

### 2.1 절차

1. `context.md` §2에서 페르소나 N개 추출 (P1, P2, ... + 외부 페르소나)
2. `domain/*.md`에서 `**AS** ...` 패턴 모두 수집
3. 매칭 표 작성 (역할별 횟수 + context.md 매핑)
4. 미매핑 alias / 외부 페르소나 / 빈 owner 확인

### 2.2 grep 패턴

```bash
rg -no "^\*\*AS\*\* (.+?) I WANT" .claude/requirements/domain/ -r '$1' \
   | sort | uniq -c | sort -rn
```

### 2.3 판정

- 모든 `AS` 역할이 context.md에 매핑 → **PASS**
- alias 명시 부족 (예: "시스템"이 P2~P4 통합 alias이나 미명시) → **FLAG**
- 페르소나 미정의 (예: "clawhip" 같은 외부 컴포넌트 등록 안 됨) → **FLAG**
- AC가 페르소나 owner 없이 작성 → **FAIL**

### 2.4 Fix 정책

- alias 미명시 → context.md에 footnote 또는 P0 추가
- 외부 페르소나 미정의 → context.md §외부 페르소나 섹션 신규
- owner 없는 AC → 가장 적합한 페르소나로 재작성

---

## Gate 3 — SSOT 일관성

**목적**: 도메인 파일에서 정의한 이벤트 / 명령 / enum / API가 architecture.md / glossary.md / notification.md (옵션)에 모두 등재.

### 3.1 SSOT 분배 룰 (doc-writer.md `SSOT 분배 규칙` 인용)

| 변경 | 업데이트 대상 | 조건 |
|---|---|---|
| 새 이벤트 | architecture.md (이벤트 목록 / 페이로드 / 토픽) | always |
| 새 API | architecture.md (역할 매트릭스) | always |
| 알림 관련 이벤트 | notification.md (알림 매핑 테이블) | only if 프로젝트 채택 |
| 동기 호출 | architecture.md (동기/비동기 경계) + risks.md (내부 의존성) | always |
| 새 전문 용어 | glossary.md | always |
| 새 성능/보안 요건 | nfr.md | always |

### 3.2 grep 패턴

```bash
# 도메인의 이벤트 → architecture.md cross-reference
rg -no "\b[a-z_]+\.[a-z_]+\.[a-z_]+\b" .claude/requirements/domain/ \
   | sort -u \
   > /tmp/domain-events.txt

rg -no "\b[a-z_]+\.[a-z_]+\.[a-z_]+\b" .claude/requirements/architecture.md \
   | sort -u \
   > /tmp/arch-events.txt

comm -23 /tmp/domain-events.txt /tmp/arch-events.txt  # 도메인에만 있는 이벤트
```

### 3.3 판정

- 도메인 ↔ architecture/glossary 100% 매핑 → **PASS**
- 1~3건 누락 → **FLAG**
- 4+ 누락 또는 핵심 이벤트 누락 → **FAIL**

### 3.4 Fix 정책

- 누락 이벤트 → architecture.md §이벤트에 행 추가 (페이로드 + 토픽)
- 누락 용어 → glossary.md에 정의 추가 (1줄 정의 + 출처 도메인 링크)
- 누락 동기 호출 → risks.md §내부 의존성에 행 추가

---

## Gate 4 — 에러 AC 쌍 (성공 + 에러 동시 작성)

**목적**: 모든 성공 AC에 대응 에러 AC가 함께 작성. "나중에 에러 케이스 추가하자"는 100% 누락.

### 4.1 에러 4분류

| HTTP | 용도 | 예시 |
|---|---|---|
| 400 | 유효성 실패 | 빈 필드 / 형식 오류 / 비즈니스 규칙 위반 |
| 404 | 리소스 없음 | 존재하지 않는 ID / 타인 리소스 접근 |
| 403 | 권한 없음 | 역할 불일치 |
| 409 | 충돌 / 중복 | 이메일 중복 / UPSERT 충돌 |

### 4.2 절차

1. 각 도메인 파일에서 AC 시나리오 추출
2. 성공 AC 1개 → 에러 AC 1+ 동반 확인
3. 4분류 cover 여부 (입력 / 리소스 / 충돌 / 인프라)

### 4.3 grep 패턴

```bash
rg -c "^### AC-" .claude/requirements/domain/   # AC 개수
rg -c "^### AC-.*-E\d" .claude/requirements/domain/  # 에러 AC 개수
```

### 4.4 판정

- 모든 성공 AC에 에러 AC 동반 + 4분류 cover → **PASS**
- 에러 AC 일부 누락 (US ≤ 3개) → **FLAG**
- 에러 AC 다수 누락 또는 4분류 미cover → **FAIL**

---

## Gate 5 — Non-Goals 3종 세트

**목적**: 의도적으로 제외하는 기능은 반드시 (제외 항목 / 제외 사유 / 재검토 트리거) 3가지 명시. 재검토 트리거는 정량적이어야 한다.

### 5.1 3종 세트

```markdown
### Non-Goal-N. <기능명>

- **제외 항목**: <무엇을 빼는지>
- **제외 사유**: <왜 빼는지>
- **재검토 트리거**: <정량적 조건 예: "상품 10만 건 초과 시" / "operator 5명 이상 시" / "P95 ≥ 2초 발생 시">
```

### 5.2 grep 패턴

```bash
rg -no "^### Non-Goal" .claude/requirements/   # Non-Goal 개수
rg -A3 "^### Non-Goal" .claude/requirements/   # 본문 정량 트리거 확인
```

### 5.3 판정

- 모든 Non-Goal에 3종 세트 + 정량 트리거 → **PASS**
- 1~2건이 정성 트리거 (예: "필요해지면") → **FLAG**
- 3종 세트 미완 또는 트리거 없음 → **FAIL**

### 5.4 Fix 정책

- 정성 트리거 → 정량 (수치 / 시점 / event)으로 변환
- 트리거 없음 → "현재로서는 재검토 트리거 없음 (영구 제외)" 명시

---

## Gate 통합 — 검증 출력 표

매 release / 매 sub-task closure 시 다음 표를 `VERIFICATION.md`에 갱신:

```markdown
| Gate | 항목 | 결과 | 발견 |
|------|-----|------|------|
| 1 | 금지어 검사 | <PASS/FLAG/FAIL> | <발견 내용> |
| 2 | 페르소나 ↔ US `AS` 추적성 | <...> | <...> |
| 3 | SSOT 일관성 | <...> | <...> |
| 4 | 에러 AC 쌍 | <...> | <...> |
| 5 | Non-Goals 3종 세트 | <...> | <...> |
```

5 Gates 모두 PASS면 release-ready. FLAG는 다음 release 전 해결. FAIL은 즉시 fix.

---

## Gate 확장 (Self-improvement loop)

본 5 Gates는 v1. 추가 Gate 후보:

- **Gate 6**: 라이센스 audit (모든 외부 dep + workspace deps의 license 검증)
- **Gate 7**: 보안 CVE 검사 (`cargo audit` / `npm audit` / `pip-audit` 통합)
- **Gate 8**: 성능 baseline 측정 (P95 / P99 / throughput 정량 매트릭스)
- **Gate 9**: 호환성 매트릭스 (OS / 버전 / 외부 system 조합)

본 verification template `gates.md`에 §확장으로 추가하면 자동 적용.

---

## 출처 인용

| 출처 | 위치 |
|---|---|
| Gate 1~5 명세 | `/home/user/example_project-analysis/.claude/requirements/VERIFICATION.md` §1~§5 (15 도메인 × 5 Gates 적용) |
| 금지어 카탈로그 | `~/.claude/skills/_common/doc-writer.md` §금지어 회피 |
| SSOT 분배 룰 | `~/.claude/skills/_common/doc-writer.md` §SSOT 분배 규칙 |
| AUTOPILOT-PLAN §3 H4 | `synthesis/AUTOPILOT-PLAN.md` |
