---
name: progressive-delivery
description: Progressive delivery as a release contract — rollout steps, traffic split, abort threshold, and post-release watch made explicit beyond "deploy and pray".
keywords: progressive-delivery rollout canary blue-green dark-launch shadow-traffic feature-flag traffic-split percentage-rollout cohort-rollout abort-threshold rollback-trigger slo-error-budget post-release-watch bake-time auto-rollback argocd-rollouts flagger spinnaker harness-io launchdarkly unleash flagsmith istio linkerd envoy weighted-routing
intent: 점진배포해 canary배포해 rollout설계해 traffic-split설정해 feature-flag로배포해 abort-threshold정해 post-release모니터해 bake-time잡아 자동롤백설정해 cohort배포해
paths: rollout/ delivery/ deploy/ flags/ release/ argo/ argocd/ flagger/ canary/ k8s/rollouts manifests/rollout
patterns: argo-rollouts flagger spinnaker harness-io launchdarkly unleash flagsmith optimizely istio linkerd envoy nginx-ingress alb traefik
requires: rollback-readiness sre-operations monitoring infra-change-readiness release
phase: plan deploy review
tech-stack: any
min_score: 2
---

# Progressive Delivery

"deploy = 100% live"는 incident 발생 시 blast radius 최대. progressive delivery는 **rollout 자체를 실험으로** 다룸 — 4축: rollout step, traffic split, abort threshold, post-release watch.

## 의사결정 트리

### IF 새 release 설계 (Plan)
1. **rollout 패턴 선택**:
   - canary: traffic % 점진(5 → 25 → 50 → 100)
   - blue-green: 두 환경 동시, switch atomic
   - dark launch / shadow: production traffic 복제 → 새 버전엔 read-only
   - feature flag: 배포 + flag toggle 분리, cohort/percentage
2. **변경 위험 분류**:
   - low(UI text, copy): direct deploy or short canary
   - medium(API behavior change): canary multi-step + bake time
   - high(DB schema, money flow): expand-contract + flag + extended bake
3. **abort threshold 사전 정의** — error rate / latency / business metric / log error 패턴
4. **rollback 경로 결정** — flag off / traffic 0% / blue-green switch back
5. **→ rollback-readiness 스킬: rollback rehearsal과 연결**

### IF Canary Rollout (Deploy)
1. step 정의 — 5% → 25% → 50% → 100%, 각 step bake time(보통 10-30분)
2. **promotion gate** — 자동(metric pass) 또는 manual approve
3. metric 측정 unit — 신/구 버전 같은 traffic 슬라이스에서 비교 (apples-to-apples)
4. **stickiness** — 같은 user는 같은 버전 (consistent hashing) — partial UX 깨짐 방지
5. step 사이 metric statistical significance — 충분한 sample 도달까지 dwell

### IF Feature Flag Rollout (Deploy)
1. flag 종류:
   - **release flag**: deploy와 분리. 100% deploy 후 flag로 enable
   - **operational flag**: kill switch. incident 시 즉시 off
   - **experiment flag**: A/B test, cohort 기반
   - **permission flag**: tenant/role 기반
2. flag 수명 정의 — release flag는 100% rollout 후 N주 안에 cleanup (technical debt 차단)
3. flag 평가 결정성 — 같은 user면 같은 결과 (avoid flapping)
4. flag service 가용성 — fallback 값을 코드에 hard-code (service down 시 안전)
5. **→ rollback-readiness 스킬: flag rollback의 사용자 고립 함정 참고**

### IF Traffic Split / Mesh (Deploy)
1. 분할 단위 — request weight / header(canary header) / cookie / user-id mod
2. mesh / ingress 도구 — Istio VirtualService, Linkerd TrafficSplit, Argo Rollouts, Flagger, ALB weighted target group
3. cross-cluster 또는 multi-region 시 — 한 region/cluster에서 먼저
4. internal user / dogfood 먼저 — header 기반 canary로 회사 내부 노출
5. session affinity 와 충돌 — sticky session이면 percentage가 정확하지 않을 수 있음

