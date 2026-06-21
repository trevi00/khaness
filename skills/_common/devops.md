---
keywords: 데브옵스 devops 배포 deploy deployment CI CD 파이프라인 pipeline 도커 docker 컨테이너 container 쿠버네티스 kubernetes k8s 인프라 infra infrastructure 클라우드 cloud AWS aws GCP gcp Azure azure 테라폼 terraform 앤서블 ansible nginx 로드밸런서 워크플로우 workflow 액션 actions GHCR 레지스트리 registry Dependabot dependabot 의존성 gradle mysql redis 카프카 kafka zookeeper kraft
intent: 배포해 도커라이즈해 CI/CD구축해 컨테이너띄워 인프라구성해 파이프라인만들어
paths: .github/workflows docker/ k8s/ terraform/ infra/ deploy/ nginx/ ansible/ Dockerfile docker-compose.yml .gitlab-ci.yml Jenkinsfile
patterns: docker-compose kubernetes helm terraform ansible nginx caddy traefik github-actions gitlab-ci jenkins argocd dependabot trivy bandit ruff mypy gradle gradlew spring-boot mysql
requires: security monitoring
phase: plan implement deploy
min_score: 3
---

# DevOps Guide

## 의사결정 트리

### IF CI/CD 파이프라인 구축 (Plan)
1. 워크플로우 구성: ci.yml(PR), cd.yml(배포), e2e.yml(주간)
2. 서비스 컨테이너 목록 (DB, Redis 등)
3. 보안 스캔 도구 선정
4. **→ security 스킬: CI 보안 스캔 파이프라인 설계**

### IF Docker 이미지 빌드 (Implement)
1. 멀티스테이지 빌드
2. .dockerignore 작성
3. non-root 유저 실행
4. 헬스체크 설정
5. 환경변수로 설정 주입 (하드코딩 금지)
6. 레이어 캐싱 최적화 (의존성 파일 먼저 COPY)
7. **→ security 스킬: 컨테이너 보안 점검**

### IF 배포 실행 (Deploy)
1. 환경변수/시크릿 설정 완료 확인
2. DB 마이그레이션 실행
3. 롤백 계획 수립
4. 보안 스캔 통과
5. 배포 후 헬스체크 확인
6. **→ monitoring 스킬: 모니터링/알림 설정 확인**

## Git Branch 전략

### 브랜치 종류 및 네이밍
| 브랜치 | 용도 | 네이밍 규칙 | 예시 |
|--------|------|------------|------|
| master | 프로덕션 출시 | 이름 그대로 | `master` |
| develop | 다음 버전 개발 통합 | 이름 그대로 | `develop` |
| feature | 기능 개발 / 버그 수정 | `feature/{기능요약}` | `feature/login` |
| release | 출시 버전 준비 | `release-{버전}` | `release-1.2` |
| hotfix | 긴급 버그 수정 | `hotfix-{버전}` | `hotfix-1.2.1` |
| fix | 일반 버그 수정 | `fix/{이슈번호}-{설명}` | `fix/42-deal-status-error` |

### 브랜치 흐름
```
master ──────────────────────────── (프로덕션, merge request 필수)
  └─ develop ────────────────────── (통합, request 없이 merge)
       ├─ feature/login ─────────── (기능 개발 → develop PR)
       ├─ fix/42-status-error ───── (버그 수정 → develop PR)
       └─ release-1.2 ──────────── (릴리즈 준비 → master + develop)
  └─ hotfix-1.2.1 ──────────────── (긴급 수정 → master + develop)
```

### 작업 루틴
1. develop에서 기능별 브랜치 분기 (`feature/`, `fix/`)
2. 기능별 브랜치에서 작업
3. 작업 완료 후 develop에 PR
4. develop 테스트 완료 후 master에 병합 (merge request 필수)
5. hotfix는 master에서 분기 → 수정 후 master + develop 양쪽에 병합

### Commit Message 규칙
```
[유형] 제목

본문 (제목만으로 표현 가능하면 생략)

꼬리말 [유형]:#이슈번호 (관련 이슈 없으면 생략)
```

