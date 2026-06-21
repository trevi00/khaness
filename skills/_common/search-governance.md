---
name: search-governance
description: Search as a relevance contract — query rewrite, ranking signals, freshness windows, and zero-result recovery made reviewable instead of trusting engine defaults.
keywords: search elasticsearch opensearch solr meilisearch typesense vector-search bm25 ranking relevance recall precision query-rewrite synonym tokenizer analyzer stemming stopwords boost field-weight freshness recency zero-result query-suggestion typo-tolerance fuzzy autocomplete facet filter index-mapping shard refresh-interval
intent: 검색설계해 검색튜닝해 query-rewrite설계해 ranking조정해 zero-result처리해 synonym추가해 freshness반영해 typo-tolerance설정해 autocomplete만들어 facet설계해 index매핑해
paths: search/ es/ elasticsearch/ opensearch/ solr/ index/ analyzers/ src/search src/query
patterns: elasticsearch opensearch solr meilisearch typesense lucene vespa algolia tantivy bleve pgroonga pg-trgm faiss milvus weaviate
requires: data-pipeline-governance monitoring api-contracts
phase: plan implement review
tech-stack: any
min_score: 2
---

# Search Governance

검색은 "엔진을 켜면 끝"이 아니라 **relevance contract** — 어떤 query가 어떤 결과를 내야 하는가의 명시적 합의. 4축: rewrite, ranking, freshness, zero-result recovery.

## 의사결정 트리

### IF 새 검색 기능 추가 (Plan)
1. domain query type 분류 — keyword exact, keyword loose, natural language, faceted filter, autocomplete
2. **golden query set** — 대표 query 30-100개 + 기대 top-k 결과 (regression 기준)
3. 데이터 모델 — 단일 index vs 다중 index, parent-child vs nested vs denormalize
4. analyzer 선택 — language(stemming, stopwords), n-gram(typo), keyword(exact)
5. ranking 신호 정의 — text relevance + business signal(popularity, freshness, paid)
6. **→ data-pipeline-governance 스킬: index ingest 파이프라인 참고**

### IF Query Rewrite (Implement)
1. **normalize** — 대소문자, 공백, accent, full-width
2. **synonym** — 양방향(brand=brands) vs 단방향(KR→Korea)
3. **typo tolerance** — fuzzy(edit distance) vs phonetic(soundex) vs n-gram
4. **stop word** — 도메인 따라 다름. "그" "the" 제거 vs 보존(노래 제목 등)
5. **multi-field** — title^3 + body^1 + tags^2 (boost)
6. **query understanding** — intent 분류(navigational/informational/transactional)

### IF Ranking 설계 (Implement)
1. baseline — BM25 또는 TF-IDF + field weight
2. business signal — recency / CTR / popularity / quality score
3. **scoring formula** — `text_score * decay(age) * popularity_boost`
4. learning-to-rank(LTR) — gradient boosting + click feedback (advanced)
5. vector search 결합 — semantic(vector) + lexical(BM25) hybrid (rank fusion 또는 RRF)
6. personalization — user signal 추가 (consent + privacy 고려)

### IF Freshness / Recency (Implement)
1. **refresh interval** — Elasticsearch 1s default. write-heavy면 30s+로 늘려 indexing 부하 감소
2. recency decay — `gauss` / `linear` / `exp` decay function on date field
3. boost recent N days — staleness penalty
4. real-time vs near-real-time — log/news는 real-time, catalog는 daily OK
5. **TTL / archival** — 옛 doc 삭제 또는 cold tier로 이동

### IF Zero-Result Recovery (Implement)
1. **detect** — top-k empty 또는 score < threshold
2. **broaden**:
   - operator AND → OR
   - fuzzy distance 증가
   - filter 일부 제거(시장/카테고리)
3. **suggest** — "did you mean X?" (edit distance 기반)
4. **fallback** — popular items, category landing, related categories
5. **log** — zero-result query를 모아 synonym/dictionary 보강
6. UX — "결과 없음" 페이지에 검색 팁 + popular items

### IF Search 회고 (Review)
- [ ] golden query CTR 또는 NDCG@10 — 변화 추적
- [ ] zero-result rate — 보통 < 5%, 이상이면 튜닝
- [ ] long-tail query — top 100 외 query 응답 품질
- [ ] latency p99 — slow query 식별
- [ ] index size / refresh rate — 비용과 freshness 균형
- [ ] reranking ratio — vector reranking이 BM25를 얼마나 변경하나

## 4축 체크리스트

```
[Query Rewrite]
□ normalize 규칙 (case/accent/space/width)
□ synonym dictionary + 단/양방향 정의
□ typo 정책 (fuzzy distance, n-gram, phonetic)
□ stop word 도메인별 결정
□ multi-field boost weight 명시

[Ranking]
□ scoring formula 문서화
□ business signal 가중치 (popularity/recency/CTR)
□ vector + lexical hybrid 전략 (해당 시)
□ A/B test로 변경 검증
□ LTR feature drift 모니터 (해당 시)

[Freshness]
□ refresh interval (write 부하 vs latency)
□ recency decay function 명시
□ TTL / cold tier 전략
□ real-time vs near-real-time 합의

[Zero-Result]
□ detect 임계 (empty / score)
□ broaden 단계 정의
□ "did you mean" 또는 fallback UX
□ zero-result query 로그 → 사전 보강 루프
```

## 가이드

