"""Greedy line-wrapping + page pagination.

Milestone 0.0.2 introduced single-font wrapping and pagination on plain
strings. Milestone 0.0.3 adds styled runs: a paragraph is now a list of
``Run`` records, each tagged with its own font and size, and a line is
a list of positioned runs. The single-font path remains for backward
compatibility (used by ``text_pdf``).

Strategy is unchanged:
  1. Split paragraphs into atomic units on whitespace.
  2. Greedily fill lines: add a unit if it fits, otherwise break.
  3. Single units wider than the column overflow into their own line.
  4. Lines accumulate onto a page until y_cursor crosses the bottom
     margin; then start a new page.

Coordinate system is PDF-native: origin bottom-left, y increases up.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from inkmd.fonts import text_width
from inkmd.embedded_metrics import embedded_text_width


# Default layout constants — fine-tuned in later milestones.
DEFAULT_FONT = "Helvetica"
DEFAULT_FONT_SIZE = 12.0
DEFAULT_LINE_HEIGHT = 14.4  # 1.2x font size, a typical reading leading
DEFAULT_MARGIN = 72.0  # 1 inch on all sides

# Deeply nested lists and blockquotes accumulate body_indent per level
# (18pt per list level, ~12pt per quote level). Past a few dozen levels
# the indent would exceed the text column, leaving no room for content:
# text marches off the right margin and, deeper still, off the page edge
# entirely. We clamp the effective indent so at least this many points of
# content column always remain. 90pt holds roughly a dozen characters at
# body size — enough to stay legible while still showing the nesting got
# very deep. The clamp only engages at pathological depth; ordinary
# nesting is far below it.
MIN_CONTENT_WIDTH = 90.0

# An inline emoji is drawn as a square-ish image scaled to the run's font
# size. The box height is this fraction of the font size (emoji glyphs read
# best at roughly the cap-to-descender extent, a touch larger than x-height
# text); the width follows the bitmap's aspect ratio.
EMOJI_BOX_RATIO = 1.2
# Fraction of the emoji box that drops below the text baseline, so the
# glyph's visual centre aligns with the surrounding lowercase text rather
# than sitting on the baseline like a capital letter.
EMOJI_BASELINE_DROP = 0.2


# Sentinel for "this flat override was not passed". A single-member Enum gives
# a singleton with a real type (``_Unset``), so flat-override parameters can be
# annotated ``T | _Unset`` and a type checker still narrows ``value is not
# _UNSET`` to ``T``. Distinct from any legal field value (including None and the
# field's own default), so the folding layer can tell "caller omitted it" from
# "caller passed the default".
class _Unset(Enum):
    token = 0


_UNSET = _Unset.token


@dataclass(frozen=True)
class LayoutConfig:
    """Grouped layout knobs for a compile, frozen so a shared config is safe.

    Every field's default reproduces inkmd's current hardcoded value, so a
    default-constructed ``LayoutConfig()`` renders byte-identically to passing
    no config at all. Pass one to group settings, or override a single knob
    with the matching flat keyword on :func:`inkmd.compile` /
    :func:`inkmd.render_file` (the flat keyword wins over the config's value).

    The object is immutable and hashable; build a varied config with
    ``dataclasses.replace(cfg, margin=54)`` rather than mutating in place.
    """

    page_size: str = "letter"
    """Page size identifier. ``"letter"`` (default) or ``"A4"``."""

    margin: float = 72.0
    """Page margin in points (default 72.0 = 1 inch). Mirrors DEFAULT_MARGIN."""

    font_size: float = 12.0
    """Body text size in points (default 12.0). Mirrors render.BODY_SIZE."""

    line_spacing: float = 1.2
    """Line-height multiplier of font size (default 1.2). Mirrors the
    paginate_runs line_height_ratio default."""


def fold_layout(layout, overrides):
    """Resolve the effective ``LayoutConfig`` from a config plus flat overrides.

    ``layout`` is the caller's ``LayoutConfig`` or None (None means all
    defaults). ``overrides`` maps field name to value for the flat keyword
    arguments; any value that is the ``_UNSET`` sentinel was not passed by the
    caller and is ignored. Precedence: a flat override that WAS passed wins
    over the config's value for that field. Returns a new ``LayoutConfig``.
    """
    base = layout if layout is not None else LayoutConfig()
    given = {name: value for name, value in overrides.items() if value is not _UNSET}
    if not given:
        return base
    return replace(base, **given)


@dataclass(frozen=True)
class Line:
    """A single line of text positioned on a page (in PDF coords).

    Used by the single-font path. The styled path uses ``StyledLine``.
    """
    text: str
    x: float
    y: float
    font: str
    size: float


@dataclass(frozen=True)
class EmojiImage:
    """A color-emoji glyph to be drawn as an inline image.

    Carried on a ``Run``/``PositionedRun`` whose ``text`` is the source
    emoji string (kept for copy/extraction fallback, never drawn as
    glyphs). ``image_id`` is a stable identifier (``"emoji:<hex>"``) so
    the PDF emitter deduplicates repeated emoji to one XObject.
    ``image_data`` is an ``inkmd.image_loader.ImageData`` (the glyph PNG).
    ``aspect`` is the bitmap's width/height ratio, used to size the inline
    box from the run's font size.
    """
    image_id: str
    image_data: object  # inkmd.image_loader.ImageData
    aspect: float


@dataclass(frozen=True)
class EmbeddedFontRef:
    """A reference to a document-shared embedded TrueType font.

    Carried on a ``Run``/``PositionedRun`` whose ``text`` holds codepoints
    the base-14 WinAnsi path can't represent (Cyrillic, Greek, Latin-Ext,
    …). When set, the run measures via the embedded font's advances
    (``embedded_text_width``) and emits as Identity-H CID hex
    (``show_text_cid_hex``) instead of the WinAnsi ``?`` byte.

    There is exactly ONE ref per document (the same ``font``/``font_bytes``
    object shared across every embedded run), so emission dedupes to a
    single Type0/FontFile2 object graph. ``font`` is the parsed
    :class:`~inkmd.truetype.TrueTypeFont` (used to measure); ``font_bytes``
    is the raw program embedded verbatim into ``/FontFile2``.
    """
    font: object  # inkmd.truetype.TrueTypeFont
    font_bytes: bytes


@dataclass(frozen=True)
class Run:
    """A fragment of inline text with a single font/size.

    Runs are the atomic unit of styled text. ``text`` is the literal
    string; whitespace inside it is preserved (used for the space chars
    that join wrapped lines).

    ``link_url`` is set for runs that are part of an ``[text](url)`` /
    ``<url>`` link; the layout collects per-line link extents and the
    PDF layer emits clickable annotations + a blue underline.

    ``strike`` is True for runs inside ``~~text~~`` GFM strikethrough;
    the layout collects per-line strike extents and emits a thin
    horizontal rectangle through the glyph mid-height.

    ``y_shift`` raises (positive) or lowers (negative) the run's
    baseline relative to the surrounding text. Used by superscript
    (positive shift) and subscript (negative shift). The wrapper still
    treats the run as occupying its own width on the baseline; the
    shift only moves where the glyph renders.

    ``background_fill`` is an optional (r, g, b) tuple. When set the
    PDF emitter draws a filled rectangle behind the run's glyph bounds.
    Used for ``<mark>`` highlights.

    ``border_fill`` is an optional (r, g, b) tuple. When set the PDF
    emitter draws a thin border around the run's glyph bounds. Used
    for ``<kbd>`` keyboard-key visuals.
    """
    text: str
    font: str
    size: float
    link_url: str | None = None
    color: tuple[float, float, float] | None = None  # None means default (black)
    strike: bool = False
    y_shift: float = 0.0
    background_fill: tuple[float, float, float] | None = None
    border_fill: tuple[float, float, float] | None = None
    underline: bool = False
    emoji: EmojiImage | None = None  # set => render as an inline image, not text
    embedded: EmbeddedFontRef | None = None  # set => render via the embedded font


@dataclass(frozen=True)
class PositionedRun:
    """A run with its absolute (x, y) baseline position on the page."""
    text: str
    x: float
    y: float
    font: str
    size: float
    link_url: str | None = None
    color: tuple[float, float, float] | None = None
    strike: bool = False
    y_shift: float = 0.0
    background_fill: tuple[float, float, float] | None = None
    border_fill: tuple[float, float, float] | None = None
    underline: bool = False
    emoji: EmojiImage | None = None  # set => render as an inline image, not text
    embedded: EmbeddedFontRef | None = None  # set => render via the embedded font


@dataclass(frozen=True)
class StyledLine:
    """A line composed of one or more runs sharing the same baseline."""
    runs: tuple[PositionedRun, ...]


@dataclass(frozen=True)
class Rect:
    """An axis-aligned filled rectangle on a page.

    PDF-coordinate (origin bottom-left). ``fill`` is RGB in 0..1 floats.
    Drawn *before* lines so text overlays it cleanly.
    """
    x: float
    y: float
    width: float
    height: float
    fill: tuple[float, float, float]


@dataclass(frozen=True)
class LinkAnnotation:
    """A clickable link region on a page (PDF Annot of subtype /Link).

    ``url`` is the destination; ``x``, ``y``, ``width``, ``height`` are
    the clickable bounding box in PDF coordinates. One link that wraps
    across multiple lines produces multiple annotations (one per line).
    """
    url: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class ImagePlacement:
    """A raster image placed on a page.

    ``image_id`` is a stable identifier (typically the source URL) used
    by the PDF emitter to deduplicate XObjects when the same image
    appears multiple times. ``image_data`` carries the loaded bytes
    plus dimensions (an ``inkmd.image_loader.ImageData`` instance).
    ``x`` / ``y`` are the bottom-left corner of the image's bounding
    box on the page in PDF coordinates. ``width`` / ``height`` are
    the displayed dimensions (the emitter scales source pixels via /cm).
    """
    image_id: str
    image_data: object  # inkmd.image_loader.ImageData
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class Page:
    """A list of lines that share one physical page.

    For the single-font path this holds ``Line`` records; for the styled
    path it holds ``StyledLine`` records. ``shapes`` are filled background
    rectangles drawn before the lines. ``annotations`` are clickable link
    regions emitted as PDF /Link annotations.
    """
    lines: tuple
    width: float
    height: float
    shapes: tuple = ()
    annotations: tuple = ()


def wrap_paragraph(
    text: str,
    column_width: float,
    font: str = DEFAULT_FONT,
    size: float = DEFAULT_FONT_SIZE,
) -> list[str]:
    """Greedy-wrap one paragraph to fit ``column_width`` points.

    Words are taken to be whitespace-separated runs. Single words wider
    than the column get their own line (no hyphenation); the resulting
    line will overflow visually but we don't attempt to shrink or break
    the word in v0.1.
    """
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    space_w = text_width(" ", font, size)

    for word in words[1:]:
        candidate_w = (
            text_width(current, font, size)
            + space_w
            + text_width(word, font, size)
        )
        if candidate_w <= column_width:
            current = current + " " + word
        else:
            lines.append(current)
            current = word

    lines.append(current)
    return lines


def paginate(
    paragraphs: list[str],
    page_width: float,
    page_height: float,
    margin: float = DEFAULT_MARGIN,
    font: str = DEFAULT_FONT,
    size: float = DEFAULT_FONT_SIZE,
    line_height: float = DEFAULT_LINE_HEIGHT,
    paragraph_spacing: float = 6.0,
) -> list[Page]:
    """Wrap and paginate ``paragraphs`` into one or more ``Page`` objects.

    ``margin`` applies symmetrically to all four sides. ``line_height``
    is the baseline-to-baseline distance. ``paragraph_spacing`` is
    additional gap between consecutive paragraphs.
    """
    column_width = page_width - 2 * margin
    top_y = page_height - margin
    bottom_y = margin

    pages: list[Page] = []
    current_lines: list[Line] = []
    y_cursor = top_y

    def flush_page() -> None:
        if current_lines:
            pages.append(Page(tuple(current_lines), page_width, page_height))

    for p_idx, para in enumerate(paragraphs):
        wrapped = wrap_paragraph(para, column_width, font, size)
        for w_idx, line_text in enumerate(wrapped):
            # Reserve vertical space for one line; the *baseline* sits
            # ``line_height`` below the previous baseline (or below the
            # top margin for the first line on a page).
            y_cursor -= line_height
            if y_cursor < bottom_y:
                flush_page()
                current_lines = []
                y_cursor = top_y - line_height
            current_lines.append(
                Line(text=line_text, x=margin, y=y_cursor, font=font, size=size)
            )
        # Inter-paragraph spacing (not applied after the last paragraph).
        if p_idx < len(paragraphs) - 1:
            y_cursor -= paragraph_spacing

    flush_page()
    return pages


def split_paragraphs(text: str) -> list[str]:
    """Split a plaintext blob into paragraphs on blank lines.

    Empty paragraphs are dropped. Internal newlines within a paragraph
    are flattened to spaces (we'll respect hard line breaks once
    markdown parsing lands).
    """
    raw_blocks = text.split("\n\n")
    paragraphs = []
    for block in raw_blocks:
        flattened = " ".join(block.split())
        if flattened:
            paragraphs.append(flattened)
    return paragraphs


# --- Styled-text path -----------------------------------------------------


def _runs_width(runs: list[Run]) -> float:
    """Sum the rendered width of a list of runs (base-14 or embedded)."""
    return sum(run_text_width(r) for r in runs)


def _tokenise_runs(runs: list[Run]) -> list[Run]:
    """Split each run on whitespace so wrapping has atomic units.

    The whitespace itself becomes its own run with the *previous* run's
    style, so that a leading space between two styled fragments inherits
    sensible formatting. Empty resulting fragments are dropped.
    """
    out: list[Run] = []
    for run in runs:
        # An emoji run is an atomic inline image — never split or merged,
        # and not subject to whitespace tokenisation. Emit it as-is.
        if run.emoji is not None:
            out.append(run)
            continue
        if not run.text:
            continue
        # Preserve internal whitespace as separate tokens so we can break
        # on it later. We split on any run of whitespace, keeping the
        # delimiter via a manual loop. The whitespace token inherits
        # link_url so an interior space inside a link still has the
        # underline + annotation.
        i = 0
        text = run.text
        while i < len(text):
            j = i
            if text[i].isspace():
                while j < len(text) and text[j].isspace():
                    j += 1
                # ``replace`` carries every field (incl. ``embedded``); a
                # whitespace token collapses to a single space but keeps its
                # lane so an interior space inside an embedded span measures
                # and emits on the same font.
                out.append(replace(run, text=" "))
            else:
                while j < len(text) and not text[j].isspace():
                    j += 1
                out.append(replace(run, text=text[i:j]))
            i = j
    return out


# Break points for splitting an over-wide token, in the order we prefer
# to break at. These are the boundaries a reader tolerates a break at
# inside an identifier or path: after a separator character, the split
# keeps the separator on the left piece. camelCase boundaries are
# handled separately (no character is consumed there).
_TOKEN_BREAK_AFTER = "_/.-:,;|\\"


def _token_break_points(text: str) -> list[int]:
    """Candidate break offsets within ``text``, as indices *after* which
    a line may break. Returns offsets in increasing order.

    A break after index ``k`` puts ``text[:k+1]`` on one line and
    ``text[k+1:]`` on the next. We offer breaks after any separator
    character in ``_TOKEN_BREAK_AFTER`` and at camelCase boundaries
    (a lowercase or digit immediately followed by an uppercase letter),
    where the break falls *before* the uppercase letter.
    """
    points: list[int] = []
    for k, ch in enumerate(text):
        if ch in _TOKEN_BREAK_AFTER and k < len(text) - 1:
            points.append(k)
        elif (
            k < len(text) - 1
            and (ch.islower() or ch.isdigit())
            and text[k + 1].isupper()
        ):
            # camelCase: break before the uppercase letter, i.e. after k.
            points.append(k)
    return points


def _split_run_at(run: Run, cut: int) -> tuple[Run, Run]:
    """Return two runs splitting ``run.text`` at offset ``cut`` (the
    second run starts at ``cut``), preserving all styling.

    ``replace`` carries every field forward (including ``embedded`` and
    ``emoji``), so breaking a long embedded token keeps both halves on the
    embedded font rather than silently dropping them to the WinAnsi path.
    """
    return (
        replace(run, text=run.text[:cut]),
        replace(run, text=run.text[cut:]),
    )


def _break_long_token(tok: Run, column_width: float) -> list[Run]:
    """Break a single over-wide token into pieces that each fit within
    ``column_width``, preferring sensible break points (separators,
    camelCase) and falling back to character-level splitting so even an
    unbreakable run (e.g. ``aaaaaa...``) wraps rather than overflowing.

    Returns the token unchanged (as a one-element list) if it already
    fits or ``column_width`` is non-positive.
    """
    if column_width <= 0:
        return [tok]
    # Measure substrings through the run's own path so an over-wide embedded
    # token (a long Cyrillic identifier) breaks against its embedded-font
    # widths, not WinAnsi ``?`` widths.
    def measure(text: str) -> float:
        return run_text_width(replace(tok, text=text))
    if measure(tok.text) <= column_width:
        return [tok]

    pieces: list[Run] = []
    remaining = tok
    # Guard against pathological non-termination; each iteration must
    # consume at least one character.
    while measure(remaining.text) > column_width:
        text = remaining.text
        # Find the largest prefix that fits, preferring a break point.
        breaks = _token_break_points(text)
        cut = 0
        # Prefer the furthest break point whose prefix (including the
        # separator char) still fits.
        for bp in breaks:
            prefix_len = bp + 1
            if measure(text[:prefix_len]) <= column_width:
                cut = prefix_len
            else:
                break
        if cut == 0:
            # No break point fits: fall back to character-level. Find the
            # longest character prefix that fits (at least one char).
            lo, hi = 1, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if measure(text[:mid]) <= column_width:
                    lo = mid
                else:
                    hi = mid - 1
            cut = lo
        head, tail = _split_run_at(remaining, cut)
        pieces.append(head)
        remaining = tail
    pieces.append(remaining)
    return pieces


def wrap_runs(
    runs: list[Run],
    column_width: float,
) -> list[list[Run]]:
    """Greedy-wrap a list of runs into lines that fit ``column_width``.

    Each returned line is a list of runs; concatenating their texts
    gives the line's visible string. Leading and trailing whitespace
    runs on each wrapped line are stripped.

    Tokens wider than ``column_width`` (long inline code spans, URLs,
    identifiers) are broken at sensible points so they wrap inside the
    column rather than overflowing its right edge. This matches how
    GitHub renders long code in narrow table cells.
    """
    tokens = _tokenise_runs(runs)
    if not tokens:
        return []

    lines: list[list[Run]] = []
    current: list[Run] = []
    current_width = 0.0

    def is_space(tok: Run) -> bool:
        return tok.text == " "

    def strip_edges(line: list[Run]) -> list[Run]:
        while line and is_space(line[0]):
            line.pop(0)
        while line and is_space(line[-1]):
            line.pop()
        return line

    def place(tok: Run) -> None:
        # Place a single (already-fitting-or-space) token, wrapping the
        # current line first if it would overflow.
        nonlocal current, current_width
        tok_w = _run_width(tok)
        if not current and is_space(tok):
            return  # don't start a wrapped line with leading whitespace
        if current_width + tok_w <= column_width or not current:
            current.append(tok)
            current_width += tok_w
        else:
            lines.append(strip_edges(current))
            if is_space(tok):
                current = []
                current_width = 0.0
            else:
                current = [tok]
                current_width = tok_w

    for tok in tokens:
        # Hard-break sentinel: force a line break and consume the token.
        # The HardBreak inline emits a single-char run with text "\x00".
        if tok.text == "\x00":
            lines.append(strip_edges(current))
            current = []
            current_width = 0.0
            continue
        tok_w = _run_width(tok)
        # A token wider than the whole column can never fit on one line;
        # break it at sensible points so it wraps inside the column
        # instead of overflowing the right edge. Each resulting piece is
        # placed through the normal fit logic. Emoji are atomic images and
        # are never broken — they place as-is even if pathologically large.
        if not is_space(tok) and tok.emoji is None and tok_w > column_width:
            for piece in _break_long_token(tok, column_width):
                place(piece)
            continue
        place(tok)

    if current:
        lines.append(strip_edges(current))
    return [ln for ln in lines if ln]


def emoji_box(size: float, aspect: float) -> tuple[float, float]:
    """Return the (width, height) in points of an inline emoji box drawn
    at font ``size`` with bitmap ``aspect`` (width/height)."""
    height = size * EMOJI_BOX_RATIO
    return height * aspect, height


def run_text_width(run) -> float:
    """Measured glyph width of a run's text, routing embedded runs to S2.

    The single decision point for "how wide is this run's text": a run
    tagged with an :class:`EmbeddedFontRef` measures via the embedded
    font's own advances (``embedded_text_width``); every other run uses
    the base-14 WinAnsi ``text_width``. Accepts any object exposing
    ``text``/``font``/``size`` and (optionally) ``embedded`` — both
    ``Run`` and ``PositionedRun`` — so every run-text measurement site
    (line accumulation, link/strike/background/border/underline extents)
    shares one embedded/base-14 dispatch and no embedded run is ever
    measured as a WinAnsi ``?``.
    """
    embedded = getattr(run, "embedded", None)
    if embedded is not None:
        return embedded_text_width(embedded.font, run.text, run.size)
    return text_width(run.text, run.font, run.size)


def _run_width(run: Run) -> float:
    """Advance width of a run: the emoji box width for emoji runs,
    otherwise the measured text width (base-14 or embedded)."""
    if run.emoji is not None:
        return emoji_box(run.size, run.emoji.aspect)[0]
    return run_text_width(run)


def _line_max_size(line: list[Run]) -> float:
    """Largest font size on a line, used to set the line's leading."""
    return max((r.size for r in line), default=DEFAULT_FONT_SIZE)


