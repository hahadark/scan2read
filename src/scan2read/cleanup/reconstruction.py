"""Reconstruct paragraphs using OCR geometry, retaining source references."""
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from statistics import median
import re

from scan2read.cleanup.footnotes import find_footnote_block_ids
from scan2read.cleanup.noise import body_line_size, is_stray
from scan2read.cleanup.text import is_page_number
from scan2read.ocr.models import OCRPage


@dataclass
class Paragraph:
    text: str
    kind: str
    sources: list[tuple[int, str]] = field(default_factory=list)
    sole_bbox: tuple[int, int, int, int] | None = None


@dataclass
class _VisualLine:
    text: str
    bbox: tuple[int, int, int, int]
    type: str
    source_ids: list[str]


def _same_visual_line(line: _VisualLine, block, page_width: int) -> bool:
    x0, y0, x1, y1 = line.bbox
    bx0, by0, bx1, by1 = block.bbox
    overlap = max(0, min(y1, by1) - max(y0, by0))
    smaller_height = max(1, min(y1-y0, by1-by0))
    centers_close = abs((y0+y1)-(by0+by1))/2 <= max(y1-y0, by1-by0)*.35
    horizontal_gap = bx0-x1
    height = max(y1-y0, by1-by0)
    punctuation = bool(re.fullmatch(r"[,.!?:;·'\"’”()\[\]{}]+", block.text.strip()))
    vertical_match = (overlap >= smaller_height*.45 or centers_close or
                      (punctuation and abs((y0+y1)-(by0+by1))/2 <= height))
    return vertical_match and -height <= horizontal_gap <= max(page_width*.08, (y1-y0)*4)


def _run_separator(line: _VisualLine, block) -> str:
    previous = line.text.rstrip()
    current = block.text.strip()
    if not previous or not current or current[0] in ",.!?:;)]}〉》”’" or previous[-1] in "([{〈《“\"":
        return ""
    x0, _, x1, _ = line.bbox
    bx0, _, bx1, _ = block.bbox
    previous_chars = max(1, len(previous.replace(" ", "")))
    current_chars = max(1, len(current.replace(" ", "")))
    char_width = min((x1-x0)/previous_chars, (bx1-bx0)/current_chars)
    return "" if bx0-x1 <= char_width*.45 else " "


def _visual_lines(blocks, page_width: int) -> list[_VisualLine]:
    """Coalesce contiguous PDF text runs while retaining every source ID."""
    lines: list[_VisualLine] = []
    for block in blocks:
        if (lines and block.id.startswith("text-")
                and all(source.startswith("text-") for source in lines[-1].source_ids)
                and _same_visual_line(lines[-1], block, page_width)):
            line = lines[-1]
            line.text += _run_separator(line, block) + block.text.strip()
            x0, y0, x1, y1 = line.bbox
            bx0, by0, bx1, by1 = block.bbox
            line.bbox = (min(x0,bx0), min(y0,by0), max(x1,bx1), max(y1,by1))
            line.source_ids.append(block.id)
            if block.type == "heading":
                line.type = "heading"
        else:
            lines.append(_VisualLine(block.text.strip(), block.bbox, block.type, [block.id]))
    return lines


def _merge_by_context(paragraphs: list[Paragraph], join: Callable[[str, str], bool] | None) -> list[Paragraph]:
    if join is None:
        return paragraphs
    eligible = [(paragraphs[index-1].text, paragraph.text)
                for index, paragraph in enumerate(paragraphs) if index and
                paragraphs[index-1].kind == paragraph.kind == "body" and
                paragraph.sources[0][0] - paragraphs[index-1].sources[-1][0] in (0, 1)]
    batch_decisions = iter(join.decide_many(eligible)) if hasattr(join, "decide_many") else None
    merged: list[Paragraph] = []
    for paragraph in paragraphs:
        eligible_boundary = (merged and merged[-1].kind == paragraph.kind == "body"
                             and paragraph.sources[0][0] - merged[-1].sources[-1][0] in (0, 1))
        should_join = next(batch_decisions) if eligible_boundary and batch_decisions is not None else (
            join(merged[-1].text, paragraph.text) if eligible_boundary else False)
        if eligible_boundary and should_join:
            merged[-1].text += " " + paragraph.text
            merged[-1].sources.extend(paragraph.sources)
            merged[-1].sole_bbox = None
        else:
            merged.append(paragraph)
    return merged


def reconstruct(pages: Iterable[OCRPage], margins: dict[int, set[str]],
                 remove_footnotes: bool = False,
                 context_join: Callable[[str, str], bool] | None = None) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    body_sizes: dict[int, float] = {}
    tail = None
    for page in pages:
        body_sizes[page.page] = body_line_size(page.blocks)
        footnote_ids = find_footnote_block_ids(page) if remove_footnotes else set()
        groups = {}
        for block in sorted(page.blocks, key=lambda b: b.reading_order):
            if (block.id in margins.get(page.page, set()) or is_page_number(block, page)
                    or block.id in footnote_ids or not block.text.strip()):
                continue
            region = block.id.split(":")[0] if block.id.startswith("region-") else "body"
            groups.setdefault(region, []).append(block)
        for region, blocks in groups.items():
            lines = _visual_lines(blocks, page.width)
            baseline = min(b.bbox[0] for b in lines)
            right = max(b.bbox[2] for b in lines)
            height = median(max(1, b.bbox[3]-b.bbox[1]) for b in lines)
            previous = None
            for index, block in enumerate(lines):
                text = block.text.strip()
                x0, y0, x1, y1 = block.bbox
                gap = y0-previous.bbox[3] if previous else 0
                next_gap = lines[index+1].bbox[1]-y1 if index+1<len(lines) else 0
                short = (x1-x0) < (right-baseline)*.78
                heading = (block.type == "heading" or region == "region-0" or
                           (short and gap > height*1.8 and len(text)<50
                            and not re.search(r"[.!?。]$", text)))
                indented = x0-baseline > height*.65
                list_item = bool(re.match(r"^(?:\d+[.)]|[•●])\s*",text))
                boundary = previous is None or heading or indented or list_item or gap > height*1.8
                if paragraphs and paragraphs[-1].kind == "heading":
                    boundary = True
                # Cross a column/page only with evidence of continuation at both margins.
                if previous is None and tail is not None and not heading and not indented and not list_item:
                    last, last_height, last_right, last_page = tail
                    continuation = (last.bbox[3] > last_height*.84 and y0 < page.height*.23
                                    and last_right-last.bbox[2] < height*1.2
                                    and not re.search(r'[.!?。][”’"\')\]]*$',last.text.strip())
                                    and page.page-last_page in (0,1)
                                    and paragraphs[-1].kind == "body")
                    if continuation:
                        boundary = False
                if boundary or not paragraphs:
                    paragraphs.append(Paragraph(text, "heading" if heading else "body",
                                                 [(page.page,source) for source in block.source_ids],
                                                 block.bbox if len(block.source_ids)==1 else None))
                else:
                    paragraphs[-1].text += " " + text
                    paragraphs[-1].sources.extend((page.page,source) for source in block.source_ids)
                    paragraphs[-1].sole_bbox = None
                previous = block
            tail = (lines[-1], page.height, right, page.page)
        if not groups:
            tail = None
    cleaned = [p for p in paragraphs
               if p.sole_bbox is None or not is_stray(p.text, p.sole_bbox, body_sizes[p.sources[0][0]])]
    return _merge_by_context(cleaned, context_join)
