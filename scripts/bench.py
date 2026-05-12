"""Benchmark inkmd against WeasyPrint+markdown.

Measures cold-start time, steady-state render time, peak RSS, and output
size. Run from the repo root:

    python scripts/bench.py

Requires two separate virtualenvs to compare against an installed
WeasyPrint cleanly. By default the script looks for:

    INKMD_VENV  = $INKMD_BENCH_VENV     (default: ./bench-venvs/inkmd)
    WEASY_VENV  = $WEASY_BENCH_VENV     (default: ./bench-venvs/weasy)

If these venvs don't exist, the script will create them and install
the relevant packages. Resulting figures are written to stdout.

Usage:
    python scripts/bench.py                  # use default venv paths
    python scripts/bench.py --output table   # print a markdown table

The benchmark uses two example documents from the repo:
  - examples/hero-sample.md  (~1 page, ~1 KB markdown)
  - examples/torture-test.md (~11 pages, ~15 KB markdown)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INKMD_VENV = REPO_ROOT / "bench-venvs" / "inkmd"
DEFAULT_WEASY_VENV = REPO_ROOT / "bench-venvs" / "weasy"


def ensure_venv(path: Path, packages: list[str]) -> Path:
    """Create venv at ``path`` if missing, install packages, return its python."""
    py = path / "bin" / "python"
    if not py.exists():
        print(f"creating venv at {path}", file=sys.stderr)
        subprocess.run([sys.executable, "-m", "venv", str(path)], check=True)
        subprocess.run(
            [str(py), "-m", "pip", "install", "--quiet"] + packages,
            check=True,
        )
    return py


def watch_rss(pid: int, peak: list[int]) -> None:
    """Poll /proc/<pid>/status, update peak[0] with max VmRSS in KB."""
    while True:
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        if kb > peak[0]:
                            peak[0] = kb
                        break
        except (FileNotFoundError, ProcessLookupError):
            return
        time.sleep(0.005)


def run_with_peak(cmd: list[str], stdin: bytes) -> tuple[float, int, bytes]:
    """Run cmd, return (wall_s, peak_rss_kb, stdout_bytes)."""
    peak = [0]
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    watcher = Thread(target=watch_rss, args=(proc.pid, peak))
    watcher.start()
    out, err = proc.communicate(input=stdin)
    watcher.join()
    t1 = time.perf_counter()
    if proc.returncode != 0:
        sys.stderr.write(err.decode())
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    return t1 - t0, peak[0], out


def bench_cold(cmd: list[str], stdin: bytes, runs: int = 5) -> dict:
    # warm filesystem cache
    run_with_peak(cmd, stdin)
    times = []
    peaks = []
    out_size = 0
    for _ in range(runs):
        t, peak, out = run_with_peak(cmd, stdin)
        times.append(t)
        peaks.append(peak)
        out_size = len(out)
    times.sort()
    peaks.sort()
    return {
        "min_s": times[0],
        "median_s": times[len(times) // 2],
        "mean_s": sum(times) / len(times),
        "max_s": times[-1],
        "peak_rss_kb": peaks[len(peaks) // 2],
        "output_bytes": out_size,
        "runs": runs,
    }


def fmt_time(t_s: float) -> str:
    if t_s < 1.0:
        return f"{t_s*1000:.0f} ms"
    return f"{t_s:.2f} s"


def fmt_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b/1024:.1f} KB"
    return f"{b/(1024*1024):.1f} MB"


def venv_size_bytes(venv: Path) -> int:
    total = 0
    for root, _, files in os.walk(venv):
        for f in files:
            p = Path(root) / f
            try:
                total += p.stat().st_size
            except FileNotFoundError:
                pass
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--inkmd-venv", type=Path, default=DEFAULT_INKMD_VENV)
    parser.add_argument("--weasy-venv", type=Path, default=DEFAULT_WEASY_VENV)
    parser.add_argument("--output", choices=["text", "table"], default="text")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    inkmd_py = ensure_venv(args.inkmd_venv, ["inkmd"])
    weasy_py = ensure_venv(args.weasy_venv, ["weasyprint", "markdown"])

    inkmd_bin = args.inkmd_venv / "bin" / "inkmd"
    weasy_code = """
import sys, markdown, weasyprint
md = sys.stdin.read()
html = markdown.markdown(md, extensions=["tables", "fenced_code"])
sys.stdout.buffer.write(weasyprint.HTML(string=html).write_pdf())
"""

    docs = {
        "small  (~1 page)": REPO_ROOT / "examples" / "hero-sample.md",
        "medium (~11 pages)": REPO_ROOT / "examples" / "torture-test.md",
    }

    results = {}
    for label, path in docs.items():
        md = path.read_text().encode()
        ink_cmd = [str(inkmd_bin)]
        weasy_cmd = [str(weasy_py), "-c", weasy_code]
        ink = bench_cold(ink_cmd, md, runs=args.runs)
        weasy = bench_cold(weasy_cmd, md, runs=args.runs)
        results[label] = {"inkmd": ink, "weasyprint": weasy, "input_bytes": len(md)}

    ink_venv_size = venv_size_bytes(args.inkmd_venv)
    weasy_venv_size = venv_size_bytes(args.weasy_venv)

    if args.output == "text":
        print()
        print(f"Install footprint")
        print(f"  inkmd venv      : {fmt_size(ink_venv_size)}")
        print(f"  weasyprint venv : {fmt_size(weasy_venv_size)}")
        print(f"  ratio (weasy/inkmd): {weasy_venv_size / ink_venv_size:.1f}x")
        for label, r in results.items():
            print()
            print(f"=== {label} ===")
            print(f"  input: {r['input_bytes']:,} bytes")
            ink = r["inkmd"]
            weasy = r["weasyprint"]
            print(f"  inkmd      median={fmt_time(ink['median_s'])} min={fmt_time(ink['min_s'])} peak_rss={ink['peak_rss_kb']/1024:.0f} MB output={fmt_size(ink['output_bytes'])}")
            print(f"  weasyprint median={fmt_time(weasy['median_s'])} min={fmt_time(weasy['min_s'])} peak_rss={weasy['peak_rss_kb']/1024:.0f} MB output={fmt_size(weasy['output_bytes'])}")
            print(f"  speed ratio (weasy/inkmd): {weasy['median_s']/ink['median_s']:.1f}x")
            print(f"  memory ratio (weasy/inkmd): {weasy['peak_rss_kb']/ink['peak_rss_kb']:.1f}x")
    else:
        # Markdown table
        print()
        print("| Metric | inkmd | WeasyPrint | Ratio |")
        print("|--------|-------|------------|-------|")
        print(f"| Install size (venv) | {fmt_size(ink_venv_size)} | {fmt_size(weasy_venv_size)} | {weasy_venv_size/ink_venv_size:.1f}x smaller |")
        for label, r in results.items():
            ink = r["inkmd"]
            weasy = r["weasyprint"]
            print(f"| Cold-start render, {label.strip()} | {fmt_time(ink['median_s'])} | {fmt_time(weasy['median_s'])} | {weasy['median_s']/ink['median_s']:.1f}x faster |")
            print(f"| Peak RSS, {label.strip()} | {ink['peak_rss_kb']/1024:.0f} MB | {weasy['peak_rss_kb']/1024:.0f} MB | {weasy['peak_rss_kb']/ink['peak_rss_kb']:.1f}x lower |")
            print(f"| Output size, {label.strip()} | {fmt_size(ink['output_bytes'])} | {fmt_size(weasy['output_bytes'])} | {ink['output_bytes']/weasy['output_bytes']:.2f}x |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