**커밋 유형:**
| 유형 | 설명 |
|------|------|
| `[feature development]` | 기능 개발 |
| `[feature delete]` | 기능 삭제 |
| `[feature modify]` | 기능 변경 |
| `[bug fix]` | 버그 수정 |
| `[refactoring]` | 코드 리팩토링 |
| `[form]` | 코드 형식, 정렬, 주석 변경 |
| `[test]` | 테스트 코드 추가/삭제/변경 |
| `[document]` | 문서 추가/삭제/변경 |
| `[project]` | 빌드 스크립트, Git 설정, 패키지 배포 설정 |
| `[version update]` | 버전 업데이트 |
| `[resolve conflict]` | 충돌 수정 |
| `[etc]` | 기타 |

**꼬리말 유형:** `해결:#이슈번호`, `관련:#이슈번호`, `참고:#이슈번호`

**예시:**
```
[feature development] 챗봇 답변 리스트 UI 작업 #1
- 더미 값으로 UI 구현.

해결:#123
```

### IF 인프라 문제 디버그 (Debug)
1. `docker logs <container>` → 로그 확인
2. `docker inspect --format='{{.State.Health}}'` → 헬스체크
3. `docker network inspect` → 네트워크
4. `docker stats` → 리소스 사용량

## 보안 스캔 도구
| 도구 | 용도 | 단계 |
|------|------|------|
| Ruff | Python 린트+포맷 | CI |
| MyPy | Python 타입 체크 | CI |
| Bandit | Python 보안 분석 | CI |
| ESLint | JS/TS 린트 | CI |
| Trivy | 컨테이너/파일 취약점 | CI |

## Docker Compose — Spring Boot + MySQL 5.7 패턴
```yaml
services:
  mysql:
    image: mysql:5.7
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: appdb
    ports:
      - "3306:3306"
    volumes:
      - ./init:/docker-entrypoint-initdb.d   # 초기 스키마/데이터
      - mysql-data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  mysql-data:
```

## Docker Compose — Kafka (KRaft 모드, Zookeeper 불필요)
```yaml
services:
  kafka:
    image: apache/kafka:3.8.0
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@localhost:9093
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_LOG_DIRS: /tmp/kraft-combined-logs
    healthcheck:
      test: ["CMD-SHELL", "kafka-broker-api-versions.sh --bootstrap-server localhost:9092"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
```
KRaft 모드: Kafka 3.3+에서 Zookeeper 없이 단독 실행 가능. 로컬 개발 시 컨테이너 1개로 충분.

## GitHub Actions — Gradle PR 테스트 워크플로우
```yaml
name: PR Test
on:
  pull_request:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'
      - uses: gradle/actions/setup-gradle@v4  # Gradle 캐싱
      - run: ./gradlew clean test -i -Pspring_profiles_active=test
      - uses: EnricoMi/publish-unit-test-result-action@v2
        if: always()
        with:
          files: '**/build/test-results/**/*.xml'
```
TestContainer 사용 시 CI에서 별도 MySQL 서비스 컨테이너 불필요 (TestContainer가 자체 관리).

### Ship 워크플로우 (GSD 흡수)

Phase 완료 후 PR을 생성하는 워크플로우:

#### Pre-flight 체크 (5가지)
1. 검증 통과 확인 (doc-verify 또는 verification PASS)
2. Clean working tree (`git status` 깨끗)
3. Feature 브랜치 확인 (main/develop 아닌 브랜치)
4. Remote 설정 확인
5. `gh` CLI 인증 확인

#### PR 본문 자동 생성
```bash
gh pr create \
  --title "Phase N: {도메인명}" \
  --body "$(cat <<'EOF'
## Summary
- ROADMAP 목표 요약
- 변경된 도메인/파일 목록

## Changes
- 각 도메인별 핵심 변경 사항

## Verification
- doc-verify PASS 결과
- 컴파일/테스트 결과

## Checklist
- [ ] 외부/공통 패키지 미수정 (회사 컨벤션 따라)
- [ ] 빌드 통과
- [ ] 테스트 통과
EOF
)" \
  --base develop
```

