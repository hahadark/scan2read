from contextlib import closing
from pathlib import Path

import pypdfium2 as pdfium

from scan2read.pdf.reader import PDFError


def render_page(source: Path, page_number: int, destination: Path, dpi: int = 300) -> Path:
    """Render one 1-based page, releasing its bitmap before returning."""
    if not 36 <= dpi <= 600:
        raise ValueError("DPI must be between 36 and 600")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with pdfium.PdfDocument(source) as document:
            if not 1 <= page_number <= len(document):
                raise ValueError(f"Page number out of range: {page_number}")
            with closing(document[page_number - 1]) as page:
                with closing(page.render(scale=dpi / 72)) as bitmap:
                    with bitmap.to_pil() as image:
                        image.save(temporary, format="PNG")
        temporary.replace(destination)
        return destination
    except pdfium.PdfiumError as exc:
        raise PDFError(f"Cannot render page {page_number}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
