"""One-off scripted cleanup for a single already-converted EPUB.

Fixes known recurring OCR typos and drops paragraphs that are pure noise
(decorative-element fragments, stray punctuation) -- never touches any
paragraph that contains Hangul or a digit, since those are the ones that
might carry real content.
"""
import re
import sys
from html import unescape
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scan2read.epub.builder import build_epub  # noqa: E402

TYPO_FIXES = [
    (re.compile(r"\bmedilation\b", re.I), "meditation"),
    (re.compile(r"\bmeditaion\b", re.I), "meditation"),
    (re.compile(r"\bmedilalion\b", re.I), "meditation"),
    (re.compile(r"\bmeditalion\b", re.I), "meditation"),
    (re.compile(r"\bmedilatin\b", re.I), "meditation"),
]

PUNCT_ONLY = re.compile(r"^[\W_]+$")
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")
WHITELIST = {"tel", "fax", "isbn"}


def fix_typos(text: str) -> str:
    for pattern, replacement in TYPO_FIXES:
        text = pattern.sub(replacement, text)
    return text


def is_junk(text: str) -> bool:
    text = text.strip()
    if not text:
        return True
    if PUNCT_ONLY.match(text):
        return True
    if text.lower() in WHITELIST:
        return False
    if len(text) <= 10 and not HANGUL.search(text) and LATIN.search(text) and not re.search(r"\d", text):
        return True
    return False


def clean_epub(source: Path, destination: Path) -> tuple[int, int, list[str]]:
    with ZipFile(source) as archive:
        chapter = archive.read("EPUB/chapter.xhtml").decode("utf-8")
        opf = archive.read("EPUB/package.opf").decode("utf-8")
    title_match = re.search(r"<dc:title>(.*?)</dc:title>", opf)
    title = unescape(title_match.group(1)) if title_match else source.stem

    raw_paragraphs = re.findall(r"<p>(.*?)</p>", chapter, re.S)
    kept: list[str] = []
    removed: list[str] = []
    for raw in raw_paragraphs:
        text = fix_typos(unescape(raw))
        if is_junk(text):
            removed.append(text)
        else:
            kept.append(text)

    build_epub(destination, title, kept)
    return len(raw_paragraphs), len(kept), removed


if __name__ == "__main__":
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    total, kept, removed = clean_epub(source, destination)
    print(f"paragraphs: {total} -> {kept} (removed {len(removed)})")
    log = destination.with_suffix(".removed.txt")
    log.write_text("\n".join(repr(r) for r in removed), encoding="utf-8")
    print(f"removed-paragraph log: {log}")
