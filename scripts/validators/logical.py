#!/usr/bin/env python3
"""validators/logical.py - 논리적 설계 ↔ ERD 정합 검증 스크립트. CWD = 프로젝트 루트."""
import sys, os, re

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def find_logical_file(cwd):
    """여러 가능한 위치에서 logical-design.md 탐색."""
    candidates = [
        os.path.join(cwd, ".claude", "design", "er", "logical-design.md"),
        os.path.join(cwd, ".claude", "design", "logical-design.md"),
        os.path.join(cwd, ".claude", "design", "db", "logical-design.md"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def find_er_file(cwd):
    """conceptual-er.md 탐색."""
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


def extract_er_entity_count(content):
    """ERD에서 엔티티 수 추출."""
    count = 0
    for m in re.finditer(r"^#{2,3}\s+(.+)", content, re.MULTILINE):
        name = m.group(1).strip().lower()
        if name in ("관계", "관계 정의", "relationships", "엔티티", "entities", "개요", "overview"):
            continue
        count += 1
    return count


def extract_logical_tables(content):
    """logical-design.md에서 테이블명 추출."""
    tables = []
    # ## 뒤의 테이블명 추출
    for m in re.finditer(r"^#{2,3}\s+(.+)", content, re.MULTILINE):
        name = m.group(1).strip()
        # 메타 헤딩 제외
        lower = name.lower()
        if lower in ("관계", "관계 정의", "relationships", "인덱스", "index", "개요", "overview",
                      "테이블 목록", "table list", "fk 관계", "외래키", "인덱스 전략"):
            continue
        # 테이블명만 추출 (괄호 안 설명 제거)
        table_name = re.split(r"[\s(（]", name)[0].strip("`")
        if table_name:
            tables.append(table_name)
    return tables


def main():
    cwd = os.getcwd()
    findings = []
    passes = []

    logical_path = find_logical_file(cwd)

    if not logical_path:
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    passes.append(f"logical-design 파일 존재: {os.path.relpath(logical_path, cwd)}")

    with open(logical_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1) 마크다운 테이블 정의 확인
    table_rows = [line for line in content.split("\n") if "|" in line and line.strip().startswith("|")]
    if table_rows:
        passes.append(f"마크다운 테이블 행 {len(table_rows)}개 존재")
    else:
        findings.append("테이블 정의를 찾을 수 없음 (마크다운 테이블 '|' 행 필요)")

    # 2) PK 명시 확인
    has_pk = bool(re.search(r"\bPK\b|PRIMARY\s*KEY|PRIMARY", content, re.IGNORECASE))
    if has_pk:
        passes.append("PK(Primary Key) 명시 존재")
    else:
        findings.append("PK(Primary Key) 명시를 찾을 수 없음 ('PK' 또는 'PRIMARY' 키워드 필요)")

    # 3) FK 관계 명시 확인
    fk_patterns = [r"\bFK\b", r"FOREIGN\s*KEY", r"FOREIGN", r"→", r"\breferences\b"]
    has_fk = any(re.search(p, content, re.IGNORECASE) for p in fk_patterns)
    if has_fk:
        passes.append("FK(Foreign Key) 관계 명시 존재")
    else:
        findings.append("FK(Foreign Key) 관계 명시를 찾을 수 없음 ('FK', 'FOREIGN', '→', 'references' 필요)")

    # 4) 인덱스 전략 확인
    has_index = bool(re.search(r"\bINDEX\b|인덱스", content, re.IGNORECASE))
    if has_index:
        passes.append("인덱스 전략 언급 존재")
    else:
        findings.append("인덱스 전략 언급을 찾을 수 없음 ('INDEX' 또는 '인덱스' 키워드 필요)")

    # 5) conceptual-er.md와 크로스 체크
    er_path = find_er_file(cwd)
    if er_path:
        with open(er_path, "r", encoding="utf-8") as f:
            er_content = f.read()

        er_entity_count = extract_er_entity_count(er_content)
        logical_tables = extract_logical_tables(content)
        logical_table_count = len(logical_tables)

        if er_entity_count > 0 and logical_table_count > 0:
            if er_entity_count <= logical_table_count:
                passes.append(f"ERD 엔티티({er_entity_count}개) ≤ logical 테이블({logical_table_count}개) — M:N 해소 반영 OK")
            else:
                findings.append(
                    f"ERD 엔티티({er_entity_count}개) > logical 테이블({logical_table_count}개) — "
                    f"일부 엔티티가 logical 설계에 누락되었을 수 있음"
                )
        elif er_entity_count == 0:
            print("[WARN] conceptual-er.md에서 엔티티를 추출할 수 없음 (크로스 체크 생략)")
        elif logical_table_count == 0:
            print("[WARN] logical-design.md에서 테이블을 추출할 수 없음 (크로스 체크 생략)")

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")


if __name__ == "__main__":
    main()
