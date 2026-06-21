---
name: ai-slop-cleaner
description: Regression-safe cleanup workflow for AI-generated code slop — duplicate code, dead code, needless wrappers, boundary violations, weak tests.
keywords: [deslop, anti-slop, ai-slop, cleanup, refactor, dead-code, duplicate, over-abstraction]
intent: [clean, cleanup, simplify, deduplicate, remove-dead-code]
phase: review
min_score: 2
---

# AI Slop Cleaner

Clean AI-generated code slop without scope drift or behavior change. Bounded, regression-safe, deletion-first.

## 언제 쓰는가

- 사용자가 `deslop`, `anti-slop`, `AI slop` 언급
- 동작하지만 부풀려지거나 반복되거나 과추상된 코드
- Ralph/autopilot 세션 후 중복 로직·데드코드·래퍼·경계 위반 잔재
- 리뷰어-온리 패스 (`--review`)

## 언제 안 쓰는가

- 새 기능 빌드 / 제품 변경
- 대대적 재설계 (이 스킬은 점진적 클린업)
- 단순화 의도 없는 리팩토링
- 회귀 테스트 / 검증 계획이 불가능할 정도로 동작이 모호

## 의사결정 트리

```
요청 의도 == 기능 추가?  → 중단. 다른 스킬/커맨드
     아니오 ↓
의도 == 재설계?  → 중단. 설계 토론 (/harness-debate)
     아니오 ↓
회귀 잠금 가능?  → 예: 회귀 테스트 먼저 → 클린업 패스
     아니오 ↓
검증 계획을 명시적으로 기록 후 진행
```

## 실행 자세

- 사용자가 동작 변경을 명시적으로 요청하지 않는 한 **동작 보존**
- 가능한 경우 **회귀 테스트로 동작 잠그고** 시작
- 코드 편집 전 **클린업 계획** 작성
- **삭제 우선**, 추가 지양
- 새 의존성 금지 (명시 요청 없으면)
- diff 작게, 되돌릴 수 있게, smell 단위로
- 간결하고 증거 중심: inspect → edit → verify → report

## `--review` 모드

Writer/reviewer 패스 분리를 위한 리뷰어-온리 모드.

- **Writer 패스**: 클린업 변경, 테스트로 동작 잠금
- **Reviewer 패스**: 계획/변경/증거 검토, 승인 여부 결정
- 동일 패스가 작성+자기승인 금지

리뷰어 체크:
1. 남은 데드코드 / 미사용 export
2. 통합되지 않은 중복 로직
3. 경계를 여전히 흐리는 불필요한 래퍼/추상
4. 보존해야 할 동작에 대한 테스트 부족
5. 의도 없이 동작이 바뀐 클린업

## 워크플로우

1. **현재 동작 보호**
   - 무엇이 유지되어야 하는지 명시
   - 좁은 회귀 테스트 추가/실행
   - 테스트 선행이 불가능하면 검증 계획을 명시적으로 기록

2. **클린업 계획 작성** (코드 편집 전)
   - 요청 파일/피처 영역으로 범위 제한
   - 제거할 구체적 smell 나열
   - 안전한 삭제 → 리스크 있는 통합 순서

3. **Slop 분류**
   - **중복**: 반복 로직, copy-paste 분기, 중복 헬퍼
   - **데드코드**: 미사용, 도달 불가 분기, 오래된 플래그, 디버그 잔재
   - **불필요한 추상**: 패스스루 래퍼, 투기적 간접층, 1회용 헬퍼 층
   - **경계 위반**: 숨겨진 결합, 책임 이동, 잘못된 계층 import / side-effect
   - **테스트 부족**: 동작 잠김 없음, 약한 회귀 커버리지, 에지케이스 갭

4. **smell별 단일 패스**
   - Pass 1: 데드코드 삭제
   - Pass 2: 중복 제거
   - Pass 3: 네이밍 + 에러 처리 정리
   - Pass 4: 테스트 보강
   - 각 패스 후 타겟 검증 재실행
   - 편집 세트에 관련 없는 리팩토링 섞지 마라

5. **품질 게이트**
   - 회귀 테스트 green 유지
   - 관련 lint / typecheck / unit+integration 실행
   - 사용 가능하면 static / security 검사
   - 게이트 실패 시 고치거나 리스크 클린업 되돌림 (강행 금지)

6. **증거 중심 보고**
   - 변경 파일
   - 적용한 단순화
   - 동작 잠금 / 검증 실행
   - 남은 리스크

## 스코프 가이드

- 좋음: `deslop this module: too many wrappers, duplicate helpers, and dead code`
- 좋음: `cleanup the AI slop in src/auth and tighten boundaries without changing behavior`
- 나쁨: `refactor auth to support SSO` (기능 추가 — 다른 스킬)
- 나쁨: `clean up formatting` (너무 작음 — lint로 충분)

## Gotchas

- **범위 확장 유혹**: 한 파일 건드리다 보면 옆 파일도 좋아 보임. 명시 범위만 유지.
- **의도하지 않은 동작 변경**: export된 심볼 이름 변경, 시그니처 변경 → 내부 스타일만 변경.
- **과추상 제거하려다 과추상 추가**: 1회용 헬퍼 지우다 새 헬퍼 만들지 마라.
- **주석 무차별 삭제**: 비자명 결정을 설명하는 주석은 보존. 자명한 걸 재언급하는 주석만 제거.
- **중복 통합 후 테스트 깨짐 방치**: 통합이 리스크라면 되돌려라.
