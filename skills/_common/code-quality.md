---
keywords: 코드 code 품질 quality 클린 clean 리팩토링 refactoring 리뷰 review 아키텍처 architecture 설계 design 패턴 pattern 응집도 cohesion 결합도 coupling SOLID solid DDD ddd TDD tdd 테스트주도 단일책임 SRP 개방폐쇄 OCP 의존역전 DIP 컨벤션 convention 코딩 스타일 style 네이밍 naming 추상화 abstraction 상속 inheritance 합성 composition
intent: 리팩토링해 코드정리해 클린코드해 분리해 추출해 SOLID적용해 리뷰해 코드리뷰해 검토해
paths: src/ lib/ core/ domain/ application/
patterns:
requires: testing
phase: implement review
min_score: 3
---

# Code Quality & Convention Guide

## 의사결정 트리

### IF 새 코드 작성 (Implement)
1. 책임 범위 결정 → 하나의 클래스/함수 = 하나의 이유로만 변경
2. 의존성 방향 결정 → 고수준(도메인) ← 저수준(인프라)
3. 테스트 가능성 확인 → 외부 의존성을 주입받는 구조인가?
4. 네이밍 → 아래 규칙 참고

### IF 기존 카테고리의 새 인스턴스 추가 (Design)
"새 X"(PG 커넥터·vendor 콜백·어댑터·integration)가 **이미 있는 종류의 새 인스턴스**면, 설계 첫 단계 = **기존 형제(sibling) 1~2개를 먼저 역설계**(`git log`/`grep`로 찾아 읽기)해 그 구조(컨트롤러/서비스/DTO/SSOT 레인)를 **그대로 합류**시킨다. 금지: (1) 그린필드 clean-arch 추상화(Port/composition/NoOp/per-instance DTO)를 새로 도입, (2) "기존 코드 0 수정 별도 레인" — 안전해 보이지만 conform 회피라 **나중에 평탄화 재작업 강제**, (3) 외부 spec(PDF)만 보고 내부 합류 구조는 안 보기. **인스턴스-고유한 부분만 fork.**

### IF 리팩토링 (Implement)
1. 먼저 테스트가 있는지 확인 (없으면 작성 후 리팩토링)
2. 변경 이유가 2개 이상인 클래스 → 분리
3. 3곳 이상 중복 → 추출 (2곳은 허용)
4. 깊은 상속 → 합성(composition)으로 전환
5. 한 번에 하나만 변경, 매 단계 테스트 통과 확인

### IF 코드 리뷰 (Review)
- [ ] 함수/클래스가 한 가지 일만 하는가
- [ ] 의존성 방향이 도메인 → 인프라가 아닌가
- [ ] 테스트 없이 동작을 변경하지 않았는가
- [ ] 불필요한 추상화를 추가하지 않았는가
- [ ] 네이밍이 동작을 정확히 설명하는가

## 핵심 원칙

### 응집도와 결합도
- **높은 응집도**: 관련된 데이터와 행위를 한 곳에. "이 클래스는 무엇을 하는가?"에 한 문장으로 답할 수 있어야.
- **낮은 결합도**: 인터페이스(추상)에 의존, 구현에 의존하지 않음. 모듈 교체 시 다른 모듈 수정 불필요.
- **판단 기준**: 변경 시 영향 범위가 좁을수록 좋은 설계.

### TDD 적용 기준
모든 코드에 TDD를 강제하지 않음. 아래 상황에서 효과적:
- **도메인 로직**: 비즈니스 규칙이 복잡할 때 → Red-Green-Refactor
- **버그 수정**: 재현 테스트 작성 → 수정 → 테스트 통과 (회귀 방지)
- **API 계약**: 입출력 스펙이 명확할 때 → 테스트가 곧 스펙 문서
- **적합하지 않은 경우**: UI 프로토타이핑, 탐색적 코딩, 외부 API 연동 초기 단계

