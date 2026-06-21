---
name: architect-lock-reproduction-discipline
description: harness-architect 가 gen N+1 convergence 시 ontology_snapshot.fields LOCK 을 byte-identical 재현해야 SHA-1 match → converged. shape 간단화 (nested dict → simplified array 등) 는 SHA 발산 = strict-rule blocked
keywords: harness debate architect ontology lock snapshot convergence sha byte-identical verbatim reproduce shape
intent: 수렴해 land해 convergence approve 종결해
paths: state/debates ~/.claude/state/debates scripts/engine
patterns: harness-architect ontology_snapshot
requires: handoff-clear-trigger
phase: plan review
tech-stack: any
min_score: 2
---

# Architect LOCK 재현 discipline

> 원칙: **convergence 는 SHA-1 byte-identical match 로만 fire 한다.** Architect 가 LOCK target shape 을 simplify 하면 (예: nested `[{name, value}]` → `[{id, type, value}]`) SHA 가 발산 → 강성 primary 규칙이 convergence 차단 → hard_cap exit.
>
> Evidence: wave 7 후속 15 Path 2 debate (`debate-1779171011-e3a746`) gen 3 Architect 가 LOCK 을 simplified array 로 emit → SHA `093b960a...` ≠ LOCK `c50ae97c...` → gen 4 명시 verbatim 지시 후 converge. 본 패턴 2-strike 확정: wave 7 후속 16 RLM debate (`debate-1779181910-f45484`) gen 4 prompt 에 "MUST reproduce LOCK contract verbatim including nested dict structure" 명시 → 정확 byte-identical → SHA `d5cc5cfcf171` match → converged.

## 의사결정 트리

### IF Architect gen N+1 convergence 시도 (Plan)

1. **gen N conditional verdict 의 LOCK contract 식별** — `ontology_snapshot.fields` 의 정확한 shape (배열 / 객체 / nested 구조 모두 포함)
2. **gen N+1 Architect 의 verdict 가 approved 이어도 SHA 검증 별도** — verdict=approved 만으로 converge 아님, fields canonical JSON SHA-1 가 gen N 의 LOCK SHA 와 byte-identical 일치해야 함
3. **shape 변형 금지** — 다음 변형 모두 SHA 발산 트리거:
   - `[{"name": "...", "value": "..."}]` → `[{"id": "...", "type": "...", "value": "..."}]`
   - `[{name, value}]` → `{name: value, ...}` (객체 형태)
   - 중첩 dict 평탄화 (예: `{"D3": {"trigger": "..."}}` → `[{"name": "D3.trigger", "value": "..."}]`)
   - 필드 순서 변경 (canonical JSON serialization 에서 순서 영향)
4. **gen N+1 prompt 에 명시 지시** — "MUST reproduce `ontology_snapshot.fields` BYTE-IDENTICAL (same shape, same names, same values, same order)"
5. **prompt 안에 LOCK target JSON 직접 포함** — Architect 가 추론하지 말고 copy-paste 하도록 spec 안에 verbatim JSON 제공

### IF debate orchestrator (Plan)

1. **gen N+1 Architect dispatch 전 LOCK SHA 사전 계산** — orchestrator 가 직접 `hashlib.sha1(canonical_json.encode())` 으로 expected SHA short hash 산출
2. **Architect 출력 후 SHA 재계산 + 비교** — 직접 산출한 SHA 와 expected 비교, 일치하지 않으면 convergence event 에 `status: 'hard_cap'` + `reason: 'SHA drift'` 명시
3. **convergence 의 strict-rule 보존** — verdict=approved 만으로 converged 처리하지 말 것. SHA match 가 필수 조건

### IF Architect prompt 작성 시 (Plan)

verbatim 지시 명시 template:

```
# Critical for convergence

Your output MUST include `ontology_snapshot.fields` BYTE-IDENTICAL to the
gen N LOCK target (X entries, same shape Y, same names/values/order).
If you re-shape to your own preferred schema (e.g., simplified
[{id, type, value}, ...] instead of [{name, value}, ...]) the SHA will
diverge and convergence will fail despite verdict=approved.

# LOCK target JSON (copy verbatim)

[
  {"name": "...", "value": "..."},
  {"name": "...", "value": "..."}
]

# Expected SHA-1 short: <PRE-COMPUTED>
```

## SHA 계산 canonical form

```python
import json, hashlib
fields = [...]  # list of dict
canonical_json = json.dumps(fields, separators=(',', ':'), sort_keys=False)
sha1_short = hashlib.sha1(canonical_json.encode('utf-8')).hexdigest()[:12]
```

- `separators=(',', ':')` — whitespace 제거 (compact form)
- `sort_keys=False` — field 순서 보존 (LOCK 의 순서가 의미)
- `:12` — 12-char short hash (HANDOFF entry 가독성)