@dataclass(frozen=True)
class _BlockParts:
    """Normalised paginator input: runs, spacing, indent, optional marker."""
    runs: list[Run]
    space_above: float
    space_below: float
    body_indent: float
    marker_runs: tuple[Run, ...]
    marker_x: float
    compact: bool  # if True, suppress the default paragraph_spacing gap before this block
    page_break: bool  # if True, a content-free forced page break (CSS page-break div)
    left_rules: tuple[float, ...]
    left_rule_fill: tuple[float, float, float]
    background_fill: tuple[float, float, float] | None
    bg_padding: float
    preserve_lines: bool
    prepositioned: bool
    prepositioned_lines: tuple
    prepositioned_line_heights: tuple
    prepositioned_shapes: tuple
    prepositioned_table: dict | None


def _block_parts(block) -> _BlockParts:
    """Normalise a paginator input element.

    Accepts a bare ``list[Run]`` (treated as a plain paragraph with no
    extra spacing or indent) or any object exposing the relevant
    attributes (e.g. ``render.RenderedBlock``). The layout module
    deliberately does not import render to keep the layer order clean.
    """
    if hasattr(block, "runs"):
        bg = getattr(block, "background_fill", None)
        rules = getattr(block, "left_rules", ())
        return _BlockParts(
            runs=list(block.runs),
            space_above=float(getattr(block, "space_above", 0.0)),
            space_below=float(getattr(block, "space_below", 0.0)),
            body_indent=float(getattr(block, "body_indent", 0.0)),
            marker_runs=tuple(getattr(block, "marker_runs", ())),
            marker_x=float(getattr(block, "marker_x", 0.0)),
            compact=bool(getattr(block, "compact", False)),
            page_break=bool(getattr(block, "page_break", False)),
            left_rules=tuple(float(r) for r in rules),
            left_rule_fill=tuple(getattr(block, "left_rule_fill", (0.6, 0.6, 0.6))),
            background_fill=tuple(bg) if bg is not None else None,
            bg_padding=float(getattr(block, "bg_padding", 4.0)),
            preserve_lines=bool(getattr(block, "preserve_lines", False)),
            prepositioned=bool(getattr(block, "prepositioned", False)),
            prepositioned_lines=tuple(getattr(block, "prepositioned_lines", ())),
            prepositioned_line_heights=tuple(getattr(block, "prepositioned_line_heights", ())),
            prepositioned_shapes=tuple(getattr(block, "prepositioned_shapes", ())),
            prepositioned_table=getattr(block, "prepositioned_table", None),
        )
    return _BlockParts(
        runs=list(block),
        space_above=0.0,
        space_below=0.0,
        body_indent=0.0,
        marker_runs=(),
        marker_x=0.0,
        compact=False,
        page_break=False,
        left_rules=(),
        left_rule_fill=(0.6, 0.6, 0.6),
        background_fill=None,
        bg_padding=4.0,
        preserve_lines=False,
        prepositioned=False,
        prepositioned_lines=(),
        prepositioned_line_heights=(),
        prepositioned_shapes=(),
        prepositioned_table=None,
    )


