"""Rebuild the local sample from preserved OCR geometry, without rerunning OCR."""
from pathlib import Path
from dataclasses import asdict
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import hashlib
import json
from kiwipiepy import Kiwi
from scan2read.cleanup.headers import repeated_margins
from scan2read.cleanup.reconstruction import reconstruct
from scan2read.cleanup.spacing import correct_spacing
from scan2read.project.storage import load_raw_ocr
from scan2read.epub.builder import build_epub
from scan2read.epub.validator import validate_epub

root=Path("output/ivp-sample")
files=sorted(Path("work/ivp-paddle").rglob("raw_ocr/*.json"))
if len(files)!=5:
    raise ValueError("Expected exactly the five saved trial pages")
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
pages=lambda: (load_raw_ocr(p) for p in files)
paragraphs=reconstruct(pages(),repeated_margins(pages()))
with ZipFile(root/"ivp-pages-30-34-paddle.epub") as archive:
    chapter=ET.fromstring(archive.read("EPUB/chapter.xhtml"))
    title=chapter.find("{http://www.w3.org/1999/xhtml}head/{http://www.w3.org/1999/xhtml}title").text
    old=[p.text or "" for p in chapter.findall(".//{http://www.w3.org/1999/xhtml}p")]
compact=lambda text: "".join(text.split())
assert compact("".join(old))==compact("".join(p.text for p in paragraphs)), "Content/order changed"
kiwi=Kiwi(num_workers=2)
records=[]
for p in paragraphs:
    before=p.text
    p.text=correct_spacing(before,lambda text:kiwi.space(text,reset_whitespace=True))
    records.append({**asdict(p),"before_spacing":before})
output=root/"ivp-pages-30-34-paragraphs.epub"
pending=output.with_suffix(".pending.epub")
try:
    build_epub(pending,title,(p.text for p in paragraphs))
    report=validate_epub(pending,Path(".tools/epubcheck-5.3.0/epubcheck.jar"))
    pending.replace(output)
finally:
    pending.unlink(missing_ok=True)
assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(root/"paragraphs-trace.json").write_text(json.dumps({"raw_hashes":hashes,"paragraphs":records},ensure_ascii=False,indent=2),encoding="utf-8")
(root/"paragraphs-text.txt").write_text("\n\n".join(p.text for p in paragraphs),encoding="utf-8")
(root/"paragraphs-epubcheck.txt").write_text(report,encoding="utf-8")
print(f"Created {output}: {len(old)} -> {len(paragraphs)} paragraphs; content and raw hashes preserved")
print("Cross-page paragraphs:",sum(len({n for n,_ in p.sources})>1 for p in paragraphs))
