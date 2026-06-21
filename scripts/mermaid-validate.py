#!/usr/bin/env python3
"""mermaid-validate.py - Mermaid 다이어그램 기본 문법 검증

플로우차트 파일(.md)에서 Mermaid 코드 블록을 추출하고,
기본 문법 오류를 검사합니다. 렌더링 검증은 아님 (구조적 검증만).

사용법:
    python mermaid-validate.py <file_or_directory>
    python mermaid-validate.py <project>/.claude/design/flows/

검증 항목:
- 빈 Mermaid 블록 감지
- 지원하지 않는 다이어그램 타입 감지
- 화살표 문법 기본 검증 (flowchart, sequenceDiagram)
- stateDiagram의 [*] 초기 상태 존재 확인
- 노드명 특수문자 미감싸기 감지
"""

import sys
import os
import re
import glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

VALID_DIAGRAM_TYPES = {
    "flowchart", "graph", "sequenceDiagram", "stateDiagram-v2",
    "stateDiagram", "classDiagram", "erDiagram", "gantt",
    "pie", "gitgraph", "mindmap", "timeline", "quadrantChart",
    "sankey-beta", "xychart-beta", "block-beta",
}

ARROW_PATTERNS = {
    "flowchart": re.compile(r"-->|==>|-.->|--[>ox]|~~>"),
    "graph": re.compile(r"-->|==>|-.->|--[>ox]|~~>"),
}


def extract_mermaid_blocks(content):
    """Extract all ```mermaid ... ``` blocks from markdown content."""
    pattern = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
    return pattern.findall(content)


def detect_diagram_type(block):
    """Detect the Mermaid diagram type from the first non-empty line."""
    for line in block.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("%%"):
            continue
        # Extract first word
        first_word = line.split()[0] if line.split() else ""
        # Handle "flowchart TD", "graph LR" etc.
        if first_word in VALID_DIAGRAM_TYPES:
            return first_word
        # Handle "stateDiagram-v2"
        if line.startswith("stateDiagram-v2"):
            return "stateDiagram-v2"
        return first_word
    return None


def validate_block(block, block_index, filename):
    """Validate a single Mermaid block. Returns list of (severity, message)."""
    issues = []
    stripped = block.strip()

    # Empty block
    if not stripped:
        issues.append(("ERROR", f"블록 #{block_index}: 빈 Mermaid 블록"))
        return issues

    diagram_type = detect_diagram_type(stripped)

    # Unknown diagram type
    if diagram_type and diagram_type not in VALID_DIAGRAM_TYPES:
        issues.append(("WARN", f"블록 #{block_index}: 알 수 없는 다이어그램 타입 '{diagram_type}'"))

    lines = stripped.split("\n")

    # flowchart/graph: check for arrows
    if diagram_type in ("flowchart", "graph"):
        has_arrow = False
        for line in lines[1:]:  # skip first line (type declaration)
            if ARROW_PATTERNS["flowchart"].search(line):
                has_arrow = True
                break
        if not has_arrow and len(lines) > 2:
            issues.append(("WARN", f"블록 #{block_index}: flowchart에 화살표(-->)가 없음"))

    # stateDiagram: check for initial state
    if diagram_type in ("stateDiagram-v2", "stateDiagram"):
        has_initial = any("[*]" in line for line in lines)
        if not has_initial:
            issues.append(("WARN", f"블록 #{block_index}: stateDiagram에 초기 상태([*])가 없음"))

    # sequenceDiagram: check for participants or actors
    if diagram_type == "sequenceDiagram":
        has_interaction = any(
            re.search(r"->|->>|-->>|-->", line) for line in lines[1:]
        )
        if not has_interaction and len(lines) > 2:
            issues.append(("WARN", f"블록 #{block_index}: sequenceDiagram에 상호작용(->)이 없음"))

    # Check for unquoted special characters in node names
    for i, line in enumerate(lines[1:], 2):
        # Match node definitions like A[text] or A{text}
        node_match = re.findall(r'(\w+)\[([^\]"]+)\]', line)
        for node_id, node_text in node_match:
            if re.search(r'[(){}|]', node_text):
                issues.append(("WARN", f"블록 #{block_index} L{i}: 노드 텍스트에 특수문자 → 큰따옴표 감싸기 필요: {node_text[:30]}"))

    return issues


def validate_file(filepath):
    """Validate all Mermaid blocks in a file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return [(filepath, [("ERROR", f"파일 읽기 실패: {e}")])]

    blocks = extract_mermaid_blocks(content)
    if not blocks:
        return [(filepath, [("INFO", "Mermaid 블록 없음")])]

    all_issues = []
    for i, block in enumerate(blocks, 1):
        issues = validate_block(block, i, filepath)
        if issues:
            all_issues.extend(issues)

    return [(filepath, all_issues if all_issues else [("PASS", f"{len(blocks)}개 블록 검증 통과")])]


def main():
    if len(sys.argv) < 2:
        print("Usage: python mermaid-validate.py <file_or_directory>")
        sys.exit(1)

    target = sys.argv[1]
    results = []

    if os.path.isfile(target):
        results = validate_file(target)
    elif os.path.isdir(target):
        md_files = sorted(glob.glob(os.path.join(target, "**/*.md"), recursive=True))
        if not md_files:
            print(f"No .md files found in {target}")
            sys.exit(0)
        for f in md_files:
            results.extend(validate_file(f))
    else:
        print(f"Not found: {target}")
        sys.exit(1)

    # Print results
    total_errors = 0
    total_warnings = 0
    total_pass = 0

    for filepath, issues in results:
        rel = os.path.basename(filepath)
        for severity, msg in issues:
            if severity == "ERROR":
                total_errors += 1
                print(f"  ERROR  {rel}: {msg}")
            elif severity == "WARN":
                total_warnings += 1
                print(f"  WARN   {rel}: {msg}")
            elif severity == "PASS":
                total_pass += 1
                print(f"  PASS   {rel}: {msg}")
            # INFO is silent

    print(f"\n결과: PASS={total_pass}, WARN={total_warnings}, ERROR={total_errors}")

    if total_errors > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
