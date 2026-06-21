---
name: vendor-spec-defense
description: 외부 vendor (PDF API spec, Postman collection) 의 self-inconsistency / spec-vs-실동작 mismatch 대응 패턴
keywords: vendor spec PDF API Postman 외부 연동 spec defense dual cover hypothesis evidence
intent: 외부 통합 디버그 시연 가설
phase: debug implement
min_score: 2
---

# Vendor Spec Defense Pattern

> 원칙: 외부 vendor spec 은 종종 자기모순 / 실동작 불일치 가능. 시연 evidence 우선 + dual fallback 방어.
>
> 학습 출처: EasyPOS POS PDF §6.1 — placeholder spec table `<ORG_*>` vs example body `<ORD_*>`
> 자체 모순 → dual cover (commit 2b54aca, 2026-05-09).
> 추가: 가설 A 진화 (subItem sDetailNo 필수 + itemPrice=0 가설 오류 → 옵션 단가 복원),
> SET_EVENT_INFO 응답 envelope (top-level returnCode 가 아닌 `header.responseCode.code` 중첩).

---

## 의사결정 트리

### IF 외부 vendor spec 통합 신규 (Plan) — "discovery 선행" (구현 前)
> 핵심: 비용은 코딩이 아니라 **discovery가 늦게(dev 시연 중) 일어나는 것**. 회수/평탄화 재작업 = Day-1 input이었어야 할 사실의 지연 발견. 빠름·정확은 trade-off가 아니라 **같은 것** — discovery를 앞으로 당기면 둘 다 달성. (poslink CJ 34PR: 평탄화 2라운드 + 회수 9건이 전부 늦은 discovery)
0. **형제(sibling) 역설계 먼저** — "기존 종류의 새 인스턴스"면(새 PG/vendor), 이미 통합된 형제 1개(UnionPos/Paytap 등)를 end-to-end 정독해 구조(컨트롤러/서비스/DTO/SSOT 합류 레인)를 청사진으로 **그대로 채택**. **별도 레인·clean-arch 추상화 금지** (cf. code-quality "기존 카테고리 새 인스턴스"). 형제 = 절반의 spec.
1. **실 wire 계약을 SSOT에서 추출** — PDF가 아니라 회사 Postman + **엔드포인트당 1회 실 송신 raw_response**. 요청/응답 필드·URL·필수헤더·템플릿변수+데이터출처·status코드 전수 확정 (spec 자기모순도 여기서: table field ↔ example body field).
2. **배포순서·스키마 의존 매핑** — DDL ALTER(NOT NULL no-default)·상대 서비스 공유 DTO의 deploy-order를 사전 표로 (cf. api-contracts "공유 DTO 배포순서").
3. **dev 스파이크 1회** — 형제 경로로 실주문 1건 흘려 raw 캡처 → 모든 가정을 현실에 고정. 모호 영역은 가설 A/B/C 명문화 → 시연 evidence(실 raw)로 검증.
4. **계약 테스트는 mock 아니라 raw ObjectMapper JSON contract test** — green=정확 (mock green은 F2).

### IF spec 자기모순 발견 (Implement)
1. **dual cover 패턴**: spec 표기 / example 표기 양쪽 substitute
2. 예시 (EasyPOS callback placeholder):
   ```dart
   final eventBody = '{'
       '"tableGroupCode":"<ORG_TABLE_GROUP_CODE>",'  // spec table 표기
       '"tableCode":"<ORG_TABLE_CODE>",'
       '"flag":"<FLAG>",'
       '"tableGroupCodeAlt":"<ORD_TABLE_GROUP_CODE>",'  // example body 표기
       '"tableCodeAlt":"<ORD_TABLE__CODE>"'
       '}';
   ```
3. parsing 측에서 `_pickValid(primary, alt)` 양쪽 fallback
4. log 진단: 양쪽 모두 unsubstituted 면 spec mismatch — 사용자/vendor 알림

### IF spec 모호 영역 (가설 검증 필요) (Debug)
1. 가설 후보 enumerate (A/B/C):
   - A: subItem sDetailNo 필수 (PDF §5.5 line 552)
   - B: subItem itemPrice=0 (PDF §5.5 line 547-550 보조 정합)
   - C: subItem 자체 미forward (UNION 패턴)
2. **1 가설 1 commit + 시연** 원칙 — 시연 결과로 가설 단계별 검증
3. **시연 evidence 필수**: agent UI 표시 + 외부 시스템 매출/응답 + raw_response 로그
4. 가설 진화: 시연 결과 따라 가설 수정/병합 — 한 commit 내 다중 가설 X
5. 가설 확정 후 코드 comment 에 "가설 A 확정 (2026-05-11 시연 evidence)" 명시 — 후속 reviewer 가 모호 영역 인지

