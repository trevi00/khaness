#!/usr/bin/env python3
"""validators/convention.py - 컨벤션 준수 검증 스크립트
Called by post-tool-reviewer.py Verification DAG.
CWD = 프로젝트 루트 (subprocess에서 cwd로 전달됨)
"""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def main():
    cwd = os.getcwd()
    convention_path = os.path.join(cwd, ".claude", "convention.md")

    findings = []
    passes = []

    # 1. convention.md 존재 여부
    if not os.path.isfile(convention_path):
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    passes.append("convention.md 존재")

    with open(convention_path, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.splitlines()

    # 2. 패키지 구조 테이블 존재 여부 ("|" 포함 행이 3개 이상)
    table_rows = [line for line in lines if "|" in line]
    if len(table_rows) >= 3:
        passes.append(f"패키지 구조 테이블 발견 ({len(table_rows)}개 테이블 행)")
    else:
        findings.append("패키지 구조 테이블이 없거나 불완전합니다 ('|' 포함 행 3개 미만)")

    # 3. DTO 네이밍 규칙 언급 여부
    dto_pattern = re.compile(r'(DTO|Request|Response)', re.IGNORECASE)
    if dto_pattern.search(content):
        passes.append("DTO 네이밍 규칙 언급 확인")
    else:
        findings.append("DTO 네이밍 규칙 언급이 없습니다 (DTO, Request, Response 키워드 없음)")

    # 4. 에러 코드 체계 언급 여부
    error_pattern = re.compile(r'(에러|error|ErrorCode)', re.IGNORECASE)
    if error_pattern.search(content):
        passes.append("에러 코드 체계 언급 확인")
    else:
        findings.append("에러 코드 체계 언급이 없습니다 (에러, error, ErrorCode 키워드 없음)")

    # 5. 백엔드 소스에서 패키지 구조 일치 확인
    src_java_dir = os.path.join(cwd, "src", "main", "java")
    if os.path.isdir(src_java_dir):
        # src/main/java/ 아래 모든 디렉토리 수집
        actual_packages = set()
        for root, dirs, files in os.walk(src_java_dir):
            rel_path = os.path.relpath(root, src_java_dir)
            if rel_path != ".":
                # 디렉토리명만 수집 (마지막 부분)
                parts = rel_path.replace(os.sep, "/").split("/")
                for part in parts:
                    actual_packages.add(part.lower())

        if actual_packages:
            # convention.md에서 패키지명 추출 (테이블 행에서)
            # 간단한 부분 매칭: 테이블 행의 각 셀에서 영문 단어 추출
            convention_packages = set()
            for row in table_rows:
                cells = [cell.strip() for cell in row.split("|") if cell.strip()]
                for cell in cells:
                    # 영문 소문자 단어 추출 (패키지명 후보)
                    words = re.findall(r'[a-z][a-z0-9]*', cell.lower())
                    convention_packages.update(words)

            # 실제 패키지와 컨벤션 패키지 매칭
            matched = actual_packages & convention_packages
            unmatched = actual_packages - convention_packages

            if matched:
                passes.append(f"패키지 구조 매칭: {len(matched)}개 일치 ({', '.join(sorted(matched)[:5])}{'...' if len(matched) > 5 else ''})")
            if unmatched and len(unmatched) <= 10:
                print(f"[WARN] convention.md에 미정의된 패키지: {', '.join(sorted(unmatched))}")
        else:
            passes.append("src/main/java/ 존재하나 하위 패키지 없음")
    else:
        passes.append("src/main/java/ 디렉토리 없음 (백엔드 소스 검증 생략)")

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")

    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")

if __name__ == "__main__":
    main()
