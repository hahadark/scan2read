from dataclasses import asdict, dataclass
import json
import math


@dataclass(frozen=True)
class OCRBlock:
    id: str
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float
    reading_order: int
    type: str = "line"

    def __post_init__(self) -> None:
        if len(self.bbox) != 4 or any(type(n) is not int for n in self.bbox):
            raise ValueError("Bounding box must contain four integers")
        x0, y0, x1, y1 = self.bbox
        if min(x0, y0) < 0 or x1 < x0 or y1 < y0:
            raise ValueError("Invalid bounding box")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Confidence must be between zero and one")
        if not isinstance(self.text, str) or not self.id or self.reading_order < 0:
            raise ValueError("Invalid OCR block")


@dataclass(frozen=True)
class OCRPage:
    page: int
    width: int
    height: int
    blocks: tuple[OCRBlock, ...]

    def __post_init__(self) -> None:
        if any(type(n) is not int or n < 1 for n in (self.page, self.width, self.height)):
            raise ValueError("Page number and dimensions must be positive integers")
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("Duplicate block IDs")
        for block in self.blocks:
            if block.bbox[2] > self.width or block.bbox[3] > self.height:
                raise ValueError("Block outside page")

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, allow_nan=False)

    @classmethod
    def from_json(cls, value: str) -> "OCRPage":
        data = json.loads(value)
        blocks = tuple(OCRBlock(**{**b, "bbox": tuple(b["bbox"])}) for b in data.pop("blocks"))
        return cls(**data, blocks=blocks)