### IF Abort Threshold / Auto-Rollback (Implement)
1. **golden signal**: error rate / p99 latency / saturation / availability
2. **business metric**: conversion / sign-up / checkout — 기술 metric이 OK여도 business 떨어지면 abort
3. baseline 정의 — 직전 stable 버전의 baseline window
4. abort 결정 — N분 동안 임계 초과 또는 이상 detection(z-score)
5. **자동 vs 수동** — 자동은 빠르지만 false positive 위험. 명확한 metric만 자동.
6. **→ monitoring 스킬: SLI/SLO 설계 참고**

### IF Post-Release Watch (Review)
- [ ] bake time 최소 N시간 (peak traffic 한 사이클 포함)
- [ ] error rate 변화 없음 또는 baseline 안
- [ ] log error 새 패턴 없음
- [ ] business KPI 변화 없음 (sign-up, conversion, revenue)
- [ ] dependent service에 영향 없음
- [ ] 사용자 feedback (support ticket, social)
- [ ] flag cleanup 일정 등록 (release flag만)

## 4축 체크리스트

```
[Rollout Step]
□ 패턴 선택 (canary/BG/dark/flag) + 명시 이유
□ step % 정의 + bake time
□ promotion gate 자동 또는 수동 합의
□ stickiness 정책 (user 동일 버전)

[Traffic Split]
□ 분할 단위 (weight / header / cookie / user-id)
□ tooling (mesh / ingress / rollout controller)
□ region/cluster 순서
□ internal/dogfood 먼저 단계

[Abort Threshold]
□ golden signal 임계 + window
□ business metric 임계
□ baseline 정의 (직전 stable)
□ 자동/수동 결정 + 권한
□ rollback 명령 documented

[Post-Release Watch]
□ bake time ≥ peak cycle
□ error rate / log pattern 검토
□ business KPI 검토
□ dependent service 영향
□ flag cleanup 일정
```

## 가이드

### Canary vs Blue-Green vs Dark Launch
- **Canary**: % 점진 → 위험 점진 노출. 시간 + 도구 필요.
- **Blue-Green**: 둘 다 가동, switch atomic. infra 비용 2배. rollback 빠름.
- **Dark launch**: 새 버전이 traffic 받지만 응답 reject 또는 shadow. risk 0이지만 production data 유효성 확인 어려움.
- **Feature flag**: deploy 100% + flag로 cohort 노출. infra 단순. flag debt 관리 필요.
혼합 가능 — 예: blue-green deploy + flag로 cohort.

### Bake Time 결정
peak traffic 1 cycle(보통 1시간) 또는 statistical significance 확보까지. 너무 짧으면 issue 못 잡음, 너무 길면 release velocity 낮음. metric variance + traffic 패턴 기준.

### Statistical Significance
canary 5% / 100 RPS → 5분에 30K 요청. error rate 0.1% baseline에서 0.5% 변화 detect는 충분. 1% / 10 RPS면 1시간 부족 — bake 시간 늘리거나 % 늘리거나.

### Abort 자동화 위험
false positive면 좋은 release 자동 abort → 신뢰 저하. 임계는 명확한 신호만(예: error rate 5x baseline). 애매한 신호(latency 10% drift)는 수동 검토.

### Feature Flag 부채
flag 누적되면 코드 if-else 미로 + 테스트 폭증. release flag는 100% rollout 후 4-6주 안에 cleanup PR. 분기별 stale flag audit.

### Internal Dogfood First
회사 내부 traffic만 새 버전으로 라우팅(`X-Canary-User: dogfood` header) → 5% public 전에 internal 전체 검증. 큰 변경에 효과적.

## Gotchas

