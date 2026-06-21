---
description: 흩어진 ADR/PRD/SPEC 문서로부터 greenfield `.planning/` 부트스트랩을 생성한다 (P2 D2). 코드가 아닌 기존 *문서*를 입력으로 받아 deterministic하게 {requirement, constraint, glossary, artifact} 버킷으로 분류 → `.planning/SPEC-seed.md` + `.planning/glossary.md` 산출. harness-reverse-prd(코드→PRD)와 입력이 다른 net-new 경로. eval/판단 없음 — 분류는 순수 휴리스틱.
user-invocable: true
argument-hint: "<문서 소스 디렉토리> [출력 planning 루트=.planning]"
allowed-tools: Read, Write, Bash, Grep, Glob
category: plan
mutates: yes
long-running: false
---

You are running the **kha-ingest-docs** workflow — bootstrapping a greenfield
`.planning/` setup from existing loose docs (ADR / PRD / SPEC / glossary).

Converged design: `debate-1780870185-827a94` (ontology sha1 `41c9cc8f…`, decision
D2). This is the sibling of `/harness-reverse-prd` but with a **different input**:
reverse-prd reads *code* → PRD; this reads existing *docs* → `.planning/`. The
single net-new engine is the deterministic classifier `lib/extractors/doc_classifier.py`
(registered in the extractor OCP registry); this command only collects + emits.

## Arguments
- `$1` (required): source directory holding loose `.md` docs (e.g. `docs/`, `adr/`).
- `$2` (optional): output planning root — default `.planning`.

## Process

1. **Resolve + validate.** Confirm `$1` exists and contains `.md` docs. If not,
   stop and tell the user there is nothing to ingest.

2. **Dry-run preview (deterministic).** Run:
   ```
   cd ~/.claude/scripts && python -m cli.ingest_docs --src "$1" --dry-run
   ```
   Show the bucket counts (`requirement / constraint / glossary / artifact / terms`).
   The dry-run now also prints a **per-doc transparency line** (`<path> -> <bucket> via
   filename/content:'<keyword>'`), so the operator can AUDIT which heuristic fired and
   catch a mis-classification before it propagates into SPEC-seed (closes the prior
   "classification opaque / heuristics unspecified" gap).
   If `total == 0` (exit 1), report that no ADR/PRD/SPEC-signalled docs were found
   and stop — `find_doc_sources` is conservative on purpose (README/CHANGELOG and
   unsignalled notes are skipped).

3. **Emit.** Run:
   ```
   cd ~/.claude/scripts && python -m cli.ingest_docs --src "$1" --out "${2:-.planning}"
   ```
   This writes `${2:-.planning}/SPEC-seed.md` + `${2:-.planning}/glossary.md` +
   `${2:-.planning}/.ingest-classifier-report.json` (the per-doc classification audit trail).
   Classification is purely deterministic (filename + heading heuristics) — it
   renders NO comparative verdict / ranking (kha-framework-selector neutrality
   invariant). Do NOT hand-edit the buckets to "improve" them here.

4. **Close ambiguity (chain).** The SPEC-seed is a *seed*, not a finished spec.
   Tell the user to run **`/harness-interview`** next to drive the ambiguity score
   below threshold before `/kha-plan-phase`. Do not author a SPEC gate here — that
   capability already lives in harness-interview (P2 D4).

## Output
- artifact: `${2:-.planning}/SPEC-seed.md` — Requirements / Constraints / Source-artifacts sections.
- artifact: `${2:-.planning}/glossary.md` — extracted `**term** — definition` entries + glossary sources.
- status: `ingested` | `aborted_no_docs` (nothing classifiable found) | `aborted_bad_src`.

## Boundaries
- vs `/harness-reverse-prd`: that reverse-engineers **code** → `.claude/requirements/` + `study/` (4-release PRD tree); this ingests existing **docs** → `.planning/`. Different input, different output root.
- vs `/kha-new-project`: that does interactive greenfield bootstrap; this seeds `.planning/` from docs you already have.
- vs `/harness-interview`: that closes ambiguity (Socratic gate); chain it AFTER this.
- No new agent, no judge, no eval pipeline — classification is deterministic only.
