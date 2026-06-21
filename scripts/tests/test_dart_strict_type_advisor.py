"""Test cases for pre_tool/dart_strict_type_advisor.py

Verifies the hook fires on real example_project hotfix patterns (positive)
and stays silent on clean code / non-Dart files / non-Dio receivers (negative).

Run: python -m scripts.tests.test_dart_strict_type_advisor
"""
import json
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows so the tick marks render in cp949 console.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

HOOK = Path(__file__).resolve().parent.parent / "handlers" / "pre_tool" / "dart_strict_type_advisor.py"


def run(payload: dict) -> tuple[str, int]:
    proc = subprocess.run(
        ["python", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
    )
    return proc.stdout.strip(), proc.returncode


def assert_fires(name: str, payload: dict, must_contain: list[str]) -> None:
    out, code = run(payload)
    if code != 0 or not out:
        print(f"  ✗ {name} — expected advisory, got empty (rc={code})")
        return
    for kw in must_contain:
        if kw not in out:
            print(f"  ✗ {name} — missing '{kw}' in advisory")
            print(f"    out: {out[:200]}")
            return
    print(f"  ✓ {name}")


def assert_silent(name: str, payload: dict) -> None:
    out, code = run(payload)
    if out:
        print(f"  ✗ {name} — expected silent, got output:")
        print(f"    {out[:200]}")
        return
    print(f"  ✓ {name}")


def main() -> None:
    print("== Positive (must fire advisory) ==")

    # Stage 17 hotfix #1: raw <Map>[] in race_order_test.dart
    assert_fires(
        "Stage17-Map-raw-list",
        {"tool_name": "Write", "tool_input": {
            "file_path": "integration_test/race_order_test.dart",
            "content": "final results = <Map>[];\nresults.add({'a': 1});",
        }},
        ["raw type literal", "Map"],
    )

    # Stage 17 hotfix #2: Dio.post without type arg
    assert_fires(
        "Stage17-Dio-post",
        {"tool_name": "Edit", "tool_input": {
            "file_path": "lib/src/data/api/store_api_client.dart",
            "new_string": 'final res = await dio.post("/api/v1/orders", data: payload);',
        }},
        ["Dio/HTTP", "post"],
    )

    # Stage 17 hotfix #3: MaterialPageRoute without type arg
    assert_fires(
        "Stage17-MaterialPageRoute",
        {"tool_name": "Write", "tool_input": {
            "file_path": "lib/src/feature/menu/menu_page.dart",
            "content": "Navigator.push(context, MaterialPageRoute(builder: (_) => OrderPage()));",
        }},
        ["MaterialPageRoute"],
    )

    # Multi-finding case (Stage 17 real file had 3 in one file)
    assert_fires(
        "Combined-3-findings",
        {"tool_name": "Write", "tool_input": {
            "file_path": "/tmp/multi.dart",
            "content": (
                "final list = <Map>[];\n"
                "Navigator.push(context, MaterialPageRoute(builder: (_) => Foo()));\n"
                "final r = await dio.post('/a', data: x);\n"
            ),
        }},
        ["Map", "MaterialPageRoute", "post"],
    )

    # MultiEdit edits array
    assert_fires(
        "MultiEdit-payload",
        {"tool_name": "MultiEdit", "tool_input": {
            "file_path": "lib/foo.dart",
            "edits": [
                {"old_string": "a", "new_string": "final m = <Map>{};"},
                {"old_string": "b", "new_string": "await dio.get('/x');"},
            ],
        }},
        ["Map", "get"],
    )

    # `<List>` raw
    assert_fires(
        "List-raw-literal",
        {"tool_name": "Write", "tool_input": {
            "file_path": "/tmp/x.dart",
            "content": "final stack = <List>[];",
        }},
        ["raw type literal", "List"],
    )

    # `_dio` private receiver
    assert_fires(
        "Dio-private-receiver",
        {"tool_name": "Edit", "tool_input": {
            "file_path": "lib/api.dart",
            "new_string": "return _dio.put('/x', data: y);",
        }},
        ["put"],
    )

    print()
    print("== Negative (must stay silent) ==")

    # Already has type argument
    assert_silent("Map-with-type-arg", {"tool_name": "Write", "tool_input": {
        "file_path": "/tmp/clean.dart",
        "content": "final list = <Map<String, dynamic>>[];",
    }})

    assert_silent("Dio-with-type-arg", {"tool_name": "Write", "tool_input": {
        "file_path": "/tmp/clean.dart",
        "content": "await dio.post<Map<String, dynamic>>('/a', data: x);",
    }})

    assert_silent("MaterialPageRoute-with-type-arg", {"tool_name": "Write", "tool_input": {
        "file_path": "/tmp/clean.dart",
        "content": "Navigator.push<void>(context, MaterialPageRoute<void>(builder: (_) => F()));",
    }})

    # Non-Dart file (Python with similar tokens) — silent
    assert_silent("Non-dart-file", {"tool_name": "Write", "tool_input": {
        "file_path": "/tmp/notdart.py",
        "content": "x = list()\nresponse = repo.post('/a')",
    }})

    # Non-Dio receiver — `userRepo.post(...)` is not HTTP, must be silent
    assert_silent("Non-Dio-receiver", {"tool_name": "Edit", "tool_input": {
        "file_path": "lib/foo.dart",
        "new_string": "await userRepo.post(model);",
    }})

    # PageRouteBuilder (not MaterialPageRoute) — silent (we only target MaterialPageRoute)
    assert_silent("PageRouteBuilder-not-flagged", {"tool_name": "Write", "tool_input": {
        "file_path": "/tmp/x.dart",
        "content": "PageRouteBuilder(pageBuilder: ...)",
    }})

    # Empty payload
    assert_silent("Empty-content", {"tool_name": "Write", "tool_input": {
        "file_path": "/tmp/x.dart",
        "content": "",
    }})

    # Tool that we don't handle
    assert_silent("Bash-tool-ignored", {"tool_name": "Bash", "tool_input": {
        "command": "dart run <Map>[]",
    }})

    # File with no extension match
    assert_silent("No-extension", {"tool_name": "Write", "tool_input": {
        "file_path": "/tmp/x",
        "content": "<Map>[]",
    }})


if __name__ == "__main__":
    main()
