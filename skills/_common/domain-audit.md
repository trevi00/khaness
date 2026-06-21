---
keywords: audit 감사 조사 리서치 research investigate 점검 health 품질 quality 도메인별
intent: 조사해 감사해 점검해 분석해 진단해 리뷰해
paths: backend/src/main frontend/src
patterns: Service Controller Repository Page
requires: backend frontend testing code-quality convention
phase: review
min_score: 3
---

# 도메인 감사 (Domain Audit)

> 목적: 도메인별 코드·UX 품질을 체계적으로 평가하여 고도화 방향을 도출
> 출처: Codacy 10-Dimension + SonarQube Rating + CodeScene Hotspot + eCommerce UX Audit
> **vs `design-audit.md`**: design-audit는 architecture-level (모듈 경계 / 의존성 그래프 / 레이어 위반). 본 스킬은 그 아래의 **per-domain 코드 품질** (BE 5축 + FE 2축).

## 의사결정 트리

### IF 전체 도메인 감사 (Review)
1. 도메인 목록 확정 (Entity 기준 그루핑)
2. Impact-Effort 우선순위로 감사 순서 결정 (결제>주문>인증>상품>...)
3. 도메인별 BE/FE 감사 매트릭스 작성 (아래 7축)
4. 발견 사항을 Quick Win / Strategic / 후순위로 분류
5. DDR(수렴율) < 0.1 되면 감사 종료

### IF 단일 도메인 감사 (Review)
1. 해당 도메인의 BE 파일 전수 Read (Entity→Repo→Service→Controller→DTO→Exception)
2. 해당 도메인의 FE 파일 전수 Read (model→api→page→widget)
3. 7축 체크리스트 적용
4. 발견 사항 기록 + 우선순위 분류

### IF 감사 후 수정 (Implement)
1. Quick Win부터 착수 (1-2시간 내 완료 가능)
2. Strategic은 Phase로 분리 (pipeline.md에 등록)
3. 수정마다 `./gradlew build` + 영향받는 evaluator 재실행
4. **→ testing 스킬: 수정 부분 테스트 보강**

## 감사 7축 (도메인 x 축 매트릭스)

### BE-1. 패턴 일관성 (Consistency)
- Service: @Transactional/@TransactionalReadOnly 사용 일관성
- Controller: CommonResponse 래핑, @CurrentUser 사용, DTO Lombok @Getter/@Setter
- Exception: 도메인별 NotFound/AccessDenied/Duplicate 3종 구비
- Repository: Spring Data JDBC 네이밍 규칙 준수
- **비교 기준**: 가장 성숙한 도메인(Order)을 골든 패턴으로 삼고 차이 측정

### BE-2. 에지케이스 처리 (Edge Cases)
- null 파라미터: Optional.orElseThrow vs null 체크 혼재
- 빈 컬렉션: List.of() 반환 vs null 반환
- 동시성: SELECT FOR UPDATE 필요한 곳에 적용되었는가
- 상태 전이: 불가능 전이 요청 시 명확한 예외
- 경계값: 0원 결제, 재고 0, 쿠폰 만료 직전

### BE-3. 비즈니스 규칙 위치 (Logic Placement)
- Controller에 비즈니스 로직이 누수되었는가 (조건문, 계산)
- Service가 다른 Service를 과도하게 호출하는가 (God Service)
- Repository에 비즈니스 조건이 @Query로 하드코딩되었는가
- DTO 변환이 Controller vs Service 어디서 수행되는가

### BE-4. 쿼리 효율 (Query Efficiency)
- N+1 가능성: 리스트 조회 후 개별 findById 반복
- 불필요한 전체 조회: Pageable 없이 findAll()
- 인덱스 활용: WHERE/ORDER BY 절이 인덱스와 매치되는가
- SELECT FOR UPDATE 범위: 최소 행만 잠그는가

### BE-5. 에러 계층 (Error Hierarchy)
- ErrorCode 체계: 도메인 접두사 일관성 (US/PD/OD/PM/...)
- HTTP 상태코드 정확성: 404 vs 400 vs 409 vs 403
- 예외 메시지: 디버깅에 유용한 정보 포함 여부
- 에러 응답 포맷: CommonResponse.error() 일관성

### FE-1. UX 완성도 (UX Completeness)
- **빈 상태**: 데이터 0건 시 안내 메시지 + CTA
- **로딩 상태**: 스켈레톤 or 스피너 (레이아웃 시프트 방지)
- **에러 상태**: API 실패 시 재시도 버튼 + 에러 메시지
- **낙관적 업데이트**: 좋아요/장바구니 등 즉각 반영
- **피드백**: 작업 성공/실패 시 토스트 알림
- **디바운스**: 검색/입력에 debounce 적용

### FE-2. KREAM 벤치마크 갭 (Benchmark Gap)
- **PLP**: 필터/정렬 + 그리드 뷰 + 무한스크롤
- **PDP**: 이미지 갤러리 + sticky 사이드패널 + 탭 구조
- **결제**: 싱글페이지 + 신뢰 시그널 + 배송비 실시간 계산
- **모바일**: 반응형 그리드 + 터치 타겟 44px+ + 바텀시트
- **마이크로 인터랙션**: hover 효과, 전환 애니메이션, 스크롤 연동

