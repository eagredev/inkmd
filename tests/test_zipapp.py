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
    """The build produces a non-empty .pyz file.

    The zipapp is inkmd's featherweight tier: it excludes the bundled
    ~10 MB color-emoji font, so it stays well under 1 MB compressed."""
    assert built_zipapp.stat().st_size > 100_000  # at least 100 KB (AFM tables alone)
    assert built_zipapp.stat().st_size < 1_000_000  # but well under 1 MB compressed


def test_zipapp_excludes_emoji_font(built_zipapp: Path) -> None:
    """The zipapp must not carry the emoji font asset (it's the lite tier)."""
    import zipfile
    with zipfile.ZipFile(built_zipapp) as z:
        assert not any("assets/emoji" in n for n in z.namelist())


def test_zipapp_emoji_falls_back_to_text(built_zipapp: Path, tmp_path: Path) -> None:
    """Without the bundled font, emoji in the zipapp render via the text
    fallback rather than as images — and the compile still succeeds."""
    src = tmp_path / "in.md"
    src.write_text("Launch \U0001F680 now\n", encoding="utf-8")
    dst = tmp_path / "out.pdf"
    subprocess.run(
        [sys.executable, str(built_zipapp), str(src), "-o", str(dst)],
        check=True,
    )
    out = dst.read_bytes()
    assert out.startswith(b"%PDF-1.4\n")
    assert b"/Subtype /Image" not in out  # no emoji image XObject


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
