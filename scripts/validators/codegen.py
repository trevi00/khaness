#!/usr/bin/env python3
"""validators/codegen.py - 구현 코드 <-> 설계 정합 검증. CWD = 프로젝트 루트."""
import sys, os, re, glob

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def main():
    cwd = os.getcwd()
    findings = []
    passes = []

    src_main_java = os.path.join(cwd, "src", "main", "java")

    # --- Java 소스 파일 존재 여부 ---
    if not os.path.isdir(src_main_java):
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    all_java = glob.glob(
        os.path.join(src_main_java, "**", "*.java"), recursive=True
    )
    if not all_java:
        print("[PASS] 검증 대상 파일 없음 (skip)")
        return

    passes.append(f"Java 소스 파일 {len(all_java)}개 발견")

    # --- Controller 파일 ---
    controllers = [f for f in all_java if f.endswith("Controller.java")]
    if controllers:
        passes.append(f"Controller 파일 {len(controllers)}개 존재")
    else:
        findings.append("Controller 파일 없음 (*Controller.java)")

    # --- Service 파일 ---
    services = [f for f in all_java if f.endswith("Service.java")]
    if services:
        passes.append(f"Service 파일 {len(services)}개 존재")
    else:
        findings.append("Service 파일 없음 (*Service.java)")

    # --- Mapper/DAO/Repository 파일 ---
    mappers = [
        f for f in all_java
        if f.endswith("Mapper.java")
        or f.endswith("DAO.java")
        or f.endswith("Repository.java")
    ]
    if mappers:
        passes.append(f"Mapper/DAO/Repository 파일 {len(mappers)}개 존재")
    else:
        findings.append("Mapper/DAO/Repository 파일 없음")

    # --- Controller -> Service 체인 검증 ---
    # 모든 Service 파일명(클래스명) 수집
    service_names = set()
    for s in services:
        basename = os.path.basename(s).replace(".java", "")
        service_names.add(basename)

    for ctrl_path in controllers:
        ctrl_name = os.path.basename(ctrl_path).replace(".java", "")
        ctrl_rel = os.path.relpath(ctrl_path, cwd)

        with open(ctrl_path, encoding="utf-8") as fp:
            ctrl_content = fp.read()

        # private final XxxService 패턴으로 주입된 서비스 추출
        injected = re.findall(r"private\s+final\s+(\w+Service)\b", ctrl_content)
        if not injected:
            # @Autowired 또는 생성자 주입도 탐색
            injected = re.findall(r"@Autowired\s+.*?(\w+Service)\b", ctrl_content)
        if not injected:
            # 생성자 파라미터에서 탐색
            injected = re.findall(r"\(\s*(?:final\s+)?(\w+Service)\s+\w+", ctrl_content)

        if injected:
            for svc in set(injected):
                if svc in service_names:
                    passes.append(f"{ctrl_name} -> {svc} 체인 확인")
                else:
                    findings.append(
                        f"{ctrl_name} -> {svc} 주입됨, 그러나 {svc}.java 파일 없음"
                    )
        else:
            # Service 미주입은 경고가 아닌 정보 수준
            passes.append(f"{ctrl_name} — Service 주입 패턴 미발견 (info)")

    # --- MyBatis Mapper XML 검증 ---
    mapper_xml_dir = os.path.join(cwd, "src", "main", "resources", "mapper")
    mapper_xmls = glob.glob(
        os.path.join(mapper_xml_dir, "**", "*.xml"), recursive=True
    ) if os.path.isdir(mapper_xml_dir) else []

    # Mapper 인터페이스 FQCN 수집
    mapper_fqcns = {}
    for m in mappers:
        basename = os.path.basename(m).replace(".java", "")
        with open(m, encoding="utf-8") as fp:
            m_content = fp.read()
        pkg_match = re.search(r"^package\s+([\w.]+)\s*;", m_content, re.MULTILINE)
        if pkg_match:
            fqcn = f"{pkg_match.group(1)}.{basename}"
            mapper_fqcns[basename] = fqcn

    if mapper_xmls:
        passes.append(f"Mapper XML 파일 {len(mapper_xmls)}개 존재")

        for xml_path in mapper_xmls:
            xml_rel = os.path.relpath(xml_path, cwd)
            with open(xml_path, encoding="utf-8") as fp:
                xml_content = fp.read()

            ns_match = re.search(r'namespace\s*=\s*"([^"]+)"', xml_content)
            if ns_match:
                ns = ns_match.group(1)
                # namespace가 Mapper 인터페이스 FQCN과 매칭되는지
                ns_simple = ns.split(".")[-1]
                if ns_simple in mapper_fqcns:
                    if mapper_fqcns[ns_simple] == ns:
                        passes.append(f"{xml_rel} namespace -> {ns_simple} 매칭 OK")
                    else:
                        findings.append(
                            f"{xml_rel} namespace '{ns}' != "
                            f"Mapper FQCN '{mapper_fqcns[ns_simple]}'"
                        )
                else:
                    findings.append(
                        f"{xml_rel} namespace '{ns}' — "
                        f"대응하는 Mapper 인터페이스({ns_simple}.java) 없음"
                    )
            else:
                findings.append(f"{xml_rel} — namespace 속성 없음")

    elif mappers and any(f.endswith("Mapper.java") for f in mappers):
        # Mapper 인터페이스는 있는데 XML이 없으면 MyBatis 프로젝트 가능성
        # build.gradle에서 mybatis 확인
        gradle_path = os.path.join(cwd, "build.gradle")
        if not os.path.isfile(gradle_path):
            gradle_path = os.path.join(cwd, "build.gradle.kts")
        pom_path = os.path.join(cwd, "pom.xml")

        is_mybatis = False
        for bp in [gradle_path, pom_path]:
            if os.path.isfile(bp):
                with open(bp, encoding="utf-8") as fp:
                    if "mybatis" in fp.read().lower():
                        is_mybatis = True
                        break

        if is_mybatis:
            findings.append(
                "MyBatis 프로젝트이나 src/main/resources/mapper/*.xml 없음"
            )

    # --- api-spec.md 대비 Controller 메서드 수 비교 (경고) ---
    api_spec_candidates = [
        os.path.join(cwd, ".claude", "design", "api-spec.md"),
        os.path.join(cwd, ".claude", "design", "api", "openapi.yaml"),
        os.path.join(cwd, ".claude", "design", "openapi.yaml"),
    ]

    api_spec_path = None
    for ap in api_spec_candidates:
        if os.path.isfile(ap):
            api_spec_path = ap
            break

    if api_spec_path:
        with open(api_spec_path, encoding="utf-8") as fp:
            spec_content = fp.read()

        ext = os.path.splitext(api_spec_path)[1].lower()
        if ext == ".md":
            spec_endpoints = len(
                re.findall(r"\b(?:GET|POST|PUT|DELETE|PATCH)\s+/\S+", spec_content)
            )
        else:
            spec_endpoints = len(
                re.findall(r"^\s{2,4}(/\S+)\s*:", spec_content, re.MULTILINE)
            )

        # Controller 메서드 수 카운트
        ctrl_methods = 0
        mapping_pattern = re.compile(
            r"@(?:Get|Post|Put|Delete|Patch|Request)Mapping"
        )
        for ctrl_path in controllers:
            with open(ctrl_path, encoding="utf-8") as fp:
                ctrl_content = fp.read()
            ctrl_methods += len(mapping_pattern.findall(ctrl_content))

        if spec_endpoints > 0:
            ratio = ctrl_methods / spec_endpoints if spec_endpoints else 0
            if ratio < 0.5 and ctrl_methods < spec_endpoints:
                findings.append(
                    f"API 명세 엔드포인트 {spec_endpoints}개 대비 "
                    f"Controller 메서드 {ctrl_methods}개 — 구현 부족 가능성 (경고)"
                )
            else:
                passes.append(
                    f"API 명세 {spec_endpoints}개, Controller 메서드 {ctrl_methods}개 — 비율 적절"
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
