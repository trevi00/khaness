---
keywords: 브라우저 browser 크롬 chrome playwright 화면 screen 스크린샷 screenshot 동작확인 작동확인 정상작동 실행확인 열어 E2E e2e 검증 evaluator verify 검증스크립트 파서 parser sentinel 센티넬 뮤테이션
intent: 브라우저에서열어봐 화면돌려봐 작동하는지봐 E2E돌려봐 스크린샷찍어 검증스크립트작성 evaluator만들어 검증해 확인해 E2E해 테스트해
paths: e2e/ tests/e2e/ playwright/ src/pages src/components src/views .claude/scripts/
patterns: playwright @playwright/test verify-*.py mutate-*.py
requires: testing frontend
phase: implement review debug
min_score: 3
---

# Product Verification Guide

> 파이프라인: 14단계(E2E 테스트) — Playwright MCP로 배치 자동 테스트
> 검증: E1-E4 이진 체크리스트 (스크린샷 + API 응답 확인)
> Evaluator 작성: 아래 "Evaluator 작성 규칙" 섹션 필독

프론트엔드 또는 풀스택 앱이 실제로 제대로 작동하는지 브라우저에서 확인하는 스킬.
스크린샷과 프로그래밍적 assertion을 결합하여 검증한다.

## 의사결정 트리

### IF 수동 확인 요청 ("열어서 확인해", "브라우저에서 테스트해") (Implement)
1. dev 서버 상태 확인 → 없으면 시작 (아래 서버 관리 참고)
2. 확인할 페이지/흐름 목록 정리
3. 각 페이지별 Playwright 스크립트 작성 → `verification/` 폴더의 헬퍼 참고
4. 스크린샷 캡처 + assertion 실행
5. 스크린샷을 Read 도구로 읽어서 시각적 검증
6. 문제 발견 시 수정 → 재검증 루프
7. dev 서버 정리 (background process kill)

### IF E2E 테스트 작성 요청 (Implement)
1. 핵심 사용자 흐름 식별 (회원가입, 로그인, 주요 기능)
2. 각 흐름별 Playwright 테스트 파일 작성
3. 인증 상태 관리 (storageState fixture)
4. 각 단계에서 스크린샷 + assertion
5. CI에서 실행 가능하도록 headless 모드

### IF 검증 실패/에러 디버그 (Debug)
1. 스크린샷 확인 → 어떤 상태에서 멈췄는지 파악
2. Playwright trace 확인 (trace.zip)
3. 콘솔 에러 수집 (`page.on('console')`)
4. 네트워크 요청 실패 확인 (`page.on('requestfailed')`)

## 이진 검증 체크리스트 (E1-E4, 모두 PASS 필수)

| # | 체크 항목 | PASS 기준 | 측정 방법 |
|---|----------|----------|----------|
| E1 | 페이지 렌더링 | 모든 주요 페이지가 빈 화면/에러 없이 렌더링 | 스크린샷 시각 검증 |
| E2 | API 응답 확인 | 모든 CRUD 엔드포인트가 정상 응답 | curl 200/201 확인 |
| E3 | 사용자 흐름 | 핵심 시나리오(회원가입→로그인→주요기능) 완주 | 스크린샷 단계별 확인 |
| E4 | 콘솔 에러 없음 | 브라우저 콘솔에 에러 0개 | `page.on('console')` 수집 |

**14단계**: E1-E4 전체 검증, 배치로 모든 도메인 흐름 자동 테스트

### Artifact Verification Levels (GSD 흡수)

검증 시 산출물의 완성도를 4단계로 평가:

| Level | 이름 | 검증 방법 | 상태 |
|-------|------|----------|------|
| 1 | Exists | 파일/디렉토리 존재 확인 | VERIFIED / MISSING |
| 2 | Substantive | TODO/FIXME/PLACEHOLDER/빈 return 없는지 | VERIFIED / STUB |
| 3 | Wired | 다른 모듈에서 import + 사용 여부 | WIRED / ORPHANED |
| 4 | Data Flow | 실제 데이터가 흐르는지 (DB→Service→Controller→Response) | FLOWING / DISCONNECTED |

