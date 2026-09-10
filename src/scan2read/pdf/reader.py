from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium


class PDFError(ValueError):
    """An input PDF cannot be processed."""


@dataclass(frozen=True)
class PDFInfo:
    path: Path
    page_count: int
    title: str
    metadata: dict[str, str]


def inspect_pdf(path: Path) -> PDFInfo:
    path = path.resolve()
    if not path.is_file():
        raise PDFError(f"PDF file not found: {path}")
    try:
        with pdfium.PdfDocument(path) as document:
            if not len(document):
                raise PDFError("PDF contains no pages")
            metadata = document.get_metadata_dict()
            # Probe rendering without retaining a full-resolution page.
            with closing(document[0]) as page:
                with closing(page.render(scale=0.1)):
                    pass
            return PDFInfo(path, len(document), metadata.get("Title", "").strip() or path.stem, metadata)
    except pdfium.PdfiumError as exc:
        raise PDFError(f"Cannot read PDF {path.name}: {exc}") from exc