def paginate_runs(
    paragraphs,
    page_width: float,
    page_height: float,
    margin: float = DEFAULT_MARGIN,
    line_height_ratio: float = 1.2,
    paragraph_spacing: float = 6.0,
) -> list[Page]:
    """Wrap and paginate styled blocks into ``Page`` records.

    Each element of ``paragraphs`` is either a bare ``list[Run]`` (plain
    paragraph) or a ``RenderedBlock``-like carrier with optional
    ``space_above`` / ``space_below`` hints (additive to the default
    inter-block spacing). Line height is set per-line as
    ``line_height_ratio * max font size on the line``. Page breaks fire
    when the next line's baseline would fall below the bottom margin;
    space-above before a block is suppressed at the top of a fresh page.
    """
    column_width = page_width - 2 * margin
    top_y = page_height - margin
    bottom_y = margin

    pages: list[Page] = []
    current_lines: list[StyledLine] = []
    current_shapes: list[Rect] = []
    current_annotations: list[LinkAnnotation] = []
    y_cursor = top_y

    def flush_page() -> None:
        # Flush whenever the page has content of any kind. Pages whose
        # only content is image placements (no lines) must still emit.
        if current_lines or current_shapes or current_annotations:
            pages.append(
                Page(
                    tuple(current_lines),
                    page_width,
                    page_height,
                    shapes=tuple(current_shapes),
                    annotations=tuple(current_annotations),
                )
            )

    for p_idx, raw_block in enumerate(paragraphs):
        parts = _block_parts(raw_block)

        # Forced page break (CSS page-break div): close the current page and
        # start a fresh one, then place no content for this block (it has
        # none). Flush only when the current page already holds content, so
        # a leading break emits no blank first page, two consecutive breaks
        # collapse to one, and a trailing break leaves no empty page (the
        # final flush_page below skips an empty page). Reuses the same
        # flush_page + accumulator reset the overflow path uses.
        if parts.page_break:
            page_has_content = bool(
                current_lines or current_shapes or current_annotations
            )
            if page_has_content:
                flush_page()
                current_lines = []
                current_shapes = []
                current_annotations = []
                y_cursor = top_y
            continue

        if p_idx > 0 and parts.space_above and current_lines:
            y_cursor -= parts.space_above

        # Clamp the indent so a minimum content column always survives.
        # Deep nesting (lists/blockquotes) would otherwise push body_indent
        # past column_width, collapsing the content column to zero or
        # negative width and marching text (or a prepositioned table/image)
        # off the page. The marker shifts left by the same delta so it
        # stays anchored to its body text. Computed before the
        # prepositioned branch so both paths share the clamped indent.
        max_indent = max(0.0, column_width - MIN_CONTENT_WIDTH)
        body_indent = min(parts.body_indent, max_indent)
        indent_delta = parts.body_indent - body_indent
        marker_x = parts.marker_x - indent_delta

        # Splittable table: place row groups (header + per body row) top to
        # bottom, breaking at row boundaries across pages and repeating the
        # header at the top of each page-slice, instead of overflowing off
        # the bottom. Grid: each slice draws verticals spanning the slice
        # height plus a bottom rule, so every page-fragment is fully boxed.
        if parts.prepositioned and parts.prepositioned_table is not None:
            tbl = parts.prepositioned_table
            prepos_x0 = margin + body_indent
            header = tbl["header"]
            grid_w = tbl["grid_width"]
            grid_fill = tbl["grid_fill"]
            table_width = tbl["table_width"]
            col_x = tbl["col_x"]

            def place_group(group: dict, group_top_y: float) -> None:
                """Place one row group with its top at absolute y group_top_y.
                Emits the group's fills/images/text lines + decorations."""
                for sh in group["shapes"]:
                    kind = sh.get("kind", "fill")
                    if kind == "image":
                        current_shapes.append(ImagePlacement(
                            image_id=sh["image_id"],
                            image_data=sh["image_data"],
                            x=prepos_x0 + sh["x_offset"],
                            y=group_top_y - sh["rel_y_top"] - sh["height"],
                            width=sh["width"],
                            height=sh["height"],
                        ))
                    else:
                        current_shapes.append(Rect(
                            x=prepos_x0 + sh["x_offset"],
                            y=group_top_y - sh["rel_y_top"] - sh["height"],
                            width=sh["width"],
                            height=sh["height"],
                            fill=sh["fill"],
                        ))
                for baseline_from_top, runs_record in group["lines"]:
                    positioned_list = [
                        PositionedRun(
                            text=pr.text,
                            x=prepos_x0 + pr.x_rel,
                            y=group_top_y - pr.y_from_top,
                            font=pr.font, size=pr.size,
                            link_url=getattr(pr, "link_url", None),
                            color=getattr(pr, "color", None),
                            strike=getattr(pr, "strike", False),
                            y_shift=getattr(pr, "y_shift", 0.0),
                            background_fill=getattr(pr, "background_fill", None),
                            border_fill=getattr(pr, "border_fill", None),
                            underline=getattr(pr, "underline", False),
                        )
                        for pr in runs_record
                    ]
                    current_lines.append(StyledLine(tuple(positioned_list)))
                    for bg_rect in _background_decorations(positioned_list):
                        current_shapes.append(bg_rect)
                    for bd_rect in _border_decorations(positioned_list):
                        current_shapes.append(bd_rect)
                    for ul_rect, ann in _link_decorations(positioned_list):
                        current_shapes.append(ul_rect)
                        current_annotations.append(ann)
                    for u_rect in _underline_decorations(positioned_list):
                        current_shapes.append(u_rect)
                    for sk_rect in _strike_decorations(positioned_list):
                        current_shapes.append(sk_rect)

            def draw_slice_grid(slice_top_y: float, slice_h: float) -> None:
                """Vertical column rules spanning this slice + the bottom rule.
                (Each group already carries its own top horizontal rule via a
                fill shape, so per-row separators come for free.)"""
                for vx in list(col_x) + [table_width]:
                    current_shapes.append(Rect(
                        x=prepos_x0 + vx - grid_w / 2.0,
                        y=slice_top_y - slice_h,
                        width=grid_w,
                        height=slice_h,
                        fill=grid_fill,
                    ))
                # Bottom rule of the slice.
                current_shapes.append(Rect(
                    x=prepos_x0,
                    y=slice_top_y - slice_h - grid_w / 2.0,
                    width=table_width,
                    height=grid_w,
                    fill=grid_fill,
                ))

            header_h = header["height"]

            def page_room() -> float:
                return y_cursor - bottom_y

            # If the header + at least one row can't fit in the remaining
            # space (and the page already has content), start fresh first.
            first_row_h = tbl["rows"][0]["height"] if tbl["rows"] else 0.0
            need = header_h + first_row_h
            page_has_content = bool(
                current_lines or current_shapes or current_annotations
            )
            if page_room() < need and page_has_content:
                flush_page()
                current_lines = []
                current_shapes = []
                current_annotations = []
                y_cursor = top_y

            # Place header + rows, slicing across pages. slice_top is the y
            # of the current slice's top; slice_h accumulates placed height
            # so the grid can be drawn when the slice ends.
            slice_top = y_cursor
            slice_h = 0.0
            place_group(header, y_cursor)
            slice_h += header_h
            y_cursor -= header_h

            for row in tbl["rows"]:
                rh = row["height"]
                # If this row won't fit, close the current slice (draw its
                # grid), flush, open a new page, repeat the header.
                if y_cursor - rh < bottom_y and slice_h > 0:
                    draw_slice_grid(slice_top, slice_h)
                    flush_page()
                    current_lines = []
                    current_shapes = []
                    current_annotations = []
                    y_cursor = top_y
                    slice_top = y_cursor
                    slice_h = 0.0
                    place_group(header, y_cursor)
                    slice_h += header_h
                    y_cursor -= header_h
                place_group(row, y_cursor)
                slice_h += rh
                y_cursor -= rh

            draw_slice_grid(slice_top, slice_h)

            # Space below + next-block spacing, mirroring the atomic path.
            if p_idx < len(paragraphs) - 1:
                y_cursor -= parts.space_below
                next_parts = _block_parts(paragraphs[p_idx + 1])
                if not next_parts.compact:
                    y_cursor -= paragraph_spacing
            continue

        # Prepositioned content (tables): atomic placement, translate
        # relative coordinates to absolute.
        if parts.prepositioned:
            # Compute the table's total height from the deepest line / shape.
            total_h = 0.0
            for shape_dict in parts.prepositioned_shapes:
                bottom = shape_dict["rel_y_top"] + shape_dict["height"]
                if bottom > total_h:
                    total_h = bottom
            for line_record in parts.prepositioned_lines:
                _baseline_from_top, _runs = line_record
                if _baseline_from_top > total_h:
                    total_h = _baseline_from_top
            # If the block doesn't fit in the remaining space on the
            # current page, flush and start fresh — but only if the page
            # already holds content (text lines, shapes, or annotations).
            # Gating on text lines alone meant a block placed after an
            # image-only page (no text) was crammed on regardless and
            # overflowed the bottom margin (or off-page entirely, losing
            # content). An empty page never flushes, so a block taller
            # than a whole page still places atomically and overflows by
            # design rather than looping.
            page_has_content = bool(
                current_lines or current_shapes or current_annotations
            )
            if y_cursor - total_h < bottom_y and page_has_content:
                flush_page()
                current_lines = []
                current_shapes = []
                current_annotations = []
                y_cursor = top_y
            table_top_y = y_cursor
            # Translate every relative shape to its absolute placement.
            # "fill" shapes become filled Rects; "image" shapes become
            # ImagePlacements that the PDF emitter resolves to /XObject
            # references.
            # Prepositioned content (tables, block images) carries its own
            # relative coordinate system. Apply body_indent so a table or
            # image nested in a blockquote/list shifts right with the body
            # rather than rendering at the bare page margin.
            prepos_x0 = margin + body_indent
            for shape_dict in parts.prepositioned_shapes:
                kind = shape_dict.get("kind", "fill")
                if kind == "image":
                    placement = ImagePlacement(
                        image_id=shape_dict["image_id"],
                        image_data=shape_dict["image_data"],
                        x=prepos_x0 + shape_dict["x_offset"],
                        y=table_top_y - shape_dict["rel_y_top"] - shape_dict["height"],
                        width=shape_dict["width"],
                        height=shape_dict["height"],
                    )
                    current_shapes.append(placement)
                else:
                    rect = Rect(
                        x=prepos_x0 + shape_dict["x_offset"],
                        y=table_top_y - shape_dict["rel_y_top"] - shape_dict["height"],
                        width=shape_dict["width"],
                        height=shape_dict["height"],
                        fill=shape_dict["fill"],
                    )
                    current_shapes.append(rect)
            # Translate every relative positioned-run line.
            for baseline_from_top, runs_record in parts.prepositioned_lines:
                positioned_list = []
                for pr in runs_record:
                    positioned_list.append(
                        PositionedRun(
                            text=pr.text,
                            x=prepos_x0 + pr.x_rel,
                            y=table_top_y - pr.y_from_top,
                            font=pr.font,
                            size=pr.size,
                            link_url=getattr(pr, "link_url", None),
                            color=getattr(pr, "color", None),
                            strike=getattr(pr, "strike", False),
                            y_shift=getattr(pr, "y_shift", 0.0),
                            background_fill=getattr(pr, "background_fill", None),
                            border_fill=getattr(pr, "border_fill", None),
                            underline=getattr(pr, "underline", False),
                        )
                    )
                current_lines.append(StyledLine(tuple(positioned_list)))
                # Backgrounds first (rendered behind text by the PDF
                # emitter), then borders, then underlines/strikes.
                for bg_rect in _background_decorations(positioned_list):
                    current_shapes.append(bg_rect)
                for bd_rect in _border_decorations(positioned_list):
                    current_shapes.append(bd_rect)
                for ul_rect, ann in _link_decorations(positioned_list):
                    current_shapes.append(ul_rect)
                    current_annotations.append(ann)
                for u_rect in _underline_decorations(positioned_list):
                    current_shapes.append(u_rect)
                for sk_rect in _strike_decorations(positioned_list):
                    current_shapes.append(sk_rect)
            y_cursor = table_top_y - total_h
            if p_idx < len(paragraphs) - 1:
                y_cursor -= parts.space_below
                next_parts = _block_parts(paragraphs[p_idx + 1])
                if not next_parts.compact:
                    y_cursor -= paragraph_spacing
            continue

        body_column_width = column_width - body_indent

        if parts.preserve_lines:
            # Code-block wrap column: left is body_indent (already in
            # body_column_width); also reserve bg_padding of right
            # padding so the rightmost glyph doesn't crash into the
            # background fill edge.
            code_column = body_column_width - parts.bg_padding
            wrapped = _split_preserved_lines(parts.runs, code_column)
        else:
            wrapped = wrap_runs(parts.runs, body_column_width) if parts.runs else [[]]

        first_line = True
        # Track per-page top/bottom for background fill that spans the block.
        block_top_on_page: float | None = None
        block_bottom_on_page: float | None = None

        def emit_bg_rect() -> None:
            nonlocal current_shapes
            if (
                parts.background_fill is not None
                and block_top_on_page is not None
                and block_bottom_on_page is not None
            ):
                # Inset the fill to the block's body indent so a code block
                # inside a blockquote does not paint over the quote's left
                # rule bars (the bg used to start at the page margin and
                # cover the indent entirely). The text sits at
                # margin + body_indent; the fill starts one bg_padding to
                # its left and runs to the right margin, preserving the
                # symmetric padding a top-level code block already has
                # (where body_indent == bg_padding, so x_start == margin).
                x_start = margin + body_indent - parts.bg_padding
                width = (page_width - margin) - x_start
                top = block_top_on_page + parts.bg_padding
                bottom = block_bottom_on_page - parts.bg_padding
                current_shapes.append(
                    Rect(
                        x=x_start,
                        y=bottom,
                        width=width,
                        height=top - bottom,
                        fill=parts.background_fill,
                    )
                )

        for line in wrapped:
            line_height = line_height_ratio * (
                _line_max_size(line) if line else DEFAULT_FONT_SIZE
            )
            # Tentatively place baseline at y_cursor - line_height.
            new_y = y_cursor - line_height
            if new_y < bottom_y:
                # Emit pending background for the just-completed page region.
                emit_bg_rect()
                block_top_on_page = None
                block_bottom_on_page = None
                flush_page()
                current_lines = []
                current_shapes = []
                current_annotations = []
                y_cursor = top_y
                new_y = y_cursor - line_height
            y_cursor = new_y

            if block_top_on_page is None:
                block_top_on_page = y_cursor + line_height  # top of this line
            block_bottom_on_page = y_cursor  # baseline; bottom-padding accounts for descender

            x = margin + body_indent
            positioned: list[PositionedRun] = []
            if first_line and parts.marker_runs:
                mx = margin + marker_x
                for mrun in parts.marker_runs:
                    positioned.append(
                        PositionedRun(
                            text=mrun.text,
                            x=mx,
                            y=y_cursor,
                            font=mrun.font,
                            size=mrun.size,
                        )
                    )
                    mx += run_text_width(mrun)
            for run in line:
                positioned.append(
                    PositionedRun(
                        text=run.text,
                        x=x,
                        y=y_cursor,
                        font=run.font,
                        size=run.size,
                        link_url=run.link_url,
                        color=run.color,
                        strike=run.strike,
                        y_shift=run.y_shift,
                        background_fill=run.background_fill,
                        border_fill=run.border_fill,
                        underline=run.underline,
                        emoji=run.emoji,
                        embedded=run.embedded,
                    )
                )
                if run.emoji is not None:
                    # Draw the emoji as an inline image. Its box sits on the
                    # text baseline: bottom = baseline - descent, so the
                    # glyph aligns with surrounding text rather than floating.
                    e_w, e_h = emoji_box(run.size, run.emoji.aspect)
                    descent = e_h * EMOJI_BASELINE_DROP
                    current_shapes.append(
                        ImagePlacement(
                            image_id=run.emoji.image_id,
                            image_data=run.emoji.image_data,
                            x=x,
                            y=y_cursor - descent,
                            width=e_w,
                            height=e_h,
                        )
                    )
                x += _run_width(run)
            current_lines.append(StyledLine(tuple(positioned)))
            # Backgrounds first (under text), then borders, then
            # link/explicit underlines, then strikes.
            for bg_rect in _background_decorations(positioned):
                current_shapes.append(bg_rect)
            for bd_rect in _border_decorations(positioned):
                current_shapes.append(bd_rect)
            for ul_rect, ann in _link_decorations(positioned):
                current_shapes.append(ul_rect)
                current_annotations.append(ann)
            for u_rect in _underline_decorations(positioned):
                current_shapes.append(u_rect)
            for sk_rect in _strike_decorations(positioned):
                current_shapes.append(sk_rect)
            # Per-line left rules for blockquotes. Multiple rules =
            # nested quote depth, each at its own x offset. Shift them by
            # the same indent_delta the body was clamped by, so the rules
            # stay anchored to their content; drop any that would still
            # fall outside the right margin once shifted (extreme depth).
            right_limit = page_width - margin
            for rule_x_rel in parts.left_rules:
                rule_w = 2.0
                rule_x = margin + rule_x_rel - indent_delta
                if rule_x < margin or rule_x + rule_w > right_limit:
                    continue
                current_shapes.append(
                    Rect(
                        x=rule_x,
                        y=y_cursor - 2.0,
                        width=rule_w,
                        height=line_height,
                        fill=parts.left_rule_fill,
                    )
                )
            first_line = False

        # Emit background fill for this block on this page.
        emit_bg_rect()

        if p_idx < len(paragraphs) - 1:
            y_cursor -= parts.space_below
            next_parts = _block_parts(paragraphs[p_idx + 1])
            if not next_parts.compact:
                y_cursor -= paragraph_spacing

    flush_page()
    return pages


