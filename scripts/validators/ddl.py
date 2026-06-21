#!/usr/bin/env python3
"""validators/ddl.py - DDL ↔ 논리 설계 정합 검증 스크립트. CWD = 프로젝트 루트."""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def find_sql_files(cwd):
    """여러 가능한 위치에서 SQL 파일 탐색."""
    patterns = [
        os.path.join(cwd, "docs", "schema.sql"),
        os.path.join(cwd, "docs", "*.sql"),
        os.path.join(cwd, "etc", "sql", "schema.sql"),
        os.path.join(cwd, "etc", "sql", "*.sql"),
        os.path.join(cwd, "init", "*.sql"),
        os.path.join(cwd, ".claude", "design", "db", "*.sql"),
        os.path.join(cwd, ".claude", "design", "*.sql"),
        os.path.join(cwd, "sql", "*.sql"),
        os.path.join(cwd, "db", "*.sql"),
        os.path.join(cwd, "src", "main", "resources", "schema.sql"),
        os.path.join(cwd, "src", "main", "resources", "*.sql"),
    ]
    files = set()
    for pattern in patterns:
        for f in glob.glob(pattern):
            if os.path.isfile(f):
                files.add(os.path.normpath(f))
    return sorted(files)


def find_logical_file(cwd):
    """logical-design.md 탐색."""
    candidates = [
        os.path.join(cwd, ".claude", "design", "er", "logical-design.md"),
        os.path.join(cwd, ".claude", "design", "logical-design.md"),
        os.path.join(cwd, ".claude", "design", "db", "logical-design.md"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def extract_ddl_tables(content):
    """DDL에서 CREATE TABLE 테이블명 추출."""
    tables = []
    for m in re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?",
        content,
        re.IGNORECASE,
    ):
        tables.append(m.group(1).lower())
    return tables


def extract_logical_tables(content):
    """logical-design.md에서 테이블명 추출."""
    tables = []
    for m in re.finditer(r"^#{2,3}\s+(.+)", content, re.MULTILINE):
        name = m.group(1).strip()
        lower = name.lower()
        if lower in ("관계", "관계 정의", "relationships", "인덱스", "index", "개요", "overview",
                      "테이블 목록", "table list", "fk 관계", "외래키", "인덱스 전략"):
            continue
        table_name = re.split(r"[\s(（]", name)[0].strip("`").lower()
        if table_name:
            tables.append(table_name)
    return tables


def check_table_has_pk(table_block):
    """테이블 정의 블록에 PRIMARY KEY가 있는지 확인."""
    return bool(re.search(r"PRIMARY\s+KEY", table_block, re.IGNORECASE))


def extract_table_blocks(content):
    """CREATE TABLE 블록을 테이블명과 함께 추출."""
    blocks = {}
    # CREATE TABLE ... ; 또는 CREATE TABLE ... ) 까지 매칭
    for m in re.finditer(
        r"(CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s*\([^;]*;)",
        content,
        re.IGNORECASE | re.DOTALL,
    ):
        table_name = m.group(2).lower()
        blocks[table_name] = m.group(1)
    return blocks


def main():
    cwd = os.getcwd()
    findings = []
    passes = []

    sql_files = find_sql_files(cwd)

    if not sql_files:
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    passes.append(f"SQL 파일 {len(sql_files)}개 발견: {', '.join(os.path.relpath(f, cwd) for f in sql_files)}")

    # 모든 SQL 파일 내용 합치기
    all_content = ""
    for sql_file in sql_files:
        with open(sql_file, "r", encoding="utf-8") as f:
            all_content += f.read() + "\n"

    # 1) CREATE TABLE 문 존재 확인
    ddl_tables = extract_ddl_tables(all_content)
    if ddl_tables:
        passes.append(f"CREATE TABLE 문 {len(ddl_tables)}개 존재: {', '.join(ddl_tables)}")
    else:
        findings.append("CREATE TABLE 문을 찾을 수 없음")
        # CREATE TABLE이 없으면 나머지 검증 의미 없음
        for p in passes:
            print(f"[PASS] {p}")
        for f in findings:
            print(f"[FAIL] {f}")
        return

    # 2) logical-design.md 크로스 체크
    logical_path = find_logical_file(cwd)
    if logical_path:
        with open(logical_path, "r", encoding="utf-8") as f:
            logical_content = f.read()

        logical_tables = extract_logical_tables(logical_content)
        if logical_tables:
            ddl_table_set = set(ddl_tables)
            missing_in_ddl = [t for t in logical_tables if t not in ddl_table_set]
            if missing_in_ddl:
                findings.append(
                    f"logical-design에 있으나 DDL에 없는 테이블: {', '.join(missing_in_ddl)}"
                )
            else:
                passes.append("logical-design의 모든 테이블이 DDL에 존재")

            # 역방향 체크 (DDL에만 있는 테이블 — 경고 수준)
            logical_table_set = set(logical_tables)
            extra_in_ddl = [t for t in ddl_tables if t not in logical_table_set]
            if extra_in_ddl:
                print(f"[WARN] DDL에 있으나 logical-design에 없는 테이블: {', '.join(extra_in_ddl)}")
    else:
        print("[WARN] logical-design.md 미발견 — 크로스 체크 생략")

    # 3) 각 테이블에 PRIMARY KEY 확인
    table_blocks = extract_table_blocks(all_content)
    tables_without_pk = []
    for table_name, block in table_blocks.items():
        if not check_table_has_pk(block):
            tables_without_pk.append(table_name)

    if tables_without_pk:
        findings.append(f"PRIMARY KEY 미정의 테이블: {', '.join(tables_without_pk)}")
    else:
        passes.append("모든 테이블에 PRIMARY KEY 정의됨")

    # 4) 스토리지 엔진 명시 확인 (MySQL)
    has_engine = bool(re.search(r"ENGINE\s*=\s*\w+", all_content, re.IGNORECASE))
    if has_engine:
        passes.append("스토리지 엔진 명시 존재 (ENGINE=...)")
    else:
        findings.append("스토리지 엔진(ENGINE=InnoDB 등)이 명시되지 않음 (MySQL 프로젝트 권장)")

    # 5) DEFAULT CHARSET 확인
    has_charset = bool(
        re.search(r"DEFAULT\s+CHARSET|CHARACTER\s+SET|CHARSET\s*=", all_content, re.IGNORECASE)
    )
    if has_charset:
        passes.append("DEFAULT CHARSET 설정 존재")
    else:
        findings.append("DEFAULT CHARSET 설정이 없음 (문자셋 명시 권장)")

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")


if __name__ == "__main__":
    main()
