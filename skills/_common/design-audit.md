---
name: design-audit
description: System architecture / module boundary / layer dependency 감사 — 도메인 코드 품질이 아닌 구조적 설계 결정을 평가한다.
keywords: 아키텍처감사 architecture-audit design-audit 모듈경계 boundary 레이어 layer 의존성방향 dependency-direction 순환의존 cyclic 패키지구조 package-structure abstraction 추상화 SOLID 인터페이스 hexagonal clean-architecture
intent: 아키텍처감사해 설계감사해 구조감사해 모듈평가해 레이어점검해
paths: src/ backend/ frontend/ shared/ domain/ infrastructure/ application/ interface/
patterns: package boundary import graph hexagonal onion clean-architecture port adapter facade
requires: code-quality convention
phase: review
min_score: 3
---

# Architecture / Design Audit

> **목적**: 시스템 **구조**의 정합성 평가 — 모듈 경계, 레이어 의존성, 추상화 일관성, 순환 import.
> **vs `domain-audit.md`**: domain-audit는 도메인별 코드 품질 (BE/FE 7축, Codacy 10-Dimension). 본 스킬은 도메인 위 layer 즉 **architecture-level 설계 감사**.
> **출처**: Hexagonal/Onion/Clean Architecture 원칙 + DDD + SOLID.

## 의사결정 트리

### IF 새 모듈/패키지 추가 (Plan)
1. 의존성 방향 명시: 어느 layer에 속하는가? 어느 layer를 import할 권한?
2. 인터페이스/구현 분리 검토: 다른 layer가 사용하면 인터페이스로 노출.
3. 순환 import 사전 차단: import 그래프에서 새 노드의 in-degree/out-degree 그려보기.

### IF 아키텍처 감사 실행 (Review)
1. **모듈 경계 그래프 작성**: 각 패키지의 import 출처/대상 매핑.
2. **5축 매트릭스 평가**: 모듈 × 5축 — Boundary, Direction, Abstraction, Consistency, Drift.
3. **P0/P1/P2 분류**:
   - P0 = 순환 import 또는 layering violation (Domain이 Infrastructure import 등)
   - P1 = 일관성 위반 (같은 역할 모듈이 다른 패턴)
   - P2 = 추상화 누수 또는 명명 불일치
4. **Quick Win 즉시 fix**: 단일 import 라인 변경으로 해결되는 것.
5. **Strategic은 phase 분리**: 모듈 분할/병합은 단독 phase로.

### IF 기존 시스템 리팩토링 (Plan)
1. 현재 dependency graph snapshot.
2. 이상적 구조 (target architecture) 그리기.
3. Migration 단계 분해: A → B → C 순으로 import 경로만 변경 → 모듈 분리 → 인터페이스 추출.
4. 각 단계 후 build PASS + import graph 재검증.

## 5축 아키텍처 감사 프레임워크

### A-1. Module Boundary (모듈 경계)
- 각 모듈/패키지가 단일 책임을 갖는가?
- 한 모듈이 여러 layer (Application + Infrastructure)에 걸쳐있지 않은가?
- 안티패턴: `util/` god-package, `helper/` 잡것 모음.

### A-2. Dependency Direction (의존성 방향)
- 의존성이 단방향인가? (예: Interface → Application → Domain ← Infrastructure)
- Domain은 어떤 외부 layer도 import하지 않는가?
- 안티패턴: `domain/UserService.java` 가 `infrastructure/UserRepository.java` 직접 import.

### A-3. Abstraction Consistency (추상화 일관성)
- 같은 역할의 모듈이 동일한 추상화 수준에 있는가?
- 일부 도메인만 인터페이스를 갖고 일부는 구현 클래스만 노출되지 않는가?
- 안티패턴: `OrderService` (interface) ↔ `PaymentServiceImpl` (concrete only) 혼재.

### A-4. Pattern Consistency (패턴 일관성 — 구조 레벨)
- 새 도메인이 기존 도메인과 동일 패키지 구조 / 클래스 네이밍 / DI 방식?
- Controller→Service→Repository 3-layer를 모두 따르는가, 아니면 일부 도메인은 우회하는가?
- 안티패턴: 특정 도메인만 Controller가 Repository를 직접 호출.

### A-5. Architectural Drift (아키텍처 표류)
- 초기 설계 (예: `.claude/architecture.md`) 와 현재 코드의 격차?
- 예: `Domain → Infrastructure`로 경계 침범하는 import가 새로 들어온 비율.
- 측정: 검토 시점 import graph vs 직전 release 시점 import graph diff.

## Output

- artifact: `.planning/audits/{NN}-ARCHITECTURE-AUDIT.md` — 5축 결과, P0/P1/P2 분류, dependency graph 시각화 (mermaid 또는 dot).
- status: `clean` | `degraded` (P1 이내) | `violated` (P0 존재 — 즉시 fix 필요).

## Failure behavior

- 모듈 경계 spec 부재: `.claude/architecture.md` / `domain/structure.md` 등 SoT 문서 없으면 inferred dependency graph만 보고 P0 → defer to design phase.
- import graph 추출 실패: 언어별 도구 (`pydeps` Python, `dependency-cruiser` JS, Gradle `--scan` Java) 미설치 → manual grep + 결과 incomplete 표기.
- 합의 부재: P0 violation이지만 현 상태 의도적 trade-off (예: 성능 hot path 직접 호출)면 `architecture-decision-records/` 에 ADR 등록 후 PASS 처리.

## Gate summary

- preflight: 코드베이스가 빌드 가능, dependency 추출 도구 사용 가능, 비교 baseline (architecture.md 또는 직전 audit) 존재.
- success criteria: 5축 점수 + P0 발견 0 + dependency graph 첨부 + 다음 audit 일정 명시.
- abort triggers: dependency 도구 부재 + manual fallback 거부, 비교 baseline 부재 + ADR 없이 진행 불가.

## Boundary

- vs **domain-audit**: domain-audit는 도메인별 코드/UX 품질 (BE/FE 7축). design-audit는 시스템 구조 (모듈 경계 + 레이어 + 의존성 그래프).
- vs **code-quality**: code-quality는 함수/클래스 단위. design-audit는 패키지/모듈/layer 단위.
- vs **convention**: convention은 명명·포맷·스타일. design-audit는 구조적 결정.

## Gotchas

### 모듈 경계와 디렉토리 구조 혼동
디렉토리가 같다고 같은 모듈은 아님. `import` 그래프가 진짜 경계.

### "그냥 같이 있어서 import" 함정
Convenience import가 long-term 결합도를 만든다. 매 import 결정마다 layer 권한 확인.

### Architecture decision를 코드 주석에 묻음
중요한 trade-off는 `.claude/decisions/` 또는 `architecture-decision-records/` ADR로 분리. 코드 주석은 사라진다.

### Premature 인터페이스 도입
구현이 1개뿐인 인터페이스는 abstraction 누수. 두 번째 구현이 나타날 때 추출.
