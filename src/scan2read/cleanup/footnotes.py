"""Opt-in geometric detection of long and continued footnotes."""
from statistics import median
import re
from scan2read.ocr.models import OCRPage

_MARKER = re.compile(r"^(?:\(?\d{1,3}\)|\[\d{1,3}\]|\d{1,3}\.\s|[*†‡§])\s*\S")


def find_footnote_block_ids(page: OCRPage) -> set[str]:
    groups = {}
    for block in sorted(page.blocks, key=lambda b: b.reading_order):
        region = block.id.split(":")[0] if block.id.startswith("region-") else "body"
        groups.setdefault(region, []).append(block)
    removed = set()
    for lines in groups.values():
        body = [b for b in lines if .15 * page.height < b.bbox[1] < .50 * page.height
                and b.type != "heading" and len(b.text.strip()) > 3]
        if not body:
            body = [b for b in lines if b.bbox[1] < .72 * page.height and b.type != "heading"]
        if not body:
            continue
        size = median(b.bbox[3] - b.bbox[1] for b in body)
        if size <= 0:
            continue
        for index, block in enumerate(lines):
            if block.bbox[1] < page.height * .45 or block.type == "heading":
                continue
            preceding = [b for b in lines[:index] if b.bbox[1] > page.height * .1
                         and b.type != "heading" and b.bbox[2]-b.bbox[0] > page.width * .45]
            if preceding:
                size = median(b.bbox[3]-b.bbox[1] for b in preceding[-3:])
            run = []
            for item in lines[index:]:
                if item.type == "heading" or item.bbox[1] < block.bbox[1] - size:
                    break
                if item.bbox[3] - item.bbox[1] > size * 1.15:
                    break
                if item.text.strip() and not item.text.strip().isdecimal():
                    run.append(item)
            if not run:
                continue
            small = median(b.bbox[3] - b.bbox[1] for b in run) <= size * .94
            if not small:
                continue
            marked = bool(_MARKER.match(block.text.strip()))
            gap = block.bbox[1] - lines[index - 1].bbox[3] if index else 0
            # An unnumbered continuation requires a separate, compact,
            # small-type run extending to the bottom of the page.
            stable_body = any(sum(abs(a.bbox[0]-b.bbox[0]) < size for a in preceding) >= 3
                              for b in preceding)
            separated = (stable_body and block.bbox[3]-block.bbox[1] <= size * .96
                         and gap >= size * 1.4 and len(run) >= 2
                         and run[-1].bbox[3] >= page.height * .88
                         and median(max(0, b.bbox[1] - a.bbox[3]) for a, b in zip(run, run[1:])) < size * .6)
            if marked or separated:
                removed.update(b.id for b in run)
                break
    # A separately detected superscript reference otherwise becomes a whole
    # spoken paragraph (e.g. "18"). Require a matching note on this page and
    # a smaller box attached to the end of a body line, not just a number.
    note_numbers = set()
    for block in page.blocks:
        if block.id in removed:
            match = re.match(r"^\s*[\[(]?(\d{1,3})[.)\]]", block.text)
            if match:
                note_numbers.add(int(match[1]))
    references = set()
    for block in page.blocks:
        text = block.text.strip()
        if block.id in removed or not text.isdecimal() or len(text) > 3 or int(text) not in note_numbers:
            continue
        x0, y0, x1, y1 = block.bbox
        for body in page.blocks:
            if body.id in removed or body.id == block.id or len(body.text.strip()) < 8:
                continue
            bx0, by0, bx1, by1 = body.bbox
            height = by1 - by0
            # Thresholds are loose enough to absorb real OCR bbox noise: a real
            # superscript "98" attached to a body line measured at 0.745x the
            # line's height and 23px left of its own line's right edge (both
            # narrowly outside the previous 0.7 / 0.3 bounds) -- verified
            # against a real cached book (589f867...5331e, page 102/78), no
            # new false positives across all 116 cached pages.
            if (height > 0 and 0 < y1-y0 <= height*.85
                    and bx1-height*.6 <= x0 <= bx1+height*.7
                    and by0-height*.4 <= y0 <= by0+height*.25 and y1 <= by1):
                references.add(block.id)
                break
    return removed | references