## Gotchas

### Architect 가 LOCK 을 "improve" 시도
gen 3 Architect 가 LOCK 의 nested dict 를 보고 "이건 simplified array 가 더 깔끔하다" 판단해서 shape 변경 → SHA 발산. **Architect 의 본분은 verdict + evidence_review 이지 LOCK schema 재설계 아님.** LOCK 은 gen 3 conditional 의 자기 spec, gen 4 에서 변경 = self-contradiction.

### convergence event 가 approved 만 보고 fire
orchestrator 가 `if verdict == "approved": converged` 패턴이면 SHA drift 놓침. 반드시 `verdict == "approved" AND sha1(this.fields) == sha1(prev.fields)` 2-condition AND.

### LOCK 가 명시 안 되고 gen N+1 가 새 ontology 생성
gen N conditional 이 conditions 만 emit 하고 `ontology_snapshot.fields=[]` (empty) → gen N+1 가 처음으로 fields 생성 → 비교 대상 없음 → fast-path 또는 option-(b) practical interpretation 으로 converge. **wave 3 OD3 / wave 7 후속 15 / wave 7 후속 16 모두 이 option-(b) 경로**. gen 3 architect 의 conditions §C-3 가 "exactly 4 fields in this order" 명시 → gen 4 가 그 spec 의 첫 concrete instance = de-facto LOCK = approved 의 first instance.

### Prompt 안에 LOCK JSON 미포함
"이전 verdict 의 ontology 를 보고 reproduce 해" 만 적으면 Architect 가 추론 실수 (필드명 변경, 순서 바꿈, 값 typo). **LOCK JSON 을 prompt 안에 verbatim 포함** + "copy-paste verbatim" 명시 — 추론 surface 차단.

### gen 3 verdict=approved (fast-path 후보) 도 shape 검증 필수
gen 1 approved 만 fast-path exception (SHA 비교 없이 converged) — gen 2+ 의 approved 는 모두 SHA match 검증 필수. wave 7 후속 15 의 gen 3 approved 가 shape divergence 로 차단된 evidence.

### canonical JSON serialization 일관성
`json.dumps` 의 default separators `(', ', ': ')` 는 whitespace 포함 → SHA 가 trim/space 차이로 발산. 반드시 `separators=(',', ':')` 사용. Architect 출력이 pretty-print 라도 orchestrator 가 다시 parse → canonical re-serialize 로 hash 산출.

### "simplified" shape 도 의도적이면 OK (단 LOCK 재설정 필요)
gen N+1 Architect 가 정말로 LOCK shape 이 잘못됐다고 판단 → 그건 verdict=conditional (not approved) 이어야 함. approved 면 LOCK 보존. shape 변경 + approved = self-contradiction.

## 도구 사용 패턴 (Harness)

- LOCK SHA 사전 계산: `Bash(python -c "import json,hashlib; print(hashlib.sha1(json.dumps([{...}], separators=(',', ':'), sort_keys=False).encode()).hexdigest()[:12])")`
- gen N+1 Architect prompt 에 LOCK JSON 포함: spec 의 `# LOCK target JSON` 섹션 직접 inline
- convergence 검증: SHA 재계산 → expected 와 비교 → event_store.append('convergence', ..., {'sha_match': bool})
- 본 스킬 cross-ref: harness-debate 의 step 4 (convergence check) 에서 본 스킬 참조

## 에러 복구 패턴 (Harness)

- SHA drift 발견 시: convergence event `status='hard_cap', reason='SHA drift sha=X expected=Y'` 명시 → 운영자 escalation
- gen 4 도 SHA mismatch: hard cap exit, 다음 cycle 에서 fresh debate (LOCK shape 자체 재설계)
- Architect 가 verdict=approved 인데 shape 변경: gen 3 의 `verdict='conditional'` 로 retroactive 처리 (사실상 reject), gen N+1 재진입 시 명시 prompt 강화

## 관련 evidence 누적 (2-strike confirmed 2026-05-19)

| wave | session | 발화 | resolution |
|------|---------|-----|-----------|
| 7 후속 15 (1st strike) | `debate-1779171011-e3a746` gen 3 | LOCK `c50ae97c...` ↔ simplified `093b960a...` | gen 4 prompt 명시 "PASTE THE LOCK JSON VERBATIM" → match |
| 7 후속 16 (2nd strike) | `debate-1779181910-f45484` gen 4 | gen 3 conditional 5-condition LOCK template | prompt 명시 "BYTE-IDENTICAL" + LOCK JSON inline → match `d5cc5cfcf171` |

본 스킬이 codify 된 이후 cycle 부터: harness-debate skill 의 step 4 가 본 스킬 cross-ref → Architect prompt 자동 명시 → 3-strike 이상 재발 시 본 스킬 또는 harness-debate 자체에 hard-block 추가 후보.
