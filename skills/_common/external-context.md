---
name: external-context
description: Fan out 2-5 parallel harness-document-specialist agents for external docs/refs research, then synthesize with citations.
keywords: [external-context, research, docs, reference, parallel-search, multi-facet]
intent: [research, fetch-docs, external-lookup]
phase: plan
min_score: 2
---

# External Context

외부 문서·레퍼런스 일괄 수집. 쿼리를 2-5 facet으로 분해하고 병렬 `harness-document-specialist` 에이전트로 fan-out, 최종 synthesize.

## 언제 쓰는가

- SDK/프레임워크/API 사용법 (여러 측면 동시 조사 유용)
- 라이브러리 비교 (예: Prisma vs Drizzle)
- 최신 패턴/컨벤션 조사
- 단일 출처로 부족한 질문

## 사용법

```
/external-context <주제 또는 질문>
```

예시:
```
/external-context What are best practices for JWT token rotation in Node.js?
/external-context Compare Prisma vs Drizzle for PostgreSQL
/external-context Latest React Server Components patterns
```

## 프로토콜

### Step 1: Facet 분해

쿼리를 2-5개 독립 검색 facet으로 분해:

```markdown
## Search Decomposition

**Query:** <원본>

### Facet 1: <facet 이름>
- **Search focus:** 무엇을 검색
- **Sources:** 공식 docs, GitHub, 블로그 등

### Facet 2: <facet 이름>
...
```

### Step 2: 병렬 에이전트 호출

Task 도구로 facet별 병렬 fan-out (최대 5개):

```
Agent(subagent_type="harness-document-specialist",
      prompt="Search for: <facet 1>. Use Context7 MCP first, then WebSearch/WebFetch for official docs. Cite every source with URLs.")

Agent(subagent_type="harness-document-specialist",
      prompt="Search for: <facet 2>. ...")
```

### Step 3: Synthesis

```markdown
## External Context: <query>

### Key Findings
1. **<finding>** — Source: [title](url)
2. **<finding>** — Source: [title](url)

### Detailed Results

#### Facet 1: <name>
<aggregated findings with citations>

#### Facet 2: <name>
...

### Sources
- [Source 1](url)
- [Source 2](url)
```

## 설정

- 최대 병렬 `harness-document-specialist`: 5개
- magic keyword trigger 없음 — 명시 invocation만

## Capability fallback

Primary path는 `harness-document-specialist` × N, but each MCP/agent layer can fail independently.
Fallback chain (각 layer 실패 시 다음으로 degrade):

| Layer | Primary | Fallback 1 | Fallback 2 |
|-------|---------|-----------|-----------|
| Agent spawn | `harness-document-specialist` | `general-purpose` (동일 prompt) | inline orchestrator |
| Doc lookup | Context7 MCP (`mcp__context7__*`) | WebFetch + URL 직접 | WebSearch 검색 → 첫 결과 |
| Aggregation | Synthesis agent | inline merge by orchestrator | — |

Fallback 사용 시에도 output schema (citations[] 필수) 유지. 인용 출처가 MCP인지 직접 web인지 `source_kind` 필드로 구분.

## Gotchas

- **Facet 5개 초과**: 에이전트 5개 한도. 필요시 2회 호출로 쪼개라.
- **같은 facet 여러 번**: 중복 비용. Facet은 서로 독립적이어야.
- **인용 없이 synthesis**: 검증 불가. 모든 finding에 URL/doc ID.
- **Context7 건너뛰기**: 공식 SDK/프레임워크는 Context7 MCP가 훨씬 정확. 생 WebSearch 전에 시도.
