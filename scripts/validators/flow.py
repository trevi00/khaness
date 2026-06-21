#!/usr/bin/env python3
"""validators/flow.py - 플로우차트 <-> PRD 크로스 검증 스크립트
Called by post-tool-reviewer.py Verification DAG.
CWD = 프로젝트 루트 (subprocess에서 cwd로 전달됨)
"""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def main():
    cwd = os.getcwd()
    design_dir = os.path.join(cwd, ".claude", "design")
    req_dir = os.path.join(cwd, ".claude", "requirements")
    flows_dir = os.path.join(design_dir, "flows")

    findings = []
    passes = []

    # 검증 대상 디렉토리 존재 여부
    if not os.path.isdir(flows_dir):
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    # 1. flows/ 아래 플로우 파일(.md) 존재 여부
    flow_files = glob.glob(os.path.join(flows_dir, "*.md"))
    if flow_files:
        passes.append(f"flows/ 디렉토리에 {len(flow_files)}개 플로우 파일 존재")
    else:
        findings.append("flows/ 디렉토리는 있지만 .md 파일이 없습니다")

    # 2. 각 플로우 파일에 mermaid 코드 블록이 있는지
    mermaid_pattern = re.compile(r'```(?:mermaid|flowchart)', re.IGNORECASE)
    for ff in flow_files:
        fname = os.path.basename(ff)
        with open(ff, "r", encoding="utf-8") as f:
            content = f.read()
        if mermaid_pattern.search(content):
            passes.append(f"{fname}: mermaid 코드 블록 발견")
        else:
            findings.append(f"{fname}: mermaid 또는 flowchart 코드 블록이 없습니다")

    # 3. US ID 커버리지 체크 (경고 레벨)
    # domain/*.md에서 US ID 추출
    domain_dir = os.path.join(req_dir, "domain")
    us_ids = set()
    if os.path.isdir(domain_dir):
        us_id_pattern = re.compile(r'US-\d+')
        for df in glob.glob(os.path.join(domain_dir, "*.md")):
            with open(df, "r", encoding="utf-8") as f:
                content = f.read()
            found_ids = us_id_pattern.findall(content)
            us_ids.update(found_ids)

    if us_ids:
        # 모든 플로우 파일 내용 합치기
        all_flow_content = ""
        for ff in flow_files:
            with open(ff, "r", encoding="utf-8") as f:
                all_flow_content += f.read() + "\n"

        covered = set()
        uncovered = set()
        for us_id in us_ids:
            if us_id in all_flow_content:
                covered.add(us_id)
            else:
                uncovered.add(us_id)

        if covered:
            passes.append(f"US ID 커버리지: {len(covered)}/{len(us_ids)} 커버됨")
        if uncovered:
            uncovered_list = ", ".join(sorted(uncovered))
            print(f"[WARN] 플로우에서 언급되지 않은 US ID: {uncovered_list}")
    else:
        if os.path.isdir(domain_dir) and glob.glob(os.path.join(domain_dir, "*.md")):
            print("[WARN] 도메인 파일에서 US ID 패턴(US-xxx)을 찾지 못했습니다 (US ID를 사용하지 않는 프로젝트일 수 있음)")

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")

    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")

if __name__ == "__main__":
    main()
