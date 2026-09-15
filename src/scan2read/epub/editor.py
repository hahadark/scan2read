"""Read the editable text blocks out of an existing EPUB, and write a new one
with some of them replaced or removed.

Separate from `epub/builder.py`, which packages a book Scan2Read produced from
a PDF. This module works on *any* EPUB, including ones from other tools, so it
has to preserve everything it doesn't understand: every zip member it isn't
editing is copied through byte for byte, and inside an edited document only
the specific elements that changed are touched.

Standard library only (zipfile + ElementTree), matching builder.py.
"""
from dataclasses import dataclass
from html.entities import html5
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

XHTML = "http://www.w3.org/1999/xhtml"
_OPF = "http://www.idpf.org/2007/opf"
_CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"

# Leaf-level text containers. An element only counts as a block if no
# descendant of it is also in this set, so a <div> wrapping <p>s yields the
# paragraphs, not the div and then the paragraphs again.
_BLOCK_TAGS = frozenset(("p", "h1", "h2", "h3", "h4", "h5", "h6",
                         "li", "blockquote", "td", "th", "dd", "dt", "div"))

# XML defines only these five entities; XHTML files routinely use HTML ones
# like &nbsp;, which make ElementTree fail outright on an otherwise fine file.
_XML_BUILTIN = frozenset(("amp", "lt", "gt", "quot", "apos"))
_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Block:
    """One editable text block, addressed by document and position."""
    document: str
    index: int
    text: str

    @property
    def key(self) -> tuple[str, int]:
        return (self.document, self.index)


def _expand_entities(markup: str) -> str:
    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name in _XML_BUILTIN:
            return match.group(0)
        character = html5.get(name + ";")
        return character if character else match.group(0)
    return _ENTITY.sub(replace, markup)


def _parse(markup: str) -> ET.Element:
    return ET.fromstring(_expand_entities(markup))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _blocks_in(root: ET.Element) -> list[ET.Element]:
    found = []
    for element in root.iter():
        if _local(element.tag) not in _BLOCK_TAGS:
            continue
        if any(_local(child.tag) in _BLOCK_TAGS for child in element.iter() if child is not element):
            continue
        if "".join(element.itertext()).strip():
            found.append(element)
    return found


def _content_documents(archive: ZipFile) -> list[str]:
    """Content document members in spine order, per the OPF; [] if unreadable."""
    try:
        container = _parse(archive.read("META-INF/container.xml").decode("utf-8"))
        rootfile = container.find(f".//{{{_CONTAINER}}}rootfile")
        opf_path = rootfile.get("full-path")
        package = _parse(archive.read(opf_path).decode("utf-8"))
    except (KeyError, AttributeError, UnicodeDecodeError, ET.ParseError):
        return []
    base = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
    manifest = {}
    for item in package.iter(f"{{{_OPF}}}item"):
        if item.get("media-type") == "application/xhtml+xml":
            href = item.get("href", "")
            manifest[item.get("id")] = f"{base}/{href}" if base else href
    documents = []
    for itemref in package.iter(f"{{{_OPF}}}itemref"):
        member = manifest.get(itemref.get("idref"))
        if member and member in archive.namelist():
            documents.append(member)
    return documents


def read_blocks(path: Path) -> list[Block]:
    """Every editable text block in the book, in reading order."""
    blocks = []
    with ZipFile(path) as archive:
        for member in _content_documents(archive):
            try:
                root = _parse(archive.read(member).decode("utf-8"))
            except (UnicodeDecodeError, ET.ParseError):
                # An unparsable document is left entirely alone rather than
                # risking a lossy rewrite of it.
                continue
            for index, element in enumerate(_blocks_in(root)):
                text = _WHITESPACE.sub(" ", "".join(element.itertext())).strip()
                blocks.append(Block(member, index, text))
    return blocks


def _edit_document(markup: str, changes: dict[int, str | None]) -> str:
    root = _parse(markup)
    parents = {child: parent for parent in root.iter() for child in parent}
    for index, element in enumerate(_blocks_in(root)):
        if index not in changes:
            continue
        replacement = changes[index]
        if replacement is None:
            parent = parents.get(element)
            if parent is not None:
                parent.remove(element)
            continue
        # Only a block the AI actually rewrote loses its inline markup
        # (<em>, <a>); untouched blocks keep theirs, since they are never
        # re-serialised from text.
        element.clear()
        element.text = replacement
    ET.register_namespace("", XHTML)
    ET.register_namespace("epub", "http://www.idpf.org/2007/ops")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


def write_edited(source: Path, target: Path, changes: dict[tuple[str, int], str | None]) -> Path:
    """Copy `source` to `target`, applying `changes` (None deletes the block).

    Everything not named in `changes` -- other members, other elements,
    metadata, styles, images -- is carried over untouched.
    """
    by_document: dict[str, dict[int, str | None]] = {}
    for (document, index), replacement in changes.items():
        by_document.setdefault(document, {})[index] = replacement
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_suffix(".pending.epub")
    with ZipFile(source) as original, ZipFile(pending, "w", compression=ZIP_DEFLATED) as archive:
        names = original.namelist()
        if "mimetype" in names:
            # Must be the first member and stored uncompressed for the file to
            # be a valid EPUB at all.
            archive.writestr("mimetype", original.read("mimetype"), compress_type=ZIP_STORED)
        for name in names:
            if name == "mimetype":
                continue
            data = original.read(name)
            if name in by_document:
                try:
                    data = _edit_document(data.decode("utf-8"), by_document[name]).encode("utf-8")
                except (UnicodeDecodeError, ET.ParseError):
                    pass
            archive.writestr(name, data)
    pending.replace(target)
    return target
