# inkmd

**A pure-Python markdown-to-PDF compiler. Zero system dependencies. MIT-licensed. Deterministic by default.**

## The problem

Compiling markdown to PDF should be a one-line operation. In practice, every off-the-shelf tool brings system dependencies that don't survive the trip into a stripped-down container, a serverless function, or a locked-down CI runner.

| Tool             | What it costs you                                                |
| ---------------- | ---------------------------------------------------------------- |
| wkhtmltopdf      | Deprecated since 2023; unpatched CVEs                            |
| Chrome headless  | 200 MB install; 5 to 15 seconds of cold-start latency            |
| WeasyPrint       | 350 to 550 MB of Pango, cairo, and GObject; breaks on Alpine     |
| Pandoc and LaTeX | A 3 GB texlive installation                                      |
| borb             | AGPL, so unusable in closed-source or commercial work            |

These are real costs. A Lambda function that pulls down Chrome at cold-start pays a tax every time it scales. An Alpine container that needs WeasyPrint stops being Alpine. A locked-down CI runner can't install 3 GB of texlive without an exception.

## The pitch

`inkmd` is the tool you would write yourself with a free weekend and no patience for browser dependencies. The whole compiler is around 11,000 lines of pure-Python logic. There is nothing to install at the system level. The wheel installs in under a second. Every PDF it produces is byte-identical for the same input.

That last property is the one most worth dwelling on. If you hash the markdown and the PDF, the relationship is stable forever: same input, same output, on every platform, every Python version, every run. Useful for version-controlled documents, signed audit trails, reproducible CI builds, and any workflow where "the document changed" needs to mean something more rigorous than a fresh timestamp.

## What it ships

Full CommonMark: paragraphs, the six heading levels, ordered and unordered lists with arbitrary nesting, blockquotes, fenced code, code spans, the complete left-and-right-flanking emphasis algorithm, thematic breaks, inline links, angle-bracket autolinks. The parts of GFM people actually reach for: pipe tables with alignments, bare-URL and email autolinks, strikethrough.

```python
import inkmd

pdf_bytes = inkmd.compile(open("report.md").read())
inkmd.render_file("report.md", "report.pdf")
```

Or via the CLI:

```sh
pip install inkmd
inkmd report.md -o report.pdf
```

The output uses real AFM kerning emitted via TJ arrays, blue underlined links that are clickable in any conforming reader, blockquote rules that stack side-by-side at each nesting level, tinted table headers, and a light-grey background tint behind fenced code.

## What it does not do, yet

> v0.5 is feature-complete for the markdown subset above. It does not yet render CJK text (the bundled font lacks those glyphs; Cyrillic, Greek, and Latin-Extended render through an embedded font), and running headers, footers, and page numbers are still ahead.

The full roadmap is at https://github.com/eagredev/inkmd. v0.6 ships running headers, footers, and page numbers, a generated table of contents, and PDF bookmarks. Further out sit syntax highlighting and footnotes, then right-to-left scripts and tagged-PDF accessibility at 1.0. None of these are blocked on dependencies that would compromise the zero-install premise.

## Where it fits

Continuous-integration documentation pipelines that need PDFs as build artefacts but cannot tolerate a 3 GB tool. LLM-agent applications that produce delivery documents like CVs, briefs, and reports. Reproducible audit trails where the document hash needs to be stable. Serverless rendering with cold-start latency that matters. Embedded systems where the disk budget for a PDF compiler is measured in megabytes, not gigabytes.

`inkmd` was built by Dylan Moir (https://linkedin.com/in/dylanmoir) as the first release in a portfolio targeting AI engineering and agentic software work. It is MIT-licensed, hosted at https://github.com/eagredev/inkmd, and accepts issues and pull requests. If it saves you a fight with WeasyPrint or a 200 MB browser install in your CI pipeline, a star on the repository is plenty.
