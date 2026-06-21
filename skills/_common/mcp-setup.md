---
keywords: MCP mcp 모델컨텍스트 프로토콜 protocol 설치 install 서버 server 도구 tool 플러그인 plugin claude 클로드 mcp-installer
intent: MCP설치해 MCP설정해 MCP추가해 MCP제거해 서버연결해
paths: .claude.json .claude/settings
patterns: mcp-installer @modelcontextprotocol @anaisbetts
requires:
phase: implement
min_score: 3
---

# MCP (Model Context Protocol) 설치 및 설정 가이드

## 의사결정 트리

### IF 새 MCP 서버 설치 (Implement)
1. **바로 설치하지 말 것!** 반드시 공식 문서 먼저 확인
2. WebSearch로 해당 MCP의 공식 사이트/레포지토리 확인
3. 현재 OS 및 환경에 맞는 설치법 확인
4. context7 MCP가 있으면 추가 확인
5. mcp-installer로 user 스코프 설치
6. 설치 확인 (claude mcp list + 디버그 모드)

### IF 설치 실패/문제 발생 (Debug)
1. claude mcp list로 등록 확인
2. 디버그 모드 실행: `echo "/mcp" | claude --debug`
3. 에러 메시지 확인 (최대 2분 관찰)
4. 아래 Gotchas 참고
5. 필요시 직접 설치 → .claude.json 수정

### IF MCP 제거 (Implement)
1. `claude mcp remove <mcp-name>`
2. claude mcp list로 제거 확인

### IF 클로드 데스크탑 MCP 가져오기 (Implement)
1. `C:\Users\<사용자>\AppData\Roaming\Claude\claude_desktop_config.json` 확인
2. mcpServers 내용을 `.claude.json`의 user 스코프로 복사
3. 디버그 모드로 작동 확인

## 환경별 설정

### Windows 네이티브 (현재 환경)
- **User 설정 파일**: `C:\Users\{사용자명}\.claude.json`
- **IMPORTANT**: Windows에서 `npx` 직접 실행 불가 → `cmd.exe` 래퍼 필수

```json
{
  "mcpServers": {
    "mcp-name": {
      "command": "cmd.exe",
      "args": ["/c", "npx", "-y", "package-name"],
      "type": "stdio",
      "env": { "API_KEY": "your-key-here" }
    }
  }
}
```

### Linux / macOS / WSL
```json
{
  "mcp-name": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "package-name"],
    "env": { "API_KEY": "your-key-here" }
  }
}
```

### .claude.json 수정 방법
`.claude.json`은 Claude Code가 실시간 갱신하므로 Edit 도구 실패 가능
→ jq 원자적 수정 사용:
```bash
jq '.mcpServers["new-mcp"] = {"command":"cmd.exe","args":["/c","npx","-y","pkg"],"type":"stdio"}' \
  "$USERPROFILE/.claude.json" > /tmp/claude_tmp.json && \
  mv /tmp/claude_tmp.json "$USERPROFILE/.claude.json"
```

## Gotchas

### Windows npx 직접 실행 불가
Windows 네이티브 Claude Code에서 `"command": "npx"`는 실패함. 반드시 `"command": "cmd.exe", "args": ["/c", "npx", ...]` 래퍼 사용. PowerShell도 가능하지만 cmd.exe가 가장 안정적.

### args 배열 토큰 분리
`["/c", "npx", "-y", "pkg"]` (정상) vs `["/c", "npx -y pkg"]` (위험) — cmd.exe 내부 따옴표 처리가 달라짐. 토큰 단위로 분리하는 것이 안전.

### JSON 경로에서 백슬래시
JSON에서 `\`는 이스케이프 문자. Windows 경로를 넣을 때 `\\` 두 번 사용: `"C:\\tools\\server.js"`.

### .claude.json Edit 도구 실패
Claude Code가 이 파일을 실시간으로 갱신하기 때문에 Edit 도구로 수정하면 race condition 발생. jq로 원자적 수정하거나, Claude Code를 잠시 중지 후 수정.

### MCP 서버 타임아웃
일부 MCP 서버는 첫 시작이 느림 (npm 패키지 다운로드 등). 디버그 모드에서 최대 2분간 관찰하여 실제 실패인지 단순 지연인지 구분.

### Node.js 버전 요구
대부분의 MCP 서버는 Node.js v18 이상 필요. `node --version`으로 확인하고, `npx -y` 옵션으로 버전 호환성 문제 감소.

### 환경변수에 특수문자
API 키에 `&`, `|`, `>` 같은 셸 특수문자가 포함되면 cmd.exe에서 해석됨. `env` 블록으로 전달하면 셸 해석 없이 안전하게 전달됨.

### user vs project 스코프 혼동
`.claude.json`(프로젝트 루트)의 mcpServers는 project 스코프. `~/.claude.json`의 mcpServers가 user 스코프. projects 항목 내부에 있으면 특정 프로젝트에만 적용됨.

## 도구 사용 패턴 (Harness)
- .claude.json 수정: `Edit` 도구 대신 `Bash(jq)` 원자적 수정 (Claude Code 실시간 갱신과 race condition 방지)
- MCP 디버그: `Bash(claude mcp list)` → `Bash(echo "/mcp" | claude --debug)` 순서
- settings.json: `Read`로 먼저 확인 → 필요한 부분만 `Edit`
- 서버 상태 확인: `Bash`로 프로세스 확인 (npx가 실행 중인지)

## 에러 복구 패턴 (Harness)
- MCP 연결 실패 → Windows에서 cmd.exe 래퍼 확인 (`"command":"cmd.exe"`, `"args":["/c","npx",...]`)
- 래퍼 정상 → `Bash(which npx)` + `Bash(node --version)`으로 경로/버전 확인 (v18+)
- 경로/버전 정상 → `Bash(echo "/mcp" | claude --debug)`로 2분간 관찰, 타임아웃 대기
- 여전히 실패 → `claude mcp remove` 후 재설치, 또는 jq로 .claude.json 직접 수정
