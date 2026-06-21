"""guard_patterns — DENY/WARN/AUTOCORRECT/SENSITIVE 패턴 정의 (Round 6 W2 P1).

Extracted from handlers/pre_tool/guard.py to enable independent unit-testing
+ pattern reuse. Pure data — no I/O or side effects.

## Categories

- DENY_PATTERNS: list of {regex, reason, [solo_override]} — match → block
- WARN_PATTERNS: list of {regex, message} — match → warn (non-blocking)
- BASH_AUTOCORRECT: list of {regex, fix, note} — match → rewrite cmd via fix(cmd)
- SENSITIVE_FILE_DENY: list of compiled regex — Write/Edit deny
- SENSITIVE_FILE_WARN: list of (regex, message) — Write/Edit warn

The guard.py main() iterates these collections; this module owns the rules.
"""
from __future__ import annotations

import re


# === DENY: 차단 (block) ===
DENY_PATTERNS = [
    # rm -rf on dangerous paths
    {
        "regex": re.compile(
            r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|"
            r"-[a-zA-Z]*f[a-zA-Z]*r)\s+"
            r"(/(?:\s|$|\")|~(?:\s|$|\")|~/'|\$HOME|\$USERPROFILE|"
            r"[A-Z]:\\\\?(?:\s|$|\"))",
            re.IGNORECASE,
        ),
        "reason": "루트/홈/시스템 디렉토리 재귀 삭제 차단",
    },
    # rm -rf /* (root wildcard)
    {
        "regex": re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+/\*"),
        "reason": "루트 디렉토리 와일드카드 삭제 차단",
    },
    # git push --force to main/master/production — flag may appear ANYWHERE
    {
        "regex": re.compile(
            r"(?=.*\bgit\s+push\b)"
            r"(?=.*(?:--force-with-lease|--force(?!-)|(?<!\w)-f(?!\w)))"
            r"(?=.*\b(?:main|master|production)\b)",
            re.IGNORECASE,
        ),
        "reason": "main/master/production 브랜치 force push 차단 (flag 위치 무관)",
    },
    # git push to main/master directly (Git Flow: PR-only)
    {
        "regex": re.compile(
            r"git\s+push\s+(?:[\w@:./\-]+\s+)?(?:origin\s+)?(?:HEAD:)?(?:main|master)(?:\s|$|:)",
            re.IGNORECASE,
        ),
        "reason": "[Git Flow] main/master 직접 push 차단 — PR 프로세스 사용 (skills/_common/git-flow.md)",
        "solo_override": True,
    },
    # DROP DATABASE
    {
        "regex": re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE),
        "reason": "DROP DATABASE 차단 — 수동 실행 필요",
    },
    # Disk destruction
    {
        "regex": re.compile(
            r"\bformat\s+[A-Z]:|"
            r"\bmkfs\b|"
            r"\bdd\s+if=/dev/(zero|random|urandom)\s+of=/dev/",
            re.IGNORECASE,
        ),
        "reason": "디스크 파괴 명령 차단",
    },
    # Fork bomb
    {
        "regex": re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;"),
        "reason": "Fork bomb 차단",
    },
    # chmod 777 on root
    {
        "regex": re.compile(r"chmod\s+(-R\s+)?777\s+/(?:\s|$)"),
        "reason": "루트 디렉토리 권한 변경 차단",
    },
    # Kill all processes
    {
        "regex": re.compile(r"taskkill\s+/f\s+/im\s+\*|killall\s+-9\s+\*|kill\s+-9\s+-1\b"),
        "reason": "전체 프로세스 종료 차단",
    },
    # Company policy: example_cloud package modification forbidden (project-specific
    # policy — user-private. Activated only when user's project has example_cloud
    # convention; harmless no-op for other projects.)
    {
        "regex": re.compile(
            r"example_cloud[/\\].*\.java",
            re.IGNORECASE,
        ),
        "reason": "[회사 정책] example_cloud 패키지 수정 절대 금지 — 모든 프로젝트가 공유하는 공통 프레임워크입니다. example_cloud-helper.sh로만 업데이트 가능.",
    },
]