## 채점 기준 (1-5)

| 점수 | 의미 | 기준 |
|------|------|------|
| 5 | Excellent | 골든 패턴 완전 준수, 에지케이스 전수 처리, UX 상태 4종 완비 |
| 4 | Good | 대부분 준수, 1-2건 마이너 이탈 |
| 3 | Adequate | 핵심 경로 OK, 에지케이스 일부 누락, UX 빈 상태 미처리 |
| 2 | Poor | 패턴 불일치 3건+, 에러 처리 불완전, UX 로딩/에러 미구현 |
| 1 | Critical | 보안 취약점, 데이터 무결성 위험, 주요 기능 미동작 |

## 우선순위 분류 (Impact-Effort)

```
Priority = (Severity + Dependency + Frequency) - 2 * Cost
```

- **Quick Win**: 높은 Impact + 낮은 Effort → 즉시 수정
- **Strategic**: 높은 Impact + 높은 Effort → Phase로 분리
- **후순위**: 낮은 Impact → 백로그 기록만

## 도메인별 Severity 기본값 (쇼핑/주문 도메인 예시)

| 도메인 | Severity | 이유 |
|--------|----------|------|
| 결제(Payment) | 5 | 매출 직결, 정산 영향 |
| 주문(Order) | 5 | 핵심 트랜잭션, 재고·배송 연쇄 |
| 인증(Auth/User) | 4 | 보안 기반, 전 도메인 의존 |
| 입찰(Bidding) | 4 | 실시간 매칭, 동시성 위험 |
| 상품(Product) | 3 | 카탈로그 정확성, SEO |
| 쿠폰(Coupon) | 3 | 할인 남용 방지 |
| 커뮤니티(Community) | 2 | 부가 기능, 매출 간접 |
| 위시리스트/장바구니 | 2 | 보조 기능 |
| 알림(Notification) | 1 | 실패해도 핵심 기능 무영향 |

## 출력 포맷 (도메인당)

```markdown
## {도메인} 감사 결과

| 축 | 점수 | 주요 발견 |
|----|------|----------|
| BE-1 패턴 일관성 | ?/5 | ... |
| BE-2 에지케이스 | ?/5 | ... |
| BE-3 로직 위치 | ?/5 | ... |
| BE-4 쿼리 효율 | ?/5 | ... |
| BE-5 에러 계층 | ?/5 | ... |
| FE-1 UX 완성도 | ?/5 | ... |
| FE-2 벤치마크 갭 | ?/5 | ... |

### Quick Wins
1. ...

### Strategic (Phase 분리)
1. ...
```

## Generator-Evaluator 쌍

감사도 예외 없이 G-E 쌍을 따른다:

| 단계 | Generator | Evaluator |
|------|-----------|-----------|
| 1. 감사 실행 | 도메인별 7축 매트릭스 + 발견 목록 작성 | 발견 0건인 축이 없는지 확인 (전부 3점이면 FAIL) |
| 2. Quick Win 수정 | 코드 수정 | `./gradlew build` + 영향 evaluator PASS |
| 3. Strategic 등록 | pipeline.md Phase 항목 추가 | 항목에 Done Criteria + Evaluator 명시 확인 |
| 4. 감사 보고서 | `.claude/audit/{domain}-audit.md` 작성 | 보고서 구조 검증 (7축 전체 포함, 점수 1-5 범위, Quick Win/Strategic 분류 존재) |

> **원칙**: 발견만 하고 검증 안 하면 감사가 아니라 감상이다.

## DDR 수렴율 (감사 종료 조건)

```
DDR(n) = |새 발견(n)| / |새 발견(n-1)|
```

- DDR < 0.1 → 감사 종료 (추가 조사의 한계 수익 체감)
- 1라운드: 전체 도메인 빠르게 스캔 (30분)
- 2라운드: 1라운드 발견 기반 심층 조사
- 3라운드: DDR 확인 후 종료 or 계속

## Gotchas

### Cycle 1 vs Cycle 2 코드 스타일 차이
Cycle 1(Phase 12)은 codegen.py가 생성한 뼈대 위에 구현. Cycle 2(Phase 22-23)는 수동 구현.
**결과**: 같은 프로젝트 내에서 패턴 불일치 가능. 감사 시 "어느 Cycle 코드인가"를 인지해야 함.

### "모든 게 3점"이면 감사 실패
점수가 전부 3이면 분별력이 없는 것. 5와 1이 섞여야 우선순위가 명확해짐.
점수 부여 시 "이 도메인에서 가장 나쁜 축은 무엇인가?"를 먼저 찾고 1-2점 부여,
"가장 좋은 축은?"을 찾고 4-5점 부여. 나머지는 상대 배치.

### FE 감사 시 실제 브라우저 확인 필수
코드만 읽으면 레이아웃 깨짐, 색상 대비 부족, 모바일 뷰 누락을 놓침.
Playwright MCP로 스크린샷을 찍어 시각적으로 확인할 것.

### 감사 ≠ 리팩터링
감사는 "발견"이지 "수정"이 아님. 발견을 모두 기록한 후, 우선순위 분류 후에 수정 착수.
감사 중 즉흥 수정하면 Read:Edit 비율이 무너지고, 수정이 새 버그를 만들 위험.
