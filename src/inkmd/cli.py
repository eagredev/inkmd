from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inkmd import __version__, compile as compile_md
from inkmd.pdf import PAGE_SIZES
from inkmd.render import FAMILIES


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="inkmd",
        description="Compile markdown to PDF. Pure Python, zero dependencies.",
    )
    p.add_argument(
        "input",
        nargs="?",
        default="-",
        help="markdown input file ('-' or omitted reads from stdin)",
    )
    p.add_argument(
        "-o",
        "--output",
        default="-",
        help="output PDF path ('-' or omitted writes to stdout)",
    )
    p.add_argument(
        "--page-size",
        choices=sorted(PAGE_SIZES),
        default="letter",
        help="page size (default: letter)",
    )
    p.add_argument(
        "--family",
        choices=sorted(FAMILIES),
        default="helvetica",
        help="font family (default: helvetica)",
    )
    p.add_argument(
        "--no-autolinks",
        dest="autolinks",
        action="store_false",
        help="disable GFM-style autodetection of bare URLs and email addresses",
    )
    p.add_argument("--version", action="version", version=f"inkmd {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.input == "-":
        md = sys.stdin.read()
    else:
        md = Path(args.input).read_text(encoding="utf-8")

    pdf = compile_md(
        md,
        page_size=args.page_size,
        family=args.family,
        autolinks=args.autolinks,
    )

    if args.output == "-":
        sys.stdout.buffer.write(pdf)
    else:
        Path(args.output).write_bytes(pdf)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