### IF spec envelope 모호 (응답 파싱) (Debug)
1. raw_response 캡처 — `log + raw=${getRes.data}` 패턴
2. spec 의 응답 예시 vs 실 응답 diff
3. 가능 위치 후보:
   - top-level `returnCode`
   - `header.responseCode.code`
   - `header.responseCode` (직접 number)
   - nested `data.header.responseCode.code`
4. 발견 위치 코드 comment 명시 — "envelope 위치: data.header.responseCode.code (시연 evidence 2026-05-11 hotfix 7a01b72)"

---

## Gotchas

### 알림톡/메시지 발송 계약의 SSOT는 vendor PDF가 아니라 회사 Postman + 실 송신 raw
메시지/알림톡 발송 4요소(**템플릿 변수명·발송 API URL·필수 헤더·변수 데이터출처**)는 vendor PDF가 아니라 **회사 message 서비스 Postman 컬렉션 + 1회 실 송신 raw_response**가 SSOT. 머지 전 전수 대조 필수. 변수 데이터출처까지 추적(예: ORIGIN payload엔 결제정보 없음 → tran outbox `tran_tender_seq[0]`). 단위테스트가 URL·헤더·수신측 DTO를 mock하면 **잘못된 값도 green** — `[8010021]` 미정의 API / `[8020003]` 헤더부족 / `payType=""` / NOT_ENOUGH_BODY 전부 mock 통과 후 dev 시연 raw로만 발견. (poslink #38→#48/#49/#52/#64 4연속 회수)

### spec 표기 1개만 substitute 시도
가장 흔한 첫 시연 실패. spec table 만 보고 substitute → vendor 실동작은 example body 표기 사용 → placeholder 미치환. **dual cover 가 vendor self-inconsistency 표준 방어**.

### "가설 A" comment 가 영구 잔존
가설 검증 commit 후 comment 의 "가설 A" 표기 영구 남김 → reviewer 가 미확정 영역으로 오해. **시연 evidence 확정 후 comment 갱신**: "가설 A 확정 (시연 YYYY-MM-DD)" 또는 "PDF §X.Y line Z 정합".

### raw_response 캡처 안 함
spec mismatch 디버깅 시 raw_response 없으면 가설 검증 불가. **모든 외부 vendor HTTP 호출 후 실패 시 `log raw=${data}` 의무**. 정상 응답은 size 클 때만 log skip.

### vendor spec 의 모호 단어 (△ / O / X 표시)
PDF spec 의 △ (보조), O (필수), X (미사용) 표시가 자체 모호 가능. 예: PDF §5.5 line 552 에 sDetailNo "△" 였는데 실 spec 은 필수. **시연 evidence 우선, spec 표기 회의적**.

### dual cover 의 over-protection
dual cover 후 양쪽 모두 unsubstituted 면 spec mismatch — 단 한쪽만 substitute 되어도 정상 — 진단 logic 이 양쪽 검사 시 false alarm. **fromJson 후 dto 값 검사로 진단 이동** (over-protection 회피 — commit dc468c5 패턴).

### vendor 측 fix 의존 vs agent 측 cover
spec mismatch 발견 시 vendor 측 spec/실동작 수정 요청 vs agent 측 dual cover. **agent 측 cover 우선** — vendor fix lead time 길고, 다른 매장 호환성 위험. agent 측 cover + log 진단으로 vendor 측 fix 유도.

---

## 도구 사용 패턴

- spec 1차 read: `Read("docs/<vendor>.pdf.txt")` 또는 `Grep("<keyword>", "docs/")`
- raw_response 캡처: code 에 `log raw=${data}` 추가 후 시연 → log 분석
- dual cover 적용: DTO 의 substitute / parse 양쪽 변경
- 가설 검증: 1 commit 1 가설 + 시연 cycle + `git revert` 대비

---

## 참조 사례 (EasyPOS PR #187)

| 발견 | spec issue | 해결 commit | 시연 evidence |
|------|-----------|-------------|--------------|
| placeholder 자체 모순 | PDF §6.1 spec table `<ORG_*>` vs example `<ORD_*>` | 2b54aca dual cover | 12:42:45 양쪽 substitute |
| envelope 위치 모호 | top-level returnCode vs `header.responseCode.code` | 7a01b72 nested 파싱 | 9:17 returnCode=null → 12:29 envelope fix |
| 환경설정 미체크 | PDF §4.1 [전자메뉴판 주문 연동] 매장 측 조작 필수 | 9c1a04b code 별 advisory | 12:29 code 37 → 12:42 success |
| 가설 A 진화 | subItem sDetailNo / itemPrice 모호 | 9e32dd3 + 후속 hotfix | itemPrice=0 → 옵션 매출 0 → 단가 복원 |
