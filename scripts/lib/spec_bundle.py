"""spec_bundle — the unified Spec Bundle contract (unified-pipeline D1).

The Spec Bundle (`<root>/.claude/spec/`) is the single stack-neutral spec both
directions share: the forward pipeline EMITS it (requirements/PRD stages), the
reverse extractors EMIT it (code -> spec), and test-gen CONSUMES it. Its SPINE is
a set of Gherkin `.feature` files describing user-observable BEHAVIOR; structural
design (ER/logical/class/API) lives in separate typed facets (D1-2), never under
the behavioral spine (debate-1781665033-4f39ca, B4 category-error ruling).

Layout:
    <root>/.claude/spec/
      manifest.yaml                 schema_version, source_mode={forward|reverse},
                                    domains[], personas[]
      domain/<d>.feature            Gherkin spine (Feature/Background/Scenario/
                                    Scenario Outline + Given-When-Then + Examples)
      domain/<d>.story.md           persona + user-story-flow (non-test-bearing)
      facets/{er,logical,class,api}.schema   typed structural schema (D1-2)

Scenario identity is an EXPLICIT `@id:<slug>` tag — NEVER a hash of the Feature/
Scenario prose (debate C-STABLE-ID): a rename must not change the id, and the
forward generator and reverse extractor must be able to agree on the same id.
This module is the read/parse half; no gherkin third-party lib is required (the
grammar subset we use is small and stable).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_STEP_KEYWORDS = ("Given", "When", "Then", "And", "But", "*")
_ID_TAG_RE = re.compile(r"@id:([A-Za-z0-9][A-Za-z0-9_.-]*)")


@dataclass
class Step:
    keyword: str          # Given | When | Then | And | But | *
    text: str


@dataclass
class Scenario:
    name: str
    tags: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)  # Scenario Outline rows
    is_outline: bool = False

    @property
    def id(self) -> str | None:
        """The explicit @id:<slug> tag value, or None if unset (a missing @id is a
        validator concern — never fall back to a prose hash)."""
        for t in self.tags:
            m = _ID_TAG_RE.fullmatch(t)
            if m:
                return m.group(1)
        return None


@dataclass
class Feature:
    name: str
    tags: list[str] = field(default_factory=list)
    description: str = ""
    background: list[Step] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)

    def scenario_ids(self) -> list[str]:
        """Explicit ids of scenarios that declare one (the round-trip key set)."""
        return [s.id for s in self.scenarios if s.id]


def _split_tags(line: str) -> list[str]:
    return [t for t in line.split() if t.startswith("@")]


def _parse_table_row(line: str) -> list[str]:
    # "| a | b |" -> ['a', 'b']
    parts = line.strip().strip("|").split("|")
    return [p.strip() for p in parts]


def parse_feature(text: str) -> Feature:
    """Parse a Gherkin `.feature` document into a Feature. Pure, fail-soft:
    malformed lines are skipped, never raised. Supports Feature/Background/
    Scenario/Scenario Outline + Given-When-Then-And-But steps + Examples tables
    + @tag lines (incl @id:<slug>)."""
    feature = Feature(name="")
    pending_tags: list[str] = []
    cur: Scenario | None = None
    section: str = "none"         # none | background | scenario | examples
    in_feature_desc = False
    example_header: list[str] | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("@"):
            pending_tags.extend(_split_tags(line))
            continue

        if line.startswith("Feature:"):
            feature.name = line[len("Feature:"):].strip()
            feature.tags = pending_tags
            pending_tags = []
            in_feature_desc = True
            section = "none"
            continue

        if line.startswith("Background:"):
            section = "background"
            in_feature_desc = False
            continue

        if line.startswith("Scenario Outline:") or line.startswith("Scenario:"):
            outline = line.startswith("Scenario Outline:")
            name = line.split(":", 1)[1].strip()
            cur = Scenario(name=name, tags=pending_tags, is_outline=outline)
            pending_tags = []
            feature.scenarios.append(cur)
            section = "scenario"
            in_feature_desc = False
            example_header = None
            continue

        if line.startswith("Examples:"):
            section = "examples"
            example_header = None
            continue

        kw = line.split(" ", 1)[0]
        if kw in _STEP_KEYWORDS and section in ("background", "scenario"):
            step = Step(keyword=kw, text=line[len(kw):].strip())
            if section == "background":
                feature.background.append(step)
            elif cur is not None:
                cur.steps.append(step)
            continue

        if section == "examples" and line.startswith("|") and cur is not None:
            row = _parse_table_row(line)
            if example_header is None:
                example_header = row
            else:
                cur.examples.append(dict(zip(example_header, row)))
            continue

        if in_feature_desc:
            feature.description += (line + "\n")

    return feature


# ── bundle ──
@dataclass
class Bundle:
    root: Path
    schema_version: str = ""
    source_mode: str = ""                       # forward | reverse
    domains: list[str] = field(default_factory=list)
    personas: list[dict] = field(default_factory=list)
    features: dict[str, Feature] = field(default_factory=dict)   # domain -> Feature

    def all_scenario_ids(self) -> list[str]:
        out: list[str] = []
        for f in self.features.values():
            out.extend(f.scenario_ids())
        return out


def spec_root(project_root: str | Path) -> Path:
    return Path(project_root) / ".claude" / "spec"


def load_bundle(project_root: str | Path) -> Bundle | None:
    """Load the Spec Bundle under <project_root>/.claude/spec/. Returns None if no
    bundle exists; otherwise a Bundle with manifest fields + parsed domain
    features. Fail-soft per-file (a bad feature file yields an empty Feature)."""
    root = spec_root(project_root)
    if not root.is_dir():
        return None
    b = Bundle(root=root)
    man = root / "manifest.yaml"
    if man.is_file():
        try:
            data = yaml.safe_load(man.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        if isinstance(data, dict):
            b.schema_version = str(data.get("schema_version", ""))
            b.source_mode = str(data.get("source_mode", ""))
            b.domains = list(data.get("domains") or [])
            b.personas = list(data.get("personas") or [])
    domain_dir = root / "domain"
    if domain_dir.is_dir():
        for fp in sorted(domain_dir.glob("*.feature")):
            try:
                b.features[fp.stem] = parse_feature(fp.read_text(encoding="utf-8"))
            except Exception:
                b.features[fp.stem] = Feature(name=fp.stem)
    return b