def _link_decorations(
    positioned: list[PositionedRun],
) -> list[tuple[Rect, LinkAnnotation]]:
    """Group adjacent same-URL runs on one line into ``(underline, annot)`` pairs.

    Each contiguous run of same-URL runs yields:
      - A thin filled rectangle below the baseline (the visible underline).
      - A LinkAnnotation covering the full text extent + a couple of
        points of vertical padding (the clickable area).

    Non-adjacent same-URL runs (e.g. ``[a](u) [b](u)``) become separate
    pairs — that's the correct behaviour for two distinct links that
    happen to share a URL.
    """
    out: list[tuple[Rect, LinkAnnotation]] = []
    i = 0
    n = len(positioned)
    while i < n:
        run = positioned[i]
        if run.link_url is None:
            i += 1
            continue
        url = run.link_url
        start_x = run.x
        last_run = run
        j = i + 1
        while j < n and positioned[j].link_url == url:
            last_run = positioned[j]
            j += 1
        end_x = last_run.x + run_text_width(last_run)
        baseline_y = run.y
        size = run.size
        underline_thickness = max(0.5, size * 0.05)
        underline_offset = size * 0.12  # below baseline
        ul = Rect(
            x=start_x,
            y=baseline_y - underline_offset - underline_thickness,
            width=end_x - start_x,
            height=underline_thickness,
            fill=run.color or (0.0, 0.0, 0.0),
        )
        # Annotation rect: a bit taller than the underline, encompassing
        # the glyph height. PDF readers usually highlight on hover.
        ann_h = size * 1.1
        ann_y = baseline_y - underline_offset - underline_thickness
        ann = LinkAnnotation(
            url=url,
            x=start_x,
            y=ann_y,
            width=end_x - start_x,
            height=ann_h,
        )
        out.append((ul, ann))
        i = j
    return out


