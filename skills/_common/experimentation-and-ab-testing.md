---
name: experimentation-and-ab-testing
description: A/B 테스트 통계 — sample size(α=0.05·β=0.2), CUPED, peeking 방지(mSPRT), SRM 검증, SUTVA/cluster randomization
keywords: experimentation ab-testing cuped mSPRT sample-size peeking srm sutva interleaving sequential
intent: design-experiment compute-sample-size diagnose-srm choose-randomization-unit handle-peeking
paths:
patterns: NormalIndPower mSPRT chi-square cluster-randomization interleaving
requires: data-pipeline-governance code-quality
phase: plan implement review
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# Experimentation & A/B Testing

> 핵심: 통계 default(α=0.05, power=0.8)는 관습일 뿐 — 실험 비용/리스크 비대칭이면 재조정한다. peeking·SRM·SUTVA 위반은 결과를 무효화하므로 검정 전 게이트로 강제.

## 의사결정 트리

### IF 신규 실험 설계 (Plan)
1. metric 종류 식별 — binary(전환율) vs continuous(매출) → sample size 공식 분기
2. pre-experiment covariate 보유 여부 → 있으면 **CUPED**로 variance ~50% 감소 (KDD 2016 Netflix 적용)
3. 단위 결정 — user-level random이 default. social/marketplace/network effect 의심 → cluster(geo, market, ego-network) randomization
4. 알고리즘 비교(랭킹 모델 등) → A/B 전에 **interleaving** 1단계 (Netflix 패턴)

### IF sample size 계산 (Plan)
1. 공식 (per-arm, two-sided): `n = 2σ² × (z_{1-α/2} + z_{1-β})² / MDE²`
2. α=0.05, power=0.8 → `(1.96+0.84)² ≈ 7.85`
3. binary metric → Evan Miller proportion calculator
4. continuous metric → `statsmodels.stats.power.NormalIndPower` 또는 동등
5. CUPED 적용 시 σ²을 `σ²·(1-ρ²)` 로 대체 (ρ = pre-period covariate 상관)

### IF 결과 분석 (Review)
1. **SRM gate 먼저** — chi-square test, p < 0.01이면 분석 **중단** (bucketing/instrumentation 버그). Microsoft 보고 6% 발생률
2. 효과 측정 — point estimate + CI. p-value 단독 의존 금지
3. 다중 metric 비교 → Bonferroni 또는 BH FDR 보정
4. 결과 발표 전 robustness check — 관측 기간 절반/주말 포함/exclude top 1% outlier

### IF 실험 일찍 보고 싶다 (Implement)
1. **naive peeking 금지** — α=0.05 fixed-horizon에서 매일 보면 FP rate ~21%까지 inflate (Johari et al. 2017)
2. mSPRT (always-valid p-value) 또는 group-sequential (Pocock/O'Brien-Fleming) 채택
3. 실무 도구: Optimizely Stats Engine(mSPRT), Eppo, Statsig, GrowthBook — fixed-horizon vs sequential 명시 확인

## 가이드

- α=0.05 / power=0.8은 Cohen(1988) 관습. critical biz decision은 power=0.9 + α=0.01도 검토.
- CUPED는 pre-period covariate가 in-experiment metric과 상관 있어야 작동 — 신규 사용자 코호트에는 이득 없음.
- SUTVA 위반 시 user-level random은 효과를 underestimate. cluster random으로 이전하면 검정력 손실 — sample size 늘려야 함.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | SRM gate(p<0.01)로 false-positive 결과 사전 차단 |
| 성능 효율성 | CUPED로 ~50% variance 감소 → sample size 절반 |
| 호환성 | mSPRT는 어느 시점에 정지해도 type I error 보장 (fixed-horizon과 호환) |
| 사용성 | Evan Miller calculator로 비통계인도 1분에 sample size 산출 |
| 신뢰성 | 다중 metric → Bonferroni / BH FDR로 family-wise error 통제 |
| 보안 | 사용자 식별자 hashing 후 bucketing — PII 노출 방지 |
| 유지보수성 | 매 실험 SRM/peeking/SUTVA 3-gate 체크리스트 표준화 |
| 이식성 | Optimizely/Statsig/Eppo/GrowthBook 도구 무관 적용 가능 |
| 확장성 | network effect 발견 시 cluster random으로 점진 확장 가능 |

## Gotchas

### naive peeking이 FP을 21%까지 부풀린다
α=0.05에서 fixed-horizon 가정인데 매일 보면 stopping rule violation → α inflation. mSPRT 또는 group-sequential 미적용 시 결과 무효.

### SRM 발생 시 효과 분석 진행 금지
chi-square test p<0.01이면 bucketing/log dropping/instrumentation 버그. Microsoft 6% 발생률 — 무시 시 잘못된 결정. 원인 파악 후 재실행.

### CUPED가 신규 코호트에서는 효과 없음
pre-period covariate 상관이 0이면 variance 감소 0. 신규 가입자 실험에는 사용 불가 — 일반 사용자에게만 적용.

### SUTVA 위반을 인지 못한 marketplace 실험
공급자/수요자 매칭 시스템에서 user-level random은 control이 treatment 효과를 흡수 → effect underestimate. geo/market/ego-cluster random으로 전환 필수.

### winner's curse — 상위 변형 효과가 항상 과대평가
다수 변형 비교에서 max 선택은 평균보다 큰 편향. Bayesian shrinkage 또는 holdout test로 보정.

## Source

- https://exp-platform.com/Documents/2013-02-CUPED-ImprovingSensitivityOfControlledExperiments.pdf — Deng/Xu/Kohavi/Walker, "The technique can reduce variance by about 50%", 조회 2026-05-10
- https://www.evanmiller.org/ab-testing/sample-size.html — α=0.05/power=0.8 default 산식, 조회 2026-05-10
- https://arxiv.org/pdf/1512.04922 — Johari et al. (KDD 2017) "Peeking at A/B Tests"; naive stop FP ~21% inflate; mSPRT always-valid p-value 해법, 조회 2026-05-10
- https://www.microsoft.com/en-us/research/articles/diagnosing-sample-ratio-mismatch-in-a-b-testing/ — "every A/B test must first pass the SRM test"; "about 6% of A/B tests have an SRM"; p<0.01 threshold, 조회 2026-05-10
- https://kdd.org/kdd2016/papers/files/adp0945-xieA.pdf — Xie & Aurisset KDD 2016, CUPED at Netflix, 조회 2026-05-10
- https://netflixtechblog.com/interleaving-in-online-experiments-at-netflix-a04ee392ec55 — interleaving "considerably smaller sample size compared to traditional A/B", 조회 2026-05-10
- https://netflixtechblog.com/quasi-experimentation-at-netflix-566b57d2e362 — geo-based quasi-experiments for SUTVA violations, 조회 2026-05-10
