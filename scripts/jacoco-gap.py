#!/usr/bin/env python3
"""jacoco-gap.py — JaCoCo 커버리지 갭 리스트업 도구

JaCoCo XML 리포트를 파싱해서 missed > 0 인 클래스/메서드를
Counter별(LINE/BRANCH/METHOD)로 출력한다.

Phase 17 회고 후 생성 (2026-04-11): 매번 python 일회성 스크립트로 XML을
파싱하던 반복 작업을 글로벌 도구로 영구화.

Usage:
    python ~/.claude/scripts/jacoco-gap.py [--xml PATH] [--counter LINE|BRANCH|METHOD|ALL]
                                           [--exclude PATTERN] [--summary-only]

Default XML path: backend/build/reports/jacoco/test/jacocoTestReport.xml (CWD 기준)
Default counter:  ALL
Exit code: 0 if 갭 없음, 1 if 갭 있음
"""

import sys
import os
import argparse
import xml.etree.ElementTree as ET

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def counter_of(elem, ctype):
    """주어진 element에서 특정 counter type의 (missed, covered) 반환."""
    for c in elem.findall("counter"):
        if c.get("type") == ctype:
            return int(c.get("missed")), int(c.get("covered"))
    return 0, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", default="backend/build/reports/jacoco/test/jacocoTestReport.xml",
                    help="JaCoCo XML report path")
    ap.add_argument("--counter", default="ALL",
                    choices=["LINE", "BRANCH", "METHOD", "INSTRUCTION", "ALL"])
    ap.add_argument("--exclude", default="",
                    help="제외 패턴 (콤마 구분, 부분일치)")
    ap.add_argument("--summary-only", action="store_true",
                    help="요약만 출력")
    args = ap.parse_args()

    if not os.path.exists(args.xml):
        print(f"[SKIP] JaCoCo report not found: {args.xml}")
        print("       Run `./gradlew test jacocoTestReport` first.")
        sys.exit(0)

    tree = ET.parse(args.xml)
    root = tree.getroot()

    excludes = [x.strip() for x in args.exclude.split(",") if x.strip()]
    counters_to_check = (["LINE", "BRANCH", "METHOD"]
                         if args.counter == "ALL" else [args.counter])

    # 전체 요약
    print("=" * 70)
    print(f"  jacoco-gap.py — {args.xml}")
    print("=" * 70)
    for ctype in ["INSTRUCTION", "BRANCH", "LINE", "METHOD", "CLASS"]:
        m, cv = counter_of(root, ctype)
        tot = m + cv
        pct = 100 * cv / tot if tot else 100.0
        mark = "OK" if m == 0 else "GAP"
        print(f"  [{mark}] {ctype:12} {cv}/{tot}  {pct:6.2f}%  missed={m}")
    print("-" * 70)

    if args.summary_only:
        any_gap = any(counter_of(root, c)[0] > 0 for c in counters_to_check)
        sys.exit(1 if any_gap else 0)

    # 상세 — package → class → method 순회
    gap_lines = []
    for pkg in root.findall("package"):
        pkg_name = (pkg.get("name") or "").replace("/", ".")
        for cls in pkg.findall("class"):
            cls_name = (cls.get("name") or "").replace("/", ".")
            if any(e in cls_name for e in excludes):
                continue

            # 클래스 레벨에서 갭이 있는 counter만 처리
            cls_gaps = {c: counter_of(cls, c)[0] for c in counters_to_check}
            if not any(v > 0 for v in cls_gaps.values()):
                continue

            for method in cls.findall("method"):
                mname = method.get("name")
                mline = method.get("line", "?")
                for ctype in counters_to_check:
                    missed, covered = counter_of(method, ctype)
                    if missed > 0:
                        gap_lines.append(
                            f"  [{ctype}] {cls_name}.{mname}:{mline}  "
                            f"missed={missed} covered={covered}"
                        )

    if gap_lines:
        print(f"[GAP] {len(gap_lines)} items missing coverage:")
        for line in gap_lines:
            print(line)
        print("-" * 70)
        print(f"  Total: {len(gap_lines)} gap(s)")
        print("=" * 70)
        sys.exit(1)
    else:
        print("[OK] No coverage gaps. 100% across selected counters.")
        print("=" * 70)
        sys.exit(0)


if __name__ == "__main__":
    main()