**Level 2 필터링**: test, spec, mock, fixture 파일은 STUB 검사에서 제외.
**Level 4 적용 대상**: 동적 데이터를 렌더링/반환하는 산출물만. 유틸리티/설정 파일은 Level 3까지.

### Anti-Pattern Scanner

검증 시 자동 스캔할 패턴:

| 패턴 | 심각도 | 제외 대상 |
|------|--------|----------|
| `TODO\|FIXME\|PLACEHOLDER` | blocker | test/spec/mock 파일 |
| `return null\|return {}\|return []` | context-dependent | 초기 상태(useState 등)는 무시 |
| Hardcoded empty props (`data={[]}`) | blocker | fetch/store로 덮어쓰는 경우 무시 |

### Re-Verification Mode

이전 검증에서 FAIL 항목이 있는 경우:
- **PASS 항목**: Level 1(존재) + Level 2(stub 없음) quick regression만
- **FAIL 항목**: Level 1~4 full verification
- **Override 적용**: FAIL이지만 의도적 편차인 경우 `PASSED (override)` 처리

Override 매칭: 80% token overlap fuzzy match (기술 용어 가중치 2배)

## 핵심 워크플로우: 서버 시작 → 검증 → 정리

### 1단계: Dev 서버 시작 및 대기
```bash
# 백그라운드로 dev 서버 시작 (PID 저장)
npm run dev > /tmp/dev-server.log 2>&1 &
DEV_PID=$!

# 서버가 준비될 때까지 대기 (최대 30초)
for i in $(seq 1 30); do
  if curl -s http://localhost:3000 > /dev/null 2>&1; then
    echo "Server ready"
    break
  fi
  sleep 1
done
```
**IMPORTANT**: Bash 도구의 `run_in_background`로 서버를 시작하고, 별도 Bash 호출에서 curl로 준비 상태를 확인할 것. 하나의 Bash 호출에서 서버 시작과 테스트를 동시에 하지 말 것.

### 2단계: Playwright 스크립트 작성 및 실행
검증용 스크립트는 임시로 생성하여 실행. 아래 패턴을 따를 것:

```javascript
// verify-<기능명>.js — 일회용 검증 스크립트
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();

  // 콘솔 에러 수집
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', err => errors.push(err.message));

  try {
    // 1. 페이지 이동
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'verify-01-home.png', fullPage: true });

    // 2. 상호작용
    await page.click('button#login');
    await page.fill('input[name="email"]', 'test@example.com');
    await page.screenshot({ path: 'verify-02-login-form.png' });

    // 3. 프로그래밍적 assertion
    const title = await page.title();
    console.log(`ASSERT title: ${title}`);
    if (!title.includes('Expected')) {
      console.error('FAIL: title mismatch');
    }

    // 4. 결과 요약
    if (errors.length > 0) {
      console.error('Console errors:', errors);
    } else {
      console.log('PASS: No console errors');
    }
  } finally {
    await browser.close();
  }
})();
```

### 3단계: 스크린샷 시각적 검증
```
# Read 도구로 스크린샷을 읽어서 시각적으로 확인
# Claude는 이미지를 읽을 수 있으므로, 레이아웃, 텍스트, UI 상태를 확인 가능
Read verify-01-home.png
```

### 4단계: 서버 정리
```bash
kill $DEV_PID 2>/dev/null
rm -f verify-*.png  # 임시 스크린샷 정리
```

## 재사용 패턴

### 로그인 후 상태 유지
```javascript
// storageState로 인증 상태 저장/재사용
await page.goto('/login');
await page.fill('[name=email]', 'test@test.com');
await page.fill('[name=password]', 'password');
await page.click('button[type=submit]');
await page.waitForURL('/dashboard');
await page.context().storageState({ path: 'auth-state.json' });

// 다른 테스트에서 재사용
const context = await browser.newContext({ storageState: 'auth-state.json' });
```

