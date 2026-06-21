---
name: live-log-db-verification
description: 배포된 기능을 실서버 로그(로그 MCP)+DB read로 라이브 검증 — 사용자가 실 플로우를 흘리는 동안 로그 이벤트와 DB 상태를 상관(correlate)해 단계별 확인
keywords: dozzle 로그 live verification 검증 dev 배포 MCP 로그
intent: 검증해 확인해 실테스트 라이브 추적해 시연
paths:
patterns:
requires: verification testing
phase: review deploy debug
tech-stack: any
min_score: 2
---

# 실서버 로그 + DB read 라이브 검증

> 배포된 기능을 **단위/IT 통과만으로 끝내지 말고**, dev 서버에 실제 플로우를 흘려 **로그 MCP(이벤트) + DB read(상태)를 상관**해 확인한다. green test ≠ 실동작 (메시지/외부연동/스케줄러는 mock green이 거짓일 수 있음 — cf. vendor-spec-defense F2).

## 의사결정 트리

### IF 배포 기능 라이브 검증 (Review/Deploy)
1. **배포 확인**: 로그 MCP `list_containers`로 대상 컨테이너 + `created` 시각 → 머지/배포 시각 이후인지. 시작 로그(스케줄러 invariant 등)로 신규 코드 기동 확인.
2. **baseline DB**: 검증 대상 컬럼/상태를 read (예: 상태플래그·deadline·시각컬럼). 컬럼 존재 + 현재값 확인.
3. **사용자가 실 액션** (주문/결제/취소 등) → "넣었어" 신호.
4. **상관 검증**: 로그 MCP로 그 시각 이벤트(외부호출 status, 발송 templateCode+결과) + DB read로 상태전이(전/후 비교). **한 액션 = 로그 N라인 + DB M컬럼**을 묶어 1 PASS 판정.
5. 시간대 정렬: 앱 `LocalDateTime.now()`=UTC vs DB `CREATED_AT`/`UPDATED_AT`=서버 TZ(KST 등). 같은 사건이 9h 차로 보일 수 있음 — 둘 다 같은 기준으로 환산 후 비교.

### IF 대용량 로그 MCP 출력 (Debug)
> dozzle/log MCP의 `get_container_logs`는 수백 KB~MB → 컨텍스트 오버플로 + 파일 라인이 너무 길어 Read offset/limit 불가.
1. 출력은 자동으로 tool-results 파일에 저장됨 → 그 경로를 python으로 처리.
2. **JSON 라인 파싱 + ANSI 제거 + 키 필터** 후 메시지 본문만 추출:
   ```python
   import re,json
   for raw in open(PATH,encoding='utf-8',errors='replace').read().split(chr(10)):
       try: obj=json.loads(raw)
       except: continue
       msg=obj.get('message','')
       if isinstance(msg,list): msg=' || '.join(map(str,msg))   # grouped log = JSON array
       clean=re.sub(r'\x1b\[[0-9;]*m','',str(msg)).replace(chr(13),'')   # strip ANSI
       clean=re.sub(r'\s+',' ',clean)
       if KEY in clean: print(obj.get('timestamp','')[11:19], clean[:300])
   ```
3. `since_minutes`를 좁게(3~6분) + 사용자 액션 직후에 호출 → 출력량 최소화.

### IF DB read 검증 (Review)
- [ ] read-only 도구로만 (쓰기는 사용자/담당자 권한 — 스케줄러 트리거용 deadline 과거 UPDATE 등)
- [ ] 대상 컬럼이 실제 dev 스키마에 존재하는지 (마이그레이션 미적용이면 SELECT * 에 안 나옴)
- [ ] 전이 전/후 2회 read 로 변화 캡처

## 가이드

- **로그 MCP는 온디맨드 조회** (shell tail 아님) → Monitor 툴로 stream 불가. 사용자 액션 → 알림 받고 → 그 직후 `get_container_logs` 끌어오는 인터랙티브 루프.
- **상관 1쌍 = 강한 증거**: "결제 로그(templateCode=X 발송 성공) + DB(status·deadline 세팅)"를 한 묶음으로 PASS 판정. 로그만/DB만으론 약함.
- 외부 발송(알림톡/후킹): 로그의 `templateCode` + 성공/실패 라인(예: send:143=성공 / send:147=실패 + response 코드)으로 분기 확인.

## Gotchas

### "발송 성공" 로그 = 중계 서버 200 OK ≠ 최종 배송 확정
메시지/알림톡 발송 "성공"은 보통 **사내 message 서비스가 200 반환**(요청 수락)을 의미. 실제 카카오/SMS 배송은 다운스트림(템플릿 심사·수신거부)에서 별도로 실패 가능. **최종 수신은 실 수신폰으로 확인**해야 확정. 미승인 템플릿도 중계 200이 떠서 로그상 "성공"으로 보일 수 있음.

### MCP를 세션 중간에 추가하면 도구가 안 올라옴
`claude mcp add` 로 등록 + `claude mcp list`가 Connected 떠도, **실행 중 세션은 MCP 도구를 시작 시점에 로드**했기 때문에 그 서버 도구가 ToolSearch에 안 잡힘. **세션 재시작** 후 로드됨. HANDOFF 갱신해두고 재시작이 안전.

### UTC(앱) vs KST(DB) 9시간 착시
앱 `LocalDateTime.now()`로 채운 컬럼(ACCEPTED_AT, *_EXPIRE_AT 등)은 UTC, DB `CURRENT_TIMESTAMP`(CREATED_AT/UPDATED_AT)는 서버 TZ(KST). 같은 사건이 9h 차로 보임. deadline 검증(예: +5h) 할 땐 **둘 다 UTC 또는 둘 다 KST로 환산** 후 비교 — 안 그러면 "5h가 아니라 14h"처럼 오판.

### tool-results 파일을 Read로 청크하려다 막힘
로그 JSON은 한 줄이 수만 자라 Read의 offset/limit(줄 단위)로 못 자름. **python으로 char-range 슬라이스 또는 라인별 json.loads** 로 처리. Read 재시도 금지.

### 스케줄러 트리거를 로그로 기다릴 때 silence=success 착각
fixedDelay 스케줄러는 **대상이 있을 때만 로그**하는 경우가 많음(스캔 0건은 조용). "로그 없음=정상 동작"이 아님 — DB로 scan 대상 존재 여부를 직접 확인하거나, deadline을 과거로 만들어(쓰기 권한자) 발화를 강제.

---
출처: example_app-backend-poslink CJ 알림톡/자동완료 라이브 검증 (2026-06-12, dozzle MCP `log-dev.paytap.co.kr` + dev DB read). 접수=결제시점·확인=§4.2·자동완료 +5h 데드라인을 로그 templateCode + DB ACCEPTED_AT/AUTO_COMPLETE_EXPIRE_AT 상관으로 확정.
