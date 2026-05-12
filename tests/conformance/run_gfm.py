"""Run inkmd against the GFM 0.29 spec test corpus.

The GFM spec extends CommonMark with five additional categories:
tables, autolinks (extension), strikethrough, task lists, and
disallowed raw HTML. We extract the spec's examples from the
canonical HTML page (see extract_gfm.py) and run them through our
parser with autolinks=True.

Usage mirrors run_commonmark.py:
    python tests/conformance/run_gfm.py [--verbose]
    python tests/conformance/run_gfm.py --section '6.5Strikethrough (extension)'
    python tests/conformance/run_gfm.py --extensions-only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inkmd.parser import parse  # noqa: E402
from html_serialise import render_document  # noqa: E402


SPEC_PATH = Path(__file__).resolve().parent / "gfm-0.29.json"

# Sections that are GFM-specific (not in CommonMark). These are the
# additive surface — for "GFM conformance" the headline number is
# these sections' pass rate.
GFM_EXTENSION_SECTIONS = {
    "4.10Tables (extension)",
    "5.3Task list items (extension)",
    "6.5Strikethrough (extension)",
    "6.9Autolinks (extension)",
    "6.11Disallowed Raw HTML (extension)",
}


def load_spec() -> list[dict]:
    if not SPEC_PATH.exists():
        print(f"ERROR: spec file not found at {SPEC_PATH}", file=sys.stderr)
        print("Run tests/conformance/extract_gfm.py first.", file=sys.stderr)
        sys.exit(2)
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def run_one(md: str) -> str:
    """Parse markdown with GFM extensions (autolinks=True)."""
    doc = parse(md, autolinks=True)
    return render_document(doc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", help="Restrict to one section.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--extensions-only",
        action="store_true",
        help="Restrict to GFM-specific sections only.",
    )
    parser.add_argument("--first-fail", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    spec = load_spec()
    if args.section:
        spec = [t for t in spec if t["section"] == args.section]
    elif args.extensions_only:
        spec = [t for t in spec if t["section"] in GFM_EXTENSION_SECTIONS]
    if not spec:
        print("no tests selected", file=sys.stderr)
        return 2

    section_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    failures: list[tuple[dict, str, str, str]] = []
    crashes: list[tuple[dict, str]] = []

    for t in spec:
        section_counts[t["section"]][1] += 1
        md, expected = t["markdown"], t["html"]
        try:
            actual = run_one(md)
        except Exception as e:  # noqa: BLE001
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
            "spec_version": "GFM 0.29 (gfm.github.com)",
            "scope": "extensions-only" if args.extensions_only else "full",
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

    scope_label = "extensions-only" if args.extensions_only else "full spec"
    print(f"GFM 0.29 conformance ({scope_label})")
    print("=" * 50)
    print(f"  Total:    {total}")
    print(f"  Passed:   {passed}  ({100 * passed / total:.1f}%)")
    print(f"  Failed:   {total - passed}")
    print(f"  Crashed:  {len(crashes)}")
    print()
    print("By section:")
    for s in sorted(section_counts):
        p, t = section_counts[s]
        pct = 100.0 * p / t if t else 0.0
        marker = "OK" if p == t else "  "
        print(f"  {s:<44s}  {p:3d}/{t:<3d}    {pct:5.1f}%  {marker}")

    show = failures if args.verbose else failures[:5]
    if failures:
        print()
        print(f"First {len(show)} failure(s):")
        print()
        for t, md, expected, actual in show:
            print(f"  Example {t['example']} [{t['section']}]:")
            print(f"    markdown:  {md!r}")
            print(f"    expected:  {expected!r}")
            print(f"    actual:    {actual!r}")
            print()

    if crashes:
        print()
        print(f"Crashes ({len(crashes)}):")
        for t, msg in crashes[:5]:
            print(f"  Example {t['example']} [{t['section']}]: {msg}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
