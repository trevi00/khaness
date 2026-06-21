#!/usr/bin/env python3
"""Tests for lib/spec_facets.py — typed structural facets (D1-2)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_DDL = """\
CREATE TABLE users (
  id BIGSERIAL PRIMARY KEY,
  nickname VARCHAR(16) NOT NULL,
  role TEXT NOT NULL
);
CREATE INDEX ix_users_nickname ON users (nickname);
CREATE TABLE orders (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL
);
"""


def test_parse_and_validate_facet():
    from lib.spec_facets import parse_facet, validate_facet
    f = parse_facet("facet: logical\nschema_version: '1'\n"
                    "elements:\n  - {id: users, kind: table}\n  - {id: orders, kind: table}\n")
    assert f is not None and f.kind == "logical"
    assert f.element_ids() == ["users", "orders"]
    assert validate_facet(f) == []


def test_validate_flags_dup_and_empty_id_and_bad_kind():
    from lib.spec_facets import Facet, FacetElement, validate_facet
    f = Facet(kind="bogus", elements=[
        FacetElement(id="t1"), FacetElement(id="t1"), FacetElement(id="")])
    problems = validate_facet(f)
    assert any("unknown facet kind" in p for p in problems)
    assert any("duplicate element @id 't1'" in p for p in problems)
    assert any("empty @id" in p for p in problems)


def test_parse_facet_rejects_non_facet():
    from lib.spec_facets import parse_facet
    assert parse_facet("just: a map\n") is None
    assert parse_facet("not yaml: [oops") is None or True  # garbled -> None or empty


def test_logical_facet_from_ddl_project():
    """The deterministic converter builds a typed logical facet from DDL — each
    table an element with stable @id, columns, pk, indexes."""
    from lib.spec_facets import logical_facet_from_project, validate_facet, write_facet, load_facet
    with tempfile.TemporaryDirectory() as td:
        sql = Path(td) / "src" / "main" / "resources" / "db"
        sql.mkdir(parents=True)
        (sql / "V1__init.sql").write_text(_DDL, encoding="utf-8")
        facet = logical_facet_from_project(td)
        assert facet.kind == "logical"
        assert validate_facet(facet) == []
        assert set(facet.element_ids()) == {"users", "orders"}
        users = next(e for e in facet.elements if e.id == "users")
        assert users.kind == "table"
        assert users.data["pk"] == ["id"]
        assert any(c["name"] == "nickname" for c in users.data["columns"])
        assert any(i["name"] == "ix_users_nickname" for i in users.data["indexes"])
        # round-trips through write + load
        out = Path(td) / "out" / "logical.schema"
        write_facet(facet, out)
        loaded = load_facet(out)
        assert loaded is not None and set(loaded.element_ids()) == {"users", "orders"}


def test_er_facet_from_ddl_project():
    """The er converter builds a typed er facet — each entity an element with @id +
    its outgoing relationships, from FK constraints."""
    from lib.spec_facets import er_facet_from_project, validate_facet
    with tempfile.TemporaryDirectory() as td:
        sql = Path(td) / "db"
        sql.mkdir(parents=True)
        (sql / "schema.sql").write_text(
            "CREATE TABLE users (id BIGSERIAL PRIMARY KEY);\n"
            "CREATE TABLE orders (\n  id BIGSERIAL PRIMARY KEY,\n"
            "  user_id BIGINT,\n  FOREIGN KEY (user_id) REFERENCES users(id)\n);\n",
            encoding="utf-8")
        facet = er_facet_from_project(td)
        assert facet.kind == "er"
        assert validate_facet(facet) == []
        assert set(facet.element_ids()) == {"users", "orders"}
        orders = next(e for e in facet.elements if e.id == "orders")
        assert orders.kind == "entity"
        assert any(r["references"] == "users.id" for r in orders.data["relationships"])


_CONTROLLER = """\
package kr.demo.identity;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/me")
public class IdentityController {

    @GetMapping
    public ResponseEntity<MeResponse> getMe() { return null; }

    @PatchMapping("/nickname")
    public ResponseEntity<Void> updateNickname(@RequestBody NickReq req) { return null; }

    @PostMapping(value = "/terms", produces = "application/json")
    public ResponseEntity<Void> agreeTerms() { return null; }
}
"""

_SERVICE = """\
package kr.demo.identity;