# === WARN: 허용 + 컨텍스트 주입 ===
WARN_PATTERNS = [
    {
        "regex": re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+"),
        "message": "재귀적 파일 삭제 — 대상 경로가 정확한지 다시 확인하세요.",
    },
    {
        "regex": re.compile(r"git\s+reset\s+--hard"),
        "message": "git reset --hard는 커밋되지 않은 변경사항을 모두 잃습니다. stash 먼저 고려하세요.",
    },
    {
        "regex": re.compile(r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)", re.IGNORECASE | re.DOTALL),
        "message": "WHERE 절 없는 DELETE — 전체 행이 삭제됩니다.",
    },
    {
        "regex": re.compile(r"git\s+checkout\s+--\s+\.|git\s+restore\s+\."),
        "message": "작업 디렉토리의 모든 변경사항이 폐기됩니다.",
    },
    {
        "regex": re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
        "message": "DROP TABLE — 테이블이 완전히 삭제됩니다. 백업 여부를 확인하세요.",
    },
    {
        "regex": re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
        "message": "TRUNCATE TABLE — 모든 데이터가 삭제됩니다.",
    },
    {
        "regex": re.compile(r"git\s+push\s+.*--force|git\s+push\s+-f\b"),
        "message": "force push — 원격 히스토리가 덮어씌워집니다. 대상 브랜치를 확인하세요.",
    },
    # Git Flow: develop direct push (PR preferred)
    {
        "regex": re.compile(
            r"git\s+push\s+(?:[\w@:./\-]+\s+)?(?:origin\s+)?(?:HEAD:)?develop(?:\s|$|:)",
            re.IGNORECASE,
        ),
        "message": "[Git Flow] develop 직접 push — PR 프로세스 권장 (feature → develop). skills/_common/git-flow.md 참조.",
    },
    # Git Flow: commit message without conventional/company prefix
    {
        "regex": re.compile(
            r"git\s+commit\s+(?:[^-]|-[^m])*-m\s+[\"']"
            r"(?!"
            r"(?:feat|fix|refactor|docs|test|chore|perf|build|ci|style|revert)"
            r"(?:\([^)]+\))?!?:\s+|"
            r"\[(?:f/d|f/r|f/m|fix|etc)\]\s+|"
            r"(?:Merge|Revert)\s+|"
            r"\$\(|"
            r"\$\{|"
            r"`"
            r")"
            r".+?[\"']",
            re.IGNORECASE | re.DOTALL,
        ),
        "message": "[Git Flow] 커밋 메시지에 접두사 없음 — `feat:/fix:/...` (일반) 또는 `[f/d]/[f/r]/[f/m]/[fix]/[etc]` (회사). skills/_common/git-flow.md 참조.",
    },
]

# === BASH AUTOCORRECT: 명령 자동 보정 ===
BASH_AUTOCORRECT = [
    {
        "regex": re.compile(r"git\s+commit\s+.*--no-verify"),
        "fix": lambda cmd: re.sub(r"\s*--no-verify", "", cmd),
        "note": "--no-verify 제거: 훅을 건너뛰지 마세요.",
    },
    {
        "regex": re.compile(r"git\s+push\s+.*--no-verify"),
        "fix": lambda cmd: re.sub(r"\s*--no-verify", "", cmd),
        "note": "--no-verify 제거: 푸시 훅을 건너뛰지 마세요.",
    },
]

# === Sensitive file patterns (Write/Edit) ===
SENSITIVE_FILE_DENY = [
    re.compile(r"\.env($|\.local|\.prod|\.production)", re.IGNORECASE),
    re.compile(r"(id_rsa|id_ed25519|id_ecdsa)($|\.pem)", re.IGNORECASE),
    re.compile(r"\.pem$|\.key$|\.p12$|\.pfx$", re.IGNORECASE),
    re.compile(r"credentials\.json$|service.account\.json$", re.IGNORECASE),
    re.compile(r"token\.json$|secrets\.json$|\.secret$", re.IGNORECASE),
    re.compile(r"known_hosts$|authorized_keys$", re.IGNORECASE),
    re.compile(r"\.netrc$|\.pgpass$|\.my\.cnf$", re.IGNORECASE),
]

SENSITIVE_FILE_WARN = [
    (re.compile(r"settings\.local\.json$", re.IGNORECASE),
     "settings.local.json — 권한 설정 변경 시 보안에 주의하세요."),
    (re.compile(r"(nginx|apache|httpd)\.conf$", re.IGNORECASE),
     "웹 서버 설정 — 변경 시 서비스 영향을 확인하세요."),
    (re.compile(r"(Dockerfile|docker-compose\.ya?ml)$", re.IGNORECASE),
     "컨테이너 설정 — 포트/볼륨 매핑을 확인하세요."),
    (re.compile(r"(?:ci|cd|pipeline|workflow).*\.(?:ya?ml|json)$", re.IGNORECASE),
     "CI/CD 설정 — 변경이 파이프라인에 영향을 줄 수 있습니다."),
    (re.compile(r"mybatis-config\.xml$", re.IGNORECASE),
     "MyBatis 설정 변경 시 모든 DAO 매핑 확인 필요"),
    (re.compile(r"application\.ya?ml$", re.IGNORECASE),
     "서비스 설정 변경 시 CI/CD 영향 확인"),
]

# DENY patterns matched against the NORMALIZED full path (not basename), so a
# bare project `settings.json` (e.g. .vscode/settings.json, app config) is NOT
# caught — only the harness/project runtime-policy file `.claude/settings.json`.
# A direct Write/Edit TOOL call to it registers hooks/permissions = the flagship
# NEVER-auto mutation; before deep-audit pass-3 this had NO guard at all (the
# documented "Bash-redirect bypasses the Write/Edit deny" presupposed a deny that
# never existed — the plain Write/Edit path, the accidental-honest-agent's most
# likely route, was wide open). Direct file I/O in install/lib scripts is NOT a
# tool call, so guard never sees it — this only blocks the agent tool path, which
# is exactly where NEVER-auto must surface. ⚠️ Bash-redirect (`echo > settings.json`)
# STILL bypasses (guard does not parse redirect targets) — documented open residual.
SENSITIVE_PATH_DENY = [
    (re.compile(r"(^|/)\.claude/settings\.json$", re.IGNORECASE),
     "runtime-policy 파일 직접 수정 차단: .claude/settings.json — 훅/권한 등록은 "
     "NEVER-auto. 수동으로 편집하세요 (잘못된 편집은 전 도구를 차단할 수 있습니다)."),
]
