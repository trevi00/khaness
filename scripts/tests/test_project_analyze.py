#!/usr/bin/env python3
"""Unit tests for cli/project_analyze.py."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import project_analyze as pa  # noqa: E402


# === Detection ===

def test_detect_java_springboot_3_2_from_gradle():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "build.gradle").write_text(
            "plugins {\n  id 'org.springframework.boot' version '3.2.5'\n}\n",
            encoding="utf-8",
        )
        (root / "src" / "main" / "java").mkdir(parents=True)
        s = pa.detect_stack(root)
        assert s is not None
        assert s.language == "java"
        assert s.framework == "springboot"
        assert s.version == "3.2", f"version trim got {s.version}"
        assert s.confidence >= 0.9


def test_detect_java_no_spring_falls_back_to_low_confidence():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src" / "main" / "java").mkdir(parents=True)
        (root / "build.gradle").write_text("// no spring boot\n", encoding="utf-8")
        s = pa.detect_stack(root)
        assert s is not None
        assert s.language == "java"
        assert s.framework == ""
        assert s.confidence < 0.9


def test_detect_typescript_react_18_from_package_json():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text(
            '{"name":"x","dependencies":{"react":"^18.2.0","typescript":"^5.0.0"}}',
            encoding="utf-8",
        )
        s = pa.detect_stack(root)
        assert s is not None
        assert s.language == "typescript"
        assert s.framework == "react"
        assert s.version == "18"


def test_detect_typescript_nextjs():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text(
            '{"dependencies":{"next":"^14.0.0","react":"^18.0.0"}}',
            encoding="utf-8",
        )
        s = pa.detect_stack(root)
        # Next has higher priority than react in detection list
        assert s.framework == "nextjs", f"got {s.framework}"


def test_detect_flutter_from_pubspec():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pubspec.yaml").write_text(
            "name: my_app\n"
            "dependencies:\n"
            "  flutter:\n"
            "    sdk: flutter\n",
            encoding="utf-8",
        )
        s = pa.detect_stack(root)
        assert s is not None
        assert s.language == "dart"
        assert s.framework == "flutter"


def test_detect_kotlin_android():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src" / "main" / "kotlin").mkdir(parents=True)
        (root / "build.gradle.kts").write_text(
            'plugins { id("com.android.application") version "8.0.0" }\n'
            'kotlin("android") version "1.9.0"\n',
            encoding="utf-8",
        )
        s = pa.detect_stack(root)
        assert s is not None
        assert s.language == "kotlin"
        assert s.framework == "android"


def test_detect_returns_none_for_unknown():
    with tempfile.TemporaryDirectory() as td:
        s = pa.detect_stack(Path(td))
        assert s is None


# === tech-stack.yaml suggestion ===

def test_suggest_yaml_for_full_monorepo():
    stacks = [
        pa.DetectedStack(subroot="backend", kind="java-be", language="java",
                         framework="springboot", version="3.2", sources=[], confidence=0.9),
        pa.DetectedStack(subroot="frontend", kind="ts-fe", language="typescript",
                         framework="react", version="18", sources=[], confidence=0.95),
    ]
    yaml = pa.suggest_tech_stack_yaml(stacks)
    assert "backend:" in yaml
    assert "language: java" in yaml
    assert "framework: springboot" in yaml
    assert 'version: "3.2"' in yaml
    assert "frontend:" in yaml
    assert "language: typescript" in yaml


def test_suggest_yaml_kotlin_android_routes_to_mobile_block():
    stacks = [
        pa.DetectedStack(subroot=".", kind="java-be", language="kotlin",
                         framework="android", version="", sources=[], confidence=0.85),
    ]
    yaml = pa.suggest_tech_stack_yaml(stacks)
    assert "mobile:" in yaml
    assert "language: kotlin" in yaml
    assert "framework: android" in yaml


def test_suggest_yaml_empty_stacks_returns_placeholder():
    yaml = pa.suggest_tech_stack_yaml([])
    assert "no stacks detected" in yaml.lower()


# === skill activation resolution ===

def test_resolve_activations_filters_to_existing_subtrees():
    stacks = [
        pa.DetectedStack(subroot="backend", kind="java-be", language="java",
                         framework="springboot", version="3.2", sources=[], confidence=0.9),
    ]
    out = pa.resolve_skill_activations(stacks)
    # Should always include _common
    assert "_common" in out
    # The backend block label should map to existing skill subtrees
    keys = list(out.keys())
    backend_key = next(k for k in keys if "backend" in k)
    paths = out[backend_key]
    # At least java/springboot-3.2 (which exists in our SKILLS_DIR) should appear
    assert any("java" in p for p in paths), f"got {paths}"


# === missing assets ===

def test_missing_assets_full_list_for_empty_project():
    with tempfile.TemporaryDirectory() as td:
        missing = pa.list_missing_assets(Path(td))
        assert any(rel == ".claude/tech-stack.yaml" for rel, _ in missing)
        assert any(rel == ".github/workflows/" for rel, _ in missing)


def test_missing_assets_skips_existing():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".claude").mkdir()
        (root / ".claude" / "tech-stack.yaml").write_text("stack:\n  language: java\n",
                                                          encoding="utf-8")
        missing = pa.list_missing_assets(root)
        rels = [rel for rel, _ in missing]
        assert ".claude/tech-stack.yaml" not in rels


# === analyze() end-to-end ===

def test_analyze_empty_dir_does_not_crash():
    with tempfile.TemporaryDirectory() as td:
        rep = pa.analyze(Path(td))
        assert rep.detected_stacks == []
        assert rep.has_tech_stack_yaml is False
        assert len(rep.missing_assets) > 0


def test_analyze_synthetic_monorepo():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # backend
        (root / "backend" / "src" / "main" / "java").mkdir(parents=True)
        (root / "backend" / "build.gradle").write_text(
            "plugins { id 'org.springframework.boot' version '3.2.0' }\n",
            encoding="utf-8",
        )
        # frontend
        (root / "frontend").mkdir()
        (root / "frontend" / "package.json").write_text(
            '{"dependencies":{"react":"^18.0.0"}}',
            encoding="utf-8",
        )
        rep = pa.analyze(root)
        kinds = {s.kind for s in rep.detected_stacks}
        assert "java-be" in kinds
        assert "ts-fe" in kinds


def test_to_markdown_renders_all_sections():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rep = pa.analyze(root)
        md = pa.to_markdown(rep)
        for section in (
            "## 1. Tech stack detection",
            "## 2. tech-stack.yaml",
            "## 3. Skill activations",
            "## 4. Validator coverage",
            "## 5. Missing harness assets",
            "## 6. Next steps",
        ):
            assert section in md, f"missing section: {section}"


def main() -> int:
    tests = [
        test_detect_java_springboot_3_2_from_gradle,
        test_detect_java_no_spring_falls_back_to_low_confidence,
        test_detect_typescript_react_18_from_package_json,
        test_detect_typescript_nextjs,
        test_detect_flutter_from_pubspec,
        test_detect_kotlin_android,
        test_detect_returns_none_for_unknown,
        test_suggest_yaml_for_full_monorepo,
        test_suggest_yaml_kotlin_android_routes_to_mobile_block,
        test_suggest_yaml_empty_stacks_returns_placeholder,
        test_resolve_activations_filters_to_existing_subtrees,
        test_missing_assets_full_list_for_empty_project,
        test_missing_assets_skips_existing,
        test_analyze_empty_dir_does_not_crash,
        test_analyze_synthetic_monorepo,
        test_to_markdown_renders_all_sections,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