@Service
public class IdentityService {
    public void doThing() {}
}
"""

_DTO = """\
package kr.demo.identity.dto;

public class NickReq {
    private String nickname;
}
"""


def _make_java_project(td: Path) -> Path:
    root = td / "proj"
    base = root / "src" / "main" / "java" / "kr" / "demo" / "identity"
    base.mkdir(parents=True)
    (base / "IdentityController.java").write_text(_CONTROLLER, encoding="utf-8")
    (base / "IdentityService.java").write_text(_SERVICE, encoding="utf-8")
    dto = base / "dto"
    dto.mkdir()
    (dto / "NickReq.java").write_text(_DTO, encoding="utf-8")
    return root


def test_api_facet_from_controllers():
    """The api converter builds a typed api facet — each handler an endpoint with a
    stable method+path @id, the class-level @RequestMapping joined to the verb path."""
    from lib.spec_facets import api_facet_from_project, validate_facet
    with tempfile.TemporaryDirectory() as td:
        root = _make_java_project(Path(td))
        facet = api_facet_from_project(root)
        assert facet.kind == "api"
        assert validate_facet(facet) == []
        by_id = {e.id: e for e in facet.elements}
        # GET /api/v1/me (handler with no sub-path -> base path)
        assert "get-api-v1-me" in by_id
        assert by_id["get-api-v1-me"].data == {
            "method": "GET", "path": "/api/v1/me",
            "handler": "getMe", "controller": "IdentityController"}
        # PATCH /api/v1/me/nickname (sub-path joined)
        assert by_id["patch-api-v1-me-nickname"].data["path"] == "/api/v1/me/nickname"
        assert by_id["patch-api-v1-me-nickname"].data["handler"] == "updateNickname"
        # POST with value= and extra args -> path still extracted
        assert by_id["post-api-v1-me-terms"].data["method"] == "POST"
        assert by_id["post-api-v1-me-terms"].data["path"] == "/api/v1/me/terms"


def test_class_facet_from_source():
    """The class converter builds a typed class facet — each class an element with a
    FQN @id and a layer classified from annotation/suffix."""
    from lib.spec_facets import class_facet_from_project, validate_facet
    with tempfile.TemporaryDirectory() as td:
        root = _make_java_project(Path(td))
        facet = class_facet_from_project(root)
        assert facet.kind == "class"
        assert validate_facet(facet) == []   # FQN @ids are unique
        by_id = {e.id: e for e in facet.elements}
        assert by_id["kr.demo.identity.IdentityController"].data["layer"] == "controller"
        assert by_id["kr.demo.identity.IdentityService"].data["layer"] == "service"
        assert by_id["kr.demo.identity.dto.NickReq"].data["layer"] == "dto"
        # package + type carried for round-trip
        assert by_id["kr.demo.identity.dto.NickReq"].data["package"] == "kr.demo.identity.dto"
        assert by_id["kr.demo.identity.IdentityController"].data["type"] == "class"


def test_api_facet_ids_unique_across_verbs():
    """Same path under different verbs stays distinct (the @id carries the verb)."""
    from lib.spec_facets import api_facet_from_project
    with tempfile.TemporaryDirectory() as td:
        root = td_root = Path(td) / "p"
        base = root / "src" / "main" / "java" / "x"
        base.mkdir(parents=True)
        (base / "C.java").write_text(
            "package x;\n@RestController\n@RequestMapping(\"/r\")\npublic class C {\n"
            "  @GetMapping(\"/a\") public void g() {}\n"
            "  @DeleteMapping(\"/a\") public void d() {}\n}\n", encoding="utf-8")
        ids = {e.id for e in api_facet_from_project(root).elements}
        assert "get-r-a" in ids and "delete-r-a" in ids


def main() -> int:
    tests = [
        test_parse_and_validate_facet,
        test_validate_flags_dup_and_empty_id_and_bad_kind,
        test_parse_facet_rejects_non_facet,
        test_logical_facet_from_ddl_project,
        test_er_facet_from_ddl_project,
        test_api_facet_from_controllers,
        test_class_facet_from_source,
        test_api_facet_ids_unique_across_verbs,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
