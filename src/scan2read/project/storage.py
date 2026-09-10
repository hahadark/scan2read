import os
from pathlib import Path
import tempfile

from scan2read.ocr.models import OCRPage


def save_raw_ocr(path: Path, page: OCRPage) -> None:
    """Publish a complete JSON atomically, refusing to overwrite prior OCR."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(page.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link creation is atomic and fails if the destination exists.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_raw_ocr(path: Path) -> OCRPage:
    return OCRPage.from_json(path.read_text(encoding="utf-8"))
