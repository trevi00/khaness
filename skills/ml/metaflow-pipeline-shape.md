---
name: metaflow-pipeline-shape
description: Metaflow 2.19+ pipeline — @step / @batch / @kubernetes 결정, artifact 직렬화, foreach 분기, retry/catch
keywords: metaflow step batch kubernetes artifact foreach branch decorator outerbounds netflix-oss
intent: shape-ml-pipeline choose-compute decorate-step handle-foreach diagnose-pickle-failure
paths:
patterns: metaflow @step @batch @kubernetes @retry @catch self.artifact
requires: oncall-and-incident-response data-pipeline-governance
phase: plan implement review debug
tech-stack: any
min_score: 2
---

# Metaflow Pipeline Shape (2.19+)

> 핵심: Metaflow는 ML-first artifact tracking + Python-native (Airflow처럼 generic DAG 아님). `self.x`는 자동 S3 직렬화, step은 indivisible — 한 step 안에서 부분 실패 처리 안 됨. Netflix 시작 → Outerbounds 상용화, Netflix internal + OSS 기여 지속.

## 의사결정 트리

### IF 신규 ML pipeline 설계 (Plan)
1. Compute 사다리 — local dev → `@batch` (AWS Batch) → `@kubernetes` (EKS/GKE/AKS)
2. Datastore — production은 `METAFLOW_DEFAULT_DATASTORE=s3` (또는 azure/gs). local은 단일 호스트만
3. Trigger — `@trigger`(event), `@schedule`(cron), `@trigger_on_finish`(flow chain). production은 AWS Step Functions / Argo
4. resource 명시 — `@kubernetes(cpu=1, memory=4096, disk=10240)` defaults에 의존하지 말고 step별 명시

### IF 데이터 분기 처리 (Implement)
1. **foreach** — `self.next(step, foreach='items')`. task 수 = `len(items)` → 큰 list는 청크 분할 (AWS Batch 동시 quota / S3 PUT throttle 주의)
2. **branch** — 정적 분기. 모든 branch는 join step 필요. join은 `inputs` 인자 받음
3. **`merge_artifacts`** — branch join에서 동일 artifact 자동 병합. tuple은 hash drift로 fail 가능 (Issue #253) — list로 우회

### IF artifact 크기/직렬화 문제 (Debug)
1. 큰 DataFrame(>2GB) → `self.df = df` 직접 저장하지 말고 S3 path/ID만 저장
2. unpicklable object(`_thread.RLock`, DB connection, GPU handle) → `self.x`에 절대 할당 금지. step 내부에서 생성/소멸
3. Pandas categorical → 이중 직렬화 + SHA1 mismatch (Issue #94). astype 정규화 후 저장
4. 2.19.26+ pluggable serializer로 pickle 외 등록 가능 — 위 함정 우회 가능

### IF retry / 부분 실패 처리 (Implement)
1. `@retry(times=3, minutes_between_retries=1)` — transient 실패 (S3 throttle, network blip)
2. `@catch(var='step_error')` — retry 소진 후 no-op task 실행, downstream 진행 가능
3. step은 indivisible — 같은 step에서 부분 결과 commit 후 실패는 불가. 분기 → join 패턴으로 분해

## 가이드

- 2.19.x 안에서 incremental — 6개월 내 breaking change 없음 (2026-05 기준).
- `@batch`와 `@resources` 둘 다 명시 시 max 적용 — 의도치 않은 over-provisioning 위험. 한쪽만.
- `metaflow.S3.get_many()` 권고 파일 크기 0.1–1GB.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | step indivisibility로 부분 실패 모호성 차단 |
| 성능 효율성 | foreach 청크 분할로 task 수 통제, S3 PUT throttle 회피 |
| 호환성 | local/AWS Batch/K8s/Step Functions 동일 코드 |
| 사용성 | Python-native, 데코레이터 1줄로 compute 전환 |
| 신뢰성 | `@retry` + `@catch`로 transient 실패 처리 |
| 보안 | datastore IAM + step 단위 secret 주입 |
| 유지보수성 | `self.x` artifact tracking으로 reproducibility |
| 이식성 | datastore property 교체로 cloud 무관 |
| 확장성 | pluggable serializer (2.19.26+)로 큰 artifact 처리 |

## Gotchas

### 큰 DataFrame을 `self`에 직접 저장
2GB 단일 pickle ceiling 위험. 50GB DataFrame은 S3 path/ID만 `self`에 보관, 데이터는 S3 직접 읽기.

### tuple artifact가 foreach join에서 merge 실패
SHA1 hash drift (Issue #253). list로 변환 후 join.

### unpicklable object를 `self`에 할당
RLock/DB connection/GPU handle 할당 시 task fail (Issue #391). 항상 step 내부 생성/소멸.

### foreach fan-out 폭발
큰 list에 foreach 돌리면 task 수 = len(list). AWS Batch 동시 quota / S3 PUT throttle 직접 타격. 청크 분할 필수.

### `@batch`와 `@resources` 우선순위 혼용
둘 다 명시 시 max 적용 — 의도치 않은 over-provisioning. 한쪽만 사용.

## Source

- https://docs.metaflow.org/metaflow/basics — "Metaflow treats steps as indivisible units of execution"; "Steps inside a foreach loop create separate tasks"; "Every branch must be joined", 조회 2026-05-10
- https://docs.metaflow.org/scaling/data — "When you assign anything to `self` in your Metaflow flow, the object gets automatically persisted in S3 as a Metaflow artifact", 조회 2026-05-10
- https://docs.metaflow.org/api/step-decorators/kubernetes — defaults `cpu=1, memory=4096, disk=10240`, 조회 2026-05-10
- https://docs.metaflow.org/api/step-decorators/retry — `@retry` + `@catch` no-op task semantics, 조회 2026-05-10
- https://pypi.org/project/metaflow/ — v2.19.28 (2026-05-07), Python 3.6–3.13, 조회 2026-05-10
- https://github.com/Netflix/metaflow/issues/253 — tuple foreach merge_artifacts hash drift, 조회 2026-05-10
- https://github.com/Netflix/metaflow/issues/391 — RLock unpicklable, 조회 2026-05-10