def _background_decorations(positioned: list[PositionedRun]) -> list[Rect]:
    """Yield a filled rect behind each run that has background_fill set.

    Used by the HTML allow-list ``<mark>`` highlight. Adjacent runs with
    the same fill colour merge into one rect to minimise PDF byte
    output and produce a single visual block.
    """
    out: list[Rect] = []
    i = 0
    n = len(positioned)
    while i < n:
        run = positioned[i]
        bg = run.background_fill
        if bg is None:
            i += 1
            continue
        start_x = run.x
        last_run = run
        j = i + 1
        while j < n and positioned[j].background_fill == bg:
            last_run = positioned[j]
            j += 1
        end_x = last_run.x + run_text_width(last_run)
        size = run.size
        # Vertical extents: from a little below baseline to about the
        # glyph top, with small padding so glyph ascenders aren't clipped.
        descender = size * 0.20
        ascender = size * 0.95
        out.append(
            Rect(
                x=start_x - 1.0,
                y=run.y - descender,
                width=end_x - start_x + 2.0,
                height=descender + ascender,
                fill=bg,
            )
        )
        i = j
    return out


def _underline_decorations(positioned: list[PositionedRun]) -> list[Rect]:
    """Yield a thin filled rect below each run with ``underline=True``.

    Distinct from link underlines: link underlines come from link_url
    being set; this is the explicit ``<u>`` form. Visual rule shared:
    same thickness, same baseline offset.
    """
    out: list[Rect] = []
    i = 0
    n = len(positioned)
    while i < n:
        run = positioned[i]
        if not run.underline:
            i += 1
            continue
        start_x = run.x
        last_run = run
        j = i + 1
        while j < n and positioned[j].underline:
            last_run = positioned[j]
            j += 1
        end_x = last_run.x + run_text_width(last_run)
        size = run.size
        thickness = max(0.5, size * 0.05)
        offset = size * 0.12
        out.append(
            Rect(
                x=start_x,
                y=run.y - offset - thickness,
                width=end_x - start_x,
                height=thickness,
                fill=run.color or (0.0, 0.0, 0.0),
            )
        )
        i = j
    return out


