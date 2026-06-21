# External Skills — agentskills.io 호환 외부 skill import

본 디렉토리는 외부 agentskills.io v1 호환 skill을 import하기 위한 영역입니다 (Hermes 흡수 — `synthesis/HARNESS-APPLY.md` H2).

## 흐름

1. agentskills.io 호환 manifest 다운로드
2. `~/.claude/skills/external/<vendor>/<skill-name>/` 배치 (`SKILL.md` + `manifest.json`)
3. `_registry.json`의 `imported[]`에 entry 추가 (`activated: false`)
4. secret scanner 통과 검증 (API key / token 누출 차단)
5. example_project `/kha-skill-activate <id> --confirm enable-skill`로 활성화 (운영자 게이트)

## 구조

```
~/.claude/skills/external/
├── README.md         (본 문서)
├── _registry.json    (외부 skill 레지스트리 — schema: agentskills.io/v1)
└── <vendor>/<skill-name>/
    ├── SKILL.md      (agentskills.io schema 본문)
    └── manifest.json (agentskills.io v1 manifest — `~/.claude/templates/skill/manifest-template.json` 참고)
```

## 활성화 게이트 (Invariant)

| 단계 | 자동 OK | 게이트 |
|------|--------|------|
| Import (디렉토리 배치 + registry entry) | ✅ | — |
| Secret scan 검증 | ✅ | — |
| **활성화 (invocation 가능 상태)** | — | ✅ `enable-skill` 토큰 |

게이트 충족 전 (`activated: false`) 외부 skill은 invocation에서 제외됩니다.

## _registry.json schema

```json
{
  "version": 1,
  "schema": "agentskills.io/v1",
  "imported": [
    {
      "vendor": "nousresearch",
      "skill": "hermes-skill-name",
      "manifest_path": "external/nousresearch/hermes-skill-name/manifest.json",
      "imported_at_unix": 1700000000,
      "verified_secret_clean": true,
      "activated": false
    }
  ]
}
```

## 의존성

- **활성화 자동화**: example_project PR-7 D13 (Skill 자동화) 완료 후 Track 2 H1 (`skill-candidate-extractor.js` PostToolUse hook)이 본 디렉토리를 후보 추출 타깃으로 사용.
- 본 디렉토리만으로는 import만 가능 — 자동 활성화는 D13 완료 의존성.

## 관련 spec

- `/home/user/example_project-analysis/synthesis/HARNESS-APPLY.md` (H2 본 항목)
- `/home/user/example_project-analysis/synthesis/HERMES-DECISIONS.md` §1 (agentskills.io 표준 채택)
- `/home/user/example_project-analysis/synthesis/SYNTHESIS.md` §2.3 호환성 (4.5 → 5.0)
