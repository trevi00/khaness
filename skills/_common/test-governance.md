---
name: test-governance
description: Testing as governed risk reduction — contract regression, flake quarantine, e2e budget, and load gate kept reviewable beyond assertion counts.
keywords: testing 테스팅 governance contract-regression golden negative-coverage compatibility flake flaky quarantine e2e end-to-end budget seed cleanup load load-test latency error-budget rollback chaos shape compatibility deprecation runtime-budget critical-path 회귀 회귀테스트
intent: 테스트설계해 contract테스트만들어 flake격리해 e2e예산정해 load게이트설정해 shape검증해 회귀테스트해 테스트정책정해
paths: tests/ test/ e2e/ integration/ load/ contract/ specs/ __tests__/ src/test
patterns: pact contract-test golden-file snapshot k6 jmeter gatling locust playwright cypress junit pytest jest vitest mocha rspec
requires: testing-anti-patterns test-driven-development verification-before-completion api-contracts
phase: plan implement review
tech-stack: any
min_score: 2
---

# Test Governance

좋은 테스트는 양이 아니라 **위험 lane이 명시·소유·만료되었는지**로 판단. 4축: contract regression, flake quarantine, e2e budget, load gate.

## 의사결정 트리

### IF 새 테스트 lane 추가 (Plan)
1. 어떤 위험을 줄이는가 — feature 회귀 / contract 변경 / 성능 회귀 / 통합 깨짐 중 하나
2. owner와 expiry — 영원한 테스트는 의심. "이 테스트 N개월 후 가치 재평가"
3. 비용 — 실행 시간, 인프라, 유지보수 비용을 lane 자체에 기록
4. 실패 시 정책 — block CI / warn only / quarantine?
5. **→ test-driven-development 스킬: TDD 사이클과 묶어서 설계**

### IF API/UI Contract 회귀 (Implement)
1. shape 정의 — 응답 필드, 타입, status 코드, error envelope, pagination
2. golden case + negative case + edge case 3종 — positive만 있으면 약함
3. compatibility 모드 — additive only? breaking 허용 시 deprecation period
4. consumer-driven contract (Pact 등) 또는 OpenAPI snapshot 비교
5. **→ api-contracts 스킬: 서비스 간 contract 거버넌스와 묶음**

### IF Flaky 테스트 발견 (Review)
1. 즉시 quarantine — 메인 CI 게이트에서 분리. 그러나 owner와 expiry 함께 등록
2. retry budget — quarantine 안에서 N회 retry 허용, 초과 시 fail
3. 분류 — timing race / network flake / data leak / order dependency
4. expiry 도래 시 — 해결 또는 영구 삭제. "그냥 두자"는 hidden risk
5. quarantine size 임계값 — 10% 넘으면 product risk로 escalation

### IF E2E 시나리오 추가 (Plan)
1. 진짜 critical path만 — 모든 user flow 자동화는 비용 폭발
2. seed/cleanup 명시 — DB 상태 reset 안 하면 다음 실행 affect
3. runtime budget — 시나리오당 N분 한도, 전체 e2e suite N분 한도
4. dependency stub vs real — 외부 API는 stub, 내부 서비스는 real이 보통
5. flake율 임계값 — e2e가 flaky 5% 넘으면 사람들이 무시

### IF Load Test / 성능 게이트 (Implement)
1. profile 정의 — peak / sustained / spike 중 어느 것
2. warmup 무시 — 처음 N초 metric 제외
3. threshold — p95/p99 latency, error rate, throughput
4. fail 시 정책 — block release / 경고 / 자동 rollback
5. capacity owner — load test 결과 review 책임자

## 4축 체크리스트

```
[Contract Regression]
□ shape 검증 (필드/타입/status)
□ golden + negative + edge 3종
□ compatibility 모드 (additive vs breaking)
□ deprecation period 정책

[Flake Quarantine]
□ 즉시 격리 — 메인 게이트에서 분리
□ owner + expiry 등록
□ retry budget 명시
□ quarantine size 임계값 알림

[E2E Budget]
□ critical path만 (모든 path 자동화 X)
□ runtime budget 시나리오/suite
□ seed/cleanup hermetic
□ dependency stub vs real 명시

[Load Gate]
□ profile (peak/sustained/spike)
□ warmup 제외
□ p95/p99 + error + throughput threshold
□ fail 정책 (block / warn / rollback)
```

