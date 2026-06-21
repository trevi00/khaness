---
description: 임의 코드베이스를 역설계하여 PRD(.claude/requirements/) + 학습 노트(study/) 2-track 폴더를 점진적 릴리즈 단위(1-A 토대 → 1-B 핵심 도메인 → 1-C 진입 플로우 → 2 유틸)로 생성한다. 원본 코드는 변경하지 않고 별도 분석 폴더에 산출. study-example_app-agent-docs / example_app-client-client-analysis 패턴 기반.
user-invocable: true
argument-hint: "<원본 프로젝트 경로> [출력 폴더] [피닝 커밋 SHA]"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate
category: design
mutates: yes
long-running: yes
external-deps: git, python-cli
---

You are running the **harness-reverse-prd** workflow — reverse-engineering a target
codebase into a 2-track PRD folder (`.claude/requirements/` + `study/`) following
the proven pattern from `study-example_app-agent-docs` and `example_app-client-client-analysis`.

## Inputs

Argument format: `<source_path> [output_path] [pinned_commit]`

- `source_path` (필수): 분석 대상 프로젝트 절대 경로 (예: `/home/user/myproject`)
- `output_path` (선택): 출력 폴더. 미제공 시 `<source_path>-analysis/` 자동 생성
- `pinned_commit` (선택): 분석 시점 commit SHA. 미제공 시 `git rev-parse HEAD`로 자동 추출

If `source_path` is empty or invalid, ask the user and stop.

## 참조 자산 (Reference Implementations)

본 명령은 다음 결과물의 패턴을 그대로 따른다. 작성 중 의문이 있으면 두 폴더를
원본으로 비교하라:

- `/home/user/study-example_app-agent-docs/` — 19 도메인 / 175 US / 21차 검증 (마스터)
- `/home/user/example_app-client-client-analysis/` — 8 도메인 / ~50 US (1-B까지 완료)

## Output Folder Structure (확정)

```
{output_path}/
├── README.md                           ← 메타 (원본 + 피닝 + 두 트랙 차이 + 운영 방침)
├── .gitignore                          ← OS/IDE/임시
├── .claude/
│   ├── tech-stack.yaml                 ← 분석 대상 스택 + extensions
│   └── requirements/                   ← PRD 트랙 (SSOT, 건조)
│       ├── README.md                   진입 가이드
│       ├── index.md                    Executive Summary + 문서 맵 + 릴리즈 + 핵심 발견 + 기술 스택
│       ├── context.md                  페르소나 N종 + KPI + In-Scope/Non-Goals
│       ├── glossary.md                 용어 사전 (prefix / 식별자 / 핵심 개념 / 에러 enum)
│       ├── architecture.md             토폴로지 / 포트맵 / 컴포넌트 / 이벤트·API 매트릭스 / 캐시 / 관찰성 / SSOT 갱신 가이드
│       ├── nfr.md                      ISO 25010 8 속성 (1-C 이후)
│       ├── risks.md                    리스크 / 의존성 / 거부된 대안 (1-C 이후)
│       ├── changelog.md                릴리즈별 변경 이력
│       └── domain/
│           ├── _ROADMAP.md             도메인 로드맵 + 의존성 그래프 + US prefix 규칙
│           ├── _template.md            도메인 파일 템플릿
│           └── {도메인}.md             각 도메인 — US + 기능상세 + AC + 상태전이 + 동시성 + 에러 + 연관문서 체크
├── study/                              ← 학습 노트 트랙 (대화형, Mermaid)
│   ├── 00-README.md                    진입 가이드
│   ├── 01-전경.md                      시스템 전체 그림
│   └── NN-{도메인}.md                  각 도메인 — Mermaid 다이어그램 + 핵심 스니펫 + 사고 실험 + PRD 링크
└── _legacy/                            (선택) 정리 전 분석 자료 보존
```

## Spec Bundle emit (통합 — unified-pipeline, 신규 기본 산출물)

본 명령은 `.claude/requirements/` 2-track PRD에 더해 **stack-neutral Spec Bundle**(`<output>/.claude/spec/`)을 emit한다. Spec Bundle은 forward test-gen(`lib.testgen`)·`spec_bundle` validator가 직접 소비하는 단일 spec 계약이라, 역설계 결과가 그대로 테스트 생성으로 이어진다.

