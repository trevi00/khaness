---
name: toolchain-reproducibility
description: Operational reproducibility for local/CI toolchains — version pinning, task-runner side effects, and bootstrap safety made explicit beyond "works on my machine".
keywords: toolchain reproducibility version-pin asdf mise nvm rbenv pyenv volta sdkman jenv corepack node-version python-version ruby-version go-toolchain rust-toolchain dockerfile lockfile package-lock yarn-lock pnpm-lock cargo-lock poetry-lock pdm-lock makefile justfile taskfile invoke devcontainer codespaces bootstrap setup-script idempotent-script side-effect
intent: 툴체인고정해 버전관리해 setup스크립트만들어 makefile만들어 task-runner설계해 dev-container설정해 lockfile검증해 toolchain드리프트해결해 bootstrap만들어
paths: .tool-versions .nvmrc .python-version .ruby-version .node-version mise.toml .mise.toml asdf.toml Makefile Justfile Taskfile.yml package.json pyproject.toml Cargo.toml go.mod .devcontainer/ scripts/setup scripts/bootstrap
patterns: asdf mise nvm pyenv rbenv volta sdkman jenv corepack make just taskfile invoke poetry pdm pip-tools yarn pnpm npm cargo go-mod devcontainer
requires: deepinit repo-automation-safety devops convention
phase: plan implement review
tech-stack: any
min_score: 2
---

# Toolchain Reproducibility

`deepinit`이 **무엇을 설치하나**라면, 이 스킬은 **그게 모든 환경에서 같게 도는가**. 4축: toolchain pinning, task-runner side effect, bootstrap safety, drift detection.

## 의사결정 트리

### IF 새 프로젝트 / 첫 환경 (Plan)
1. **manager 1개 결정** — asdf / mise / 또는 native(nvm+pyenv+rbenv...). 혼용 금지(동일 PATH 충돌)
2. version 파일 — `.tool-versions`(asdf/mise) 또는 individual(`.nvmrc`, `.python-version`)
3. lockfile 정책 — package manager별 lockfile commit 의무
4. **bootstrap script** — `scripts/setup` 한 줄로 모든 도구 설치 + 의존성 설치
5. CI에 같은 manager + 같은 version 파일 사용 (local과 동일 경로)
6. **→ deepinit 스킬: 도구 검출 / 설치 가이드 참고**

### IF Task-Runner / Make / Just (Implement)
1. task-runner 1개 — Makefile / Justfile / Taskfile / npm scripts. 혼용 시 entry point 모호
2. **side effect 분리** — pure(generate file) / mutating(global install, daemon start) 명시
3. **idempotent** — 같은 명령 재실행해도 결과 같음. 임시 파일 cleanup, lock 충돌 방지
4. dependency graph — task 간 의존을 manager가 풀어줌(Make `prereq`, Just `dep`)
5. dry-run 또는 plan 모드 — destructive task는 prompt 또는 `--yes`

### IF Bootstrap Script 작성 (Implement)
1. **idempotent 의무** — 이미 설치된 것 검출 → skip
2. **fail-fast** — 한 단계 실패 시 다음 진행 금지(`set -e`)
3. **권한 명시** — sudo 필요한 부분 분리, 안 되면 user-local로 fallback
4. **OS 분기** — macOS/Linux/Windows(WSL/native) — 또는 명시적 단일 OS 선언
5. **의존성 포함** — manager 설치 자체도 포함(asdf install asdf 식)
6. **state 검증** — 끝에 `version` 명령으로 실제 설치 확인 + 기대값 매칭

### IF DevContainer / Codespaces (Implement)
1. base image pin — `mcr.microsoft.com/devcontainers/...:<hash>` 또는 `ubuntu-22.04`
2. tool 설치를 Dockerfile / postCreateCommand에서 — bootstrap script 재사용
3. user permission — root 안 되면 `containerUser`/`remoteUser` 명시
4. mount cache — node_modules, .gradle, ~/.cargo 등 named volume
5. extension/setting pin — `.devcontainer/devcontainer.json`

### IF Drift 감지 (Review)
- [ ] CI에서 `<manager> current` / `<lang> --version` 출력 + 기대값 비교
- [ ] lockfile drift — `npm ci` / `cargo build --locked` / `poetry install --no-update`
- [ ] bootstrap 재실행 시 결과 변화 없음(idempotent 검증)
- [ ] new contributor onboarding 시간(< 1h target)
- [ ] CI cache hit ratio — 너무 낮으면 lockfile 자주 깨짐

## 4축 체크리스트

```
[Toolchain Pinning]
□ manager 1개 + 버전 파일 commit
□ language version, package manager version 모두 pin
□ CI와 local에 같은 manager + 같은 파일 사용
□ lockfile commit + frozen install (--locked / ci / --no-update)

[Task-Runner Side Effect]
□ task-runner 1개로 통일
□ pure vs mutating task 구분 (주석 또는 naming)
□ 모든 task idempotent
□ dependency graph 명시 (manual 호출 순서 금지)

[Bootstrap Safety]
□ scripts/setup 한 줄로 동작
□ idempotent (재실행 OK)
□ fail-fast (set -e)
□ 끝에 state 검증 (`<tool> --version`)
□ OS / 권한 명시

[Drift Detection]
□ CI에서 toolchain 버전 echo + 기대값 검증
□ lockfile frozen install 강제
□ 분기별 manager / image 업데이트 PR
□ onboarding time 측정
```

## 가이드

### asdf vs mise vs native
- **asdf**: 오래됨, plugin 풍부. shim 방식이라 일부 명령 느림.
- **mise**(rtx 후속): 빠름, 같은 .tool-versions 호환. 일부 plugin asdf 대비 부족.
- **native(nvm/pyenv/rbenv)**: 도구별 독립. PATH 우선순위 충돌 위험.
프로젝트 단위로 1개 선택하고 README에 명시. 혼용은 금지.

