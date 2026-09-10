from collections.abc import Iterable
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import re
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

# XML 1.0 forbids these code points in text content outright -- not even a
# character reference makes them legal. OCR occasionally produces one from a
# garbled image region (a stray control character), and unlike '<' or '&'
# these survive html.escape() untouched, so a single one is enough to make
# the whole chapter file fail to parse as XML at all.
_ILLEGAL_XML_CHARS = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]"
)


def _sanitize(text: str) -> str:
    return _ILLEGAL_XML_CHARS.sub("", text)


def build_epub(path: Path, title: str, paragraphs: Iterable[str]) -> Path:
    """Package a single reflowable chapter; callers validate before publishing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    title = escape(_sanitize(title))
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    head = f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ko" xml:lang="ko"><head><title>{title}</title></head><body>'
    items=[]
    for item in paragraphs:
        if isinstance(item,tuple):items.append(item)
        else:items.append((item,"body",0))
    headings=[(i,text) for i,(text,kind,level) in enumerate(items) if kind=="heading" or level]
    toc="".join(f'<li><a href="chapter.xhtml#heading-{i}">{escape(_sanitize(text))}</a></li>'
                for i,text in headings) or f'<li><a href="chapter.xhtml">{title}</a></li>'
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        archive.writestr("EPUB/package.opf", f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="book-id">urn:uuid:{uuid4()}</dc:identifier><dc:title>{title}</dc:title><dc:language>ko</dc:language><meta property="dcterms:modified">{modified}</meta>
</metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="chapter"/></spine></package>''')
        archive.writestr("EPUB/nav.xhtml", head + f'<nav epub:type="toc" id="toc"><h1>목차</h1><ol>{toc}</ol></nav></body></html>')
        with archive.open("EPUB/chapter.xhtml", "w") as chapter:
            chapter.write((head + f"<h1>{title}</h1>").encode("utf-8"))
            for index,(paragraph,kind,level) in enumerate(items):
                safe=escape(_sanitize(paragraph))
                if kind=="heading" or level:
                    tag=f"h{min(3,max(2,level or 2))}"
                    chapter.write((f'<{tag} id="heading-{index}">'+safe+f'</{tag}>').encode("utf-8"))
                else:chapter.write(("<p>"+safe+"</p>").encode("utf-8"))
            chapter.write(b"</body></html>")
    return path