**emit 흐름 (결정론 + 행위 저작 분리):**
1. **결정론 절반 (CLI)** — 1-A 토대 시작 시 1회:
   ```
   python -m cli.spec_bundle_emit --root <source_path> --out <output_path>
   ```
   → `spec/facets/{logical,er}.schema`(DDL → typed 구조 facet, 결정론), `spec/manifest.yaml`(*Controller.java에서 도메인 감지 + source_mode=reverse), `spec/domain/<d>.feature` **scaffold**(도메인별 Feature 헤더 + `@id:<d>-TODO`). **read-only on source** — 절대 `<source_path>`에 쓰지 않음. 재실행 시 저작된 `.feature`는 clobber 안 함.
2. **행위 spine 저작 (이 명령/LLM)** — 1-B 핵심 도메인 단계에서 각 도메인의 실 행위(컨트롤러/서비스 정독)를 읽어 `spec/domain/<d>.feature`의 scaffold를 **`@id`'d Given-When-Then 시나리오**로 교체. 성공 AC + 에러 AC 동시 작성. 코드만으로 확정 불가/미구현은 `> ⚠️ 역설계 추정` 주석 + `@not-implemented` 태그로 명시(추측 금지 — 실 행위만, vendor-spec-defense).
3. **검증** — `python -m validators.spec_bundle` 또는 autopilot이 `@id` 유일성·manifest↔domain·facet 정합을 advisory로 점검. 생성된 spec은 `python -m cli.spec_bundle_emit --json` 또는 `lib.testgen`으로 스택별 테스트 stub(java→Cucumber-JVM)까지 round-trip.

**facets vs 행위**: 구조(ER/논리/클래스/API)는 facet(typed, 결정론), 행위는 Gherkin spine(behavior only)으로 **분리**(Gherkin에 DB/API 구조 넣지 않음). 이는 2-track PRD의 `domain/*.md`(서술형 GWT)를 **기계가독 `.feature`로 승격**한 것.

## Protocol — 4 릴리즈 단위 점진 작성