def _border_decorations(positioned: list[PositionedRun]) -> list[Rect]:
    """Yield border-stroke rects around each run with ``border_fill`` set.

    Used by the HTML allow-list ``<kbd>`` keyboard-key visual: a thin
    grey rectangle just outside the run's glyph bounds. Emitted as four
    Rects (top, bottom, left, right) per merged group so the existing
    fill-based shape pipeline can paint them without needing a new
    stroke primitive in the PDF emitter.
    """
    out: list[Rect] = []
    i = 0
    n = len(positioned)
    while i < n:
        run = positioned[i]
        border = run.border_fill
        if border is None:
            i += 1
            continue
        start_x = run.x
        last_run = run
        j = i + 1
        while j < n and positioned[j].border_fill == border:
            last_run = positioned[j]
            j += 1
        end_x = last_run.x + run_text_width(last_run)
        size = run.size
        descender = size * 0.20
        ascender = size * 0.90
        pad = 1.0
        x = start_x - pad
        y = run.y - descender
        w = end_x - start_x + 2 * pad
        h = descender + ascender
        thick = 0.5
        # Four border strips: top, bottom, left, right.
        out.append(Rect(x=x, y=y + h - thick, width=w, height=thick, fill=border))
        out.append(Rect(x=x, y=y, width=w, height=thick, fill=border))
        out.append(Rect(x=x, y=y, width=thick, height=h, fill=border))
        out.append(Rect(x=x + w - thick, y=y, width=thick, height=h, fill=border))
        i = j
    return out


