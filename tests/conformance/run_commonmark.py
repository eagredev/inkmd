"""Run inkmd against the CommonMark 0.31.2 spec test suite.

Usage:
    python tests/conformance/run_commonmark.py [--verbose]
    python tests/conformance/run_commonmark.py --section 'Tabs'
    python tests/conformance/run_commonmark.py --first-fail

Expects the spec JSON at tests/conformance/commonmark-0.31.2.json. If
absent, prints a curl command and exits.

Output:
    Pass/fail count overall, per-section breakdown, list of first N
    failures with diff. Exit code 0 if all pass, 1 otherwise (so this
    can run in CI in the future).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Allow running as `python tests/conformance/run_commonmark.py` from repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from inkmd.parser import parse  # noqa: E402

# Avoid colliding with site-packages: explicit relative import.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from html_serialise import render_document  # noqa: E402


SPEC_PATH = Path(__file__).resolve().parent / "commonmark-0.31.2.json"
SPEC_URL = "https://spec.commonmark.org/0.31.2/spec.json"


def load_spec() -> list[dict]:
    if not SPEC_PATH.exists():
        print(f"ERROR: spec file not found at {SPEC_PATH}", file=sys.stderr)
        print(f"Fetch with: curl -sL {SPEC_URL} -o {SPEC_PATH}", file=sys.stderr)
        sys.exit(2)
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def run_one(md: str) -> str:
    """Parse markdown, serialise AST to HTML. Strict CommonMark mode
    (autolinks=False) so GFM autolinks don't accidentally pass GFM-flavoured
    cases.
    """
    doc = parse(md, autolinks=False)
    return render_document(doc)


def diff_lines(expected: str, actual: str, max_lines: int = 10) -> str:
    """Return a short side-by-side diff for the first divergent lines."""
    import difflib

    diff = list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile="expected",
            tofile="actual",
            n=2,
        )
    )
    if len(diff) > max_lines + 4:
        diff = diff[: max_lines + 4] + [f"... ({len(diff) - max_lines - 4} more lines)\n"]
    return "".join(diff) if diff else "(no diff)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--section",
        help="Restrict to one section (e.g. 'Tabs', 'ATX headings').",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every failure with diff (default: summary + first 5).",
    )
    parser.add_argument(
        "--first-fail",
        action="store_true",
        help="Stop after the first failure and print its full diff.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON summary on stdout.",
    )
    args = parser.parse_args()

    spec = load_spec()
    if args.section:
        spec = [t for t in spec if t["section"] == args.section]
        if not spec:
            print(f"no tests in section {args.section!r}", file=sys.stderr)
            return 2

    section_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [pass, total]
    failures: list[tuple[dict, str, str, str]] = []  # (test, md, expected, actual)
    crashes: list[tuple[dict, str]] = []

    for t in spec:
        section_counts[t["section"]][1] += 1
        md, expected = t["markdown"], t["html"]
        try:
            actual = run_one(md)
        except Exception as e:  # noqa: BLE001  (we want every crash classified)
            crashes.append((t, f"{type(e).__name__}: {e}"))
            actual = None

        if actual == expected:
            section_counts[t["section"]][0] += 1
        else:
            failures.append((t, md, expected, actual or ""))
            if args.first_fail:
                break

    total = sum(v[1] for v in section_counts.values())
    passed = sum(v[0] for v in section_counts.values())

    if args.json:
        out = {
            "spec_version": "0.31.2",
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "crashed": len(crashes),
            "by_section": {
                s: {"passed": v[0], "total": v[1]} for s, v in section_counts.items()
            },
        }
        print(json.dumps(out, indent=2))
        return 0 if passed == total else 1

    # Human-readable summary
    print(f"CommonMark 0.31.2 conformance")
    print(f"=============================")
    print(f"")
    print(f"  Total:    {total}")
    print(f"  Passed:   {passed}  ({100 * passed / total:.1f}%)")
    print(f"  Failed:   {total - passed}")
    print(f"  Crashed:  {len(crashes)}")
    print(f"")
    print(f"By section:")
    print(f"{'  Section':<42s}  pass/total   %")
    for s in sorted(section_counts):
        p, t = section_counts[s]
        pct = 100.0 * p / t if t else 0.0
        marker = "OK" if p == t else "  "
        print(f"  {s:<40s}  {p:3d}/{t:<3d}    {pct:5.1f}%  {marker}")

    if args.verbose:
        show = failures
    else:
        show = failures[:5]

    if failures:
        print(f"")
        print(f"First {len(show)} failure(s):")
        print(f"")
        for t, md, expected, actual in show:
            print(f"  Example {t['example']} [{t['section']}] (line {t['start_line']}):")
            print(f"    markdown:  {md!r}")
            print(f"    expected:  {expected!r}")
            print(f"    actual:    {actual!r}")
            print(f"")

    if crashes:
        print(f"")
        print(f"Crashes ({len(crashes)}):")
        for t, msg in crashes[:5]:
            print(f"  Example {t['example']} [{t['section']}]: {msg}")
            print(f"    markdown: {t['markdown']!r}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
