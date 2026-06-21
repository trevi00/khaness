"""testgen — acceptance test generation from the Gherkin spine (unified-pipeline D4).

The behavioral spine (`spec/domain/*.feature`, lib.spec_bundle) is the SOLE test-gen
key. `generate()` turns its `@id`-tagged scenarios into stack-specific test artifacts
via the stack overlay's `testgen` binding (java -> cucumber-jvm glue, flutter ->
flutter_gherkin, rust -> cucumber-rs), so the SAME spec drives tests in any stack.
Scenario identity is
the explicit `@id` tag (never a prose hash) — the round-trip key that lets a
generated test be matched back to the spec and to a reverse-extracted scenario
(debate-1781665033-4f39ca, contract-by-example).

This is the FORWARD generator + a pure round-trip coverage function. It returns
{path: content} dicts; the caller decides where to write (a project's test tree),
never inside a read-only source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .spec_bundle import Feature, Step

_OUTLINE_PARAM_RE = re.compile(r"<([A-Za-z0-9_]+)>")


def _effective_keyword(steps: list[Step]) -> list[tuple[str, str]]:
    """Resolve And/But/* to the preceding Given/When/Then for glue annotation."""
    out: list[tuple[str, str]] = []
    last = "Given"
    for s in steps:
        kw = s.keyword
        if kw in ("And", "But", "*"):
            kw = last
        else:
            last = kw
        out.append((kw, s.text))
    return out


def _unique_steps(feature: Feature) -> list[tuple[str, str]]:
    """All distinct (effective-keyword, text) steps across background + scenarios,
    order-stable. Background steps first."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for kw, text in _effective_keyword(feature.background):
        if text not in seen:
            seen.add(text)
            out.append((kw, text))
    for sc in feature.scenarios:
        for kw, text in _effective_keyword(sc.steps):
            if text not in seen:
                seen.add(text)
                out.append((kw, text))
    return out


def _snake_method_name(text: str, idx: int) -> str:
    """snake_case step identifier — a valid method name in Java AND a valid fn name
    in Rust (both stack glue generators reuse it)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()[:40] or "step"
    return f"step_{idx}_{slug}"


def _to_cucumber_expr(text: str) -> str:
    """Gherkin Scenario Outline <param> -> Cucumber {string} placeholder; literal
    text is escaped minimally (kept readable for a pending stub)."""
    return _OUTLINE_PARAM_RE.sub("{string}", text).replace('"', '\\"')


def _gen_cucumber_jvm(feature: Feature, *, domain: str, package: str) -> dict[str, str]:
    cls = re.sub(r"[^A-Za-z0-9]+", " ", domain).title().replace(" ", "") or "Spec"
    cls = f"{cls}Steps"

    # step-def glue (one method per unique step, @id-traceable header)
    lines = [
        f"package {package};",
        "",
        "import io.cucumber.java.en.Given;",
        "import io.cucumber.java.en.When;",
        "import io.cucumber.java.en.Then;",
        "import io.cucumber.java.PendingException;",
        "",
        f"// AUTO-GENERATED step-def stubs for spec/domain/{domain}.feature (unified-pipeline D4).",
        f"// Scenario @ids (round-trip keys): {', '.join(feature.scenario_ids())}",
        f"public class {cls} {{",
    ]
    anno = {"Given": "Given", "When": "When", "Then": "Then"}
    for i, (kw, text) in enumerate(_unique_steps(feature), 1):
        expr = _to_cucumber_expr(text)
        params = _OUTLINE_PARAM_RE.findall(text)
        sig = ", ".join(f"String {p}" for p in params)
        lines.append(f'  @{anno.get(kw, "Given")}("{expr}")')
        lines.append(f"  public void {_snake_method_name(text, i)}({sig}) {{")
        lines.append("    throw new PendingException();")
        lines.append("  }")
        lines.append("")
    lines.append("}")
    stepdefs = "\n".join(lines)

    pkg_path = package.replace(".", "/")
    return {
        f"src/test/resources/features/{domain}.feature": _render_feature(feature),
        f"src/test/java/{pkg_path}/{cls}.java": stepdefs,
    }


def _gen_flutter_gherkin(feature: Feature, *, domain: str) -> dict[str, str]:
    steps = _unique_steps(feature)
    lines = [
        "import 'package:flutter_gherkin/flutter_gherkin.dart';",
        "import 'package:gherkin/gherkin.dart';",
        "",
        f"// AUTO-GENERATED step defs for {domain}.feature (unified-pipeline D4).",
        f"// Scenario @ids: {', '.join(feature.scenario_ids())}",
    ]
    for i, (kw, text) in enumerate(steps, 1):
        cls = f"Step{i}"
        base = {"Given": "Given1", "When": "When1", "Then": "Then1"}.get(kw, "Given1")
        lines += [
            f"class {cls} extends {base}WithWorld {{",
            f"  @override RegExp get pattern => RegExp(r'{_to_dart_pattern(text)}');",
            "  @override Future<void> executeStep(_) async { throw UnimplementedError(); }",
            "}",
        ]
    return {f"test/features/{domain}.feature": _render_feature(feature),
            f"test/steps/{domain}_steps.dart": "\n".join(lines)}


def _to_dart_pattern(text: str) -> str:
    return _OUTLINE_PARAM_RE.sub(r"(.+)", text).replace("'", "\\'")


def _gen_cucumber_rs(feature: Feature, *, domain: str) -> dict[str, str]:
    """cucumber-rs glue: a World struct + #[given]/#[when]/#[then] async fn stubs,
    one per unique step, plus a tokio main that runs the .feature. {param} from a
    Scenario Outline becomes a trailing String arg (cucumber {string} expr)."""
    world = re.sub(r"[^A-Za-z0-9]+", " ", domain).title().replace(" ", "") or "Spec"
    world = f"{world}World"
    lines = [
        "use cucumber::{given, when, then, World};",
        "",
        f"// AUTO-GENERATED cucumber-rs step defs for spec/domain/{domain}.feature (unified-pipeline D4).",
        f"// Scenario @ids (round-trip keys): {', '.join(feature.scenario_ids())}",
        "",
        "#[derive(Debug, Default, World)]",
        f"struct {world} {{}}",
        "",
    ]
    attr = {"Given": "given", "When": "when", "Then": "then"}
    for i, (kw, text) in enumerate(_unique_steps(feature), 1):
        expr = _to_cucumber_expr(text)
        params = _OUTLINE_PARAM_RE.findall(text)
        extra = "".join(f", {p}: String" for p in params)
        lines.append(f'#[{attr.get(kw, "given")}(expr = "{expr}")]')
        lines.append(f"async fn {_snake_method_name(text, i)}(world: &mut {world}{extra}) {{")
        lines.append('    todo!("pending step");')
        lines.append("}")
        lines.append("")
    lines += [
        "#[tokio::main]",
        "async fn main() {",
        f'    {world}::run("tests/features/{domain}.feature").await;',
        "}",
    ]
    return {f"tests/features/{domain}.feature": _render_feature(feature),
            f"tests/{domain}_steps.rs": "\n".join(lines) + "\n"}


def _render_feature(feature: Feature) -> str:
    """Re-render the Feature to .feature text, preserving @id tags (the test
    resource Cucumber/flutter_gherkin runs). Scenario @ids are kept verbatim."""
    out: list[str] = []
    if feature.tags:
        out.append(" ".join(feature.tags))
    out.append(f"Feature: {feature.name}")
    if feature.background:
        out.append("  Background:")
        for s in feature.background:
            out.append(f"    {s.keyword} {s.text}")
    for sc in feature.scenarios:
        out.append("")
        if sc.tags:
            out.append("  " + " ".join(sc.tags))
        out.append(f"  {'Scenario Outline' if sc.is_outline else 'Scenario'}: {sc.name}")
        for s in sc.steps:
            out.append(f"    {s.keyword} {s.text}")
        if sc.examples:
            out.append("    Examples:")
            cols = list(sc.examples[0].keys())
            out.append("      | " + " | ".join(cols) + " |")
            for row in sc.examples:
                out.append("      | " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
    return "\n".join(out) + "\n"


def generate(feature: Feature, *, framework: str, domain: str,
             package: str = "kr.example.spec") -> dict[str, str]:
    """Generate stack test artifacts for `feature` per the overlay's testgen
    framework. Returns {relative_path: content}. Unknown framework -> {}."""
    if framework == "cucumber-jvm":
        return _gen_cucumber_jvm(feature, domain=domain, package=package)
    if framework == "flutter_gherkin":
        return _gen_flutter_gherkin(feature, domain=domain)
    if framework == "cucumber-rs":
        return _gen_cucumber_rs(feature, domain=domain)
    return {}


# ── round-trip coverage (advisory; the spec_roundtrip key set comparison) ──
@dataclass
class RoundTrip:
    matched: list[str]
    missing: list[str]    # in spec, no generated/extracted test
    orphan: list[str]     # test scenario with no backing spec @id
    coverage_pct: float


def roundtrip_coverage(spec_ids: list[str], test_ids: list[str]) -> RoundTrip:
    """Compare the spec's scenario @ids against the test-covered @ids — the
    explicit-id round-trip (never prose). Pure."""
    spec = list(dict.fromkeys(spec_ids))
    tset = set(test_ids)
    matched = [i for i in spec if i in tset]
    missing = [i for i in spec if i not in tset]
    orphan = [i for i in dict.fromkeys(test_ids) if i not in set(spec)]
    pct = round(100.0 * len(matched) / len(spec), 1) if spec else 0.0
    return RoundTrip(matched=matched, missing=missing, orphan=orphan, coverage_pct=pct)
