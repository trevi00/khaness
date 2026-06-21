#!/usr/bin/env python3
"""validators/collab.py - 협업 인프라 검증 스크립트
Called by post-tool-reviewer.py Verification DAG.
CWD = 프로젝트 루트 (subprocess에서 cwd로 전달됨)
"""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def main():
    cwd = os.getcwd()
    github_dir = os.path.join(cwd, ".github")

    findings = []
    passes = []

    # 1. .github/ 디렉토리 존재 여부
    if not os.path.isdir(github_dir):
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    passes.append(".github/ 디렉토리 존재")

    # 2. .github/workflows/ 아래 최소 1개의 yml 파일 존재
    workflows_dir = os.path.join(github_dir, "workflows")
    if os.path.isdir(workflows_dir):
        yml_files = glob.glob(os.path.join(workflows_dir, "*.yml"))
        yml_files += glob.glob(os.path.join(workflows_dir, "*.yaml"))
        if yml_files:
            passes.append(f"workflows/ 에 {len(yml_files)}개 워크플로우 파일 존재")
        else:
            findings.append("workflows/ 디렉토리는 있지만 .yml/.yaml 파일이 없습니다")
    else:
        findings.append(".github/workflows/ 디렉토리가 없습니다")

    # 3. PULL_REQUEST_TEMPLATE.md 존재 여부 (경고)
    pr_template = os.path.join(github_dir, "PULL_REQUEST_TEMPLATE.md")
    if os.path.isfile(pr_template):
        passes.append("PULL_REQUEST_TEMPLATE.md 존재")
    else:
        print("[WARN] .github/PULL_REQUEST_TEMPLATE.md가 없습니다 (권장 사항)")

    # 4. CODEOWNERS 존재 여부 (경고)
    codeowners = os.path.join(github_dir, "CODEOWNERS")
    if os.path.isfile(codeowners):
        passes.append("CODEOWNERS 존재")
    else:
        print("[WARN] .github/CODEOWNERS가 없습니다 (권장 사항)")

    # 5. CONTRIBUTING.md 존재 여부 (경고)
    contributing = os.path.join(cwd, "CONTRIBUTING.md")
    if os.path.isfile(contributing):
        passes.append("CONTRIBUTING.md 존재")
    else:
        print("[WARN] CONTRIBUTING.md가 없습니다 (권장 사항)")

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")

    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")

if __name__ == "__main__":
    main()
