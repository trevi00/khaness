---
name: gsd-skill-promotion-runbook
description: Operator runbook for promoting auto-detected skill candidates via cli/promote_skill.py — token gate, body authoring, atomic commit sequence, exit code recovery.
keywords: skill-promotion, enable-skill, promote_skill, operator-cli, harness-mutation-token, atomic-commit
---

# Skill Promotion Runbook (gsd-skill-promotion-runbook)

> 본 스킬은 `cli/promote_skill.py` (debate-1779507623-8a6f45 73-LOCK consumer)의 operator workflow를 영구화합니다. wave 20 architectural gap → wave 21 consumer land → wave 22 첫 의미적 promote.

## 언제 사용하는가

- `~/.claude/skill-candidates/<cid>.json`이 누적되고 (PostToolUse extractor 발화 후) 그 중 하나를 실제 스킬로 등록하고 싶을 때
- candidate manifest는 trigger일 뿐 — 실제 등록되는 스킬 body는 operator가 별도 작성
- harness 외 일반 도메인 스킬을 등록할 때도 같은 파이프라인 (manual candidate stub 만들고 promote)

## 4단계 워크플로우

### 1. Token export (same-shell)

```bash
# Git Bash
export HARNESS_MUTATION_TOKEN=enable-skill

# PowerShell
$env:HARNESS_MUTATION_TOKEN='enable-skill'

# 검증
python -c "import os,sys; sys.exit(0 if os.environ.get('HARNESS_MUTATION_TOKEN')=='enable-skill' else 1)"
echo $?  # 0 이어야 진행
```

### 2. Body 작성

frontmatter 필수 키 3개 — 누락 시 exit 3:

```markdown
---
name: gsd-<short-name>
description: <single-line, no period needed>
keywords: <comma, separated, list>
---

# <Title>

<body 내용 — markdown 자유 형식>
```

### 3. Dry-run

```bash
python -m cli.promote_skill \
  --candidate <cid> \
  --body-from /path/to/body.md \
  --as gsd-<name> \
  --dry-run
```

dry-run 출력의 `target=<...>` 경로 확인. SKILLS_DIR/<name>/SKILL.md 형식이어야 함.

### 4. Real promote

dry-run 검토 후 `--dry-run` 제거. 성공 시:

- `~/.claude/skills/gsd-<name>/SKILL.md` 작성 (atomic in-place tmp + os.replace)
- 후보 JSON → `<cid>.json.promoted.<ts_ms>` rename (audit trail; never deleted)
- `~/.claude/state/skill_promotion_completed.txt`에 `<ts_ms>:<cid>` ack 추가
- 다음 prompt match cycle부터 matcher가 자동 인식

## Exit code 복구 가이드

| code | 의미 | 복구 |
|------|------|------|
| 0 | success | — |
| 1 | token missing / mismatch | env 재설정 + 같은 shell에서 재시도 |
| 2 | --body-from missing | 파일 경로 확인 |
| 3 | frontmatter shape | name/description/keywords 3개 모두 non-empty |
| 4 | stale .promoting marker | `~/.claude/skill-candidates/<cid>.json.promoting` 수동 삭제 후 재시도 |
| 5 | PermissionError | SKILL.md를 열고 있는 editor/indexer 닫고 재시도 |
| 6 | candidate JSON parse | candidate JSON 수동 수정 |
| 7 | Unicode encode/decode | body 파일 UTF-8 확인 |
| 8 | namespace policy | `gsd-*` 또는 `_gsd/<single-segment>` 만 허용; `harness-*` 금지 |
| 9 | other OSError | 메시지 확인 (candidate 미존재, target dir 권한 등) |

## Namespace policy

- 허용 prefix: `gsd-<rest>` (단일 세그먼트) OR `_gsd/<subname>` (subname 정규식 `^[a-z][a-z0-9_-]{0,31}$`)
- 금지: `harness-*` 또는 bare `harness` (validators/skill_frontmatter.py와 mirror)
- `--as gsd-foo/bar` → exit 8 (gsd- prefix는 슬래시 금지)
- `--as _gsd/foo/bar` → exit 8 (subname은 단일 세그먼트)

## Atomic commit sequence (LOCK)

1. `mark_candidate_promoting(candidate_path)` — `.promoting` sibling marker 작성. stale 시 exit 4 차단 (재진입 방지).
2. `target_dir/.SKILL.md.tmp.<uuid8>` 작성 (UTF-8)
3. `os.replace(tmp, target_dir/SKILL.md)` — same-directory atomic rename
4. `commit_candidate_promoted(candidate_path, ts_ms)` — candidate JSON → `.promoted.<ts_ms>` rename (audit; 삭제 금지)
5. `advisory_ack.resolve('skill_promotion_completed').ack(f'{ts_ms}:{cid}')`
6. finally: `.promoting` marker best-effort 삭제

각 단계는 별도 syscall — 중간 crash 시 `.promoting` marker가 남아 재시도가 exit 4로 차단됨. 운영자가 marker를 검토 후 수동 삭제하고 처음부터 다시.

## Gotchas

### CLAUDE_HOME 불일치 (Git Bash vs Python)
Git Bash `~`는 `$HOME` 환경변수 ($APPDATA/HOME_REDIRECT 등으로 redirect되는 경우 있음). Python `Path.home()`은 USERPROFILE. 둘이 다르면 `ls ~/.claude/skills/...`가 빈 결과를 반환하지만 Python-resolved 경로에 실제 파일이 존재. `python -c "from lib.paths import CLAUDE_HOME; print(CLAUDE_HOME)"`로 authoritative 경로 확인.

### Operator-CLI only invocation
`promote_skill`은 cron/hook/posttooluse/subagent로 호출 금지 (LOCK invariant). 운영자가 명시적으로 shell에서 실행. 자동화하려면 새 토큰 정의 + 별도 wrapper (이번 LOCK 외).

### Body는 candidate manifest와 무관
candidate JSON의 description/allowed_tools는 trigger metadata일 뿐. 실제 SKILL.md body는 operator가 자유롭게 작성 — manifest 자동 매핑 안 됨 (`manifest_to_frontmatter_auto_mapping = disabled`).

### `.promoted.<ts_ms>` 누적
audit trail 보존 정책상 promote 성공 후에도 candidate JSON은 sibling rename으로 보존됨. 주기적 clean-up은 별도 운영자 작업 (자동 삭제 안 함).

### 첫 promote 후 matcher 인식
SKILL.md land → 다음 prompt match cycle에 자동 노출. 별도 reload 불필요. 단, 동일 cycle 안에서는 인식 안 됨 (cache).

## 도구 사용 패턴 (Harness)

- 환경 검증: `Bash(python -c "import os; print(os.environ.get('HARNESS_MUTATION_TOKEN'))")`
- candidate 목록: `Glob(~/.claude/skill-candidates/*.json)`
- promoted audit: `Glob(~/.claude/skill-candidates/*.promoted.*)`
- ack log: `Read(~/.claude/state/skill_promotion_completed.txt)`
- dry-run 우선: 실제 promote 전 항상 `--dry-run` 1회

## 5축 품질 체크 (E2 evaluator alignment)

| 축 | 본 워크플로우 충족 |
|---|---|
| 응집 | 단일 책임 — candidate → SKILL.md 1회 promote |
| 결합 | lib/advisory_ack + lib/paths + lib/frontmatter만 의존 (낮은 결합) |
| 확장 | 새 namespace prefix는 `_resolve_namespace` 한 곳만 수정 |
| 안정 | atomic commit + .promoting marker로 crash-safe |
| 사용 | 9 exit code 명시 → 운영자 복구 결정 가능 |