def _strike_decorations(positioned: list[PositionedRun]) -> list[Rect]:
    """Group adjacent strike runs on one line into horizontal-bar rectangles.

    Each contiguous run of struck runs yields one thin filled rectangle
    crossing the glyph mid-height. Non-adjacent struck runs (separated
    by a non-struck run) become separate bars.
    """
    out: list[Rect] = []
    i = 0
    n = len(positioned)
    while i < n:
        run = positioned[i]
        if not run.strike:
            i += 1
            continue
        start_x = run.x
        last_run = run
        j = i + 1
        while j < n and positioned[j].strike:
            last_run = positioned[j]
            j += 1
        end_x = last_run.x + run_text_width(last_run)
        size = run.size
        thickness = max(0.5, size * 0.06)
        # Strike sits roughly at the visual x-height midline (~36% above
        # baseline for the body fonts we ship).
        offset = size * 0.30
        out.append(
            Rect(
                x=start_x,
                y=run.y + offset,
                width=end_x - start_x,
                height=thickness,
                fill=run.color or (0.0, 0.0, 0.0),
            )
        )
        i = j
    return out


def _split_preserved_lines(
    runs: list[Run], column_width: float | None = None
) -> list[list[Run]]:
    """Split runs on embedded ``\\n`` for code blocks, then soft-wrap.

    Each source line (delimited by ``\\n``) is preserved as a logical
    unit so whitespace within it stays intact. If ``column_width`` is
    set and a source line's rendered width exceeds it, the line is
    soft-wrapped at the last whitespace before the overflow point;
    if no whitespace exists, the line is hard-broken at the column
    boundary. Continuation lines are flat (no indent change) so they
    align with the original line's left edge under the same body_indent.
    """
    source_lines: list[list[Run]] = []
    current: list[Run] = []
    for run in runs:
        # An emoji run is an atomic inline image and never contains a
        # newline — carry it through whole (preserving .emoji and styling)
        # so emoji survive inside code blocks instead of being flattened to
        # bare text and mangled to '?'.
        if run.emoji is not None:
            current.append(run)
            continue
        parts = run.text.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                source_lines.append(current)
                current = []
            if part:
                current.append(replace(run, text=part))
    source_lines.append(current)

    if column_width is None:
        return source_lines

    wrapped: list[list[Run]] = []
    for line in source_lines:
        wrapped.extend(_wrap_preserved_line(line, column_width))
    return wrapped


