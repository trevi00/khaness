<div align="center">

# khaness

### 설계하라. 만들어라. 검증하라.

**[Claude Code](https://claude.ai/code)를 위한 자기개선 운영 레이어** — 에이전트를 시니어 엔지니어링 프로세스로 감싸, 사소하지 않은 작업이 *만들기 전에 설계되고* *끝났다 말하기 전에 검증되도록* 합니다.

[English](README.md) · 한국어

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](requirements.txt)
[![CI](https://img.shields.io/badge/CI-run__all%20%2B%20run__units-brightgreen.svg?style=for-the-badge)](.github/workflows/ci.yml)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-orange.svg?style=for-the-badge)](CONTRIBUTING.md)
[![Status: experimental](https://img.shields.io/badge/status-v0.1%20experimental-lightgrey.svg?style=for-the-badge)](#상태)

</div>

* * *

## 무엇인가

Claude Code는 이미 유능한 에이전트입니다. **khaness**는 그 위에 시니어 엔지니어링 프로세스의 규율 — 구조·게이트·메모리 — 을 더해, 에이전트가 만들기 전에 설계하고 끝났다 말하기 전에 검증하게 합니다.

*메타 레이어*입니다: Claude Code는 평소대로 쓰고, khaness가 실질 작업을 **DGE 루프**로 감쌉니다:

- **Designer** — *"올바른 것을 만드는가?"* 아키텍처 결정은 3-에이전트 토론(Planner → Critic → Architect)이 결정론적으로 수렴.
- **Generator** — *"설계대로 만들었는가?"* 합의된 설계만 구현.
- **Evaluator** — *"실제로 동작하는가?"* 3-tier 스택: 기계적 검증자 → 의미적 LLM 평가자 → 선택적 멀티모델 합의. 검증이 다음 단계를 게이트.

> *Claude Code는 강력합니다. khaness는 그걸 규율 있게 만듭니다.*

* * *

## 어떻게 동작하나

1. **목표를 말한다.** 프롬프트 훅이 설계-클래스 작업을 감지해 토론 엔진을 표면화.
2. **설계가 수렴한다.** `/harness-debate`가 Planner / Critic / Architect 서브에이전트를 띄움. Critic은 제안을 assumption·failure·over-simplification 축으로 공격하고 Architect가 판결. 수렴은 결정론적(연속 2회 승인 + 동일 ontology-snapshot 해시)이며 모든 단계가 이벤트 로그에 append되어 재생 가능.
3. **생성이 진행된다.** 잠긴 설계 기준으로, 라이프사이클 훅이 가드레일(파괴적 명령 차단·민감 파일 보호·브랜치/PR 컨벤션) 강제.
4. **평가가 done을 게이트한다.** ~40개 기계적 검증자가 회귀 스위트로 실행; 의미적 평가자가 5축 + 엄격한 완성도 boolean 점수; paradox guard가 자기 작업을 done으로 채점하는 것을 차단.
5. **하네스가 자기개선한다.** 반복된 실패는 영구 스킬/훅 규칙이 됨(2-Strike Rule) — 같은 실수 재발 불가.

* * *

## 빠른 시작

**Claude Code 플러그인으로 (권장):**

```bash
claude plugin marketplace add github:trevi00/khaness
claude plugin install khaness@khaness
```

플러그인은 commands·agents·skills·hooks를 번들합니다. Claude Code가 번들 스크립트를 `${CLAUDE_PLUGIN_ROOT}`로 해석하고, 런타임 상태는 당신의 `~/.claude`에 저장됩니다. PyYAML 의존성은 한 번 `pip install -r requirements.txt`.

**또는 `~/.claude` 클론으로** (하네스 자체를 해킹할 때):

```bash
git clone https://github.com/trevi00/khaness ~/.claude
cd ~/.claude && bash install.sh
```

`install.sh`는 템플릿에서 포터블 `settings.json`을 생성(클론 위치를 훅 경로에 보간)하고, Python 의존성을 설치하고, 회귀 스위트를 돌려 설치 건전성을 증명합니다. 이후 그 디렉토리에서 새 Claude Code 세션을 엽니다.

시도해볼 명령:

```
/harness-debate <설계 결정>              # 3-에이전트 설계 수렴
/harness-autopilot                       # DGE 단계로 작업 자율 진행
/harness-audit                           # 6축 하네스 자가점검
```

> **모든 프로젝트의 첫 단계:** `.claude/tech-stack.yaml`로 스택을 선언해 스킬 트리를 관련된 것만 로드.

* * *

## 안에 든 것

| | |
|---|---|
| **42** 서브에이전트 | Planner / Critic / Architect 토론 역할, 평가자, 리서처, 프로젝트 워크플로 에이전트 |
| **17** `harness-*` 명령 | debate, autopilot, audit, interview, team, ultrawork, … |
| **69** `kha-*` 워크플로 스킬 | spec → plan → execute → verify 프로젝트 라이프사이클 |
| **~40** 검증자 | 회귀 스위트로 실행되는 기계적 pass/fail 게이트 |
| **254** 스킬 문서 총합 | 위 69 `kha-*` + 스택별 트리(java, kotlin, typescript, flutter, …) + 상시 `_common/` 포함 |

`scripts/` 코드베이스는 단방향 4계층(`lib/` → `validators/` → `handlers/` → `engine/`)이며 **설계상 OCP**: 새 provider·worker·validator는 *파일 1개 + 레지스트리 1줄*이지 기존 코드 수정이 아닙니다.

📖 **문서:** [ARCHITECTURE.md](ARCHITECTURE.md) (전체 지도) · [CONTRIBUTING.md](CONTRIBUTING.md) (시작 가이드) · [CLAUDE.md](CLAUDE.md) (매 세션 로드되는 운영 계약)

* * *

## 상태

**v0.1 / 실험적.** 동작하고 회귀 스위트는 통과(fresh clone에서 검증된 `run_all` + `run_units`)하지만, 의견이 강하고 주로 Windows에서 개발됐으며(크로스플랫폼 경로는 가드됐으나 덜 검증) API가 바뀔 수 있습니다.

런타임 데이터 — `state/`·`memory/`·`brain/`·`atlas/`·라이브 `HANDOFF.md` — 는 per-user이며 git-ignore됩니다. repo는 세션 상태가 아니라 템플릿과 기계장치를 배포합니다.

## 보증에 대한 정직함

이 하네스는 절대 단언을 불신하는 엔지니어가 만들었고, 설계가 그걸 반영합니다:

- **mutation-gate는 defense-in-depth이지 보안 경계가 아닙니다.** 런타임 정책 파일에 대한 *우발적* 쓰기(`.claude/settings.json` 직접 `Write`는 차단)는 표면화·차단하지만, 셸 가진 에이전트는 토큰 게이트를 우회할 수 있습니다. 실 경계는 **커밋된 diff에 대한 operator 리뷰**입니다.
- **훅은 fail-open.** 크래시한 훅은 도구를 막지 않고 깨끗이 종료 — 강제보다 가용성.
- **완성도는 단언이 아니라 정량화.** "done"은 알려진 결함 수·커버리지와 함께 보고하며, "완벽" 같은 단어는 일부러 피합니다.

코드가 뒷받침하는 것보다 강한 주장을 찾으면 버그입니다 — [이슈를 열어주세요](https://github.com/trevi00/khaness/issues).

* * *

## 크레딧 & 레퍼런스

khaness는 세 프로젝트의 아이디어 위에 서 있고, 그것들을 참고하여 만들어졌습니다:

- **[get-shit-done (GSD)](https://github.com/open-gsd/gsd-core)** — 스펙 주도 phase-loop 프로젝트 워크플로. khaness의 `kha-*` 명령과 번들된 `get-shit-done/` 서브시스템이 여기서 파생됐습니다.
- **Ouroboros** — 토론 엔진과 Ralph verify-fix 루프 뒤의 이벤트 소싱 / 무상태 재개 패턴 (`scripts/engine/debate.py`, `scripts/engine/ralph.py` 참조).
- **OMC** — 오케스트레이션 모델 + 단방향 4계층 `scripts/` 아키텍처 (`lib/` → `validators/` → `handlers/` → `engine/`).

* * *

## 라이선스

[MIT](LICENSE).

<div align="center">

*설계하라. 만들어라. 검증하라.*

</div>
