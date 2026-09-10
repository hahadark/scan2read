"""Reuse a PDF's own embedded text layer instead of OCR, when one exists.

Some PDFs (for example, ones exported from Word) already contain real text,
not just a scanned page image. Rendering and OCR-ing such a page throws away
perfectly accurate text and risks introducing new OCR errors. When a page has
one, this module extracts it directly into the same OCRPage/OCRBlock shape
OCR engines produce, so the rest of the pipeline (header detection, paragraph
reconstruction, EPUB build) does not need to know the difference.

A minority of PDFs have a text layer whose encoding is broken (a missing or
wrong ToUnicode mapping), which surfaces as replacement characters, private-use
codepoints, or bare Hangul jamo instead of composed syllables. Those are
unambiguous technical corruption signatures, not just "unusual" words, so only
those blocks are corrected -- by cropping the rendered page image to the
block's own bounding box and re-running OCR on just that crop.
"""
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
import re
import uuid

import pypdfium2 as pdfium

from scan2read.ocr.base import OCREngine
from scan2read.ocr.models import OCRBlock, OCRPage
from scan2read.pdf.reader import PDFError

DEFAULT_MIN_CHARS = 20

# Known encoding-corruption signatures only -- never a judgement about whether
# a word "looks right", to avoid speculatively rewriting legitimate text.
# Built from explicit \\u escapes (never literal characters) so the pattern
# cannot be silently mangled by source-file re-encoding.
_CORRUPTION_RANGES = (
    (0xFFFD, 0xFFFD),  # Unicode replacement character
    (0xE000, 0xF8FF),  # Private Use Area
    (0xF0000, 0xFFFFD),  # Supplementary PUA-A
    (0x100000, 0x10FFFD),  # Supplementary PUA-B
    (0x0000, 0x0008),  # C0 control characters (not whitespace)
    (0x000B, 0x000C),
    (0x000E, 0x001F),
    (0x3131, 0x318E),  # isolated Hangul compatibility jamo (not composed syllables)
)
_CORRUPTION = re.compile(
    "[" + "".join(f"{chr(lo)}-{chr(hi)}" if lo != hi else chr(lo) for lo, hi in _CORRUPTION_RANGES) + "]"
)


def _extract_from_page(page, page_number: int, dpi: int, min_chars: int) -> OCRPage | None:
    width_pt, height_pt = page.get_size()
    scale = dpi / 72
    width = max(1, round(width_pt * scale))
    height = max(1, round(height_pt * scale))
    with closing(page.get_textpage()) as textpage:
        blocks: list[OCRBlock] = []
        total_chars = 0
        for index in range(textpage.count_rects()):
            left, bottom, right, top = textpage.get_rect(index)
            text = textpage.get_text_bounded(left, bottom, right, top).strip()
            if not text:
                continue
            total_chars += len(text)
            # PDF canvas units grow upward; image pixels grow downward.
            x0 = max(0, min(width, round(left * scale)))
            y0 = max(0, min(height, round((height_pt - top) * scale)))
            x1 = max(0, min(width, round(right * scale)))
            y1 = max(0, min(height, round((height_pt - bottom) * scale)))
            if x1 <= x0 or y1 <= y0:
                continue
            blocks.append(OCRBlock(
                id=f"text-{index}-{uuid.uuid4().hex[:8]}",
                text=text,
                bbox=(x0, y0, x1, y1),
                confidence=1.0,
                reading_order=index,
                type="line",
            ))
        if total_chars < min_chars:
            return None
        return OCRPage(page=page_number, width=width, height=height, blocks=tuple(blocks))


def extract_text_layer(source: Path, page_number: int, dpi: int = 300,
                        min_chars: int = DEFAULT_MIN_CHARS) -> OCRPage | None:
    """Return the PDF's own text for one page, or None if there is effectively none."""
    try:
        with pdfium.PdfDocument(source) as document:
            if not 1 <= page_number <= len(document):
                raise ValueError(f"Page number out of range: {page_number}")
            with closing(document[page_number - 1]) as page:
                return _extract_from_page(page, page_number, dpi, min_chars)
    except pdfium.PdfiumError as exc:
        raise PDFError(f"Cannot read text layer for page {page_number}: {exc}") from exc


@dataclass(frozen=True)
class TextLayerSummary:
    page_count: int
    pages_with_text_layer: int


def analyze_text_layer(source: Path, dpi: int = 300, min_chars: int = DEFAULT_MIN_CHARS) -> TextLayerSummary:
    """Scan every page once (no rendering) to report how many already have real text.

    Meant to tell a user up front, before committing to a slow OCR run, whether
    their PDF (for example, one exported from Word) can skip OCR entirely.
    """
    try:
        with pdfium.PdfDocument(source) as document:
            page_count = len(document)
            detected = 0
            for number in range(1, page_count + 1):
                with closing(document[number - 1]) as page:
                    if _extract_from_page(page, number, dpi, min_chars) is not None:
                        detected += 1
            return TextLayerSummary(page_count=page_count, pages_with_text_layer=detected)
    except pdfium.PdfiumError as exc:
        raise PDFError(f"Cannot read {source.name}: {exc}") from exc


def has_corruption_markers(text: str) -> bool:
    """True if `text` carries a known encoding-corruption signature.

    Shared by `find_corrupted_blocks()` below and by the AI cleanup
    pre-filter (`cleanup/ai_filter.py`), which reuses this exact,
    already-verified character-range check rather than inventing a second
    "does this text look wrong" heuristic.
    """
    return bool(_CORRUPTION.search(text))


def find_corrupted_blocks(page: OCRPage) -> tuple[OCRBlock, ...]:
    """Blocks whose text carries a known encoding-corruption signature.

    This deliberately does not try to judge whether a word "looks right" --
    that would risk rewriting legitimate but unusual text. It only flags
    characters that are technically impossible in well-formed output.
    """
    return tuple(block for block in page.blocks if has_corruption_markers(block.text))


def correct_with_ocr(page: OCRPage, image_path: Path, engine: OCREngine) -> OCRPage:
    """Replace corrupted blocks' text with OCR results cropped to their own bbox."""
    corrupted = {block.id for block in find_corrupted_blocks(page)}
    if not corrupted:
        return page
    from PIL import Image

    blocks = list(page.blocks)
    with Image.open(image_path) as image:
        for index, block in enumerate(blocks):
            if block.id not in corrupted:
                continue
            crop_path = image_path.with_name(f"{image_path.stem}.crop-{block.id}.png")
            try:
                image.crop(block.bbox).save(crop_path)
                recognized = engine.recognize(crop_path)
                lines = sorted(recognized.blocks, key=lambda b: b.reading_order)
                text = " ".join(line.text.strip() for line in lines if line.text.strip())
                if text:
                    confidence = min((line.confidence for line in lines), default=block.confidence)
                    blocks[index] = replace(block, text=text, confidence=confidence)
            finally:
                crop_path.unlink(missing_ok=True)
    return replace(page, blocks=tuple(blocks))
