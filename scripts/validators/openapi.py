#!/usr/bin/env python3
"""validators/openapi.py - OpenAPI/API 명세 정합성 검증. CWD = 프로젝트 루트."""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def main():
    cwd = os.getcwd()
    findings = []
    passes = []

    # --- 산출물 후보 경로 ---
    candidates = [
        os.path.join(cwd, ".claude", "design", "api", "openapi.yaml"),
        os.path.join(cwd, ".claude", "design", "api-spec.md"),
        os.path.join(cwd, ".claude", "design", "openapi.yaml"),
    ]

    found_files = [f for f in candidates if os.path.isfile(f)]

    if not found_files:
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    for fpath in found_files:
        rel = os.path.relpath(fpath, cwd)
        ext = os.path.splitext(fpath)[1].lower()

        with open(fpath, encoding="utf-8") as fp:
            content = fp.read()

        if ext in (".yaml", ".yml"):
            # YAML: paths: 섹션 존재
            if re.search(r"^paths\s*:", content, re.MULTILINE):
                passes.append(f"{rel} — 'paths:' 섹션 존재")
            else:
                findings.append(f"{rel} — 'paths:' 섹션 누락")

            # 엔드포인트 수 카운트 (paths 아래 /로 시작하는 경로)
            endpoints = re.findall(r"^\s{2,4}(/\S+)\s*:", content, re.MULTILINE)
            if endpoints:
                passes.append(f"{rel} — 엔드포인트 {len(endpoints)}개 정의됨")
            else:
                findings.append(f"{rel} — 엔드포인트 정의 없음 (paths 아래 경로 0개)")

        elif ext == ".md":
            # MD: HTTP 메서드 키워드 존재
            methods_found = re.findall(
                r"\b(GET|POST|PUT|DELETE|PATCH)\b", content
            )
            unique_methods = set(methods_found)
            if unique_methods:
                passes.append(
                    f"{rel} — HTTP 메서드 키워드 발견: {', '.join(sorted(unique_methods))}"
                )
            else:
                findings.append(f"{rel} — HTTP 메서드 키워드(GET/POST/PUT/DELETE) 없음")

            # 엔드포인트 수 추정 (메서드 + 경로 패턴)
            ep_patterns = re.findall(
                r"\b(?:GET|POST|PUT|DELETE|PATCH)\s+(/\S+)", content
            )
            if ep_patterns:
                passes.append(f"{rel} — 엔드포인트 약 {len(ep_patterns)}개 정의됨")

    # --- 도메인 파일 대비 엔드포인트 수 비교 (경고) ---
    domain_dir = os.path.join(cwd, ".claude", "design", "requirements", "domain")
    if not os.path.isdir(domain_dir):
        domain_dir = os.path.join(cwd, ".claude", "requirements", "domain")

    if os.path.isdir(domain_dir):
        domain_files = glob.glob(os.path.join(domain_dir, "*.md"))
        domain_count = len(domain_files)
        if domain_count > 0:
            # 전체 엔드포인트 수 재계산
            total_endpoints = 0
            for fpath in found_files:
                with open(fpath, encoding="utf-8") as fp:
                    content = fp.read()
                ext = os.path.splitext(fpath)[1].lower()
                if ext in (".yaml", ".yml"):
                    total_endpoints += len(
                        re.findall(r"^\s{2,4}(/\S+)\s*:", content, re.MULTILINE)
                    )
                elif ext == ".md":
                    total_endpoints += len(
                        re.findall(
                            r"\b(?:GET|POST|PUT|DELETE|PATCH)\s+(/\S+)", content
                        )
                    )

            if total_endpoints < domain_count:
                findings.append(
                    f"도메인 {domain_count}개 대비 엔드포인트 {total_endpoints}개 — "
                    f"도메인당 최소 1개 엔드포인트 권장 (경고)"
                )
            else:
                passes.append(
                    f"도메인 {domain_count}개, 엔드포인트 {total_endpoints}개 — 비율 적절"
                )

    # --- 결과 출력 ---
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")


if __name__ == "__main__":
    main()
