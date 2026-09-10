from pathlib import Path
from typing import Protocol

from scan2read.ocr.models import OCRPage


class OCRError(RuntimeError):
    """OCR failed or its local runtime is unavailable."""


class OCREngine(Protocol):
    def recognize(self, image_path: Path) -> OCRPage: ...
