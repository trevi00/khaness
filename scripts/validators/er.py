#!/usr/bin/env python3
"""validators/er.py - 개념적 ERD 검증 스크립트. CWD = 프로젝트 루트."""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def find_er_file(cwd):
    """여러 가능한 위치에서 conceptual-er.md 탐색."""
    candidates = [
        os.path.join(cwd, ".claude", "design", "er", "conceptual-er.md"),
        os.path.join(cwd, ".claude", "design", "conceptual-erd.md"),
        os.path.join(cwd, ".claude", "design", "db", "conceptual-er.md"),
        os.path.join(cwd, ".claude", "design", "conceptual-er.md"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def find_convention_file(cwd):
    """convention.md 탐색."""
    candidates = [
        os.path.join(cwd, ".claude", "design", "convention.md"),
        os.path.join(cwd, ".claude", "convention.md"),
        os.path.join(cwd, "convention.md"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def extract_entity_names(content):
    """ERD에서 엔티티명 추출 (## / ### 헤딩)."""
    names = []
    for m in re.finditer(r"^#{2,3}\s+(.+)", content, re.MULTILINE):
        name = m.group(1).strip()
        # 메타 헤딩 제외
        if name.lower() in ("관계", "관계 정의", "relationships", "엔티티", "entities", "개요", "overview"):
            continue
        names.append(name)
    return names


def check_snake_case(name):
    """snake_case 여부 체크."""
    return bool(re.match(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", name))


def main():
    cwd = os.getcwd()
    findings = []
    passes = []

    er_path = find_er_file(cwd)

    if not er_path:
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    passes.append(f"conceptual-er 파일 존재: {os.path.relpath(er_path, cwd)}")

    with open(er_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1) 엔티티 정의 확인
    has_headings = bool(re.search(r"^#{2,3}\s+", content, re.MULTILINE))
    has_entity_keyword = "엔티티" in content or "entity" in content.lower()
    if has_headings or has_entity_keyword:
        passes.append("엔티티 정의 존재")
    else:
        findings.append("엔티티 정의를 찾을 수 없음 (## / ### 헤딩 또는 '엔티티' 키워드 필요)")

    # 2) 관계 표현 확인
    relation_patterns = [
        r"1\s*:\s*1", r"1\s*:\s*N", r"N\s*:\s*M", r"M\s*:\s*N",
        r"1\s*:\s*n", r"n\s*:\s*m", r"m\s*:\s*n",
        "일대일", "일대다", "다대다", "다대일",
        "one-to-one", "one-to-many", "many-to-many",
    ]
    has_relation = any(re.search(p, content, re.IGNORECASE) for p in relation_patterns)
    if has_relation:
        passes.append("관계 표현 존재 (1:1, 1:N, N:M 등)")
    else:
        findings.append("관계 표현을 찾을 수 없음 (1:1, 1:N, N:M, 일대다, 다대다 등 필요)")

    # 3) mermaid erDiagram 블록 확인
    if re.search(r"```mermaid[\s\S]*?erDiagram", content):
        passes.append("mermaid erDiagram 블록 존재")

    # 4) convention.md 존재 시 네이밍 일관성 체크
    conv_path = find_convention_file(cwd)
    if conv_path:
        with open(conv_path, "r", encoding="utf-8") as f:
            conv_content = f.read()

        # convention에서 snake_case 네이밍 규칙 확인
        expects_snake = bool(re.search(r"snake[_\s]?case", conv_content, re.IGNORECASE))

        if expects_snake:
            entity_names = extract_entity_names(content)
            non_snake = [n for n in entity_names if not check_snake_case(n)]
            if non_snake and entity_names:
                # 경고 수준
                print(f"[WARN] convention.md에 snake_case 규칙이 있으나 ERD 엔티티명 중 snake_case가 아닌 항목: {', '.join(non_snake)}")
            elif entity_names:
                passes.append("convention.md snake_case 규칙과 ERD 엔티티명 일관성 OK")

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")


if __name__ == "__main__":
    main()
