#!/usr/bin/env python3
"""validators/skeleton.py - 스캐폴딩 <-> 설계 정합 검증. CWD = 프로젝트 루트."""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def main():
    cwd = os.getcwd()
    findings = []
    passes = []

    src_main_java = os.path.join(cwd, "src", "main", "java")

    # --- src/main/java/ 존재 여부 ---
    if not os.path.isdir(src_main_java):
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    passes.append("src/main/java/ 디렉토리 존재")

    # --- build.gradle 또는 pom.xml 존재 여부 ---
    build_gradle = os.path.join(cwd, "build.gradle")
    build_gradle_kts = os.path.join(cwd, "build.gradle.kts")
    pom_xml = os.path.join(cwd, "pom.xml")

    has_gradle = os.path.isfile(build_gradle) or os.path.isfile(build_gradle_kts)
    has_maven = os.path.isfile(pom_xml)

    if has_gradle or has_maven:
        build_file = "build.gradle" if has_gradle else "pom.xml"
        passes.append(f"{build_file} 존재")
    else:
        findings.append("build.gradle / pom.xml 모두 없음")

    # --- build.gradle 상세 검증 ---
    gradle_path = build_gradle if os.path.isfile(build_gradle) else (
        build_gradle_kts if os.path.isfile(build_gradle_kts) else None
    )
    if gradle_path:
        with open(gradle_path, encoding="utf-8") as fp:
            gradle_content = fp.read()

        # spring-boot 의존성
        if re.search(r"spring-boot", gradle_content):
            passes.append("build.gradle — spring-boot 의존성 포함")
        else:
            findings.append("build.gradle — spring-boot 의존성 누락")

        # 테스트 의존성
        if re.search(r"spring-boot-starter-test", gradle_content):
            passes.append("build.gradle — spring-boot-starter-test 의존성 포함")
        else:
            findings.append("build.gradle — spring-boot-starter-test 의존성 누락")

    # --- application.yml / application.properties 존재 여부 ---
    resources_dir = os.path.join(cwd, "src", "main", "resources")
    app_yml = os.path.join(resources_dir, "application.yml")
    app_yaml = os.path.join(resources_dir, "application.yaml")
    app_props = os.path.join(resources_dir, "application.properties")

    if os.path.isfile(app_yml) or os.path.isfile(app_yaml) or os.path.isfile(app_props):
        found_name = (
            "application.yml" if os.path.isfile(app_yml)
            else "application.yaml" if os.path.isfile(app_yaml)
            else "application.properties"
        )
        passes.append(f"src/main/resources/{found_name} 존재")
    else:
        findings.append("src/main/resources/application.yml|properties 없음")

    # --- convention.md 패키지 경로 검증 ---
    convention_candidates = [
        os.path.join(cwd, ".claude", "design", "convention.md"),
        os.path.join(cwd, ".claude", "convention.md"),
        os.path.join(cwd, "convention.md"),
    ]

    convention_path = None
    for cp in convention_candidates:
        if os.path.isfile(cp):
            convention_path = cp
            break

    if convention_path:
        with open(convention_path, encoding="utf-8") as fp:
            conv_content = fp.read()

        # com.xxx.yyy 형태 패키지명 추출
        pkg_matches = re.findall(r"\b(com\.\w+(?:\.\w+)+)\b", conv_content)
        if pkg_matches:
            # 가장 짧은 (루트) 패키지 선택
            root_pkg = min(pkg_matches, key=len)
            pkg_dir = os.path.join(src_main_java, root_pkg.replace(".", os.sep))

            if os.path.isdir(pkg_dir):
                passes.append(
                    f"convention.md 패키지 '{root_pkg}' — "
                    f"src/main/java/{root_pkg.replace('.', '/')} 존재"
                )
            else:
                findings.append(
                    f"convention.md 패키지 '{root_pkg}' — "
                    f"src/main/java/{root_pkg.replace('.', '/')} 디렉토리 없음"
                )
        else:
            passes.append("convention.md — 패키지 경로 패턴 미발견 (skip)")

    # --- 결과 출력 ---
    for p in passes:
        print(f"[PASS] {p}")
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")


if __name__ == "__main__":
    main()
