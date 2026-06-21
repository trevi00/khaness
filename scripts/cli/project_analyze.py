#!/usr/bin/env python3
"""Project analyzer — reverse-engineer a target project through the harness pipeline.

Backend for the `/harness-pinit` slash command. Given a project path:

1. Detect tech stack from build files (per-subroot in monorepos)
2. Suggest `.claude/tech-stack.yaml` (or compare against existing)
3. Resolve which skill subtrees will activate (via lib.tech_stack candidates)
4. Map detected language to pipeline stages.yaml variant
5. Run cli.validate_project to summarize validator coverage
6. List missing harness assets (.claude/ dir, convention.md, etc.)

Outputs a markdown init report by default, --json for machine consumption.

Usage:
    cd ~/.claude/scripts
    python -m cli.project_analyze --root /home/user/some-project
    python -m cli.project_analyze --root . --json

Exit code: 0 always (this is read-only analysis; failures are findings).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli.validate_project import _classify_dir, _discover_subroots, run as run_validate  # noqa: E402
from lib.extractors import REGISTRY as EXTRACTOR_REGISTRY  # noqa: E402
from lib.paths import SKILLS_DIR  # noqa: E402
from lib.tech_stack import _candidate_paths, load_tech_stack  # noqa: E402


# ---------------------------------------------------------------------------
# Tech stack detection
# ---------------------------------------------------------------------------

# Detection priority (first match wins per subroot)
SPRING_BOOT_VERSION_RE = re.compile(
    r"(?:org\.springframework\.boot|spring-boot)['\"]?\s*(?:version)?\s*['\"]([\d.]+)['\"]"
)
KOTLIN_VERSION_RE = re.compile(r"kotlin['\"]?\s*\)?\s*version\s*['\"]([\d.]+)['\"]")
TS_VERSION_DEP_RE = re.compile(r'"typescript"\s*:\s*"\^?([\d.]+)"')
REACT_VERSION_DEP_RE = re.compile(r'"react"\s*:\s*"\^?([\d.]+)"')
NEXT_VERSION_DEP_RE = re.compile(r'"next"\s*:\s*"\^?([\d.]+)"')
NUXT_VERSION_DEP_RE = re.compile(r'"nuxt"\s*:\s*"\^?([\d.]+)"')
VUE_VERSION_DEP_RE = re.compile(r'"vue"\s*:\s*"\^?([\d.]+)"')
FLUTTER_DEP_RE = re.compile(r"^\s*flutter\s*:", re.MULTILINE)


@dataclass
class DetectedStack:
    subroot: str             # relative path
    kind: str                # "java-be" | "ts-fe" | "kotlin" | "flutter" | "root"
    language: str            # java | kotlin | typescript | dart | ...
    framework: str           # springboot | react | nextjs | vue | nuxt | android | ...
    version: str             # parsed version string, may be empty
    sources: list[str]       # files we read to determine this
    confidence: float        # 0.0..1.0


def _read_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _detect_java_subroot(path: Path) -> DetectedStack | None:
    """Detect Java + Spring Boot from build.gradle / pom.xml / build.gradle.kts.

    Requires `src/main/java/` to disambiguate from Kotlin projects that share
    the same build file extension. Falls through to _detect_kotlin_subroot
    when only src/main/kotlin/ is present.
    """
    if not (path / "src" / "main" / "java").is_dir():
        return None

    sources: list[str] = []
    framework = ""
    version = ""

    candidates = [path / "build.gradle", path / "build.gradle.kts", path / "pom.xml"]
    for c in candidates:
        if not c.is_file():
            continue
        sources.append(c.name)
        text = _read_safe(c)
        m = SPRING_BOOT_VERSION_RE.search(text)
        if m:
            framework = "springboot"
            version = m.group(1).rsplit(".", 1)[0]  # "3.2.0" → "3.2"
            break
        if "spring-boot" in text or "org.springframework.boot" in text:
            framework = "springboot"
            break

    if not sources:
        return None

    return DetectedStack(
        subroot=path.name or ".",
        kind="java-be",
        language="java",
        framework=framework,
        version=version,
        sources=sources,
        confidence=0.9 if framework else 0.6,
    )


def _detect_kotlin_subroot(path: Path) -> DetectedStack | None:
    sources = []
    framework = ""
    version = ""
    has_kotlin_src = (path / "src" / "main" / "kotlin").is_dir()
    if not has_kotlin_src:
        return None

    for c in [path / "build.gradle.kts", path / "build.gradle"]:
        if not c.is_file():
            continue
        sources.append(c.name)
        text = _read_safe(c)
        if "com.android.application" in text or "com.android.library" in text:
            framework = "android"
        elif "compose-multiplatform" in text or "kotlin-multiplatform" in text:
            framework = "multiplatform"
        m = KOTLIN_VERSION_RE.search(text)
        if m:
            version = m.group(1).rsplit(".", 1)[0] + ".x"
        break

    return DetectedStack(
        subroot=path.name or ".",
        kind="java-be",  # validate_project classifies kotlin as java-be by src/main/java
        language="kotlin",
        framework=framework,
        version=version,
        sources=sources or ["src/main/kotlin/"],
        confidence=0.85 if framework else 0.6,
    )


def _detect_ts_subroot(path: Path) -> DetectedStack | None:
    pkg = path / "package.json"
    if not pkg.is_file():
        return None
    text = _read_safe(pkg)

    framework = ""
    version = ""
    fw_versions = [
        ("nextjs", NEXT_VERSION_DEP_RE),
        ("nuxt", NUXT_VERSION_DEP_RE),
        ("react", REACT_VERSION_DEP_RE),
        ("vue", VUE_VERSION_DEP_RE),
    ]
    for fw, rx in fw_versions:
        m = rx.search(text)
        if m:
            framework = fw
            version = m.group(1).split(".")[0]  # "18.2.0" → "18"
            break

    ts_match = TS_VERSION_DEP_RE.search(text)
    ts_version = ts_match.group(1).split(".")[0] if ts_match else ""

    return DetectedStack(
        subroot=path.name or ".",
        kind="ts-fe",
        language="typescript",
        framework=framework,
        version=version or ts_version,
        sources=[pkg.name],
        confidence=0.95 if framework else 0.7,
    )


def _detect_flutter_subroot(path: Path) -> DetectedStack | None:
    pubspec = path / "pubspec.yaml"
    if not pubspec.is_file():
        return None
    text = _read_safe(pubspec)
    framework = "flutter" if FLUTTER_DEP_RE.search(text) else ""
    return DetectedStack(
        subroot=path.name or ".",
        kind="flutter",
        language="dart",
        framework=framework,
        version="3.x" if framework else "",
        sources=[pubspec.name],
        confidence=0.95 if framework else 0.7,
    )


_DETECTORS = (_detect_java_subroot, _detect_kotlin_subroot, _detect_ts_subroot, _detect_flutter_subroot)


def detect_stack(path: Path) -> DetectedStack | None:
    for fn in _DETECTORS:
        result = fn(path)
        if result:
            return result
    return None


# ---------------------------------------------------------------------------
# Skill activation resolution
# ---------------------------------------------------------------------------

def _existing_skill_paths(candidates: list[str]) -> list[str]:
    """Filter candidates to only those that exist as actual skill subtrees."""
    return [c for c in candidates if (SKILLS_DIR / c).is_dir()]


def resolve_skill_activations(stacks: list[DetectedStack]) -> dict[str, list[str]]:
    """For each detected stack, return the skill paths that WILL activate."""
    out: dict[str, list[str]] = {"_common": ["always"]}
    for s in stacks:
        cands = _candidate_paths(s.language, s.framework, s.version)
        existing = _existing_skill_paths(cands)
        out[f"{s.subroot} ({s.language}/{s.framework or '?'}/{s.version or '?'})"] = existing
    return out


# ---------------------------------------------------------------------------
# Tech-stack.yaml suggestion
# ---------------------------------------------------------------------------

def suggest_tech_stack_yaml(stacks: list[DetectedStack]) -> str:
    """Generate a tech-stack.yaml content string from detected stacks (nested form)."""
    if not stacks:
        return "# no stacks detected — add manually\n"

    lines: list[str] = []
    block_for = {"java-be": "backend", "ts-fe": "frontend", "flutter": "mobile"}
    by_block: dict[str, DetectedStack] = {}
    for s in stacks:
        block = block_for.get(s.kind)
        # kotlin under java-be becomes mobile if framework=android, else backend
        if s.language == "kotlin" and s.framework == "android":
            block = "mobile"
        if not block:
            continue
        if block not in by_block or s.confidence > by_block[block].confidence:
            by_block[block] = s

    for block in ("backend", "frontend", "mobile"):
        s = by_block.get(block)
        if s is None:
            continue
        lines.append(f"{block}:")
        lines.append(f"  language: {s.language}")
        if s.framework:
            lines.append(f"  framework: {s.framework}")
        if s.version:
            lines.append(f'  version: "{s.version}"')

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Missing assets
# ---------------------------------------------------------------------------

REQUIRED_HARNESS_FILES = [
    (".claude/tech-stack.yaml",   "활성 스킬 트리 명시"),
    (".claude/convention.md",     "프로젝트 컨벤션 (패키지·DTO·에러)"),
    (".claude/changelog.md",      "변경이력 (기능별 add/change/fix)"),
    (".claude/requirements/",     "PRD 트리 (도메인별 US/AC)"),
    (".github/workflows/",        "CI 워크플로우"),
    ("HANDOFF.md",                "세션 인계 문서 (있으면 우대)"),
]


def list_missing_assets(root: Path) -> list[tuple[str, str]]:
    out = []
    for rel, why in REQUIRED_HARNESS_FILES:
        p = root / rel
        exists = p.is_dir() if rel.endswith("/") else p.is_file()
        if not exists:
            out.append((rel, why))
    return out


# ---------------------------------------------------------------------------
# Top-level analyzer
# ---------------------------------------------------------------------------

@dataclass
class ExtractorPreview:
    extractor: str
    target: str
    confidence: float
    notes: list[str] = field(default_factory=list)
    sources_count: int = 0
    content_preview: str = ""    # first ~400 chars of the extracted draft
    content_length: int = 0
    # Whether the target file already exists (we never overwrite during analyze)
    target_exists: bool = False


@dataclass
class AnalysisReport:
    root: str
    has_tech_stack_yaml: bool
    existing_active_paths: list[str]
    detected_stacks: list[DetectedStack] = field(default_factory=list)
    suggested_tech_stack_yaml: str = ""
    skill_activations: dict[str, list[str]] = field(default_factory=dict)
    missing_assets: list[tuple[str, str]] = field(default_factory=list)
    validate_summary: dict = field(default_factory=dict)
    extractor_previews: list[ExtractorPreview] = field(default_factory=list)


def analyze(root: Path) -> AnalysisReport:
    root = root.resolve()

    existing = load_tech_stack(root) or []
    has_yaml = (root / ".claude" / "tech-stack.yaml").is_file()

    # Walk one level + classify subroots
    subroots = _discover_subroots(root)

    detected: list[DetectedStack] = []
    seen_paths: set[str] = set()
    # root itself first
    root_stack = detect_stack(root)
    if root_stack:
        root_stack.subroot = "."
        detected.append(root_stack)
        seen_paths.add(".")
    # then siblings
    for s in subroots:
        rel = "." if s.path == root else s.path.relative_to(root).as_posix()
        if rel in seen_paths:
            continue
        ds = detect_stack(s.path)
        if ds:
            ds.subroot = rel
            detected.append(ds)
            seen_paths.add(rel)

    activations = resolve_skill_activations(detected)
    suggestion = suggest_tech_stack_yaml(detected)
    missing = list_missing_assets(root)

    # Run extractors on each detected subroot (java-be, ts-fe, flutter).
    # The extractor's can_extract() gates whether to attempt; output is
    # PREVIEW only — analyze() never writes (use cli.reverse_engineer --write).
    previews: list[ExtractorPreview] = []
    extractor_roots = [root] + [
        sub.path for sub in subroots if sub.path != root and sub.kind in {"java-be", "ts-fe", "flutter"}
    ]
    seen_targets: set[str] = set()
    for ex_cls in EXTRACTOR_REGISTRY:
        ex = ex_cls()
        # Skip non-code extractors (e.g. doc_classifier) — analyze previews
        # CODE-reverse targets only; doc-ingest is driven by cli.ingest_docs.
        if not getattr(ex, "code_extractor", True):
            continue
        for ex_root in extractor_roots:
            if not ex.can_extract(ex_root):
                continue
            res = ex.extract(ex_root)
            target_path = ex_root / res.target
            target_rel = (ex_root.relative_to(root) / res.target).as_posix() if ex_root != root else res.target
            if target_rel in seen_targets:
                continue
            seen_targets.add(target_rel)
            previews.append(ExtractorPreview(
                extractor=ex.name,
                target=target_rel,
                confidence=res.confidence,
                notes=list(res.notes),
                sources_count=len(res.sources),
                content_preview=res.content[:400],
                content_length=len(res.content),
                target_exists=target_path.is_file(),
            ))
            break  # one extraction per extractor per analyze run

    # Run validate_project to get coverage summary
    validate = run_validate(root)
    validate_summary = {
        "subroots": [{"path": s.path.name or ".", "kind": s.kind} for s in validate.subroots],
        "counts": {
            "PASS": sum(1 for r in validate.results if r.status == "PASS"),
            "SKIP": sum(1 for r in validate.results if r.status == "SKIP"),
            "FAIL": sum(1 for r in validate.results if r.status == "FAIL"),
        },
        "fails": [
            {"validator": r.validator, "subroot": r.subroot, "tail": r.output_tail[:200]}
            for r in validate.results if r.status == "FAIL"
        ],
    }

    return AnalysisReport(
        root=str(root),
        has_tech_stack_yaml=has_yaml,
        existing_active_paths=existing,
        detected_stacks=detected,
        suggested_tech_stack_yaml=suggestion,
        skill_activations=activations,
        missing_assets=missing,
        validate_summary=validate_summary,
        extractor_previews=previews,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def to_markdown(rep: AnalysisReport) -> str:
    L = []
    L.append(f"# harness-pinit analysis — `{rep.root}`")
    L.append("")
    L.append("## 1. Tech stack detection")
    L.append("")
    if rep.detected_stacks:
        L.append("| Subroot | Language | Framework | Version | Confidence | Sources |")
        L.append("|---|---|---|---|---|---|")
        for s in rep.detected_stacks:
            L.append(f"| `{s.subroot}` | {s.language} | {s.framework or '?'} | {s.version or '?'} | {s.confidence:.2f} | {', '.join(s.sources)} |")
    else:
        L.append("(no stacks detected)")
    L.append("")

    L.append("## 2. tech-stack.yaml")
    L.append("")
    if rep.has_tech_stack_yaml:
        L.append("**Existing** — active paths resolved:")
        L.append("```")
        for p in rep.existing_active_paths or ["(none)"]:
            L.append(f"  {p}")
        L.append("```")
    else:
        L.append("**Missing** — suggested content:")
    L.append("```yaml")
    L.append(rep.suggested_tech_stack_yaml.rstrip())
    L.append("```")
    L.append("")

    L.append("## 3. Skill activations (by subroot)")
    L.append("")
    for label, paths in rep.skill_activations.items():
        L.append(f"### `{label}`")
        if paths:
            for p in paths:
                L.append(f"- `{p}/`")
        else:
            L.append("- (no matching subtrees)")
        L.append("")

    L.append("## 4. Validator coverage (via `cli.validate_project`)")
    L.append("")
    counts = rep.validate_summary.get("counts", {})
    L.append(f"PASS={counts.get('PASS',0)}  SKIP={counts.get('SKIP',0)}  FAIL={counts.get('FAIL',0)}")
    fails = rep.validate_summary.get("fails", [])
    if fails:
        L.append("")
        L.append("### Failures")
        for f in fails:
            L.append(f"- `{f['validator']}@{f['subroot']}` → {f['tail']}")
    L.append("")

    L.append("## 5.5 Reverse-engineered drafts (extractors)")
    L.append("")
    if rep.extractor_previews:
        L.append("| Extractor | Target | Confidence | Target exists? | Sources |")
        L.append("|---|---|---|---|---|")
        for p in rep.extractor_previews:
            exists = "yes (won't overwrite)" if p.target_exists else "no (would create)"
            L.append(f"| `{p.extractor}` | `{p.target}` | {p.confidence:.2f} | {exists} | {p.sources_count} files |")
        L.append("")
        L.append("Apply with:")
        L.append("```bash")
        L.append("python -m cli.reverse_engineer --root <PATH> --write")
        L.append("python -m cli.reverse_engineer --root <PATH> --write --stage convention   # one stage")
        L.append("```")
        L.append("")
        L.append("Drafts (preview):")
        for p in rep.extractor_previews:
            L.append(f"<details><summary><code>{p.extractor}</code> → <code>{p.target}</code> "
                     f"(conf={p.confidence:.2f}, {p.content_length} chars)</summary>")
            L.append("")
            L.append("```")
            L.append(p.content_preview.rstrip())
            L.append(f"... [{max(0, p.content_length - len(p.content_preview))} more chars]")
            L.append("```")
            L.append("")
            if p.notes:
                L.append("Notes: " + "; ".join(p.notes))
                L.append("")
            L.append("</details>")
            L.append("")
    else:
        L.append("(no extractors had source material — empty project or unsupported stack)")
    L.append("")

    L.append("## 5. Missing harness assets")
    L.append("")
    if rep.missing_assets:
        L.append("| Path | Why |")
        L.append("|---|---|")
        for path, why in rep.missing_assets:
            L.append(f"| `{path}` | {why} |")
    else:
        L.append("(none — all harness assets present)")
    L.append("")

    L.append("## 6. Next steps")
    L.append("")
    if not rep.has_tech_stack_yaml:
        L.append("1. Create `.claude/tech-stack.yaml` with the suggested content above")
    if any(rel == ".claude/convention.md" for rel, _ in rep.missing_assets):
        L.append("2. Author `.claude/convention.md` (use `convention` validator to check)")
    if rep.validate_summary.get("counts", {}).get("FAIL", 0) > 0:
        L.append("3. Resolve validator FAILs listed above")
    if not rep.detected_stacks:
        L.append("4. Add a recognized build file (build.gradle, package.json, pubspec.yaml, ...) so detection works")

    return "\n".join(L) + "\n"


def to_json_str(rep: AnalysisReport) -> str:
    payload = asdict(rep)
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Analyze a project through the harness pipeline")
    ap.add_argument("--root", default=os.getcwd(), help="project root (default: cwd)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[project_analyze] root not a directory: {root}", file=sys.stderr)
        return 2

    rep = analyze(root)
    print(to_json_str(rep) if args.json else to_markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
