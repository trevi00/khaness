---
name: visual-verdict
description: Structured visual QA verdict for screenshot-to-reference comparisons. Emits strict JSON verdict with score 0-100, pass threshold 90+.
keywords: [visual, screenshot, ui-fidelity, pixel-diff, verdict, compare]
intent: [verify, compare, verdict, visual-qa]
phase: review
min_score: 2
---

# Visual Verdict

Compare generated UI screenshots against reference images and return strict JSON verdict that drives the next edit iteration.

## 언제 쓰는가

- 태스크에 시각적 충실도 요구 (레이아웃, 여백, 타이포, 컴포넌트 스타일)
- 생성 스크린샷 + 최소 1장의 레퍼런스 이미지 존재
- 다음 편집 전 deterministic pass/fail 필요

## 입력

- `reference_images[]` (1장 이상 이미지 경로)
- `generated_screenshot` (현재 출력 이미지)
- 선택: `category_hint` (예: `dashboard`, `feed`, `hackernews-like`)

## 출력 계약 (JSON만)

```json
{
  "score": 0,
  "verdict": "revise",
  "category_match": false,
  "differences": ["..."],
  "suggestions": ["..."],
  "reasoning": "short explanation"
}
```

규칙:
- `score`: 0-100 정수
- `verdict`: `pass` | `revise` | `fail`
- `category_match`: 생성 스크린샷이 의도된 UI 카테고리/스타일과 일치
- `differences[]`: 구체적 시각 불일치 (레이아웃, 여백, 타이포, 색, 계층)
- `suggestions[]`: differences에 연결된 실행 가능한 다음 편집
- `reasoning`: 1-2 문장 요약

## 임계값 + 루프

- **pass 임계값: 90+**
- `score < 90` 이면 편집 계속 후 다시 `/visual-verdict` 재실행 (다음 시각 리뷰 전에)
- 다음 스크린샷이 임계값 넘기기 전에는 시각 태스크 완료 주장 금지

## 디버그 시각화

불일치 진단이 어려울 때:
1. Visual Verdict를 **authoritative decision**으로 유지
2. 픽셀 레벨 diff 툴 (pixel-diff, pixelmatch overlay) 을 **보조 디버그 도구**로 사용 (hotspot 위치 파악)
3. 픽셀 diff hotspot을 `differences[]` + `suggestions[]` 업데이트로 변환

## 예시

```json
{
  "score": 87,
  "verdict": "revise",
  "category_match": true,
  "differences": [
    "Top nav spacing is tighter than reference",
    "Primary button uses smaller font weight"
  ],
  "suggestions": [
    "Increase nav item horizontal padding by 4px",
    "Set primary button font-weight to 600"
  ],
  "reasoning": "Core layout matches, but style details still diverge."
}
```

## Gotchas

- **JSON 외 prose 출력 금지**: verdict loop 자동화가 깨짐.
- **카테고리 mismatch ignored**: `category_match: false`인데 `verdict: pass` 내리면 안 됨.
- **90+ 도달 전 complete 선언**: threshold 존중.
- **차이 추상 서술**: "look doesn't match" 대신 "nav padding 16px vs 24px".
