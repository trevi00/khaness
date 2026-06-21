# {{도메인명}} ({{Domain Name}}) 도메인

> 관련: [context.md](../context.md) Personas 참조

---

## US-0XX: {{유저스토리 제목}}

- **AS** {{역할}} **I WANT** {{행동}} **SO THAT** {{가치/이유}}

### 기능 상세
- {{구현 세부사항 1}}
- {{구현 세부사항 2}}
- {{이벤트/캐시/동시성 관련 사항 (해당 시)}}

### Acceptance Criteria
```
Given {{사전 조건 (성공 시나리오)}}
When {{API: METHOD /api/path}}
Then {{기대 결과: HTTP 상태코드 + 응답 내용}}

Given {{사전 조건 (에러 시나리오 — 유효성 실패)}}
When {{API: METHOD /api/path}}
Then {{400 Bad Request + 에러 메시지}}

Given {{사전 조건 (에러 시나리오 — 리소스 없음)}}
When {{API: METHOD /api/path}}
Then {{404 Not Found + { status: 404, code: "XX001", message: "..." }}}

Given {{사전 조건 (에러 시나리오 — 권한 없음)}}
When {{API: METHOD /api/path}}
Then {{403 Forbidden}}

Given {{사전 조건 (에러 시나리오 — 충돌/중복)}}
When {{API: METHOD /api/path}}
Then {{409 Conflict + 에러 메시지}}
```

---

## US-0XX: {{유저스토리 제목 2}}

- **AS** {{역할}} **I WANT** {{행동}} **SO THAT** {{가치/이유}}

### 기능 상세
- {{세부사항}}

### Acceptance Criteria
```
Given {{성공 시나리오}}
When {{API}}
Then {{결과}}

Given {{에러 시나리오}}
When {{API}}
Then {{에러 응답}}
```

---

<!-- 아래 섹션은 해당 도메인에 상태가 있는 경우에만 작성 -->

## {{도메인명}} 상태 전이 규칙

```
[*] → {{초기상태}}    : {{트리거 (어떤 행동으로 생성되는지)}}
{{상태A}} → {{상태B}} : {{트리거}}
{{상태B}} → {{상태C}} : {{트리거}}
```

**금지 전이**: {{불가능한 전이와 그 사유}}

---

<!-- 아래 섹션은 해당 도메인에 동시성 이슈가 있는 경우에만 작성 -->

## 동시성 제어

| 자원 | 제어 전략 | 에러 시 |
|------|----------|---------|
| {{자원명}} | {{전략: 비관적 락/낙관적 락/UPSERT 등}} | {{에러 응답}} |

---

<!-- 작성 체크리스트 (작성 완료 후 삭제) -->
<!--
- [ ] 모든 US에 고유 ID (US-XXX)
- [ ] 모든 US에 AS/I WANT/SO THAT
- [ ] 모든 성공 AC에 대응하는 에러 AC (404/400/403/409)
- [ ] 목록 API에 정렬/필터/페이징 기준 명시
- [ ] 상태 있는 도메인: 초기 상태 + 허용/금지 전이
- [ ] 에러 메시지: { status, code, message } 구조 통일
- [ ] 이벤트 발행/소비 시 architecture.md 교차 반영 (notification.md는 해당 시)
-->
