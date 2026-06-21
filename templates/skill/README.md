# Skill Manifest Template — agentskills.io v1

본 디렉토리는 외부 agentskills.io v1 호환 skill의 manifest 작성 template입니다 (Hermes 흡수 — `synthesis/HARNESS-APPLY.md` H4).

## 사용법

새 skill manifest 작성 시:

```bash
cp ~/.claude/templates/skill/manifest-template.json \
   ~/.claude/skills/external/<vendor>/<skill-name>/manifest.json

# 그 다음 필드 채우기:
# - name / version / description / vendor / license
# - category (implement | review | plan | debug | research)
# - allowed_tools / denied_tools (security boundary)
# - tech_stack_filter (해당 시)
```

## 필드 가이드

| 필드 | 필수 | 설명 |
|------|------|------|
| `$schema` | ✅ | `https://agentskills.io/schema/v1.json` 고정 |
| `name` | ✅ | skill 고유 식별자 (kebab-case, vendor namespace 제외) |
| `version` | ✅ | SemVer (`0.1.0`) |
| `description` | ✅ | 한 줄, 도구 카탈로그 표시용 |
| `vendor` | ✅ | 작성자 / 조직명 |
| `license` | ✅ | SPDX identifier (`MIT`, `Apache-2.0` 등) |
| `category` | ✅ | 라이프사이클 단계 매핑 |
| `allowed_tools` | ✅ | 허용 도구 (whitelist) |
| `denied_tools` | ⚠️ | 차단 도구 (blacklist) — 권장 |
| `mutates` | ✅ | 시스템 상태 변경 여부 (true 시 게이트 강제) |
| `long_running` | ✅ | 30초+ 작업 여부 (UX 표시용) |
| `secret_scan_required` | ✅ | API key / token 누출 차단 강제 |
| `invariant_constraints` | ✅ | 본 skill이 따라야 할 invariant 목록 |
| `evidence_artifact_pattern` | ⚠️ | 실행 결과 durable artifact 경로 |
| `tech_stack_filter` | ⚠️ | tech-stack.yaml 필터링 (null = all) |
| `activation` | ✅ | 활성화 게이트 (auto + confirm_token + requires_operator) |
| `self_improvement` | ⚠️ | Hermes self-improving 패턴 enable 여부 (기본 false — invariant 보존) |

## Invariant (Hermes 흡수 결정 — `synthesis/HERMES-DECISIONS.md`)

- **활성화 NEVER 자동** — `confirm_token: enable-skill` 강제
- **runtime policy 변경 NEVER 자동** — yaml + 재빌드만
- **placeholder reason 거부** — `"test"`, `"tmp"` 등 일반 단어 자동 차단
- **self_improvement.enabled=true 시에도 적용은 게이트** — 후보 추출만 자동

## 관련 spec

- `/home/user/example_project-analysis/synthesis/HARNESS-APPLY.md` (H4 본 항목)
- `/home/user/example_project-analysis/synthesis/HERMES-DECISIONS.md` §1 (Hermes Skill 자동 생성 흡수 결정)
- `~/.claude/skills/external/README.md` (외부 skill import 흐름)
- `~/.claude/skills/_pipeline/stages-skill-lifecycle.yaml` (lifecycle pipeline)
