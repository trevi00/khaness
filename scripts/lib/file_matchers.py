"""file_matchers — 18 file-path predicates used by handlers/post_tool/reviewer.

Extracted from reviewer.py (Round 6 W2 P1: 931 LoC bloat). These are simple
path-suffix / substring matchers that classify edited files into validator
trigger categories (openapi, ER, DDL, PRD, code, test, CI config, etc.).

## Usage

```python
from lib.file_matchers import is_openapi, is_ddl, ...
if is_openapi(file_path):
    # trigger openapi validator
```

Each predicate takes a normalized file path and returns bool. They are pure,
no side effects, no I/O — easily unit-testable.
"""
from __future__ import annotations


def is_openapi(p: str) -> bool:
    return p.endswith("openapi.yaml") or p.endswith("openapi.yml")


def is_flow(p: str) -> bool:
    return "/design/flows/" in p and p.endswith(".md")


def is_er(p: str) -> bool:
    return p.endswith("conceptual-er.md") and "/design/er/" in p


def is_logical(p: str) -> bool:
    return p.endswith("logical-design.md") and "/design/er/" in p


def is_ddl(p: str) -> bool:
    return p.endswith(".sql") and "/init/" in p


def is_class(p: str) -> bool:
    return "/design/class/" in p and p.endswith(".md")


def is_skeleton(p: str) -> bool:
    return p.endswith("skeleton-design.md") and "/design/" in p


def is_prd_domain(p: str) -> bool:
    return "/requirements/domain/" in p and p.endswith(".md")


def is_prd_root(p: str) -> bool:
    return "/requirements/" in p and "/domain/" not in p and p.endswith(".md")


def is_convention(p: str) -> bool:
    return p.endswith("convention.md")


def is_code_file(p: str) -> bool:
    """Match generated code files (backend Java + frontend TS/TSX)."""
    return (
        (p.endswith(".java") and "/backend/" in p)
        or ((p.endswith(".tsx") or p.endswith(".ts") or p.endswith(".css")) and "/frontend/src/" in p)
    )


def is_fe_contract(p: str) -> bool:
    """Match FE contract-related files (api.ts, model.ts)."""
    return (
        "/frontend/src/" in p
        and (p.endswith("/api.ts") or p.endswith("/model.ts"))
    )


def is_be_dto(p: str) -> bool:
    """Match BE DTO/enum files that affect contract."""
    return (
        "/backend/" in p and p.endswith(".java")
        and (
            "Request.java" in p or "Response.java" in p
            or "/domain/" in p  # enum files live here
        )
    )


def is_test_file(p: str) -> bool:
    """Match test files (backend JUnit tests)."""
    return (
        "/backend/" in p and p.endswith(".java")
        and "/src/test/" in p
    )


def is_ci_config(p: str) -> bool:
    """Match CI/CD config files (GitHub Actions workflow, build.gradle jacoco)."""
    n = p.replace("\\", "/")
    return (
        n.endswith("/.github/workflows/ci.yml")
        or n.endswith("/backend/build.gradle")
        or n.endswith("/.github/PULL_REQUEST_TEMPLATE.md")
    )


def is_collab_config(p: str) -> bool:
    """Match collaboration infrastructure files (Tier 1 collab).

    PR_TEMPLATE.md은 validators/ci.py와 공용 — 둘 다 cascade되도록 별도 체크.
    """
    n = p.replace("\\", "/")
    return (
        n.endswith("/.github/CODEOWNERS")
        or n.endswith("/.github/dependabot.yml")
        or n.endswith("/.github/workflows/codeql.yml")
        or n.endswith("/.github/ruleset-main.json")
        or "/.github/ISSUE_TEMPLATE/" in n
        or n.endswith("/.github/PULL_REQUEST_TEMPLATE.md")
        or n.endswith("/CONTRIBUTING.md")
        or n.endswith("/SECURITY.md")
    )


def is_pipeline_md(p: str) -> bool:
    """Match pipeline.md edits for step-complete retrospective."""
    return p.endswith("pipeline.md") and ("/.claude/" in p or "\\.claude\\" in p)


def is_impl_code_edit(p: str) -> bool:
    """Match implementation (non-test, non-config) code edits for gap detection."""
    n = p.replace("\\", "/")
    return (
        (n.endswith(".java") and "/backend/src/main/" in n)
        or ((n.endswith(".tsx") or n.endswith(".ts"))
            and "/frontend/src/" in n
            and "/node_modules/" not in n)
    )
