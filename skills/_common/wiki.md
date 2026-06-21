---
name: wiki
description: Persistent markdown knowledge base — ingests, queries, and maintains project knowledge pages that compound across sessions. No vector embeddings; keyword + tag matching.
keywords: [wiki, knowledge-base, kb, ingest, query, lint, cross-reference]
intent: [document, remember, catalog, reference]
phase: plan
min_score: 2
---

# Wiki

세션 넘어 쌓이는 프로젝트/세션 지식의 영구 markdown knowledge base. Karpathy LLM Wiki 영감.

## 동작

### Ingest — 지식을 페이지로 처리
단일 ingest이 여러 페이지 생성 가능.

```
wiki_ingest({
  title: "Auth Architecture",
  content: "...",
  tags: ["auth", "architecture"],
  category: "architecture"
})
```

### Query — 키워드/태그로 모든 페이지 검색
매칭 페이지 + snippet 반환 — 답변과 citation은 **LLM이** 합성.

```
wiki_query({ query: "authentication", tags: ["auth"], category: "architecture" })
```

### Lint — 위키 헬스 체크
- 고아 페이지
- stale 콘텐츠
- 깨진 cross-reference
- oversized 페이지
- 구조적 모순

```
wiki_lint()
```

### Quick Add — 단일 페이지 빠른 추가

```
wiki_add({ title: "Page Title", content: "...", tags: ["tag1"], category: "decision" })
```

### List / Read / Delete

```
wiki_list()                              # 모든 페이지 표시 (index.md)
wiki_read({ page: "auth-architecture" })
wiki_delete({ page: "outdated-page" })
```

### Log — 위키 작업 이력
`<project>/.harness/wiki/log.md` 읽기.

## 카테고리

- `architecture`
- `decision`
- `pattern`
- `debugging`
- `environment`
- `session-log`

## 저장소

- 페이지: `<project>/.harness/wiki/*.md` (YAML frontmatter + markdown)
- 인덱스: `<project>/.harness/wiki/index.md` (자동 관리 카탈로그)
- 로그: `<project>/.harness/wiki/log.md` (append-only)

## Cross-Reference

`[[page-name]]` wiki-link 문법.

## Auto-Capture

세션 종료 시 중요한 발견은 session-log 페이지로 자동 캡처.
- 설정: `.harness-config.json`의 `wiki.autoCapture` (기본: 활성)

## Hard Constraints

- **Vector embedding 없음** — query는 키워드 + 태그 매칭만.
- `.harness/wiki/`는 기본 git-ignored (프로젝트 로컬).

## vs auto-memory

| 측면 | auto-memory | wiki |
|------|-------------|------|
| 스코프 | 사용자/세션 글로벌 | 프로젝트 로컬 |
| 저장 | `~/.claude/projects/.../memory/` | `<project>/.harness/wiki/` |
| 구조 | index.md + 타입별 (user/feedback/project/reference) | 카테고리별 markdown + YAML frontmatter |
| Cross-ref | 없음 | `[[page-name]]` |
| 자동 캡처 | 세션 종료 시 (사용자 선호 기반) | 세션 종료 시 (프로젝트 발견 기반) |
| Query | 관련성 기반 로드 (항상 MEMORY.md) | 명시적 `wiki_query` |

**규칙**: 사용자/세션-글로벌 → memory. 프로젝트-로컬 → wiki.

## Gotchas

- **Vector search 기대**: 키워드 + 태그 매칭만. 의미 검색 원하면 embedding 레이어 외부에 필요.
- **태그 없이 ingest**: query가 카테고리로만 검색 가능 → 검색 정확도 떨어짐. 항상 2-3개 태그 붙여라.
- **Session-log 과다**: 세션마다 auto-capture 되면 wiki가 세션 로그로 오염. `autoCapture: false`로 off + 선별 ingest 권장.
- **Cross-ref 깨짐**: 페이지 이름 바꾸면 `[[old-name]]` 깨짐. `wiki_lint()` 정기 실행 + 이름 변경 시 업데이트.
- **Oversized 페이지**: 한 페이지가 >500줄이면 주제 쪼개라 — lint가 경고.