> **릴리즈 체크포인트 + 소스 드리프트 감지 (결정론 — closes "no checkpointing / source
> change invalidates prior artifacts")**: 각 릴리즈 commit 직후
> `lib.reverse_prd_checkpoint.record_release(out_root, "<release>", src_commit=<pinned_commit>, status="complete")`.
> 다음 릴리즈 시작 전 `check_drift(out_root, src)` 로 **소스 commit이 이전 릴리즈 빌드 시점과
> 달라졌는지** 확인 — drift면 stale 산출물 위에 layering하지 말고 re-baseline (사용자에게 보고).
> `render_status(out_root, src)` 로 릴리즈별 상태+drift를 한눈에.

### 릴리즈 1-A: 토대 (Foundation)

**의도**: 다음 릴리즈가 빌드할 기반. 페르소나·용어·아키텍처가 여기서 확정되어야 도메인 파일이 정합.

1. **출력 폴더 생성 + git init** (로컬 전용, 원격 push 금지)
2. **코드 quick scan**:
   - `pubspec.yaml` / `package.json` / `pom.xml` / `Cargo.toml` 등에서 스택 + 의존성 추출
   - `lib/` / `src/` 트리에서 디렉토리 구조 파악
   - `main.dart` / `index.ts` / `Application.kt` 등 entry point 읽기
   - DI 컨테이너 / Routes / DB 정의 / WebSocket / 에러 enum 위치 확인
3. **도메인 식별**:
   - DI 컨테이너의 등록 카탈로그
   - 디렉토리 구조의 도메인 단위 폴더 (예: `Logics/global/{domain}/` 또는 `features/{domain}/`)
   - 라우트 그룹 (예: `/admin/*` / `/menu/*`)
   - 사용자에게 도메인 N개 식별 결과 보고 → 동의 받음
4. **페르소나 식별**:
   - 라우트 그룹 + 화면 흐름에서 추정 (예: 관리자 / 일반 사용자 / 자동)
   - 사용자에게 페르소나 N종 보고 → 명세 보강 받음
5. **파일 작성** (의존성 순서):
   - `README.md` (메타)
   - `.gitignore`
   - `.claude/tech-stack.yaml`
   - `.claude/requirements/README.md`
   - `.claude/requirements/context.md` (페르소나 + KPI + Non-Goals — KPI/Non-Goals는 사용자 입력 필수)
   - `.claude/requirements/glossary.md` (코드에서 발견한 용어 + prefix + enum 카탈로그)
   - `.claude/requirements/architecture.md` (토폴로지 + 컴포넌트 트리 + 이벤트·API 매트릭스 골격)
   - `.claude/requirements/changelog.md` ([1.0.0-A] 항목)
   - `.claude/requirements/domain/_ROADMAP.md` (도메인 + 의존성 그래프 + 상태 기호 📝🔨✅🔁)
   - `.claude/requirements/domain/_template.md` (US/AC/상태전이/동시성/에러/연관문서 체크)
   - `study/00-README.md`
   - `study/01-전경.md` (Mermaid 토폴로지 + 핵심 스니펫 + 사고 실험)
   - `.claude/requirements/index.md` (마지막 — 모든 파일 완성 후 문서 맵)
6. **commit** (`[1-A] 릴리즈: 토대 (Foundation)`)
7. **사용자 보고**: 1-A 산출물 매트릭스 + 1-B 진행 의사 확인

### 릴리즈 1-B: 핵심 도메인

**의도**: 시스템의 가장 중요한 도메인 (인프라 + 백엔드 핵심) 명세.

1. **도메인 의존성 그래프**에서 외부 의존이 적은 도메인부터 작성
2. **각 도메인** 작성 시:
   - `cp _template.md {domain}.md` 후 본문 작성
   - US-{prefix}NN 단위 (AS / I WANT / SO THAT + 기능상세 + AC Given/When/Then 다수 시나리오)
   - 상태 전이 + 동시성 + 에러 코드 요약 + 연관 문서 업데이트 체크
   - 코드 인용 시 GitHub 피닝 커밋 링크 (`https://github.com/{org}/{repo}/blob/{commit}/{path}`)
   - **역설계 추정** 항목은 `> ⚠️ 역설계 추정` 블록으로 표시
3. **SSOT 연쇄 갱신** — 도메인 1개 완성 시 architecture.md / glossary.md 동시 갱신
4. **학습 노트 작성** — 각 도메인당 study/NN-{domain}.md (Mermaid 시퀀스 + 핵심 스니펫 + 사고 실험)
5. **commit** (`[1-B] 릴리즈: 핵심 도메인`)

### 릴리즈 1-C: 진입 플로우 + nfr/risks

1. 부팅 / 인증 / 환경설정 / 라이선스 등 진입 도메인 작성
2. `nfr.md` (ISO 25010 8 속성 + 측정 지표)
3. `risks.md` (리스크 매트릭스 + 거부된 대안)
4. study/ 진입 노트
5. **commit** (`[1-C] 릴리즈: 진입 플로우`)

### 릴리즈 2: 유틸/관리자

1. 로깅 / 관리자 화면 / 백오피스 도메인
2. `changelog.md` 최종 정리
3. `index.md` 최종 갱신
4. **commit** (`[2] 릴리즈: 유틸·관리자`)

## 핵심 자동화 포인트

| 항목 | 자동 추출 | 사용자 입력 필요 |
|------|---------|----------------|
| 기술 스택 | pubspec/package.json 등 | - |
| 도메인 카탈로그 | DI 컨테이너 + 디렉토리 트리 | 도메인 분류 동의 |
| 페르소나 | 라우트 그룹에서 추정 | 페르소나 명세 보강 |
| KPI / Non-Goals | (자동 X) | **필수** |
| 에러 enum | implements ErrorType 패턴 | - |
| 액션/이벤트 | enum + 메시지 핸들러 | agent contract (외부) 추가 자료 |
| 상태 전이 | enum + flag 필드 + 분기 | 사용자 검증 |
| 코드 인용 | GitHub 피닝 커밋 링크 자동 생성 | - |

## 작성 컨벤션

### PRD 트랙
- **건조, 명세적, 3인칭**
- **금지어 차단**: 적절한/충분한/빠르게/효율적으로/처리한다/할 수 있다/등 → 구체 수치/동사
- **에러 AC 동시 작성**: 성공 AC 1개 + 에러 AC 1개 이상 (입력/리소스/충돌/인프라 4분류)
- **`> ⚠️ 역설계 추정`** 블록으로 코드만으로 확정 불가한 항목 표시
- **SSOT 단방향**: 도메인 → architecture/glossary 갱신, 역방향 금지

### 학습 노트 트랙
- **대화형, 자연스러운 한국어**
- **Mermaid 다이어그램** (시퀀스 / 상태 / 클래스 / 플로우)
- **핵심 스니펫** 5~10줄 + "왜 중요한가" 한 단락
- **사고 실험** ("만약 ~하면?") 3~5건
- **PRD로 건너가기** — 대응 US-ID 링크

### git 운영
- **로컬 전용**: 원격 push 안 함, `git push` / `git remote add` 실행 금지
- **author**: 사용자 명시 회사 정보로 (`-c user.email=... -c user.name=...`)
- **commit = 세이브포인트**: 릴리즈 경계마다 의미 있는 commit
- **`.gitignore`**: OS/IDE/임시만. 원본 프로젝트 commit 정책은 별도

## Output schema (mandatory — print as the FIRST visible message)

분석 시작 전 사용자에게 다음 보고:

```
## 분석 대상
- 원본: <source_path>
- 피닝 커밋: <commit>
- 출력 폴더: <output_path>

## 1단계 도메인 식별 결과 (코드 quick scan)
- 도메인 N개: {domain_a}, {domain_b}, ...
- 페르소나 N종: {persona_a}, {persona_b}, ...
- 기술 스택: {language} {framework} {version}

## 사용자 입력 필요
[ ] KPI 비즈니스 목표 (예: P95 부팅 ≤10초)
[ ] In-Scope / Non-Goals 범위
[ ] 페르소나 명세 (역할/니즈/페인포인트)
[ ] git author 정보 (commit author)

진행해도 될까요? 도메인 분류에 추가/제거할 게 있나요?
```

이후 단계마다 다음 형태로 진행 보고:

```
## 릴리즈 1-A 토대 작성 중 (8/12 파일)
- ✅ README.md / .gitignore / tech-stack.yaml / requirements/README.md
- ✅ context.md / glossary.md / architecture.md / changelog.md
- 🔨 _ROADMAP.md / _template.md
- 📝 study/00, 01 / index.md (마지막)
```

## Non-Goals

- **원본 코드 수정**: 절대 안 함. read-only 분석.
- **원격 push**: 출력 폴더는 로컬 git only. `git push` / remote 추가 금지.
- **페르소나/KPI 자동 발명**: 사용자 입력 없이 임의 작성 안 함. "필수 입력" 표시.
- **모든 도메인 한 번에 생성**: 점진적 릴리즈. 각 단계 사용자 검토 받음.
- **`~/.claude/skills/` 변경**: 본 명령은 출력 폴더만 수정. 글로벌 스킬은 별도.
- **CI/빌드 실행**: 분석은 read-only. 빌드 안 함.

## Error handling

- **`source_path` 없음/invalid** → 사용자에게 정확한 경로 요청, 정지
- **`output_path` 이미 존재 + 비어있지 않음** → 사용자 확인 필수 (덮어쓰기 vs 새 폴더)
- **`pinned_commit` 무효** → `git rev-parse HEAD` fallback + 경고
- **도메인 식별 실패 (DI/엔트리 못 찾음)** → 사용자에게 수동 입력 받음
- **페르소나 식별 실패** → 사용자 입력 필수, 자동 진행 금지
- **flutter analyze / 빌드 명령** → 본 명령에선 실행 안 함 (분석만)

## Comparison with related commands

| 명령 | 차이 |
|------|------|
| `harness-pinit` | 프로젝트 분석 → .claude/ 초기 세팅 제안 (PRD 작성 안 함). 본 명령은 PRD 본문까지 자동 작성. |
| `harness-skill` | ~/.claude/skills/ 트리 관리. 본 명령과 영역 다름. |
| `harness-debate` | 단일 설계 결정 토론 엔진. 본 명령 안에서 호출 가능 (도메인 분류 모호 시) |
| `harness-interview` | 사용자 명세 인터뷰. 본 명령의 "사용자 입력 필요" 단계에서 chain 호출 가능 |

## Examples

### 예시 1 — Flutter 프로젝트 역설계
```
/harness-reverse-prd /home/user/myapp
→ 출력: /home/user/myapp-analysis/
→ 피닝: 자동 (현재 HEAD)
→ 1-A 토대 작성 → 사용자 검토 → 1-B 진행
```

### 예시 2 — 명시 출력 + 명시 피닝
```
/harness-reverse-prd /c/repo/spring-boot-app /c/study/spring-app-docs abc1234
→ 출력: /c/study/spring-app-docs/
→ 피닝: abc1234 (HEAD 무관)
```

### 예시 3 — 자매 프로젝트 페어 분석
```
/harness-reverse-prd /c/repo/client
... 작성 후 ...
/harness-reverse-prd /c/repo/server
→ 두 분석 폴더가 cross-reference (client의 contract → server에서 검증)
```

## Roadmap (v1 → v2)

- **v0 (current)**: 사용자 input 받고 대부분 수동 작성. orchestrator 역할.
- **v1**: 도메인 식별 자동화 강화 (DI/Routes 분석기), Mermaid 자동 생성
- **v2**: SSOT 연쇄 갱신 자동화 (도메인 작성 → architecture.md 자동 patch)
- **v3**: doc-verify 통합 (작성 후 5 Quality Gates 자동 검증)

## Output

- output sibling repo at `<output_path>` (default `<source_path>-analysis`):
  - `.claude/requirements/` — PRD tree (context, domain/*.md, nfr, architecture, risks, glossary, changelog, index)
  - `study/` — release-staged learning notes (1-A, 1-B, 1-C, 2)
  - `.git/` — initialized + per-release commits
- status: `release_<n>_complete` | `aborted_source_invalid` | `aborted_output_conflict` | `aborted_pinned_commit_invalid`.

## Failure behavior

- **source path invalid OR not a git repo**: abort with `aborted_source_invalid`. No output writes.
- **output path already exists with non-empty content**: abort with `aborted_output_conflict`. Refuse to overwrite — user must remove or supply different path.
- **source readonly assertion** (Round-3 P0 #8): NEVER write to `<source_path>`; use `git -C <source>` only with read-only commands (`log`, `show`, `cat-file`, `diff`). Verify by tracking source repo HEAD pre/post — if changed, error out.
- **pinned_commit invalid**: abort with `aborted_pinned_commit_invalid` + suggestion to use `git -C <source> log --oneline | head`.
- **release stage failure**: preserve completed releases, mark this release as `partial`, surface what's missing. User can resume from `--release 1-B` with prior 1-A artifacts intact.
- **output git commit failure** (signing key missing, hook block): surface exact reason; staged files remain in `<output_path>` so user can commit manually.

## Gate summary

- preflight: `<source_path>` is a git work tree; `<output_path>` is empty or doesn't exist; `<pinned_commit>` resolves under source if specified; python-cli + git available.
- success criteria: target release stage's expected artifacts written under `<output_path>` AND committed to output git.
- abort triggers: source readonly violation; output conflict; pinned commit invalid; user interrupt mid-stage.

## Retry / Resume

- checkpoint: per-release commit in output repo's git log. Each release stage = one commit (or commits with shared prefix).
- resume command: `/harness-reverse-prd <source> <output> --release 1-B` (or whichever stage failed). Reads existing `<output>/.claude/`, picks up at next-needed stage.
- idempotent: per-release stage YES (re-running 1-A produces equivalent output if source HEAD unchanged). Across stages: incremental — earlier artifacts feed later, never overwritten.
- stall detection: stage counter monotonic. If command stops mid-release, output git working tree dirty — `git status` shows uncommitted; safe to delete or cherry-pick.

## Boundary with other commands

- vs `harness-pinit`: pinit ANALYZES existing `.claude/` (read-only, no PRD generation); reverse-prd CREATES new sibling repo with reverse-engineered PRD docs.
- vs `cli.reverse_engineer`: reverse-prd is the orchestrator; reverse_engineer is the per-extractor backend (convention/er/logical/openapi/...). reverse-prd composes them into staged PRD.
- vs `kha-new-project`: kha-new-project bootstraps `.planning/` for greenfield work; reverse-prd retro-fits PRD onto existing brownfield code.
- vs `harness-extend`: extend designs new harness mechanisms; reverse-prd documents existing project mechanisms.
