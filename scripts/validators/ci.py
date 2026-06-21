#!/usr/bin/env python3
"""validators/ci.py - CI 설정 정합성 검증. CWD = 프로젝트 루트."""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def detect_project_type(cwd):
    """프로젝트 타입 감지."""
    types = set()
    if os.path.isfile(os.path.join(cwd, "build.gradle")) or os.path.isfile(
        os.path.join(cwd, "build.gradle.kts")
    ):
        types.add("java-gradle")
    if os.path.isfile(os.path.join(cwd, "pom.xml")):
        types.add("java-maven")
    if os.path.isfile(os.path.join(cwd, "package.json")):
        types.add("node")
    if os.path.isfile(os.path.join(cwd, "requirements.txt")) or os.path.isfile(
        os.path.join(cwd, "pyproject.toml")
    ):
        types.add("python")
    return types


def main():
    cwd = os.getcwd()
    findings: list[str] = []
    warnings: list[str] = []
    passes: list[str] = []

    workflows_dir = os.path.join(cwd, ".github", "workflows")

    # .github/workflows/ 존재 여부
    if not os.path.isdir(workflows_dir):
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    passes.append(".github/workflows/ 디렉토리 존재")

    # === CI 워크플로우 파일 탐색 ===
    yml_files = glob.glob(os.path.join(workflows_dir, "*.yml"))
    yml_files.extend(glob.glob(os.path.join(workflows_dir, "*.yaml")))
    yml_files = sorted(set(yml_files))

    if not yml_files:
        findings.append("workflows/ 디렉토리에 YAML 파일 없음")
        for p in passes:
            print(f"[PASS] {p}")
        for f in findings:
            print(f"[FAIL] {f}")
        return

    passes.append(f"워크플로우 파일 {len(yml_files)}개 발견")

    # CI 트리거 포함 파일 찾기
    ci_files = []
    trigger_re = re.compile(r"on:\s*(?:\[.*?\]|\n\s+(?:push|pull_request))", re.DOTALL)
    push_re = re.compile(r"on:.*?push", re.DOTALL)
    pr_re = re.compile(r"on:.*?pull_request", re.DOTALL)
    simple_trigger_re = re.compile(r"^\s*on:\s*\[?\s*(?:push|pull_request)", re.MULTILINE)

    for yf in yml_files:
        try:
            with open(yf, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            # 간단한 트리거 감지
            has_push = bool(re.search(r"\bpush\b", content))
            has_pr = bool(re.search(r"\bpull_request\b", content))
            if has_push or has_pr:
                ci_files.append((yf, content))
        except OSError:
            pass

    if not ci_files:
        # ci.yml 이름 체크
        ci_yml = os.path.join(workflows_dir, "ci.yml")
        ci_yaml = os.path.join(workflows_dir, "ci.yaml")
        if os.path.isfile(ci_yml) or os.path.isfile(ci_yaml):
            path = ci_yml if os.path.isfile(ci_yml) else ci_yaml
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                ci_files.append((path, content))
                passes.append(f"ci 파일 발견: {os.path.basename(path)}")
            except OSError:
                pass
        if not ci_files:
            findings.append("push/pull_request 트리거가 있는 CI 워크플로우 없음")

    if ci_files:
        passes.append(f"CI 트리거 워크플로우 {len(ci_files)}개 발견")

    # === 프로젝트 타입별 CI 내용 검증 ===
    project_types = detect_project_type(cwd)

    for ci_path, ci_content in ci_files:
        ci_name = os.path.relpath(ci_path, cwd)

        # Java 프로젝트
        if "java-gradle" in project_types or "java-maven" in project_types:
            has_build_tool = bool(
                re.search(r"\b(?:gradlew|gradle|mvn|maven)\b", ci_content)
            )
            if has_build_tool:
                passes.append(f"{ci_name}: Java 빌드 도구 명령어 포함")
            else:
                findings.append(f"{ci_name}: Java 프로젝트인데 gradlew/gradle/mvn 명령어 없음")

        # Node 프로젝트
        if "node" in project_types:
            has_node_tool = bool(
                re.search(r"\b(?:npm|yarn|pnpm)\b", ci_content)
            )
            if has_node_tool:
                passes.append(f"{ci_name}: Node 패키지 매니저 명령어 포함")
            else:
                findings.append(f"{ci_name}: Node 프로젝트인데 npm/yarn/pnpm 명령어 없음")

        # Python 프로젝트
        if "python" in project_types:
            has_python_tool = bool(
                re.search(r"\b(?:pip|poetry|pytest|python)\b", ci_content)
            )
            if has_python_tool:
                passes.append(f"{ci_name}: Python 빌드/테스트 도구 포함")
            else:
                findings.append(f"{ci_name}: Python 프로젝트인데 pip/poetry/pytest 명령어 없음")

        # 테스트 실행 단계
        has_test = bool(re.search(r"\btest\b", ci_content, re.IGNORECASE))
        if has_test:
            passes.append(f"{ci_name}: test 키워드 포함")
        else:
            findings.append(f"{ci_name}: 'test' 키워드 없음 (테스트 실행 단계 누락 가능)")

        # JaCoCo / coverage 연동
        has_coverage = bool(
            re.search(r"\b(?:jacoco|coverage)\b", ci_content, re.IGNORECASE)
        )
        if has_coverage:
            passes.append(f"{ci_name}: 커버리지(jacoco/coverage) 연동 확인됨")
        else:
            warnings.append(f"{ci_name}: jacoco/coverage 키워드 없음 (커버리지 미연동)")

    # === build.gradle 존재 시 java 플러그인 + test 태스크 ===
    for gradle_name in ["build.gradle", "build.gradle.kts"]:
        gradle_path = os.path.join(cwd, gradle_name)
        if os.path.isfile(gradle_path):
            try:
                with open(gradle_path, encoding="utf-8", errors="ignore") as f:
                    gradle_content = f.read()

                has_java_plugin = bool(
                    re.search(
                        r"""(?:apply\s+plugin\s*:\s*['"]java['"]|id\s*\(\s*['"]java['"]|id\s+['"]java['"]|plugin\s*:\s*['"]java)""",
                        gradle_content,
                    )
                )
                # java-library, org.springframework.boot 등도 java 포함
                if not has_java_plugin:
                    has_java_plugin = bool(
                        re.search(
                            r"""(?:java-library|org\.springframework\.boot|kotlin\b)""",
                            gradle_content,
                        )
                    )

                if has_java_plugin:
                    passes.append(f"{gradle_name}: Java/Kotlin 플러그인 확인됨")
                else:
                    warnings.append(f"{gradle_name}: java 관련 플러그인 미발견")

                has_test_task = bool(re.search(r"\btest\b", gradle_content))
                if has_test_task:
                    passes.append(f"{gradle_name}: test 태스크 참조 확인됨")
                else:
                    warnings.append(f"{gradle_name}: test 키워드 없음")

            except OSError:
                pass
            break  # 하나만 검사

    # 결과 출력
    for p in passes:
        print(f"[PASS] {p}")
    for w in warnings:
        print(f"[WARN] {w}")
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings and not warnings and not passes:
        print("[PASS] 검증 대상 파일 없음 (skip)")


if __name__ == "__main__":
    main()