## 가이드

### Contract test vs Integration test
- **Contract**: 한쪽 서비스만 띄우고 다른 쪽은 stub. 빠르고 격리됨. 실제 통합 보장은 못 함.
- **Integration**: 둘 다 띄움. 느리고 환경 의존. 실제 통합 검증.
- 일반: contract로 producer-consumer 호환성 보장 + 핵심 path만 integration.

### Flake의 진짜 원인 분류
- **timing race**: sleep으로 가리지 말고 wait_until_condition
- **shared state**: 테스트 간 격리 (DB/cache/file 분리)
- **order dependency**: 임의 순서로 돌려도 통과해야 함
- **external flake**: 외부 API는 stub 또는 retry with cap

### Quarantine은 일시적이어야 함
"오래된 quarantine = 사실상 무관심." 모든 quarantine 항목에 expiry(보통 14-30일) 강제. expiry 만료 시 자동 알림 → 해결 또는 삭제.

### E2E 비용 vs unit 비용 비율
일반 권장: unit 70% / integration 20% / e2e 10%. e2e가 30%+면 피드백 루프 너무 느림. 같은 위험 단위 비용을 unit/contract로 내릴 수 있나 항상 질문.

### Load test threshold 결정
SLO에서 도출. SLO가 p95 < 200ms면 load gate threshold는 더 엄격(p95 < 150ms). margin 없이 SLO랑 같으면 production에서 즉시 fail.

## Gotchas

### Contract 테스트가 positive only
"성공 응답 검증"만 있고 4xx/5xx error envelope, 빈 결과, 페이지네이션 끝 케이스가 없으면 진짜 client-breaking 변경을 못 잡음. negative + edge 필수.

### Flaky 테스트를 retry로 가림
`retry: 3`으로 통과시키면 진짜 race condition을 숨김. retry는 외부 의존 일시 실패에만, 내부 코드 race는 fix해야 함.

### Quarantine = 영구 삭제처럼 운영
quarantine에 넣고 owner도 expiry도 없으면 1년 후 "이거 왜 quarantine?" 아무도 모름. owner + expiry + 분류 라벨 필수.

### E2E suite 60분+
e2e가 너무 느려서 PR마다 못 돌리고 nightly만 돌리면, breaking change가 다음날 발견 → 회복 비용 폭발. critical path 추려서 PR ≤ 10분 보장.

### Seed/cleanup 안 한 e2e
앞 시나리오가 만든 user를 뒤 시나리오가 우연히 사용 → 처음엔 통과, 시나리오 순서 바뀌면 실패. 각 시나리오는 hermetic — 자기가 만들고 자기가 cleanup.

### Load test가 warmup 포함
처음 30초 JIT 컴파일 / connection pool 채우기 / cache warm은 latency 폭증 구간. 이걸 포함하면 p99 항상 fail. warmup 명시 제외.

### Load test profile이 평균
실제 트래픽은 불균형(아침 spike 등). 평균 RPS로만 테스트하면 burst 내성 모름. peak / sustained / spike 3종 profile.

### Snapshot test가 너무 광범위
JSON 전체 snapshot 비교는 무관한 필드 변경에도 fail → snapshot 갱신이 일상. 의미 있는 필드만 추출해 비교(Pact, JSON path 단언).

### Test가 production code 구현 detail 의존
"메서드 호출 횟수 검증" 같은 테스트는 리팩토링하면 깨짐 → 테스트가 변경 비용. 입출력 + 관찰 가능한 side-effect만 검증.

### Quarantine 비율 이상 — 알림 없음
quarantine 비율이 슬금슬금 늘어 30%까지 가면 사실상 테스트 신뢰 없음. 비율 임계값(10%) 알림으로 product risk escalation.

## 도구 사용 패턴 (Harness)
- contract test 실행: `Bash`로 pact / postman / openapi-checker
- flake 추적: CI 결과 history에서 같은 테스트 fail 빈도 집계
- load test: `Bash`로 k6/jmeter, 결과는 markdown 리포트로 review

## 에러 복구 패턴 (Harness)
- 갑자기 contract 깨짐 → producer git log + schema diff 추적, deprecation period 합의 부재 의심
- e2e 일제 실패 → seed/cleanup 또는 외부 의존 stub 변경 의심, dependency stub config 비교
- load test fail → recent deploy 추적, profile/warmup 설정 변경 여부 검사