### Canary 5%로 metric 안 보임
5% × 10 RPS = 0.5 RPS → 1시간에 1800 요청. p99 / error rate variance가 커서 신호 묻힘. 작은 traffic은 % 빨리 올리거나 절대 RPS 기준으로 step 정의.

### 신/구 traffic 비교 안 함
canary error rate 1%인데 stable도 1%면 release 영향 아님. 항상 baseline(직전 stable)과 비교. 절대값만 보면 false alarm.

### Sticky session으로 % 부정확
LB sticky cookie → 첫 hit 후 같은 backend → 의도한 5%가 실제 다른 % 됨. % rollout은 stateless 또는 user-id 기반 hash로.

### Flag 평가가 random
같은 user가 새로고침마다 다른 버전 → UX 깨짐 + state 불일치. flag는 user-id 또는 session-id 기반 deterministic hash.

### Flag service 다운 시 default 위험
flag service unreachable → default가 "off"인데 새 기능이 on 가정 → broken UI. 코드에 안전한 fallback 명시 + flag service health 모니터.

### Rollout 중 hotfix 끼어듦
canary 25% 진행 중 다른 hotfix가 새 release 만듦 → canary가 무엇 vs 무엇인지 모호. rollout 중 freeze 또는 명확한 versioning.

### Auto-rollback이 trigger 안 됨
임계가 너무 관대(error rate 50% 도달 시 abort) → incident 다 끝난 후 rollback. baseline 대비 N배 + 절대 임계 둘 다.

### Bake time이 한가한 시간만
새벽에 5% bake → traffic 패턴 다름 → peak에서 다른 동작. peak time 적어도 1번 포함.

### Multi-region 동시 100%
canary 통과 후 모든 region 동시 100% → region-specific 문제 발견 못 함. region 단위 sequential rollout.

### Dependent service 영향 미관찰
배포된 service는 OK인데 호출하는 dependent service가 새 동작에 못 따라감 → 다른 곳에서 break. dependency map + 양쪽 metric 동시 watch.

### Flag rollback 후 사용자 state 불일치
flag on에서 user가 새 기능으로 데이터 생성 → flag off 시 옛 코드가 새 데이터 못 읽음. 양쪽 호환 코드 N주 유지 + 데이터 마이그레이션 후 cleanup.

### Promotion gate가 사람 의존
"Slack에서 PM approve"인데 PM 부재 → rollout stalled. 자동 metric pass 또는 명확한 SLA 가진 approver pool.

### Canary header만 dogfood, 외부 노출 0%
"5% canary 시작"이라 했지만 traffic split 설정이 internal header만 → 외부 사용자 0%. 의도한 대로 라우팅 되는지 actual traffic 분포 확인.

### Post-release watch 끝 시점 모호
"잘 도는 것 같다" → watch 종료 → 며칠 후 새 issue 발견. bake window를 명시(예: 24h or 1 peak cycle)하고 그 후 closure 의식.

## 도구 사용 패턴 (Harness)
- rollout 정의: `Read`로 `Rollout`(Argo) / `Canary`(Flagger) manifest 검토
- traffic split 상태: `Bash`로 `kubectl describe rollout/<name>` / `kubectl get virtualservice`
- flag 상태: flag service API 또는 dashboard
- metric 비교: monitoring 스킬 + canary/stable 라벨 분리
- abort 로그: rollout controller events / audit log

## 에러 복구 패턴 (Harness)
- "canary stuck at 25%" → metric pass 임계 미달 또는 promotion gate 막힘. controller events 확인
- "flag toggle 후 일부 사용자 broken" → flag aware 코드 양쪽 호환 검증, sticky session 영향
- "auto-rollback false positive" → 임계 검토 + statistical significance 미달, baseline window 점검
- "rollout 후 dependent service 깨짐" → API contract change 확인, expand-contract로 분해
- "post-release N일 후 issue" → bake window 너무 짧음, watch SLA 갱신 + flag cleanup 일정 검토
