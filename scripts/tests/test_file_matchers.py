#!/usr/bin/env python3
"""Unit tests for lib/file_matchers.py — extracted from reviewer.py W2 P1."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import file_matchers as fm  # noqa: E402


def test_openapi_matches_yaml_yml():
    assert fm.is_openapi("/proj/openapi.yaml")
    assert fm.is_openapi("/proj/openapi.yml")
    assert not fm.is_openapi("/proj/api.yaml")


def test_flow_requires_design_flows_dir():
    assert fm.is_flow("/proj/design/flows/login.md")
    assert not fm.is_flow("/proj/flows/login.md")
    assert not fm.is_flow("/proj/design/flows/login.txt")


def test_er_requires_conceptual_filename():
    assert fm.is_er("/proj/design/er/conceptual-er.md")
    assert not fm.is_er("/proj/design/er/logical-design.md")
    assert not fm.is_er("/proj/conceptual-er.md")  # 잘못된 dir


def test_logical_specific_filename():
    assert fm.is_logical("/proj/design/er/logical-design.md")
    assert not fm.is_logical("/proj/design/er/conceptual-er.md")


def test_ddl_requires_init_dir():
    assert fm.is_ddl("/proj/init/01-schema.sql")
    assert not fm.is_ddl("/proj/migrations/01.sql")
    assert not fm.is_ddl("/proj/init/script.py")


def test_class_requires_design_class_dir():
    assert fm.is_class("/proj/design/class/User.md")
    assert not fm.is_class("/proj/design/User.md")


def test_skeleton_filename():
    assert fm.is_skeleton("/proj/design/skeleton-design.md")
    assert not fm.is_skeleton("/proj/skeleton-design.md")  # design/ required


def test_prd_domain_vs_root():
    assert fm.is_prd_domain("/proj/requirements/domain/user.md")
    assert fm.is_prd_root("/proj/requirements/index.md")
    # mutual exclusion
    assert not fm.is_prd_root("/proj/requirements/domain/user.md")
    assert not fm.is_prd_domain("/proj/requirements/index.md")


def test_convention_filename():
    assert fm.is_convention("/proj/.claude/convention.md")
    assert not fm.is_convention("/proj/conventions.md")


def test_code_file_backend_java_or_frontend_ts():
    assert fm.is_code_file("/proj/backend/User.java")
    assert fm.is_code_file("/proj/frontend/src/App.tsx")
    assert fm.is_code_file("/proj/frontend/src/api.ts")
    assert fm.is_code_file("/proj/frontend/src/style.css")
    assert not fm.is_code_file("/proj/User.java")  # not under backend/
    assert not fm.is_code_file("/proj/frontend/src/api.json")


def test_fe_contract_api_or_model():
    assert fm.is_fe_contract("/proj/frontend/src/api.ts")
    assert fm.is_fe_contract("/proj/frontend/src/model.ts")
    assert not fm.is_fe_contract("/proj/frontend/src/App.tsx")


def test_be_dto_request_response_or_domain_enum():
    assert fm.is_be_dto("/proj/backend/UserRequest.java")
    assert fm.is_be_dto("/proj/backend/UserResponse.java")
    assert fm.is_be_dto("/proj/backend/domain/Status.java")
    assert not fm.is_be_dto("/proj/backend/Service.java")  # not request/response/domain


def test_test_file_in_src_test():
    assert fm.is_test_file("/proj/backend/src/test/UserTest.java")
    assert not fm.is_test_file("/proj/backend/src/main/User.java")


def test_ci_config_specific_paths():
    assert fm.is_ci_config("/proj/.github/workflows/ci.yml")
    assert fm.is_ci_config("/proj/backend/build.gradle")
    assert not fm.is_ci_config("/proj/.github/workflows/cd.yml")


def test_collab_config_multiple_files():
    assert fm.is_collab_config("/proj/.github/CODEOWNERS")
    assert fm.is_collab_config("/proj/.github/dependabot.yml")
    assert fm.is_collab_config("/proj/CONTRIBUTING.md")
    assert fm.is_collab_config("/proj/SECURITY.md")
    assert fm.is_collab_config("/proj/.github/ISSUE_TEMPLATE/bug.md")
    assert not fm.is_collab_config("/proj/random.md")


def test_pipeline_md_under_claude_dir():
    assert fm.is_pipeline_md("/proj/.claude/pipeline.md")
    # Windows backslash form
    assert fm.is_pipeline_md("C:\\proj\\.claude\\pipeline.md")
    assert not fm.is_pipeline_md("/proj/pipeline.md")


def test_impl_code_edit_excludes_node_modules():
    assert fm.is_impl_code_edit("/proj/backend/src/main/User.java")
    assert fm.is_impl_code_edit("/proj/frontend/src/App.tsx")
    assert not fm.is_impl_code_edit("/proj/frontend/src/node_modules/lib.ts")
    assert not fm.is_impl_code_edit("/proj/backend/src/test/UserTest.java")  # test/ not main/


def test_windows_path_normalization():
    """is_ci_config / is_collab_config / is_pipeline_md / is_impl_code_edit
    must handle Windows-style backslashes."""
    assert fm.is_ci_config("C:\\proj\\.github\\workflows\\ci.yml")
    assert fm.is_collab_config("C:\\proj\\.github\\CODEOWNERS")


def main() -> int:
    failures = []
    test_count = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        test_count += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failures.append((name, str(e)))
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            failures.append((name, repr(e)))
            print(f"  [ERR]  {name}: {e!r}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        return 1
    print(f"\n[OK] {test_count} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
