#!/usr/bin/env python3
"""Re-render every document in docs/gallery/real-world/.

Reads each ``source.md`` under ``docs/gallery/real-world/*/`` and
writes the compiled PDF to ``output.pdf`` in the same directory.
Reports per-document timing and byte counts.

Run from the repository root::

    python scripts/render_gallery.py

The gallery is rendered with ``allow_remote_images=True`` so any HTTP
image references are fetched at compile time. The fetches are the
dominant cost; expect about a second total even though inkmd itself
compiles each document in under 100 ms.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import inkmd


def main() -> int:
    gallery = REPO_ROOT / "docs" / "gallery" / "real-world"
    if not gallery.is_dir():
        print(f"error: {gallery} not found", file=sys.stderr)
        return 1

    docs = sorted(d for d in gallery.iterdir() if d.is_dir())
    if not docs:
        print(f"error: no document directories in {gallery}", file=sys.stderr)
        return 1

    print(f"{'document':40s}  {'md bytes':>10s}  {'pdf bytes':>10s}  {'time':>8s}")
    print("-" * 76)

    for d in docs:
        source = d / "source.md"
        output = d / "output.pdf"
        if not source.is_file():
            print(f"{d.name}: no source.md, skipping", file=sys.stderr)
            continue

        md = source.read_text(encoding="utf-8")
        # Most exhibits resolve their images relative to their own folder.
        # The self-render exhibit is inkmd's own README, whose image paths
        # (the hero) are relative to the repository root — render it exactly
        # as `inkmd README.md` would, from the root, so the hero embeds.
        base = REPO_ROOT if d.name == "inkmd-self-render" else d
        start = time.perf_counter()
        pdf = inkmd.compile(
            md,
            page_size="letter",
            family="helvetica",
            allow_remote_images=True,
            base_dir=base,
        )
        elapsed = time.perf_counter() - start
        output.write_bytes(pdf)

        print(f"{d.name:40s}  {len(md):>10d}  {len(pdf):>10d}  {elapsed * 1000:>6.0f} ms")

    return 0


if __name__ == "__main__":
    sys.exit(main())
