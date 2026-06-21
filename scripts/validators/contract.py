#!/usr/bin/env python3
"""validators/contract.py - FE-BE 계약 정합 검증. CWD = 프로젝트 루트."""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def find_fe_api_urls(fe_root):
    """FE api.ts / *Api.ts 파일에서 /api/ 패턴 URL 추출."""
    urls = set()
    patterns = [
        os.path.join(fe_root, "**", "api.ts"),
        os.path.join(fe_root, "**", "*Api.ts"),
        os.path.join(fe_root, "**", "api.js"),
        os.path.join(fe_root, "**", "*Api.js"),
    ]
    files_found = []
    for pat in patterns:
        files_found.extend(glob.glob(pat, recursive=True))

    # /api/... 패턴 추출 (따옴표 안의 URL)
    url_re = re.compile(r"""['"`](/api/[a-zA-Z0-9/_\-${}]+)['"`]""")
    # 템플릿 리터럴 ${...} 를 와일드카드로 치환
    tmpl_re = re.compile(r"\$\{[^}]+\}")

    for f in files_found:
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    for m in url_re.finditer(line):
                        raw = m.group(1)
                        # 템플릿 변수를 * 로 치환
                        normalized = tmpl_re.sub("*", raw)
                        urls.add(normalized)
        except OSError:
            pass
    return urls, files_found


def find_be_controller_urls(cwd):
    """BE Controller 파일에서 @XxxMapping URL 추출."""
    urls = set()
    controller_files = glob.glob(
        os.path.join(cwd, "src", "main", "java", "**", "*Controller.java"),
        recursive=True,
    )

    # 클래스 레벨 @RequestMapping
    class_mapping_re = re.compile(
        r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']'
    )
    # 메서드 레벨 매핑
    method_mapping_re = re.compile(
        r"@(?:Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']+)[\"']"
    )
    # 파라미터 없는 매핑 (클래스 레벨만)
    bare_mapping_re = re.compile(
        r'@RequestMapping\s*\(\s*["\']([^"\']+)["\']'
    )

    for f in controller_files:
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                content = fh.read()

            # 클래스 레벨 prefix
            prefix = ""
            cm = class_mapping_re.search(content)
            if cm:
                prefix = cm.group(1).rstrip("/")

            # 메서드 레벨 URL
            for mm in method_mapping_re.finditer(content):
                path = mm.group(1)
                if not path.startswith("/"):
                    path = "/" + path
                full = prefix + path if not path.startswith(prefix) else path
                urls.add(full)

            # prefix만 있고 메서드 매핑이 없는 경우
            if prefix and not method_mapping_re.search(content):
                urls.add(prefix)

        except OSError:
            pass

    return urls, controller_files


def normalize_url(url):
    """URL을 비교 가능한 패턴으로 정규화. 경로 변수를 * 로."""
    # Spring {param} -> *
    normalized = re.sub(r"\{[^}]+\}", "*", url)
    # 후행 슬래시 제거
    normalized = normalized.rstrip("/")
    return normalized


def url_pattern_match(fe_url, be_urls_normalized):
    """FE URL이 BE URL 중 하나와 매칭되는지."""
    fe_norm = normalize_url(fe_url)
    for be_url in be_urls_normalized:
        if fe_norm == be_url:
            return True
        # 와일드카드 매칭: * 을 [^/]+ 로 변환
        pattern = "^" + re.escape(be_url).replace(r"\*", "[^/]+") + "$"
        if re.match(pattern, fe_norm):
            return True
        # 반대도
        pattern2 = "^" + re.escape(fe_norm).replace(r"\*", "[^/]+") + "$"
        if re.match(pattern2, be_url):
            return True
    return False


