"""Extract GFM 0.29 spec examples from the HTML page.

GFM doesn't publish a JSON test suite; we scrape the canonical
spec page (saved to /tmp/gfm.html). Each example has a markdown
block and an HTML block; we keep both plus the nearest section
heading for grouping.

Special characters in the source HTML: the GFM spec uses U+2190
(LEFTWARDS ARROW) to represent literal newlines in code listings,
and U+2192 (RIGHTWARDS ARROW) to represent tabs. We restore them.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from collections import Counter
from pathlib import Path

SRC = Path(__file__).parent / "gfm-spec-source.html"
DST = Path(__file__).parent / "gfm-0.29.json"


def main() -> None:
    if not SRC.exists():
        raise SystemExit(
            f"GFM spec HTML missing: {SRC}\n"
            f"Fetch with: curl -sL https://github.github.com/gfm/ -o {SRC}"
        )

    html_doc = SRC.read_text()

    ex_pat = re.compile(
        r'<div class="example" id="example-(\d+)">(.*?)</div>\s*</div>',
        re.DOTALL,
    )
    md_pat = re.compile(
        r'<pre><code class="language-markdown">(.*?)</code></pre>',
        re.DOTALL,
    )
    html_inner_pat = re.compile(
        r'<pre><code class="language-html">(.*?)</code></pre>',
        re.DOTALL,
    )
    h_pat = re.compile(r'<h(\d)[^>]*id="[^"]*"[^>]*>(.*?)</h\1>', re.DOTALL)

    def strip_spans(s: str) -> str:
        # The GFM HTML wraps spaces inside example blocks as <span class="space"> </span>.
        # Strip the wrappers, keep the contents.
        return re.sub(r'<span class="space">(\s*)</span>', r'\1', s)

    examples = []
    for m in ex_pat.finditer(html_doc):
        n = int(m.group(1))
        block = m.group(2)
        md_m = md_pat.search(block)
        html_m = html_inner_pat.search(block)
        if not md_m or not html_m:
            continue
        md = htmllib.unescape(strip_spans(md_m.group(1))).replace("→", "\t")
        html_out = htmllib.unescape(strip_spans(html_m.group(1))).replace("→", "\t")
        snippet = html_doc[: m.start()]
        last_h = None
        for h in h_pat.finditer(snippet):
            last_h = re.sub(r"<[^>]+>", "", h.group(2)).strip()
        examples.append(
            {
                "example": n,
                "section": last_h or "Unknown",
                "markdown": md,
                "html": html_out,
            }
        )

    print(f"total examples: {len(examples)}")
    by_section = Counter(e["section"] for e in examples)
    for s, n in sorted(by_section.items(), key=lambda x: -x[1])[:20]:
        print(f"  {n:3d}  {s}")

    DST.write_text(json.dumps(examples, indent=2))
    print(f"wrote {DST}")


if __name__ == "__main__":
    main()
