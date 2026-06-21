---
keywords: AI ai 인공지능 LLM llm 언어모델 GPT gpt 챗봇 chatbot 프롬프트 prompt 올라마 ollama OpenAI openai 임베딩 embedding RAG rag 벡터 vector 파인튜닝 fine-tuning 추론 inference 모델 model 토큰 token 컨텍스트 context 에이전트 agent 체인 chain
intent: LLM연동해 챗봇만들어 임베딩해 RAG구축해 프롬프트작성해 파인튜닝해 AI해 AI만들어 LLM해
paths: src/tutor src/ai src/llm src/ml src/rag tutor/ ai/ llm/ ml/ rag/ embeddings/ prediction/ recommendation/ analysis/
patterns: openai anthropic langchain llama ollama transformers sentence-transformers faiss chromadb pinecone huggingface torch pytorch tensorflow codebert
requires: backend testing
phase: plan implement review
min_score: 3
---

# AI/LLM Integration Guide

## 의사결정 트리

### IF LLM 서비스 신규 구축 (Plan)
1. Provider 선택 (로컬 vs 클라우드 vs 하이브리드)
2. Graceful Degradation 체인 설계 (LLM → 패턴 → 기본 응답)
3. 비용/성능 트레이드오프 결정
4. **→ backend 스킬: API 엔드포인트 설계**

### IF LLM 통합 구현 (Implement)
1. Provider 추상화 인터페이스 정의 (generate, is_available)
2. Provider별 구현체 작성
3. 시스템 프롬프트 설계 (역할, 규칙, 출력 포맷)
4. 컨텍스트 윈도우 관리 (최근 N개 메시지)
5. Rate limiting + 재시도 (지수 백오프, 429/5xx)
6. **→ testing 스킬: LLM 응답 mock 테스트**

### IF RAG 파이프라인 구축 (Implement)
1. 임베딩 모델 선택 (다국어 지원 여부 확인)
2. 벡터 저장소 설정
3. 청크 전략 결정 (크기, 오버랩)
4. 듀얼 검색 (키워드 + 벡터)
5. 프롬프트에 컨텍스트 주입 템플릿

### IF LLM 성능 문제 (Debug)
1. 응답 시간 측정 (p50, p95)
2. 토큰 사용량/비용 추적
3. 프롬프트 길이 최적화
4. 모델 사이즈 다운그레이드 검토

## Graceful Degradation (필수)
```
1순위: 설정된 LLM 프로바이더
  ↓ 장애/타임아웃 시
2순위: 패턴 기반 폴백 응답
  ↓ 불가 시
3순위: 미리 정의된 기본 응답
```

## 한국어 특수 고려사항
- 다국어 임베딩 모델 사용 (paraphrase-multilingual-MiniLM-L12-v2 등)
- 한국어 키워드 매핑 딕셔너리 필요 (투 포인터 → two-pointers)
- 한국어는 영어 대비 토큰 효율이 2-3배 낮음 → 컨텍스트 윈도우 계획에 반영

## Gotchas

### 스트리밍 응답 에러 핸들링
SSE 스트리밍 중 에러가 발생하면 이미 200 응답을 보냈으므로 HTTP 에러 코드 전송 불가. 스트림 내에서 에러 이벤트를 전송하는 프로토콜을 설계할 것.

### 토큰 계산 불일치
tiktoken 결과와 실제 API 과금 토큰 수가 다를 수 있음. 시스템 프롬프트, 함수 정의, 이미지 토큰도 포함됨. 예상보다 20-30% 더 사용될 수 있음.

### 프롬프트 인젝션
사용자 입력을 시스템 프롬프트에 직접 삽입하면 지시를 덮어쓸 수 있음. 사용자 입력은 반드시 user role 메시지로 분리하고, 중요 지시는 시스템 프롬프트 끝에 배치.

### Ollama 메모리 요구량
7B 모델도 최소 4GB VRAM 필요. 양자화(4-bit) 적용해도 RAM 사용량 높음. `OLLAMA_MAX_LOADED_MODELS=1`로 동시 로드 제한.

### 임베딩 차원 불일치
모델 변경 시 차원이 달라져 기존 벡터 인덱스와 호환 불가 → 전체 재인덱싱 필요. 벡터 저장소에 모델 버전 메타데이터를 기록할 것.

### API 키 로테이션
시작 시 한 번만 읽으면 키 갱신이 불가능. 키 로테이션 시 재시작 없이 반영되도록 매 요청마다 환경변수를 읽거나 시크릿 매니저 사용.

### temperature=0이어도 비결정적
동일 프롬프트에 temperature=0을 줘도 GPU 부동소수점 연산 차이로 결과가 달라질 수 있음. 결정적 출력이 필요하면 seed 파라미터 사용 (지원하는 API만).

## 도구 사용 패턴 (Harness)
- 프롬프트 파일 수정: `Read`로 현재 프롬프트 확인 → `Edit`으로 정밀 수정 (전체 재작성 시 의도 손실 위험)
- 임베딩/벡터 관련: `Bash`로 스크립트 실행, 큰 출력은 `run_in_background` 활용
- API 응답 확인: `Bash(curl)`로 테스트하되, 응답이 길면 파일로 저장 후 `Read`
- 모델 설정 검색: `Grep`으로 temperature, max_tokens, model 등 설정값 검색

## 에러 복구 패턴 (Harness)
- 429 Rate Limit → 재시도 대기 (지수 백오프), `Grep`으로 rate limit 설정 확인
- 401 Unauthorized → `Read`로 .env/설정 파일의 API 키 확인, 키 유효성 점검
- 500 Server Error → 폴백 모델로 전환 (Graceful Degradation 체인 따름)
- 타임아웃 → timeout 값 증가, 프롬프트 길이 축소 검토 (`Grep`으로 max_tokens 설정 확인)