def main():
    cwd = os.getcwd()
    findings = []
    passes = []

    # FE 존재 여부
    fe_root = None
    if os.path.isdir(os.path.join(cwd, "frontend", "src")):
        fe_root = os.path.join(cwd, "frontend", "src")
    elif os.path.isdir(os.path.join(cwd, "src", "main", "resources", "static")):
        fe_root = os.path.join(cwd, "src", "main", "resources", "static")

    # BE Controller 존재 여부
    be_controllers = glob.glob(
        os.path.join(cwd, "src", "main", "java", "**", "*Controller.java"),
        recursive=True,
    )
    has_be = len(be_controllers) > 0

    if not fe_root and not has_be:
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    # === FE + BE 계약 검증 ===
    if fe_root and has_be:
        fe_urls, fe_files = find_fe_api_urls(fe_root)
        be_urls, be_files = find_be_controller_urls(cwd)

        if not fe_files:
            passes.append("FE api 파일 없음 (skip)")
        elif not fe_urls:
            passes.append(f"FE api 파일 {len(fe_files)}개 발견, API URL 패턴 없음")
        else:
            be_normalized = {normalize_url(u) for u in be_urls}

            unmatched_fe = []
            matched_count = 0
            for fe_url in sorted(fe_urls):
                if url_pattern_match(fe_url, be_normalized):
                    matched_count += 1
                else:
                    unmatched_fe.append(fe_url)

            if matched_count > 0:
                passes.append(f"FE-BE URL 매칭: {matched_count}개 일치")

            for url in unmatched_fe:
                findings.append(f"FE URL '{url}' -> BE Controller에서 대응 엔드포인트 없음")

            # BE에만 있는 URL (info)
            fe_normalized = {normalize_url(u) for u in fe_urls}
            be_only = []
            for be_url in sorted(be_urls):
                be_norm = normalize_url(be_url)
                matched = False
                for fu in fe_normalized:
                    if fu == be_norm:
                        matched = True
                        break
                    pat = "^" + re.escape(fu).replace(r"\*", "[^/]+") + "$"
                    if re.match(pat, be_norm):
                        matched = True
                        break
                if not matched:
                    be_only.append(be_url)

            if be_only and len(be_only) <= 10:
                passes.append(
                    f"BE 전용 엔드포인트 {len(be_only)}개 (FE 미사용): "
                    + ", ".join(be_only[:5])
                )

    # === BE Only: convention 검증 ===
    elif has_be and not fe_root:
        be_urls, be_files = find_be_controller_urls(cwd)

        if be_urls:
            passes.append(f"BE Controller {len(be_files)}개, 엔드포인트 {len(be_urls)}개 발견")

            # /api/ 접두사 체크
            no_api_prefix = [u for u in be_urls if not u.startswith("/api/") and not u.startswith("/api")]
            if no_api_prefix:
                for url in sorted(no_api_prefix)[:5]:
                    findings.append(f"'/api/' 접두사 미사용: {url}")
                if len(no_api_prefix) > 5:
                    findings.append(f"  ... 외 {len(no_api_prefix) - 5}개")
            else:
                passes.append("모든 엔드포인트가 /api/ 접두사 사용")

            # convention.md 확인
            conv_paths = [
                os.path.join(cwd, "convention.md"),
                os.path.join(cwd, "CONVENTION.md"),
                os.path.join(cwd, ".planning", "convention.md"),
                os.path.join(cwd, "docs", "convention.md"),
            ]
            conv_file = None
            for cp in conv_paths:
                if os.path.isfile(cp):
                    conv_file = cp
                    break

            if conv_file:
                passes.append(f"convention 파일 발견: {os.path.relpath(conv_file, cwd)}")
            else:
                passes.append("convention.md 없음 (URL 규칙 비교 skip)")
        else:
            passes.append(f"BE Controller {len(be_files)}개 발견, 매핑 URL 추출 없음")

    # === FE Only ===
    elif fe_root and not has_be:
        fe_urls, fe_files = find_fe_api_urls(fe_root)
        if fe_urls:
            passes.append(f"FE 전용 프로젝트: API URL {len(fe_urls)}개 발견 (BE 없어 정합 검증 skip)")
        else:
            passes.append("FE 전용 프로젝트: API URL 없음 (skip)")

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")


if __name__ == "__main__":
    main()