### Golden Query Set의 가치
30-100개 대표 query + 기대 top-k 결과를 regression 기준으로 유지. 매핑 변경 / 가중치 변경 / synonym 추가 시 NDCG / MRR / Recall 측정. 사람 판단 + 클릭 로그로 정답 보강.

### BM25 vs Vector vs Hybrid
- **BM25**: 정확 단어 매칭. brand/code 같은 keyword에 강함.
- **Vector(semantic)**: 의미 매칭. "운동화" ↔ "스니커즈" 같은 paraphrase에 강함.
- **Hybrid**: 두 score 정규화 후 weight sum, 또는 RRF(Reciprocal Rank Fusion). 일반적으로 가장 강함.

### Synonym의 양면성
- 양방향(`car, automobile`): 어느 쪽 query든 매칭.
- 단방향(`KR => Korea`): 좁은 → 넓은으로만.
- 위험: "apple"이 과일/회사 둘 다이면 양방향이 잡음. context별 sub-index 또는 disambiguation.

### Refresh Interval Trade-off
Elasticsearch default 1s — small/medium index OK. write-heavy(분당 만+ docs)면 30s-60s로 늘려 segment merge 부하 감소 + indexing throughput up. 대신 write 후 search 까지 lag.

### N-gram vs Fuzzy
- **n-gram**(edge-ngram, n-gram): index time에 substring 미리 만듦. 빠르지만 index 크기 N배.
- **fuzzy**: query time에 edit distance 계산. 느리지만 index 작음.
- 짧은 prefix(autocomplete)면 edge-ngram, 일반 typo면 fuzzy + max-edits=2.

### Zero-Result는 silent quality killer
사용자가 "결과 없음" 보면 이탈. 보통 5% 이하 유지. analytics로 zero-result query 모아 weekly 검토 → synonym / dictionary / 데이터 보강.

## Gotchas

### Index 매핑이 바뀌어도 reindex 안 함
analyzer 변경 / field type 변경은 기존 doc에 적용 안 됨 — reindex 필수. dynamic mapping은 첫 doc 기준으로 고정 → 잘못된 type이 영원 남음. explicit mapping 권장.

### Stop word를 무자각하게 적용
"to be or not to be" 검색이 "be"만 남거나 zero — 노래/책 제목에선 stop word 제거 금지. 도메인별 analyzer 분리.

### Synonym dictionary가 search-time만
search-time synonym은 query 확장. index-time과 다름. 보통 search-time이 유연하지만 multi-word synonym은 index-time이 정확. 둘 중 하나 일관 선택.

### Boost 값이 임의로 N
`title^10 body^1` 같은 boost가 과해서 title 한 단어 매칭이 정확한 body 매칭 압도 → 품질 저하. boost는 1-3 범위 + golden set으로 검증.

### Popularity boost 무한 누적
인기 item이 더 노출 → 더 click → 더 인기 → cold start item 영원 못 노출. log decay 또는 minimum exposure 보장.

### Recency decay scale 단위 혼동
`gauss` decay의 scale이 "30d"인데 데이터는 시간 단위로 바뀌는 도메인 → 효과 없음. domain time scale에 맞춤.

### Refresh interval 1s에 write 폭주
default 1s는 좋은 search latency지만 write QPS 높으면 segment 폭증 → merge 부하 → cluster 불안정. write 패턴 보고 30s+ 검토.

### Vector index 크기 폭증
embedding 768-dim float32면 doc당 3KB — 1M doc = 3GB. quantization(int8, PQ) + dimension reduction 검토. RAM 못 들어가면 query latency 폭증.

### Deleted doc이 score 왜곡
Lucene tombstone 누적되면 IDF 계산이 deleted 포함해서 왜곡 → relevance drift. force_merge 또는 자동 segment merge tuning.

### Multi-language 한 index
EN/KR 섞어 한 analyzer 쓰면 양쪽 다 손상. language detect → field 분리 또는 index 분리.

### Zero-result 로그 안 함
zero-result query를 보지 않으면 dictionary/synonym 영원 안 늘어남 → 사용자 검색 품질 정체. weekly review pipeline 필수.

### Reindex 다운타임
prod index를 직접 reindex하면 수 시간 lock / 자원 점유. **alias** + 새 index 빌드 → atomic switch 패턴(zero-downtime reindex).

### "did you mean" 무한 루프
suggest 결과도 zero면 "did you mean X" 반복 → UX 깨짐. suggest depth cap + final fallback(popular items).

## 도구 사용 패턴 (Harness)
- 매핑 점검: `Bash`로 `curl <es>/<index>/_mapping`
- analyzer 테스트: `_analyze` API로 토큰화 결과 확인
- query plan: `_validate/query?explain=true` 또는 `explain=true` query
- relevance: golden set으로 NDCG/MRR 계산 스크립트
- slow log: ES `index.search.slowlog.threshold` 설정 후 로그 분석

## 에러 복구 패턴 (Harness)
- "갑자기 검색 결과 다 다름" → 최근 매핑/synonym/boost 변경 추적, A/B 또는 rollback
- "특정 query만 0건" → analyzer로 토큰화 검사, query rewrite 단계별 결과 확인
- "indexing lag spike" → refresh interval, bulk size, replica 수 검토
- "vector + BM25 hybrid에서 vector만 dominant" → 정규화 방법(min-max, z-score) 확인, RRF 도입
- "특정 사용자만 결과 부적절" → personalization signal drift, 또는 stale user profile
