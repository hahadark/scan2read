import csv
from dataclasses import replace
import tempfile
import hashlib
import json
import shutil
from io import StringIO
from pathlib import Path
import subprocess

from PIL import Image

from scan2read.ocr.base import OCRError
from scan2read.ocr.models import OCRBlock, OCRPage


def parse_tsv(value: str, width: int, height: int) -> OCRPage:
    """Convert word rows into ordered lines; retain layout for cleanup."""
    groups: dict[tuple[str, ...], list[dict[str, str]]] = {}
    for row in csv.DictReader(StringIO(value), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row["level"] == "5" and row["text"].strip():
            key = tuple(row[k] for k in ("page_num", "block_num", "par_num", "line_num"))
            groups.setdefault(key, []).append(row)
    blocks = []
    for order, (key, words) in enumerate(groups.items()):
        x0 = min(int(w["left"]) for w in words)
        y0 = min(int(w["top"]) for w in words)
        x1 = max(int(w["left"]) + int(w["width"]) for w in words)
        y1 = max(int(w["top"]) + int(w["height"]) for w in words)
        confidence = sum(max(0, min(100, float(w["conf"]))) for w in words) / (100 * len(words))
        blocks.append(OCRBlock("-".join(key), " ".join(w["text"] for w in words),
                               (x0, y0, x1, y1), confidence, order))
    return OCRPage(1, width, height, tuple(blocks))


def apply_native_spacing(page: OCRPage, text: str) -> OCRPage:
    """Use native text only when every non-whitespace character agrees."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != len(page.blocks):
        raise OCRError("TSV/text line count mismatch; refusing ambiguous OCR mapping")
    blocks = []
    for block, line in zip(page.blocks, lines):
        if "".join(block.text.split()) != "".join(line.split()):
            raise OCRError("TSV/text content mismatch; refusing ambiguous OCR mapping")
        blocks.append(replace(block, text=line))
    return replace(page, blocks=tuple(blocks))


class TesseractEngine:
    def __init__(self, executable: str = "tesseract", language: str = "kor+eng", timeout: int = 180, psm: int = 6):
        self.executable = executable
        self.language = language
        self.timeout = timeout
        self.psm = psm

    def cache_identity(self) -> str:
        """Include runtime and trained-data content so upgrades invalidate OCR."""
        executable = shutil.which(self.executable)
        if executable is None:
            raise OCRError(f"Tesseract executable not found: {self.executable}")
        try:
            result = subprocess.run([executable, "--list-langs"], capture_output=True,
                                    text=True, encoding="utf-8", check=True, timeout=30)
            header, *languages = result.stdout.splitlines()
            directory = Path(header.split('"')[1])
            hashes = {}
            for language in self.language.split("+"):
                if language not in languages:
                    raise OCRError(f"Tesseract language data missing: {language}")
                with (directory / (language + ".traineddata")).open("rb") as stream:
                    hashes[language] = hashlib.file_digest(stream, "sha256").hexdigest()
            with Path(executable).open("rb") as stream:
                binary_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            return json.dumps({"adapter": 2, "binary": binary_hash, "models": hashes,
                               "language": self.language, "psm": self.psm}, sort_keys=True)
        except (OSError, IndexError, subprocess.SubprocessError) as exc:
            raise OCRError(f"Cannot inspect Tesseract installation: {exc}") from exc

    def recognize(self, image_path: Path) -> OCRPage:
        with tempfile.TemporaryDirectory(prefix="scan2read-ocr-") as directory:
            base = Path(directory) / "result"
            try:
                subprocess.run(
                    [self.executable, str(image_path.resolve()), str(base), "-l", self.language,
                     "--psm", str(self.psm), "tsv", "txt"],
                    capture_output=True, text=True, encoding="utf-8", timeout=self.timeout, check=True,
                )
            except FileNotFoundError as exc:
                raise OCRError("Tesseract is not installed or not on PATH; install it with kor and eng language data") from exc
            except subprocess.TimeoutExpired as exc:
                raise OCRError(f"OCR exceeded {self.timeout} seconds: {image_path.name}") from exc
            except subprocess.CalledProcessError as exc:
                raise OCRError(f"Tesseract failed: {exc.stderr.strip()}") from exc
            with Image.open(image_path) as image:
                try:
                    page = parse_tsv(base.with_suffix(".tsv").read_text(encoding="utf-8"), *image.size)
                    return apply_native_spacing(page, base.with_suffix(".txt").read_text(encoding="utf-8"))
                except (OSError, KeyError, TypeError, ValueError) as exc:
                    raise OCRError(f"Invalid Tesseract output: {exc}") from exc
