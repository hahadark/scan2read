"""Conservative repeated margin detection across nearby pages."""
from collections import defaultdict
from collections.abc import Iterable
import re

from scan2read.ocr.models import OCRPage

# A running header is sometimes fused with its own page number into one
# block (e.g. a PDF's own text layer emitting "Author's Preface9" as a
# single text run, no separating space). Stripping a leading/trailing
# page-number-shaped run before comparing lets the header still be
# recognized as repeating page to page; the whole original block --
# header text and embedded number together -- is still what gets removed.
_MARGIN_DIGITS = re.compile(r"^\d{1,4}|\d{1,4}$")
_ANY_DIGITS = re.compile(r"\d{1,4}")

# How far into the page the header/footer band extends. Real books vary a lot
# here -- one real title measured its running head ending at ~13% of page
# height and its footer starting at ~89% -- so this stays generous. It is
# safe to be generous because the real filter is the repetition check below
# (3+ nearby pages sharing the same normalized text at a stable position):
# ordinary body text essentially never does that, no matter how wide this
# band is, so widening it only catches more real margins, not false ones.
MARGIN_ZONE = 0.15
TEXT_WINDOW = 4
OFFSET_WINDOW = 8


def _candidates(pages: Iterable[OCRPage]):
    """Compact blocks in the outer margin band: (page, id, side, position, text)."""
    for page in pages:
        for block in page.blocks:
            x0, y0, x1, y1 = block.bbox
            side = "top" if y1 <= page.height * MARGIN_ZONE else "bottom" if y0 >= page.height * (1 - MARGIN_ZONE) else None
            text = re.sub(r"\s+", "", block.text)
            if (side is None or block.type == "heading" or not 2 <= len(text) <= 60
                    or text.isdecimal() or (y1-y0) > page.height*.025):
                continue
            yield page.page, block.id, side, (y0+y1)/(2*page.height), text


def repeated_margins(pages: Iterable[OCRPage]) -> dict[int, set[str]]:
    entries = list(_candidates(pages))
    removed: dict[int, set[str]] = defaultdict(set)

    # Pass 1: the same text (after stripping a fused page number) recurring
    # at a stable position -- catches a title that never changes, e.g. a
    # book title repeated on every page.
    by_text = defaultdict(list)
    for number, block_id, side, position, text in entries:
        normalized = _MARGIN_DIGITS.sub("", text)
        if 2 <= len(normalized) <= 60:
            by_text[(side, normalized)].append((number, block_id, position))
    for group in by_text.values():
        for number, block_id, position in group:
            neighbors = {n for n, _, pos in group if abs(n-number) <= TEXT_WINDOW and abs(pos-position) <= .015}
            if len(neighbors) >= 3:
                removed[number].add(block_id)

    # Pass 2: a page number fused with a label that itself changes (e.g. the
    # current chapter's title, one per chapter) -- the label text alone
    # never repeats often enough within a short chapter, but the embedded
    # number still tracks the page sequence at one constant offset. A wider
    # page window is safe here because "same offset AND same position" is
    # far too specific for ordinary prose (which sometimes ends in a
    # citation number) to satisfy by coincidence 3+ times nearby.
    by_offset = defaultdict(list)
    for number, block_id, side, position, text in entries:
        match = _ANY_DIGITS.search(text)
        if match is not None:
            by_offset[side].append((number, block_id, position, int(match.group()) - number))
    for group in by_offset.values():
        for number, block_id, position, offset in group:
            neighbors = {n for n, _, pos, off in group
                        if abs(n-number) <= OFFSET_WINDOW and abs(pos-position) <= .015 and off == offset}
            if len(neighbors) >= 3:
                removed[number].add(block_id)

    return dict(removed)
