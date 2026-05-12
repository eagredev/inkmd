"""CLI tests — milestone 0.1.0 release polish."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from inkmd import __version__
from inkmd.cli import main


def _read_pdf(p: Path) -> bytes:
    return p.read_bytes()


def test_file_in_file_out(tmp_path: Path) -> None:
    src = tmp_path / "in.md"
    src.write_text("# Hello\n\nA paragraph.\n", encoding="utf-8")
    dst = tmp_path / "out.pdf"
    rc = main([str(src), "-o", str(dst)])
    assert rc == 0
    out = _read_pdf(dst)
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_stdin_to_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("# Hi\n"))
    dst = tmp_path / "out.pdf"
    rc = main(["-", "-o", str(dst)])
    assert rc == 0
    assert dst.read_bytes().startswith(b"%PDF-1.4\n")


def test_default_input_is_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("Body text.\n"))
    dst = tmp_path / "out.pdf"
    rc = main(["-o", str(dst)])
    assert rc == 0
    assert dst.read_bytes().startswith(b"%PDF-1.4\n")


def test_file_to_stdout(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    src = tmp_path / "in.md"
    src.write_text("Just one line.\n", encoding="utf-8")
    rc = main([str(src)])
    assert rc == 0
    out = capsysbinary.readouterr().out
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_page_size_a4(tmp_path: Path) -> None:
    src = tmp_path / "in.md"
    src.write_text("# A4\n", encoding="utf-8")
    dst = tmp_path / "out.pdf"
    rc = main([str(src), "-o", str(dst), "--page-size", "A4"])
    assert rc == 0
    out = dst.read_bytes()
    # A4 width = 595, height = 842 — appears in the /MediaBox.
    assert b"/MediaBox [0 0 595 842]" in out


def test_family_times(tmp_path: Path) -> None:
    src = tmp_path / "in.md"
    src.write_text("# Serif\n\nBody.\n", encoding="utf-8")
    dst = tmp_path / "out.pdf"
    rc = main([str(src), "-o", str(dst), "--family", "times"])
    assert rc == 0
    out = dst.read_bytes()
    assert b"/Times-Roman" in out or b"/Times-Bold" in out


def test_no_autolinks_disables_bare_url_detection(tmp_path: Path) -> None:
    src = tmp_path / "in.md"
    src.write_text("Visit https://example.com today.\n", encoding="utf-8")
    plain = tmp_path / "plain.pdf"
    auto = tmp_path / "auto.pdf"
    assert main([str(src), "-o", str(auto)]) == 0
    assert main([str(src), "-o", str(plain), "--no-autolinks"]) == 0
    # Autolinks produce /Annot ... /Subtype /Link entries; --no-autolinks
    # should produce no link annotations for a bare URL.
    assert b"/Subtype /Link" in auto.read_bytes()
    assert b"/Subtype /Link" not in plain.read_bytes()


def test_invalid_page_size_exits_with_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "in.md"
    src.write_text("x\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main([str(src), "--page-size", "tabloid"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "tabloid" in err or "invalid choice" in err


def test_invalid_family_exits_with_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "in.md"
    src.write_text("x\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main([str(src), "--family", "comic"])
    assert exc.value.code == 2


def test_missing_input_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "nope.md"
    with pytest.raises(FileNotFoundError):
        main([str(missing), "-o", str(tmp_path / "out.pdf")])


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out


# --- subprocess smoke (verifies the installed entry point wires up) ---------


def test_subprocess_module_invocation(tmp_path: Path) -> None:
    """`python -m inkmd.cli` should work as a script too."""
    src = tmp_path / "in.md"
    src.write_text("# Smoke\n", encoding="utf-8")
    dst = tmp_path / "out.pdf"
    result = subprocess.run(
        [sys.executable, "-m", "inkmd.cli", str(src), "-o", str(dst)],
        capture_output=True,
        check=True,
    )
    assert result.returncode == 0
    assert dst.read_bytes().startswith(b"%PDF-1.4\n")
