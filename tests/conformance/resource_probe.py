"""Resource-exhaustion probe for inkmd.

Renders a series of pathological markdown inputs and reports the
time and output-size cost of each. Numbers are referenced in
docs/security.md. Re-run any time to refresh the numbers.

Usage:
    python tests/conformance/resource_probe.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

import inkmd  # noqa: E402


sys.setrecursionlimit(50_000)


def time_compile(md: str, label: str) -> None:
    t0 = time.monotonic()
    try:
        out = inkmd.compile(md)
        dt = time.monotonic() - t0
        print(f"  {label:<46s}  {dt * 1000:8.1f}ms  ok  {len(out):>9d} bytes")
    except Exception as e:  # noqa: BLE001
        dt = time.monotonic() - t0
        print(f"  {label:<46s}  {dt * 1000:8.1f}ms  ERR  {type(e).__name__}: {e}")


def main() -> int:
    print("Pathological-input probe")
    print("=" * 78)
    print()

    cases: list[tuple[str, str]] = [
        (">" * 1000 + " hi", "blockquote nest depth 1000"),
        (">" * 10_000 + " hi", "blockquote nest depth 10000"),
        ("\n".join("  " * i + "- item" for i in range(200)), "list nest depth 200"),
        ("*" * 2000, "asterisk 2000"),
        ("*a" * 1000, "(*a) repeated 1000 times"),
        ("_" * 1000 + "foo" + "_" * 1000, "underscores 1000+foo+1000"),
        (
            "| a | b |\n| - | - |\n" + ("| x | y |\n" * 5000),
            "table 5000 rows",
        ),
        (
            "| " + " | ".join(["c"] * 200) + " |\n"
            "| " + " | ".join(["-"] * 200) + " |\n"
            "| " + " | ".join(["v"] * 200) + " |\n",
            "table 200 columns",
        ),
        (f"[link]({'a' * 10_000})", "link with 10000-char URL"),
        ("*" + "*" * 5000 + "foo" + "*" * 5000 + "*", "emphasis 5000+foo+5000"),
    ]

    for md, label in cases:
        time_compile(md, label)

    print()
    print("URL-scheme handling (v0.1.0 known issue)")
    print("=" * 78)

    for md, label in [
        ("[ok](https://example.com)", "https:"),
        ("[ok](http://example.com)", "http:"),
        ("[mail](mailto:foo@example.com)", "mailto:"),
        ("[xss](javascript:alert(1))", "javascript:"),
        ("[xss](data:text/html,<script>x</script>)", "data:"),
        ("[xss](vbscript:msgbox(1))", "vbscript:"),
        ("[xss](file:///etc/passwd)", "file:"),
    ]:
        time_compile(md, label)

    print()
    print("Malformed input")
    print("=" * 78)

    # BOM, CRLF, null byte
    bom_crlf_null = b"\xef\xbb\xbf# heading\r\n\r\nfoo\x00bar\r\n".decode("utf-8")
    time_compile(bom_crlf_null, "BOM + CRLF + null byte")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
