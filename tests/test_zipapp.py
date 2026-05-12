"""Zipapp build + execution smoke tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_zipapp.py"


@pytest.fixture(scope="module")
def built_zipapp(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a fresh zipapp into a temp dir and return its path."""
    out_dir = tmp_path_factory.mktemp("zipapp-build")
    out_path = out_dir / "inkmd.pyz"
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_zipapp", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.build(out_path)
    assert out_path.exists()
    return out_path


def test_zipapp_builds(built_zipapp: Path) -> None:
    """The build produces a non-empty .pyz file."""
    assert built_zipapp.stat().st_size > 100_000  # at least 100 KB (AFM tables alone)
    assert built_zipapp.stat().st_size < 1_000_000  # but well under 1 MB compressed


def test_zipapp_version_flag(built_zipapp: Path) -> None:
    """`inkmd.pyz --version` prints a version string."""
    result = subprocess.run(
        [sys.executable, str(built_zipapp), "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.startswith("inkmd ")


def test_zipapp_compiles_pdf(built_zipapp: Path, tmp_path: Path) -> None:
    """End-to-end: zipapp turns markdown into a valid PDF."""
    src = tmp_path / "in.md"
    src.write_text("# Zipapp test\n\nA paragraph.\n", encoding="utf-8")
    dst = tmp_path / "out.pdf"
    subprocess.run(
        [sys.executable, str(built_zipapp), str(src), "-o", str(dst)],
        check=True,
    )
    out = dst.read_bytes()
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_zipapp_matches_module_byte_for_byte(
    built_zipapp: Path, tmp_path: Path
) -> None:
    """Zipapp output and `python -m inkmd.cli` output must be identical
    for the same input. This pins the determinism property across
    distribution forms."""
    src = tmp_path / "in.md"
    src.write_text(
        "# Title\n\nBody **bold** *italic* `code`.\n", encoding="utf-8"
    )
    via_zipapp = tmp_path / "z.pdf"
    via_module = tmp_path / "m.pdf"
    subprocess.run(
        [sys.executable, str(built_zipapp), str(src), "-o", str(via_zipapp)],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "inkmd.cli", str(src), "-o", str(via_module)],
        check=True,
    )
    assert via_zipapp.read_bytes() == via_module.read_bytes()
