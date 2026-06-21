#!/usr/bin/env python3
"""validators/prd.py - PRD 내부 정합성 검증 스크립트
Called by post-tool-reviewer.py Verification DAG.
CWD = 프로젝트 루트 (subprocess에서 cwd로 전달됨)
"""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def main():
    cwd = os.getcwd()
    req_dir = os.path.join(cwd, ".claude", "requirements")

    findings = []
    passes = []

    # 검증 대상 디렉토리 존재 여부
    if not os.path.isdir(req_dir):
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    # 1. index.md 존재 여부
    index_path = os.path.join(req_dir, "index.md")
    if os.path.isfile(index_path):
        passes.append("requirements/index.md 존재")
    else:
        findings.append("requirements/index.md 파일이 없습니다")

    # 2. domain/ 디렉토리 아래 도메인 파일 존재 여부
    domain_dir = os.path.join(req_dir, "domain")
    domain_files = []
    if os.path.isdir(domain_dir):
        domain_files = [f for f in glob.glob(os.path.join(domain_dir, "*.md"))
                       if not os.path.basename(f).startswith("_")]
        if domain_files:
            passes.append(f"domain/ 디렉토리에 {len(domain_files)}개 도메인 파일 존재")
        else:
            findings.append("domain/ 디렉토리는 있지만 .md 파일이 없습니다")
    else:
        findings.append("requirements/domain/ 디렉토리가 없습니다")

    # 3. index.md에 나열된 도메인 파일이 실제로 존재하는지 (파일 링크 체크)
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            index_content = f.read()

        # 마크다운 링크 패턴: [텍스트](경로)
        link_pattern = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
        links = link_pattern.findall(index_content)

        if links:
            for link_text, link_path in links:
                # 상대 경로를 절대 경로로 변환
                abs_link = os.path.normpath(os.path.join(req_dir, link_path))
                if os.path.isfile(abs_link):
                    passes.append(f"링크 파일 존재: {link_path}")
                else:
                    findings.append(f"index.md 링크 '{link_path}' → 파일이 존재하지 않습니다")

    # 4. 각 도메인 파일에 "AS ... I WANT ... SO THAT" 패턴의 사용자 스토리가 있는지
    us_pattern = re.compile(r'as\s+.+?\s+i\s+want\s+.+?\s+so\s+that\s+', re.IGNORECASE | re.DOTALL)
    for df in domain_files:
        fname = os.path.basename(df)
        with open(df, "r", encoding="utf-8") as f:
            content = f.read()
        # Strip markdown bold/italic markers for pattern matching
        content = content.replace("**", "").replace("__", "").replace("*", "").replace("_", "")
        if us_pattern.search(content):
            passes.append(f"{fname}: 사용자 스토리 패턴 발견")
        else:
            findings.append(f"{fname}: 'AS ... I WANT ... SO THAT' 사용자 스토리 패턴이 없습니다")

    # 5. glossary.md 존재 여부 (경고)
    glossary_path = os.path.join(req_dir, "glossary.md")
    if os.path.isfile(glossary_path):
        passes.append("glossary.md 존재")
    else:
        print("[WARN] glossary.md가 없습니다 (권장 사항)")

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")

    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")

if __name__ == "__main__":
    main()
