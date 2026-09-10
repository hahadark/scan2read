from dataclasses import dataclass
import re

from scan2read.cleanup.footnotes import find_footnote_block_ids
from scan2read.cleanup.headers import MARGIN_ZONE
from scan2read.cleanup.noise import body_line_size, is_stray
from scan2read.ocr.models import OCRBlock, OCRPage


@dataclass(frozen=True)
class CleanPage:
    page: int
    paragraphs: tuple[str, ...]
    removed_block_ids: tuple[str, ...]


def is_page_number(block: OCRBlock, page: OCRPage) -> bool:
    """Only isolated digits close to the physical top/bottom margin.

    Uses the same margin band as repeated_margins() -- a real book measured
    its own bare page-number footer as close as 90.9% down the page, well
    outside a naive 8%/92% guess.
    """
    text = block.text.strip()
    return bool(re.fullmatch(r"(?:[-–—]\s*)?\d{1,4}(?:\s*[-–—])?", text)) and (
        block.bbox[3] <= page.height * MARGIN_ZONE or block.bbox[1] >= page.height * (1 - MARGIN_ZONE)
    )


def clean_page(page: OCRPage, margin_ids: set[str] | None = None, remove_footnotes: bool = False) -> CleanPage:
    footnote_ids = find_footnote_block_ids(page) if remove_footnotes else set()
    removed = tuple(b.id for b in page.blocks
                     if is_page_number(b, page) or b.id in (margin_ids or set()) or b.id in footnote_ids)
    lines = sorted((b for b in page.blocks if b.id not in removed), key=lambda b: b.reading_order)
    body_size = body_line_size(page.blocks)
    paragraphs: list[str] = []
    sole_sources: list[OCRBlock | None] = []
    previous: OCRBlock | None = None
    for line in lines:
        text = line.text.strip()
        if not text:
            previous = None
            continue
        boundary = previous is None or line.type == "heading"
        if previous is not None:
            height = max(1, previous.bbox[3] - previous.bbox[1])
            gap = line.bbox[1] - previous.bbox[3]
            # A large gap or a clearly indented line is structural evidence.
            boundary |= previous.type == "heading" or gap > height * .9
            boundary |= line.bbox[0] - previous.bbox[0] > height * 1.5
        if boundary or not paragraphs:
            paragraphs.append(text)
            sole_sources.append(line)
        else:
            paragraphs[-1] += " " + text
            sole_sources[-1] = None
        previous = line
    stray_ids = tuple(b.id for b in sole_sources if b is not None and is_stray(b.text, b.bbox, body_size))
    kept = tuple(p for p, b in zip(paragraphs, sole_sources)
                 if not (b is not None and is_stray(b.text, b.bbox, body_size)))
    return CleanPage(page.page, kept, removed + stray_ids)