def _wrap_preserved_line(line: list[Run], column_width: float) -> list[list[Run]]:
    """Wrap a single preserved-whitespace line at the column boundary.

    Walks the line char-by-char, tracking accumulated width. When width
    exceeds column_width, break at the last whitespace seen if any;
    otherwise hard-break at the current position. Continues until the
    whole line is consumed.
    """
    if not line:
        return [[]]
    # Fast path: does the whole line already fit?
    total = sum(_run_width(r) for r in line)
    if total <= column_width:
        return [line]

    # Flatten the line into atomic units so we can walk it while tracking
    # width and break points. A text run becomes one unit per character
    # (so it can hard-break anywhere); an emoji run is a single atomic unit
    # — an inline image that must never be split or merged into text.
    # Each unit carries its source run so styling (and .emoji) survives
    # reassembly.
    Unit = tuple  # (char_or_None, width, source_run, is_space)
    units: list[tuple[str | None, float, Run, bool]] = []
    for r in line:
        if r.emoji is not None:
            units.append((None, _run_width(r), r, False))
        else:
            for ch in r.text:
                # Per-char width through the run's own path: a char in an
                # embedded run measures on the embedded font, not WinAnsi.
                w = run_text_width(replace(r, text=ch))
                units.append((ch, w, r, ch == " "))

    def make_runs(start: int, end: int) -> list[Run]:
        out: list[Run] = []
        buf = ""
        cur: Run | None = None
        for ch, _w, src, _sp in units[start:end]:
            if ch is None:
                # Atomic emoji unit — flush any pending text, emit as-is.
                if buf and cur is not None:
                    out.append(replace(cur, text=buf))
                    buf = ""
                cur = None
                out.append(src)
                continue
            if cur is not None and (
                src.font != cur.font or src.size != cur.size
            ):
                if buf:
                    out.append(replace(cur, text=buf))
                buf = ch
                cur = src
            else:
                buf += ch
                cur = src
        if buf and cur is not None:
            out.append(replace(cur, text=buf))
        return out

    wrapped: list[list[Run]] = []
    start = 0
    i = 0
    last_space = -1
    width_so_far = 0.0
    while i < len(units):
        _ch, w, _src, is_sp = units[i]
        if width_so_far + w > column_width and i > start:
            # Break point: prefer last_space if found within this segment.
            if last_space > start:
                wrapped.append(make_runs(start, last_space))
                start = last_space + 1  # skip the whitespace itself
            else:
                # Hard break — no whitespace available.
                wrapped.append(make_runs(start, i))
                start = i
            i = start
            last_space = -1
            width_so_far = 0.0
            continue
        if is_sp:
            last_space = i
        width_so_far += w
        i += 1
    if start < len(units):
        wrapped.append(make_runs(start, len(units)))
    return wrapped or [[]]