### 여러 뷰포트 테스트
```javascript
for (const viewport of [
  { width: 375, height: 812, name: 'mobile' },
  { width: 768, height: 1024, name: 'tablet' },
  { width: 1920, height: 1080, name: 'desktop' },
]) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  await page.screenshot({ path: `verify-${viewport.name}.png` });
}
```

### 비디오 녹화 (복잡한 흐름 디버깅)
```javascript
const context = await browser.newContext({
  recordVideo: { dir: './videos/', size: { width: 1280, height: 720 } }
});
// ... 테스트 수행 ...
await context.close(); // 비디오 파일 저장됨
```

### Behavioral Spot-Checks (GSD 흡수)

코드 존재를 넘어 실제 동작을 확인하는 경량 테스트:

| 체크 | 명령 예시 | 성공 기준 | 제약 |
|------|----------|----------|------|
| API 응답 비어있지 않음 | `curl -s localhost:8080/api/endpoint \| jq length` | > 0 | 10초 이내 |
| 빌드 산출물 존재 | `ls build/libs/*.jar \| wc -l` | > 0 | 서버 시작 금지 |
| Gradle 컴파일 통과 | `./gradlew compileJava` | exit 0 | 상태 변경 금지 |

**제약**: 각 체크 max 10초, 서버 시작 금지, DB/파일 상태 변경 금지, 실패 시 soft flag (abort 아님)

## Gotchas

### Bash run_in_background와 서버 관리
dev 서버를 `run_in_background: true`로 시작하면 PID를 직접 추적할 수 없음. 대신 포트로 프로세스를 찾아 종료: `lsof -ti:3000 | xargs kill` (Linux/Mac) 또는 `netstat -ano | findstr :3000`으로 PID 확인 후 `taskkill /PID <pid> /F` (Windows).

### Windows에서 Playwright 설치
`npx playwright install chromium`을 먼저 실행해야 함. 처음 실행 시 브라우저 다운로드에 시간이 걸림. 이미 설치되어 있는지 `npx playwright install --dry-run`으로 확인.

### headless vs headed
Claude Code는 GUI가 없으므로 반드시 headless 모드 사용 (기본값). `chromium.launch({ headless: true })`. headed 모드를 사용하면 실행은 되지만 Claude가 브라우저 창을 볼 수 없음 → 스크린샷만이 유일한 시각적 피드백.

### networkidle 대기
SPA에서 `waitUntil: 'networkidle'`은 API 호출이 끝날 때까지 대기. 폴링이나 웹소켓이 있으면 영원히 대기할 수 있음. 대신 특정 요소를 기다리는 것이 안전: `page.waitForSelector('.content-loaded')`.

### 스크린샷 경로 (Windows)
스크린샷 저장 경로에 한글이나 공백이 포함되면 실패할 수 있음. `/home/user/verify-01.png`처럼 짧고 ASCII 경로 사용.

### dev 서버 포트 충돌
이전 테스트에서 서버가 정리되지 않으면 포트가 점유됨. 검증 시작 전에 포트 사용 여부를 확인하고, 필요하면 기존 프로세스를 종료할 것.

### 페이지 로드 전 assertion
`page.goto()` 직후 바로 요소를 찾으면 아직 렌더링이 안 됐을 수 있음. `waitForSelector`, `waitForLoadState('networkidle')`, 또는 Playwright의 auto-waiting locator (`page.locator().click()`)를 사용.

### 스크린샷을 읽지 않는 실수
스크린샷을 찍었으면 반드시 Read 도구로 읽어서 확인할 것. 찍기만 하고 안 보면 검증의 의미가 없음. 특히 레이아웃 깨짐, 빈 페이지, 에러 화면은 assertion으로 잡기 어렵고 스크린샷으로만 확인 가능.

