#!/usr/bin/env python3
"""Generator: decompose the existing stages.yaml (+ variants) into a stack-neutral
stages.core.yaml + per-stack overlays (unified-pipeline D2-2/D2-3).

Java is the GOLDEN REFERENCE — the core is derived from stages.yaml, so the java
overlay only needs to restore gate/skills (its name/input/output/artifact already
equal the core). The flutter and rust overlays are produced by DIFFING
stages-flutter.yaml / stages-rust.yaml against the core: only fields that differ
(output paths, artifact text, dropped/added stages) land in the overlay. This
proves the SAME neutral core serves THREE distinct stacks (test_java_golden_pin +
test_flutter_golden_pin + test_rust_golden_pin). Re-run if a source pipeline
changes; the YAML files are the artifact.

    python -m cli.gen_pipeline_core_overlay            # write core + java + flutter + rust
    python -m cli.gen_pipeline_core_overlay --check    # dry-run summary
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.pipeline_overlay import core_path, overlay_path  # noqa: E402
from lib.pipeline_yaml import _pipeline_dir  # noqa: E402

# Tool-free neutral gate_intent overrides for stages whose Java gate is tool-specific.
_NEUTRAL_GATE_INTENT: dict[str, list[str]] = {
    "ddl": ["스키마 산출물이 빌드/생성 성공", "논리설계와 1:1 대응"],
    "ci-setup": ["PR 시 빌드+테스트 자동 실행", "커버리지 리포트 생성", "커버리지 미달 시 실패"],
    "scaffolding": ["빌드/컴파일 성공", "패키지 구조가 컨벤션과 일치", "관찰성(헬스체크) 의존성 포함"],
    "implementation": ["빌드/컴파일 성공", "프론트엔드 빌드 성공(해당 시)", "모든 엔드포인트의 계층 체인 존재"],
    "wiring-verify": ["헬스체크 200 OK", "계층 간 주입 무결성", "핸들러 매핑 존재"],
    "e2e-test": ["모든 AC에 대응하는 호출 PASS", "에러 응답 형식이 컨벤션과 일치"],
    "blackbox-test": ["핵심 플로우 happy path가 UI에서 PASS", "에러 플로우 피드백 확인"],
    "unit-test": ["단위 테스트 0 failures", "커버리지 목표 달성", "각 공개 메서드 정상/예외 케이스"],
    "integration-test": ["핵심 플로우 happy path PASS", "네트워크 실패/타임아웃 시나리오 PASS"],
    "reliability-test": ["프로퍼티 기반 테스트 PASS", "엣지케이스 PASS", "실 DB 통합 테스트 PASS"],
    "monitoring": ["관찰성 엔드포인트 접근 가능", "메트릭 수집 중", "대시보드 시각화"],
    "cd-setup": ["통합 브랜치 머지 시 자동 빌드+배포"],
    "api-docs": ["브라우저에서 API 문서 접근 가능"],
    "batch": ["배치 작업 실행 성공", "처리 결과가 정확히 반영"],
}

# Neutral core fields (gate/skills are stack-specific -> overlay).
_CORE_FIELDS = ("id", "name", "dge", "input", "output", "artifact", "optional")
# Fields the overlay may override per stage (besides always gate+skills).
_OVERRIDABLE = ("name", "dge", "input", "output", "artifact", "optional")


def _load_stages(path: Path) -> list[dict]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw["stages"] if isinstance(raw, dict) else raw


def gen_core(java_stages: list[dict]) -> list[dict]:
    core: list[dict] = []
    for st in java_stages:
        sid = st["id"]
        c: dict = {k: st[k] for k in _CORE_FIELDS if k in st}
        gi = _NEUTRAL_GATE_INTENT.get(sid)
        if gi is None and isinstance(st.get("gate"), list):
            gi = st["gate"]  # already-neutral design-stage gate
        if gi is not None:
            c["gate_intent"] = gi
        if isinstance(st.get("skills"), list):
            c["skills_intent"] = st["skills"]
        core.append(c)
    return core


def gen_overlay(variant_stages: list[dict], core_by_id: dict, *, stack: str,
                source_finder: str, testgen: dict) -> dict:
    overrides: dict[str, dict] = {}
    applicable: list[str] = []
    for st in variant_stages:
        sid = st["id"]
        applicable.append(sid)
        base = core_by_id.get(sid)
        ov: dict = {}
        if base is None:
            # stack-added stage absent from core -> full definition
            for k in _OVERRIDABLE:
                if k in st:
                    ov[k] = st[k]
        else:
            for k in _OVERRIDABLE:
                if k in st and st.get(k) != base.get(k):
                    ov[k] = st[k]
        # gate + skills are always stack-specific
        if isinstance(st.get("gate"), list):
            ov["gate"] = st["gate"]
        if isinstance(st.get("skills"), list):
            ov["skills"] = st["skills"]
        if ov:
            overrides[sid] = ov
    return {
        "stack": stack,
        "source_finder": source_finder,
        "testgen": testgen,
        "applicable_stages": applicable,
        "stages": overrides,
    }


def _dump(path: Path, header: str, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=1000),
                    encoding="utf-8")


# Per-stack overlay generation params (besides java, which derives the core).
# A new stack is one entry here + its stages-<lang>.yaml + a <lang>_golden_pin test.
_VARIANTS: tuple[dict, ...] = (
    {"stack": "flutter", "variant_file": "stages-flutter.yaml",
     "source_finder": "find_dart_sources",
     "testgen": {"framework": "flutter_gherkin", "runner_cmd": "flutter test"}},
    {"stack": "rust", "variant_file": "stages-rust.yaml",
     "source_finder": "find_rust_sources",
     "testgen": {"framework": "cucumber-rs", "runner_cmd": "cargo test"}},
)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check = "--check" in argv
    pd = _pipeline_dir()
    java = _load_stages(pd / "stages.yaml")

    core = gen_core(java)
    core_by_id = {s["id"]: s for s in core}
    java_overlay = gen_overlay(
        java, core_by_id, stack="java", source_finder="find_java_sources",
        testgen={"framework": "cucumber-jvm", "runner_cmd": "gradlew test"})

    variants: list[tuple[dict, dict]] = []  # (spec, overlay)
    for spec in _VARIANTS:
        v_stages = _load_stages(pd / spec["variant_file"])
        overlay = gen_overlay(
            v_stages, core_by_id, stack=spec["stack"],
            source_finder=spec["source_finder"], testgen=spec["testgen"])
        variants.append((spec, overlay))

    print(f"core: {len(core)} stages")
    print(f"java overlay: {len(java_overlay['applicable_stages'])} applicable, "
          f"{len(java_overlay['stages'])} with overrides")
    for spec, overlay in variants:
        added = [s for s in overlay["applicable_stages"] if s not in core_by_id]
        print(f"{spec['stack']} overlay: {len(overlay['applicable_stages'])} applicable, "
              f"{len(overlay['stages'])} with overrides (added: {added})")
    if check:
        return 0

    _dump(core_path(),
          "# stages.core.yaml — stack-NEUTRAL pipeline core (unified-pipeline D2).\n"
          "# Generated by cli.gen_pipeline_core_overlay. gate/skills are stack-specific\n"
          "# (see overlays/<lang>.overlay.yaml); this core has neutral fields + tool-free\n"
          "# gate_intent. Merge: lib.pipeline_overlay.load_merged.\n",
          {"stages": core})
    _dump(overlay_path("java"),
          "# java.overlay.yaml — Java/Spring overlay (golden reference).\n"
          "# load_merged(None, 'java') reproduces legacy stages.yaml (test_java_golden_pin).\n",
          java_overlay)
    print(f"wrote {core_path()}")
    print(f"wrote {overlay_path('java')}")
    for spec, overlay in variants:
        st = spec["stack"]
        _dump(overlay_path(st),
              f"# {st}.overlay.yaml — {st} overlay (diffed vs neutral core).\n"
              f"# load_merged(None, '{st}') reproduces {spec['variant_file']} (test_{st}_golden_pin).\n",
              overlay)
        print(f"wrote {overlay_path(st)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