### Lockfile Frozen Install
- `npm ci` (vs `npm install`) — package-lock 신뢰, drift 시 fail.
- `pnpm install --frozen-lockfile`
- `yarn install --immutable` (yarn 2+)
- `cargo build --locked`
- `poetry install --no-update` 또는 `--sync`
- `pip install -r requirements.txt` + `pip-tools`/`pip-compile`로 hash까지 고정.
CI에서 frozen 안 쓰면 lockfile drift가 silent.

### Task-Runner 선택
- **Make**: ubiquitous, tab-sensitive, escape 어려움.
- **Just**: simple recipes, error message 좋음, cross-platform.
- **Taskfile (yaml)**: declarative, Windows 호환.
- **npm scripts**: JS 프로젝트엔 자연스럽지만 cross-language 약함.
선택보다 **혼용 금지**가 중요.

### Idempotency 패턴
```
[ -f /usr/local/bin/foo ] || install_foo
which jq >/dev/null || apt-get install jq
mkdir -p path/  # idempotent
ln -sf src dst  # 기존 link 덮어씀
```
조건부 + 멱등 명령으로 재실행 안전성 확보.

### "Works on my machine" 진단
- PATH 우선순위(`echo $PATH` 비교)
- shell rc 차이(zshrc/bashrc/profile)
- manager shim 활성 여부
- 환경 변수(특히 `NODE_OPTIONS`, `JAVA_OPTS`)
- locale(`LANG=ko_KR.UTF-8` 등)

## Gotchas

### Manager 혼용으로 PATH 충돌
asdf + nvm 동시 활성 → `node` 명령이 PATH 우선순위에 따라 다름. 다른 사람 환경에서 다른 node. 한 manager만.

### `.nvmrc` 있는데 `nvm use` 안 함
파일은 commit 됐지만 shell auto-switch 설정 안 한 사람은 default node로 실행 → 미묘한 버그. direnv / chpwd hook 또는 manager auto-load 의무.

### Lockfile 무시하고 install
`npm install` (no `ci`) → 항상 latest 호환 version 가져옴 → CI마다 다른 transitive dep. CI는 항상 `npm ci` / `--frozen-lockfile`.

### `package.json` `engines` 만 보고 안심
`engines.node` 명시해도 강제 안 됨 — 단지 npm warning. `engines-strict=true` (.npmrc) 또는 별도 version 파일 + manager로 hard enforcement.

### Bootstrap script가 not idempotent
재실행 시 `cargo install` 매번 컴파일 / `git clone` "already exists" error → 새 사람이 setup 도중 멈춤. 체크 후 skip 패턴.

### Make tab vs space
Makefile은 recipe 들여쓰기가 **tab 의무** — 에디터 자동 space 변환 시 silent fail("missing separator"). `.editorconfig`로 Makefile만 tab 강제.

### Just / Make / npm scripts 동시 사용
`make build` / `npm run build` / `just build` 셋이 다른 일을 하면 contributor가 어느 게 진실인지 모름. one entry point + 다른 건 wrapper 또는 삭제.

### Devcontainer base image latest
`mcr.microsoft.com/devcontainers/javascript-node:latest` → 어느 날 base 변경 → reproducibility 깨짐. 명시 tag 또는 hash pin.

### Cache mount 없이 devcontainer rebuild
매번 npm install / gradle build 처음부터 → 빌드 10분+. named volume mount(node_modules, .gradle, .cargo).

### CI는 frozen인데 local은 unfrozen
local에서 `npm install` 자유로 → lockfile drift → CI에서 깨짐. local도 `npm ci`로 install (또는 hook).

### Tool installer가 sudo 가정
`sudo apt-get install ...` 가정한 bootstrap이 corp restricted env에서 fail. user-local fallback(asdf, mise는 user-local 가능).

### Toolchain manager 자체가 stale
asdf / mise를 1년+ 안 업데이트하면 plugin 새 버전 못 가져옴 / shell hook 깨짐. 분기별 manager update PR.

### `set -e` 빠진 setup script
한 줄 실패해도 다음 진행 → 부분 설치 → 사용자 다음 명령에서 모호한 에러. `set -euo pipefail` + `trap` cleanup.

### CI/local OS divergence
local macOS, CI Ubuntu — 미묘한 sed/grep 차이로 setup script 다른 결과. `/usr/bin/env bash` + portable POSIX, 또는 둘 다 같은 docker base.

## 도구 사용 패턴 (Harness)
- 버전 파일 검출: `Glob`으로 `.tool-versions`, `.nvmrc`, `.python-version`, `.ruby-version`
- lockfile 검출: `Glob`으로 `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `Cargo.lock`, `poetry.lock`
- task-runner: `Glob`으로 `Makefile`, `Justfile`, `Taskfile.yml`, `package.json`(scripts)
- 실제 버전 확인: `Bash`로 `<tool> --version` 출력 캡처
- bootstrap idempotency: `Bash`로 `scripts/setup`을 2회 실행 + 결과 비교

## 에러 복구 패턴 (Harness)
- "node version mismatch" → manager auto-switch hook 미설치, README의 `nvm use` / `mise install` 명시
- "lockfile keeps drifting" → CI frozen install 강제 + local commit hook
- "bootstrap fail mid-way" → 실패 step 식별 + 그 step부터 재실행 가능한가 점검(idempotent 미달 신호)
- "devcontainer 빌드 슬로우" → cache mount 누락, named volume 추가, base image layer 점검
- "PATH에 두 manager" → 한 쪽 비활성, shell rc 정리, 표준 manager 1개 합의 후 onboarding 갱신
