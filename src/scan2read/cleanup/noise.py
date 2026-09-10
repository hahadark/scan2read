"""Drop a paragraph only when its ENTIRE content is one isolated 1-2 char
block that never merged with any neighboring line.

Distinct from header/footer and footnote removal, which rely on a block
repeating across pages or matching a marker+note pattern. This targets
one-off OCR noise that never repeats and has no note to match: illustration
captions/credits, misread decorative dividers, and detector false positives
on scan artifacts (ink specks, blurred page edges).

Must only ever be applied to a block confirmed to be a paragraph's SOLE
contributor. A citation initial like "M." or a bare comma routinely appears
as its own OCR block (especially from a PDF's own text layer, which splits
runs per font/style change) but gets glued into a real sentence during
paragraph joining -- checking it in isolation, before joining decides
whether it merges, would strip real text out of real paragraphs.
"""
from scan2read.ocr.models import OCRBlock

_ROMAN_NUMERALS = set("IVXLCDM")


def _has_hangul_or_digit(text: str) -> bool:
    return any(ch.isdigit() or "가" <= ch <= "힣" for ch in text)


def is_stray(text: str, bbox: tuple[int, int, int, int], body_size: float) -> bool:
    text = text.strip()
    if not text or len(text) > 2:
        return False
    x0, y0, x1, y1 = bbox
    # No real glyph at this scan resolution renders smaller than a third of
    # the surrounding body text's own line height.
    tiny = body_size > 0 and (y1 - y0) < body_size * .35 and (x1 - x0) < body_size * .35
    no_real_content = not _has_hangul_or_digit(text) and bool(set(text) - _ROMAN_NUMERALS)
    return tiny or no_real_content


def body_line_size(blocks: tuple[OCRBlock, ...]) -> float:
    from statistics import median
    body = [b for b in blocks if len(b.text.strip()) > 3]
    return median((b.bbox[3] - b.bbox[1] for b in body)) if body else 0