#### 에러 처리
- Push 실패: upstream 설정 후 재시도
- 검증 미통과: 경고 + 사용자 확인 필요
- gh CLI 미설치: 설치 안내

## Gotchas

### Windows Docker 경로 문제
Windows에서 volume mount 시 경로가 `/c/Users/...` 형태여야 함. `C:\Users\...`는 동작하지 않을 수 있음. Docker Desktop 설정에서 드라이브 공유 확인.

### line ending (CRLF vs LF)
Windows에서 만든 셸 스크립트를 Docker Linux 컨테이너에 COPY하면 `\r` 때문에 실행 실패. `.gitattributes`에 `*.sh text eol=lf` 설정하거나, Dockerfile에서 `RUN sed -i 's/\r$//'` 적용.

### COPY 순서와 캐시 무효화
`COPY . .` 전에 `COPY package*.json ./` + `RUN npm ci`를 해야 소스 변경 시에도 의존성 레이어 캐시 활용 가능. 순서가 바뀌면 매번 전체 재설치.

### GitHub Actions secrets와 Fork PR
Fork된 PR에서는 repository secrets에 접근 불가. `pull_request_target` 이벤트를 사용하면 되지만 보안 위험이 있으므로 주의.

### docker-compose depends_on 함정
`depends_on`은 컨테이너 시작 순서만 보장하지, 서비스 준비 상태를 보장하지 않음. `condition: service_healthy`와 healthcheck를 함께 사용해야 실제 준비 완료 대기 가능.

### HEALTHCHECK start-period
컨테이너 시작 직후 헬스체크 실패는 정상. `--start-period`를 충분히 줘야 불필요한 컨테이너 재시작 방지.

### Docker BuildKit 비활성화 시 --mount 사용 불가
`RUN --mount=type=cache` 같은 BuildKit 기능은 `DOCKER_BUILDKIT=1` 환경변수가 설정되어야 동작. Docker Desktop 최신 버전에서는 기본 활성화.

## 도구 사용 패턴 (Harness)
- Dockerfile 수정: `Read`로 현재 내용 확인 → `Edit`으로 수정 (전체 재작성 지양)
- 컨테이너 로그: `Bash(docker logs)`로 확인, 긴 출력은 `Bash(timeout 10 docker logs --tail 100)`
- CI 파일 수정: YAML은 들여쓰기가 중요하므로 `Edit`으로 정확한 위치만 수정
- 환경변수/시크릿: `Grep`으로 사용처 확인 후 설정 (Bash(echo) 대신 Write 사용)

## 에러 복구 패턴 (Harness)
- 배포 실패 → `Bash`로 빌드 로그 확인, 실패 단계 특정
- 빌드 성공/런타임 실패 → `Bash(docker logs)` + 헬스체크 상태 확인
- 헬스체크 실패 → `Read`로 환경변수 설정 확인, 의존 서비스 연결 점검
- 복구 불가 → 롤백 계획 실행 (이전 이미지 태그로 `Bash(docker run)` 또는 이전 배포 트리거)

## Related (신규 그래프 cross-ref)

devops가 참조하거나 진화한 신규 노드:
- `infra/spinnaker-pipeline.md` — Spinnaker 2026.x multi-cloud CD (Bake/Deploy/Manual Judgment/Pipeline/Webhook 표준 stage), GitHub Actions 보완
- `infra/k8s-runtime-titus-style.md` — vanilla K8s + Karpenter v1 (Titus archived 2022, reference만)
- `infra/observability-otel-prom.md` — OTel collector + Prometheus remote write + Grafana
- `_common/chaos-engineering.md` — AWS FIS / Gremlin (배포 후 reliability 검증 자동화)
- `_common/edge-gateway-routing.md` — Envoy 1.38 + Istio 1.5+ + Spring Cloud Gateway 4.x
- `_common/load-shedding-prioritized.md` — Zuul priority threshold + service-level shedding
- `java/lang/gradle-nebula-multi-project.md` — Gradle 8.14 Kotlin DSL + version catalog + custom plugin
- `java/lang/testcontainers-junit-integration.md` — Testcontainers + Spring Boot `@ServiceConnection` + DinD sibling 패턴