### 의존성 방향
```
Interface(라우터) → Application(서비스) → Domain(엔티티)
                         ↓
                   Infrastructure(DB, 외부API) → Domain 인터페이스 구현
```
Domain은 아무것도 import하지 않음. Infrastructure가 Domain의 인터페이스를 구현.

## 네이밍 규칙
- **함수**: 동사로 시작, 부작용 여부 표현 (`getUserById` vs `createUser`)
- **불리언**: is/has/can/should 접두사 (`isValid`, `hasPermission`)
- **컬렉션**: 복수형 (`users`, `orderItems`)
- **약어 금지**: `usr`, `mgr`, `svc` 대신 `user`, `manager`, `service`
- **의미 없는 이름 금지**: `data`, `info`, `item`, `temp`, `result` 단독 사용 지양

## Gotchas

### 과도한 추상화
Claude는 인터페이스, 팩토리, 전략 패턴을 지나치게 사용하는 경향이 있음. 구현체가 1개뿐인 인터페이스는 불필요. "지금 필요한 것만 만들고, 두 번째 사용처가 나타날 때 추상화"가 원칙.

### 기존 카테고리 새 인스턴스를 그린필드로 설계 → 대량 평탄화 재작업
이미 UnionPos/Paytap 등으로 정립된 PG-연동 패턴이 있는데, 새 커넥터(CJ)를 별도 도메인 레인(CJ-native DTO + Port 추상화 + NoOp + 별도 컨트롤러)으로 "깨끗하게" 설계 → 곧 회사 표준 dispatch로 평탄화 + 재평탄화(+2232/−2326, 29파일) + 징검다리 DTO 다발 제거로 이어짐. **신규 인스턴스 설계 전 형제 역설계가 빠지면 "깨끗한 새 구조"가 곧 재작업 부채.** "0 수정 별도 레인"은 미덕이 아니라 anti-pattern.

### 3줄 코드를 함수로 추출
한 곳에서만 쓰이는 3줄 코드를 별도 함수로 만들면 오히려 가독성이 떨어짐. 함수 추출은 재사용 또는 복잡한 로직 분리 목적일 때만.

### God Object 방치
점점 커지는 클래스에 메서드를 계속 추가하지 말 것. 메서드가 10개를 넘거나 파일이 300줄을 넘으면 분리 시점.

### 상속 남용
"is-a" 관계가 아닌데 코드 재사용 목적으로 상속을 쓰면 깨지기 쉬운 계층 구조가 됨. 합성(composition)을 먼저 고려.

### 순환 의존
모듈 A가 B를, B가 A를 import하면 구조적 문제. 공통 인터페이스를 별도 모듈로 추출하거나 의존성 역전 적용.

### 리팩토링 중 기능 변경
리팩토링과 기능 변경을 동시에 하면 버그 원인 추적이 불가능. 커밋을 분리할 것: 리팩토링 커밋 → 기능 변경 커밋.

### DTO와 도메인 엔티티 합치기
DTO(입출력 구조)와 도메인 엔티티(비즈니스 규칙)를 한 클래스에 합치면 API 변경이 도메인에 영향을 줌. 반드시 분리.

### "일단 동작하면 됨" 함정
프로토타입을 프로덕션 코드로 그대로 가져가지 말 것. 동작 확인 후 구조를 정리하는 리팩토링 단계가 반드시 필요.

## Related (신규 그래프 cross-ref)

code-quality가 결합되는 신규 노드:
- `_common/skill-distillation-pipeline.md` — 9게이트 자동 강제 (≤250 lines / ≤8KB / Source ≥1 / Gotchas ≥3 / 9축 main label)
- `kotlin/android/circuit-unidirectional-architecture.md` — Presenter ↔ Ui 직접 접근 차단 (단방향 강제)
- `kotlin/android/dagger-hilt-di-architecture.md` — `@ApplicationContext` 강제로 Activity ref 누수 차단
- `_common/durable-execution.md` — workflow 함수 안에 side effect 금지 (deterministic replay)
- `java/lang/grpc-service-contracts.md` — `reserved` 강제로 schema evolution 안전
