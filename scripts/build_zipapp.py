"""Build a single-file inkmd.pyz zipapp.

Run from the repo root: `python scripts/build_zipapp.py`. Produces
`dist/inkmd.pyz` — a self-contained executable Python archive that
can be invoked as `python inkmd.pyz in.md -o out.pdf` (or directly
on systems where the shebang resolves).

Pass `--output PATH` to write the archive somewhere other than the
default `dist/inkmd.pyz`.

The script copies `src/inkmd/` into a staging directory so the
package sits at the archive root, then runs `python -m zipapp`
against the staging directory with compression enabled. Without
the copy step, zipapp would package the *contents* of
`src/inkmd/` at the root, and the resulting archive wouldn't be
importable as `inkmd`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PKG = REPO_ROOT / "src" / "inkmd"
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "inkmd.pyz"


def build(output: Path) -> None:
    """Build the zipapp at ``output``. Parent directory is created if needed."""
    if not SOURCE_PKG.is_dir():
        raise FileNotFoundError(f"{SOURCE_PKG} not found")

    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as staging:
        staging_path = Path(staging)
        shutil.copytree(SOURCE_PKG, staging_path / "inkmd")
        # Remove the package-level __main__.py from the staging copy.
        # The non-zipapp install keeps it (for `python -m inkmd`); but
        # for the zipapp, we want a fresh top-level __main__.py that
        # zipapp generates from the --main entry point. zipapp errors
        # if both an existing __main__.py and a --main are supplied.
        pkg_main = staging_path / "inkmd" / "__main__.py"
        if pkg_main.exists():
            pkg_main.unlink()
        zipapp.create_archive(
            source=staging_path,
            target=output,
            interpreter="/usr/bin/env python3",
            main="inkmd.cli:main",
            compressed=True,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output .pyz path (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    args = parser.parse_args(argv)
    try:
        build(args.output)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    size_kb = args.output.stat().st_size / 1024
    try:
        rel = args.output.relative_to(REPO_ROOT)
    except ValueError:
        rel = args.output
    print(f"built {rel} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
