"""Opt-in equal-width two-column OCR for normal printed pages."""
from dataclasses import replace
from pathlib import Path
import tempfile

from PIL import Image

from scan2read.ocr.base import OCREngine
from scan2read.ocr.models import OCRPage


def title_bottom(image: Image.Image) -> int:
    """Preserve a top title only when separated from body by a large blank gap."""
    width, height = image.size
    with image.convert("L") as gray:
        pixels = gray.load()
        rows = [y for y in range(int(height*.075), int(height*.25))
                if 10 <= sum(pixels[x,y] < 160 for x in range(width)) < width*.4]
    if not rows:
        return int(height*.075)
    for previous, current in zip(rows, rows[1:]):
        if current-previous > height*.025 and previous < height*.16:
            return (previous+current)//2
    return int(height*.075)


def gutter(image: Image.Image) -> int | None:
    """The likely column gutter's x position, or None for an image too small to judge."""
    width, height = image.size
    with image.convert("L") as gray:
        pixels=gray.load()
        counts=[(x,sum(pixels[x,y]<160 for y in range(int(height*.25),int(height*.85),2)))
                for x in range(int(width*.42),int(width*.58))]
    if not counts:
        return None
    threshold=min(n for _,n in counts)+3
    runs=[]
    for x,n in counts:
        if n<=threshold:
            if not runs or x!=runs[-1][-1]+1: runs.append([])
            runs[-1].append(x)
    if not runs:
        return None
    best=max(runs,key=len)
    return (best[0]+best[-1])//2


class TwoColumnEngine:
    """Keep the top band, then read the entire left and right columns in order.

    Intended for explicitly selected centered-gutter pages, not arbitrary layouts.
    The wrapped engine should use single-block segmentation (PSM 6).
    """
    def __init__(self, engine: OCREngine):
        self.engine = engine

    def recognize(self, image_path: Path) -> OCRPage:
        blocks = []
        with Image.open(image_path) as image, tempfile.TemporaryDirectory(prefix="scan2read-columns-") as directory:
            width, height = image.size
            top = title_bottom(image)
            middle = gutter(image)
            if middle is None:
                # Too narrow to judge a column split (e.g. a single-line crop
                # re-OCR'd for text-layer correction) -- treat it as one column.
                regions = [(0, 0, width, top), (0, top, width, height)]
            else:
                regions = [(0, 0, width, top), (0, top, middle, height), (middle, top, width, height)]
            for index, (x0, y0, x1, y1) in enumerate(regions):
                path = Path(directory) / f"region-{index}.png"
                with image.crop((x0, y0, x1, y1)) as crop:
                    # Tight content bounds avoid excessive margins disrupting segmentation.
                    with crop.convert("L") as gray:
                        mask = gray.point(lambda value: 255 if value < 160 else 0)
                        bounds = mask.getbbox()
                        mask.close()
                    if bounds is None:
                        continue
                    left, upper, right, lower = bounds
                    with crop.crop(bounds) as tight:
                        tight.save(path)
                    x0 += left
                    y0 += upper
                page = self.engine.recognize(path)
                for block in page.blocks:
                    a, b, c, d = block.bbox
                    blocks.append(replace(block, id=f"region-{index}:{block.id}",
                                          bbox=(a+x0, b+y0, c+x0, d+y0), reading_order=len(blocks)))
        return OCRPage(1, width, height, tuple(blocks))