---

## Evaluator 작성 규칙 (verify-*.py)

> 실 프로젝트에서 21단계 207건 관찰 로그 기반으로 정제된 규칙.
> **반응적 자동화 86.7% → 선제적 전환을 위한 메타 규칙**.

### Parser Anti-Patterns — 절대 금지 (4회 재발 검증)

| Anti-Pattern | 사례 | 올바른 방법 |
|-------------|------|------------|
| **고정 윈도우 검색** (2000자, 3000자 슬라이스) | P6 B-2: 다음 섹션 "UK" 오매칭 → false PASS | 섹션 경계(`###`, `---`) 파싱 후 해당 섹션 내에서만 검색 |
| **부분 문자열 매칭** (`"checkstyle" in text`) | P18: `// id 'checkstyle'` 주석도 매치 | 활성 코드 라인만 필터 + `re.search(r'^id\s', line)` 앵커 |
| **주석 미필터링** | P20: `/* @theme_REMOVED */` 매치 | `line.strip().startswith('//') or line.strip().startswith('/*')` 제거 후 검색 |
| **단일 차원 키** (이름만으로 dict key) | P7: `IDX_status_created` 3개 테이블 충돌 | `(table_name, index_name)` 복합 키 |

### Evaluator 작성 체크리스트

1. **섹션 파싱 함수 필수**: `parse_by_section(text, delimiter='###')` → `{section_title: content}` dict
2. **활성 코드 필터**: 주석 라인 제외 후 매칭 (`gradle_active_lines`, `css_active_lines` 등)
3. **복합 키 사용**: 파일명·테이블명 등 스코프 정보 포함한 키로 dict 구성
4. **센티넬 값 포함**: 기대 수량을 상수로 정의하고 비교 (`EXPECTED_TABLES = 16`)
5. **뮤테이션 테스트 동반**: evaluator 1개당 최소 mutate-*.py 1개 (false PASS 주입 → FAIL 확인)
6. **Windows 인코딩**: `sys.stdout.reconfigure(encoding="utf-8")` 필수 (첫 줄)
7. **BASE 경로**: `os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))` 패턴 고정

### 센티넬 관리 규칙

- **SSOT**: 프로젝트 `.claude/sentinels.yaml`에 모든 기대값 정의
- **갱신 시점**: 상위 문서(ER/OpenAPI/Skeleton) 변경 시 센티넬도 함께 갱신
- **Phase 진입 전**: "Pre-Flight Sentinel Checklist" 확인 — 어떤 evaluator의 어떤 센티넬이 변경되는지 사전 파악
- **교차 참조**: 동일 개념(예: 테이블 수)을 여러 evaluator가 참조하면, sentinels.yaml에서 한 번만 정의

### 선제적 설계 원칙

> 반응적 86.7% → 선제적으로 전환하려면:

1. **Phase 설계 시 evaluator 먼저 정의**: Generator 명세와 동시에 "이 Phase가 만드는 산출물을 어떻게 검증할 것인가?" 정의
2. **크로스검증 사전 정의**: "이 문서가 변경되면 어떤 다른 문서가 영향받는가?" → DAG 노드 사전 등록
3. **3회 반복 규칙**: 동일 패턴 버그가 3회 발생하면, 개별 수정이 아닌 **메타 규칙으로 승격** (이 섹션에 추가)
4. **뮤테이션 우선**: evaluator 작성 직후 뮤테이션 테스트. "내일 하자" 금지

### 에이전트 위임 시 주의사항

에이전트에게 evaluator 작성을 위임할 때 이 규칙을 프롬프트에 포함:
```
evaluator 작성 규칙:
- 고정 윈도우 검색 금지 → 섹션 경계 파싱
- 부분 문자열 매칭 금지 → regex 앵커 + 활성 코드 필터
- 센티넬 상수 필수 → sentinels.yaml 참조
- 뮤테이션 테스트 동반 필수
```
