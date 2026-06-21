---
name: deepinit
description: Deep codebase initialization — hierarchical AGENTS.md documentation across the entire project with parent-child references.
keywords: [deepinit, agents-md, init-docs, hierarchical, codebase-documentation]
intent: [init, document, bootstrap]
phase: plan
min_score: 3
---

# Deep Init

AI-readable hierarchical documentation (`AGENTS.md`) for every meaningful directory. Helps agents understand: directory purpose, component relationships, local instructions, dependencies.

## 언제 쓰는가

- 새 프로젝트에 AI 오케스트레이션 시작
- 기존 프로젝트에 AGENTS.md 체계 없음
- 리팩토링 후 구조 변경 → AGENTS.md 업데이트

## 계층 태깅

root 외 모든 AGENTS.md는 상위 참조 포함:

```markdown
<!-- Parent: ../AGENTS.md -->
```

트리:
```
/AGENTS.md                       ← root (parent tag 없음)
├── src/AGENTS.md                ← <!-- Parent: ../AGENTS.md -->
│   ├── src/components/AGENTS.md ← <!-- Parent: ../AGENTS.md -->
│   └── src/utils/AGENTS.md      ← <!-- Parent: ../AGENTS.md -->
└── docs/AGENTS.md               ← <!-- Parent: ../AGENTS.md -->
```

## 템플릿

```markdown
<!-- Parent: {상대경로}/AGENTS.md -->
<!-- Generated: {timestamp} | Updated: {timestamp} -->

# {디렉터리 이름}

## Purpose
{이 디렉토리가 무엇을 담고 무슨 역할을 하는지 한 단락}

## Key Files
| File | Description |
|------|-------------|
| `file.ts` | 간단한 목적 |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `subdir/` | 내용 (`subdir/AGENTS.md` 참조) |

## For AI Agents

### Working In This Directory
{이 디렉토리 내 수정 시 특별 지시}

### Testing Requirements
{변경 테스트 방법}

### Common Patterns
{여기서 쓰는 코드 패턴/컨벤션}

## Dependencies

### Internal
{코드베이스 다른 부분에의 의존}

### External
{사용하는 주요 외부 패키지}

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
```

## 워크플로우

1. **디렉터리 구조 매핑**: `harness-explore` 에이전트로 재귀 리스트. `node_modules`, `.git`, `dist`, `build`, `__pycache__`, `.venv`, `coverage`, `.next`, `.nuxt` 등 제외.
2. **작업 계획**: 디렉토리별 todo, 깊이 레벨로 조직.
3. **레벨 순 생성**: **부모를 자식보다 먼저** 생성 (parent reference 유효성 보장).
4. **존재 시 비교+업데이트**:
   - 기존 읽기
   - 섹션 식별: 자동 생성 vs `<!-- MANUAL -->` 보존
   - diff + merge (수동 주석 보존, timestamp 갱신)
5. **계층 검증**:
   - 모든 parent reference가 실제 파일로 resolve
   - 고아 AGENTS.md 없음
   - 모든 의미 있는 디렉토리에 AGENTS.md 존재 (완전성)
   - timestamp 최신

검증 명령:
```bash
find . -name "AGENTS.md" -type f    # 모든 AGENTS.md 찾기
grep -r "<!-- Parent:" --include="AGENTS.md" .
```

## 스마트 위임

| Task | Primary Agent | Fallback (agent unavailable) |
|------|---------------|-------------------------------|
| 디렉터리 매핑 | `harness-explore` | inline `Glob` + `Grep` 도구 |
| 파일 분석 | `harness-architect` | `general-purpose` agent |
| 콘텐츠 생성 | `kha-doc-writer` | inline `Write`/`Edit` |
| AGENTS.md 쓰기 | `kha-doc-writer` | inline `Write` |

**Capability contract**: 위 agent 중 하나라도 spawn 실패 (등록 누락 / 권한 거부 / context cap)하면 fallback로 sequential degradation. agent 없이도 산출물 schema는 동일하게 유지.

## 빈 디렉토리 처리

| 조건 | 액션 |
|------|------|
| 파일 없음, 서브디렉토리 없음 | **Skip** (AGENTS.md 생성 안 함) |
| 파일 없음, 서브디렉토리 있음 | 서브디렉토리 리스트만 있는 minimal AGENTS.md |
| 생성 파일만 (`*.min.js`, `*.map`) | Skip 또는 minimal |
| 설정 파일만 | 설정 목적 설명 AGENTS.md |

## 병렬화 규칙

1. 같은 레벨 디렉토리 → 병렬
2. 다른 레벨 → 순차 (부모 먼저)
3. 큰 디렉토리 → 전용 에이전트
4. 작은 디렉토리 → 여러 개 배치

## 품질 기준

필수:
- [ ] 정확한 파일 설명
- [ ] 올바른 parent reference
- [ ] 서브디렉토리 링크
- [ ] AI agent 지시

금지:
- [ ] 제네릭 보일러플레이트
- [ ] 잘못된 파일명
- [ ] 깨진 parent reference
- [ ] 주요 파일 누락

## Gotchas

- **자식을 부모 전에 생성**: parent reference가 아직 없는 파일을 가리킴. 항상 부모 먼저.
- **MANUAL 섹션 덮어쓰기**: 사용자 수동 주석이 regenerate 때 사라짐. `<!-- MANUAL -->` 밑은 보존.
- **너무 잦은 regenerate**: 작은 변경에도 전체 재생성 → timestamp 스팸. 디렉토리 변경 시에만.
- **깊은 트리 전체 병렬**: 리소스 폭발. 레벨별 순차 (부모→자식).
