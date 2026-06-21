#!/usr/bin/env python3
"""validators/test.py - 테스트 커버리지 검증. CWD = 프로젝트 루트."""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def main():
    cwd = os.getcwd()
    findings = []
    passes = []
    warnings = []

    test_dir = os.path.join(cwd, "src", "test")
    main_dir = os.path.join(cwd, "src", "main", "java")

    # src/test/ 존재 여부
    if not os.path.isdir(test_dir):
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    passes.append(f"src/test/ 디렉토리 존재")

    # === 테스트 클래스 수 카운트 ===
    test_patterns = ["**/*Test.java", "**/*Tests.java", "**/*Spec.java"]
    test_files = []
    for pat in test_patterns:
        test_files.extend(glob.glob(os.path.join(test_dir, pat), recursive=True))
    # 중복 제거
    test_files = sorted(set(test_files))
    test_count = len(test_files)

    if test_count > 0:
        passes.append(f"테스트 클래스 {test_count}개 발견")
    else:
        findings.append("src/test/ 존재하나 테스트 클래스 0개 (Test/Tests/Spec.java)")

    # === Service 대비 테스트 커버리지 ===
    if os.path.isdir(main_dir):
        service_files = glob.glob(
            os.path.join(main_dir, "**", "*Service.java"), recursive=True
        )
        # Impl 제외한 순수 Service 인터페이스/클래스
        service_names = set()
        for sf in service_files:
            name = os.path.basename(sf).replace(".java", "")
            service_names.add(name)

        if service_names:
            # 테스트 파일 이름 집합
            test_basenames = {os.path.basename(tf).replace(".java", "") for tf in test_files}

            missing_tests = []
            covered = []
            for svc in sorted(service_names):
                expected_test = svc + "Test"
                expected_tests = svc + "Tests"
                if expected_test in test_basenames or expected_tests in test_basenames:
                    covered.append(svc)
                else:
                    missing_tests.append(svc)

            if covered:
                passes.append(
                    f"Service 테스트 커버리지: {len(covered)}/{len(service_names)} "
                    f"({100 * len(covered) // len(service_names)}%)"
                )

            for svc in missing_tests[:10]:
                warnings.append(f"{svc} -> {svc}Test.java 미존재")
            if len(missing_tests) > 10:
                warnings.append(f"  ... 외 {len(missing_tests) - 10}개 Service 테스트 미존재")
        else:
            passes.append("Service 클래스 없음 (커버리지 비교 skip)")

    # === JaCoCo 설정 확인 ===
    build_gradle = None
    for name in ["build.gradle", "build.gradle.kts"]:
        path = os.path.join(cwd, name)
        if os.path.isfile(path):
            build_gradle = path
            break

    if build_gradle:
        try:
            with open(build_gradle, encoding="utf-8", errors="ignore") as f:
                gradle_content = f.read()

            # jacoco 플러그인
            has_jacoco_plugin = bool(
                re.search(r"""jacoco""", gradle_content)
            )
            if has_jacoco_plugin:
                passes.append("build.gradle에 JaCoCo 플러그인 존재")

                # jacocoTestReport / jacocoTestCoverageVerification
                has_report = bool(
                    re.search(r"jacocoTestReport", gradle_content)
                )
                has_verification = bool(
                    re.search(r"jacocoTestCoverageVerification", gradle_content)
                )
                if has_report:
                    passes.append("jacocoTestReport 태스크 정의됨")
                else:
                    warnings.append(" jacocoTestReport 태스크 미정의")
                if has_verification:
                    passes.append("jacocoTestCoverageVerification 태스크 정의됨")
                else:
                    warnings.append(" jacocoTestCoverageVerification 태스크 미정의")
            else:
                warnings.append(" build.gradle에 JaCoCo 플러그인 없음")
        except OSError:
            pass
    else:
        # Maven pom.xml 체크
        pom_path = os.path.join(cwd, "pom.xml")
        if os.path.isfile(pom_path):
            try:
                with open(pom_path, encoding="utf-8", errors="ignore") as f:
                    pom_content = f.read()
                if "jacoco" in pom_content:
                    passes.append("pom.xml에 JaCoCo 설정 존재")
                else:
                    warnings.append(" pom.xml에 JaCoCo 설정 없음")
            except OSError:
                pass
        else:
            passes.append("빌드 파일 없음 (JaCoCo 검증 skip)")

    # === 테스트 실행 결과 디렉토리 ===
    reports_dir = os.path.join(cwd, "build", "reports", "tests")
    results_dir = os.path.join(cwd, "build", "test-results")

    if os.path.isdir(reports_dir):
        passes.append("build/reports/tests/ 존재 (테스트 리포트 생성됨)")
    elif os.path.isdir(results_dir):
        passes.append("build/test-results/ 존재 (테스트 결과 생성됨)")
    else:
        warnings.append(" 테스트 실행 결과 디렉토리 없음 (build/reports/tests/ 또는 build/test-results/)")

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for w in warnings:
        print(f"[WARN] {w}")
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings and not passes and not warnings:
        print("[PASS] 검증 대상 파일 없음 (skip)")


if __name__ == "__main__":
    main()
