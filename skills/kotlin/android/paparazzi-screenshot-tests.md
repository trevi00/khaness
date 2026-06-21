---
name: paparazzi-screenshot-tests
description: Paparazzi 1.3.5 / 2.0-alpha JVM 스크린샷 테스트 — record/verify, layoutlib, locale/timezone 결정성, AGP 정합
keywords: paparazzi screenshot snapshot golden layoutlib jvm compose pseudolocale rtl recordPaparazzi verifyPaparazzi
intent: setup-screenshot-tests record-golden verify-regression handle-rtl pin-agp-version
paths: app/src/test
patterns: Paparazzi DeviceConfig recordPaparazzi verifyPaparazzi snapshot RenderingMode
requires: coroutines-flow-viewmodel-and-compose-state-boundaries
phase: plan implement review debug
tech-stack: kotlin
min_score: 2
quality_axes_enforced: true
---

# Paparazzi — Screenshot Tests on JVM

> 핵심: Paparazzi는 Android `layoutlib`을 JVM에 임베딩하여 **에뮬레이터 없이** Compose/View UI 렌더링 + golden 회귀. CI 빠르고 결정적이지만 **layoutlib 렌더링은 실제 device와 byte-identical 아님** — golden은 platform-pinned (Linux CI에서 record/verify 일관).

## 의사결정 트리

### IF 스크린샷 테스트 도입 (Plan)
| 신호 | 권장 |
|---|---|
| 에뮬레이터 없이 빠른 CI 회귀 | **Paparazzi 1.3.5** stable |
| Java 21+ + 최신 Compose 1.10 | **Paparazzi 2.0.0-alpha04** (alpha — production 보류) |
| 실제 device 화소 일치 필요 | Roborazzi 또는 Compose Preview tools |
| 멀티 라이브러리 비교 검증 | cross-library screenshot tests (Sergio Sastre 패턴) |

### IF 신규 테스트 작성 (Implement)
```kotlin
class HomeSnapshotTest {
  @get:Rule val paparazzi = Paparazzi(
    deviceConfig = DeviceConfig.PIXEL_5.copy(
      locale = "en-rXA",          // pseudolocale: accent
      nightMode = NightMode.NIGHT_NO,
    ),
    theme = "android:Theme.Material.Light.NoActionBar",
    renderingMode = SessionParams.RenderingMode.SHRINK,
  )

  @Test fun homeDefault() = paparazzi.snapshot {
    MaterialTheme { HomeScreen(state = HomeState.Loaded(sample)) }
  }
}
```

### IF Gradle 통합 (Implement)
1. **`./gradlew recordPaparazziDebug`** — golden 생성 후 `src/test/snapshots/`에 PNG 저장
2. **`./gradlew verifyPaparazziDebug`** — 회귀 검증 (HTML report `build/reports/paparazzi/`)
3. **`./gradlew testDebug`** — verifyPaparazzi 포함
4. CI에 Git LFS 필수 — `git lfs pull` 후 `verifyPaparazziDebug`

### IF RTL / 다국어 / dark mode 커버 (Implement)
- `en-rXA` (accent pseudolocale) — 텍스트 길이 폭증, 클립 검출
- `ar-rXB` (bidi pseudolocale) — RTL 레이아웃 검증
- `nightMode = NightMode.NIGHT_YES` — dark theme golden
- 각 조합별 별도 `@Test` (또는 parameterized)

### IF AGP/layoutlib 업그레이드 (Plan)
1. Paparazzi 버전을 AGP에 **lockstep** 핀:
   - 1.3.5 ↔ AGP 8.4.2 / Compose 1.7.5 / Kotlin 2.0.21
   - 2.0.0-alpha04 ↔ AGP 8.13.2 / Compose 1.10.1 / Kotlin 2.3.0 / Java 21+
2. AGP 업그레이드 시 layoutlib 변경 → golden 재기록 필요. PR에 record + diff 포함

## 가이드

- 2.0.0-alpha04는 **Java 21 필수** — JDK 17 CI는 1.3.5 유지.
- preview-aware 코드(`if (LocalInspectionMode.current)`)는 `CompositionLocalProvider(LocalInspectionMode provides true) { ... }` 래핑.
- Paparazzi `inflate<T>(R.layout.x)`로 View system도 같은 rule 안에서.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | golden 회귀로 시각 변경 자동 감지 |
| 성능 효율성 | JVM 렌더링이 에뮬레이터 대비 5-10x 빠름 |
| 호환성 | View + Compose 모두 같은 Paparazzi rule로 |
| 사용성 | `recordPaparazzi` 1 task로 golden 일괄 생성 |
| 신뢰성 | locale/timezone/nightMode 명시로 CI 결정성 |
| 보안 | golden PNG가 PII 포함하지 않게 sample data 사용 |
| 유지보수성 | AGP-Paparazzi lockstep 핀으로 drift 차단 |
| 이식성 | layoutlib JVM 동작 — Linux/Mac CI 무관 (단 platform-pinned) |
| 확장성 | parameterized test로 device/locale/theme matrix 확장 |

## Gotchas

### Locale/timezone non-determinism
comma separator, 날짜 format이 CI host에 따라 다름. `language`/`country`/`timeZone` 명시 안 하면 동일 코드가 다른 host에서 다른 golden — flaky test. 항상 `DeviceConfig`에 명시 또는 Gradle test JVM args.

### AGP 업그레이드 후 verify fail 폭주
layoutlib이 AGP에 묶여 있어 텍스트 anti-aliasing/color 미세 변동(이슈 #1465). lockstep 핀 + 업그레이드 시 record 재실행 + diff 검토.

### Custom font + AppCompatTextView 미스 렌더 (이슈 #1403)
`isSingleLine = true` + `gravity = CENTER` + custom typeface 조합에서 잘못된 위치. Compose Text로 마이그레이션 또는 DeviceConfig에서 fontScale 핀.

### RTL 미테스트
LTR golden만 있고 release 후 RTL 깨짐 발견 — 너무 늦음. `ar-rXB` 또는 actual locale 별도 `@Test` 필수.

### Cross-platform golden mismatch
Mac에서 record + Linux에서 verify → mismatch. 한 platform(보통 Linux CI)에 record/verify 통일.

## Source

- https://github.com/cashapp/paparazzi — `recordPaparazziDebug` "Saves snapshots as golden values"; `verifyPaparazziDebug` "verifies against previously-recorded golden values", 조회 2026-05-10
- https://cashapp.github.io/paparazzi/ — `Paparazzi(deviceConfig, theme)` rule, `paparazzi.snapshot { Composable() }`, `inflate<T>(R.layout.x)`, 조회 2026-05-10
- https://github.com/cashapp/paparazzi/releases — 1.3.5 stable + 2.0.0-alpha04 (Jan 2026, Java 21+ / Kotlin 2.3.0 / Compose 1.10.1 / AGP 8.13.2), 조회 2026-05-10
- https://github.com/cashapp/paparazzi/issues/1403 — custom fonts + gravity 미스 렌더, 조회 2026-05-10
- https://github.com/cashapp/paparazzi/issues/1465 — 플랫폼별 rendering 차이, 조회 2026-05-10
- https://cashapp.github.io/paparazzi/changelog/ — 버전별 AGP/Compose/Kotlin 매핑, 조회 2026-05-10
