"""Rebuild existing Paddle trial with traceable space-only corrections, no OCR."""
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from importlib.metadata import version
import hashlib
import json
from kiwipiepy import Kiwi
from scan2read.cleanup.spacing import correct_spacing
from scan2read.epub.builder import build_epub
from scan2read.epub.validator import validate_epub

root = Path("output/ivp-sample")
source = root / "ivp-pages-30-34-paddle.epub"
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
with ZipFile(source) as archive:
    chapter = ET.fromstring(archive.read("EPUB/chapter.xhtml"))
    title = chapter.find("{http://www.w3.org/1999/xhtml}head/{http://www.w3.org/1999/xhtml}title").text
    paragraphs = [p.text or "" for p in chapter.findall(".//{http://www.w3.org/1999/xhtml}p")]
kiwi = Kiwi(num_workers=2)
results = [correct_spacing(p, lambda text: kiwi.space(text, reset_whitespace=True)) for p in paragraphs]
assert all(a.replace(" ", "") == b.replace(" ", "") for a, b in zip(paragraphs, results))
output = root / "ivp-pages-30-34-paddle-spacing.epub"
pending = output.with_suffix(".pending.epub")
try:
    build_epub(pending, title, results)
    report = validate_epub(pending, Path(".tools/epubcheck-5.3.0/epubcheck.jar"))
    pending.replace(output)
finally:
    pending.unlink(missing_ok=True)
assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
(root / "spacing-comparison.json").write_text(json.dumps({"kiwipiepy": version("kiwipiepy"),
    "source_sha256": source_hash, "changed_paragraphs": sum(a != b for a,b in zip(paragraphs,results)),
    "paragraphs": [{"before": a, "after": b} for a,b in zip(paragraphs,results)]}, ensure_ascii=False, indent=2), encoding="utf-8")
(root / "spacing-text.txt").write_text("\n\n".join(results), encoding="utf-8")
(root / "spacing-epubcheck.txt").write_text(report, encoding="utf-8")
print(f"Created {output}; {len(results)} paragraphs checked; non-space characters unchanged")
