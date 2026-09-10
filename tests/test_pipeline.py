from contextlib import closing
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch
from zipfile import ZipFile
import pypdfium2 as pdfium

from scan2read.cleanup.ai_enhance import AIOptions
from scan2read.ocr.models import OCRPage, OCRBlock
from scan2read.epub.validator import validate_structure
from scan2read.pipeline import convert, ocr_only


class RecordingEnhancer:
    """A minimal ai_enhancer double: records exactly what it was asked to check."""
    def __init__(self, options):
        self.options = options
        self.calls: list[list[str]] = []
        self.audit_records: list[dict] = []

    def enhance(self, records):
        self.calls.append([r["text"] for r in records])
        return records


class SingleParagraphEngine:
    def __init__(self, text):
        self.text = text

    def recognize(self, path):
        return OCRPage(1, 300, 600, (OCRBlock("1", self.text, (10, 200, 250, 220), .9, 0),))


class FakeEngine:
    def __init__(self, fail_at=0):
        self.calls = 0
        self.fail_at = fail_at

    def recognize(self, path):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("interrupted")
        return OCRPage(1, 300, 600, (OCRBlock("1", "테스트 본문입니다.", (10, 200, 250, 220), .9, 0),))


class NumberedEngine:
    """Returns text that identifies which rendered page image it was given."""
    def recognize(self, path):
        number = int(Path(path).stem.split("_")[1])
        return OCRPage(1, 300, 600, (OCRBlock("1", f"페이지{number}본문", (10, 200, 250, 220), .9, 0),))


class ParentheticalEngine:
    def recognize(self, path):
        return OCRPage(1, 300, 600, (OCRBlock("1", "본문 내용이다(계2:5) 계속됩니다.", (10, 200, 250, 220), .9, 0),))


class PipelineTests(unittest.TestCase):
    def test_text_layer_modes_have_separate_reusable_caches(self):
        for modes in ((True, False), (False, True)):
            with self.subTest(modes=modes), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "input.pdf"
                with pdfium.PdfDocument.new() as document:
                    with closing(document.new_page(72, 144)):
                        pass
                    document.save(source)
                engine = FakeEngine()
                page = OCRPage(1, 300, 600, (OCRBlock("text", "PDF 텍스트 레이어 본문입니다.",
                                                     (10, 200, 250, 220), 1.0, 0),))
                snapshots = {}
                with patch("scan2read.pipeline.extract_text_layer", return_value=page) as extract:
                    for mode in (*modes, *modes):
                        output = root / "book.epub"
                        convert(source, output, root / "work", engine, "v1", validate_structure,
                                use_text_layer=mode)
                        with ZipFile(output) as archive:
                            text = archive.read("EPUB/chapter.xhtml").decode()
                        self.assertIn(page.blocks[0].text if mode else "테스트 본문입니다.", text)
                        for path in root.rglob("raw_ocr/*.json"):
                            if path in snapshots:
                                self.assertEqual(path.read_bytes(), snapshots[path])
                            snapshots[path] = path.read_bytes()
                self.assertEqual(engine.calls, 1)
                self.assertEqual(extract.call_count, 1)
                self.assertEqual(len(snapshots), 2)

    def test_parentheses_transform_preserves_clean_and_raw_in_both_paths(self):
        for reconstructed in (False, True):
            with self.subTest(reconstructed=reconstructed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "input.pdf"
                with pdfium.PdfDocument.new() as document:
                    with closing(document.new_page(72, 144)):
                        pass
                    document.save(source)
                snapshots = None
                for remove in (False, True, False):
                    output = root / "book.epub"
                    convert(source, output, root / "work", ParentheticalEngine(), "v1", validate_structure,
                            reconstruct_paragraphs=reconstructed, remove_parentheses=remove,
                            spacing=lambda text: text.replace("계속됩니다", "계속 됩니다"))
                    with ZipFile(output) as archive:
                        text = archive.read("EPUB/chapter.xhtml").decode()
                    self.assertEqual("계2:5" in text, not remove)
                    self.assertIn("계속 됩니다", text)
                    current = {p: p.read_bytes() for pattern in ("raw_ocr/*.json", "clean/*.json")
                               for p in root.rglob(pattern)}
                    if snapshots is not None:
                        self.assertEqual(current, snapshots)
                    snapshots = current
                    clean = json.loads(next(root.rglob("clean/*.json")).read_text(encoding="utf-8"))
                    clean_text = clean[0]["text"] if reconstructed else clean["paragraphs"][0]
                    self.assertIn("계2:5", clean_text)
                    self.assertIn("계속 됩니다", clean_text)

    def test_context_reconstruction_preserves_raw_and_records_all_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            with pdfium.PdfDocument.new() as document:
                with closing(document.new_page(72, 144)):
                    pass
                document.save(source)
            page = OCRPage(1, 300, 600, (
                OCRBlock("text-1", "고대", (10, 200, 55, 220), .9, 0),
                OCRBlock("text-2", "근동의", (65, 200, 125, 220), .9, 1),
                OCRBlock("line-3", "문화를 설명한다.", (25, 260, 250, 280), .9, 2),
            ))
            with patch("scan2read.pipeline.extract_text_layer", return_value=page):
                convert(source, root / "book.epub", root / "work", FakeEngine(), "v1",
                        validate_structure, reconstruct_paragraphs=True,
                        context_join=lambda left, right: left.endswith("의"))
            raw_path = next(root.rglob("raw_ocr/*.json"))
            clean_path = next(root.rglob("clean/document.json"))
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            clean = json.loads(clean_path.read_text(encoding="utf-8"))
            self.assertEqual([b["text"] for b in raw["blocks"]], ["고대", "근동의", "문화를 설명한다."])
            self.assertEqual(clean[0]["text"], "고대 근동의 문화를 설명한다.")
            self.assertEqual(clean[0]["sources"], [[1, "text-1"], [1, "text-2"], [1, "line-3"]])

    def test_resume_cache_and_force_preserve_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            with pdfium.PdfDocument.new() as document:
                for _ in range(3):
                    with closing(document.new_page(72, 144)):
                        pass
                document.save(source)
            output = root / "book.epub"
            def run(engine, force=False):
                return convert(source, output, root / "work", engine, "fake-v1", validate_structure, force=force)
            with self.assertRaises(RuntimeError):
                run(FakeEngine(fail_at=2))
            self.assertFalse(output.exists())
            original = {p: p.read_bytes() for p in root.rglob("raw_ocr/*.json")}
            self.assertEqual(len(original), 1)
            resumed = FakeEngine()
            run(resumed)
            self.assertEqual(resumed.calls, 2)
            cached = FakeEngine()
            run(cached)
            self.assertEqual(cached.calls, 0)
            forced = FakeEngine()
            run(forced, True)
            self.assertEqual(forced.calls, 3)
            for path, value in original.items():
                self.assertEqual(path.read_bytes(), value)
            validate_structure(output)

    def test_settings_invalidation_and_failed_validation_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            with pdfium.PdfDocument.new() as document:
                with closing(document.new_page(72, 144)):
                    pass
                document.save(source)
            output = root / "book.epub"
            engine = FakeEngine()
            def run(key="v1", dpi=300, validator=validate_structure):
                convert(source, output, root / "work", engine, key, validator, dpi=dpi)
            run()
            run()
            self.assertEqual(engine.calls, 1)
            run(key="v2")
            run(dpi=200)
            self.assertEqual(engine.calls, 3)
            original = output.read_bytes()
            def fail(path):
                raise ValueError("validation failed")
            with self.assertRaises(ValueError):
                run(validator=fail)
            self.assertEqual(output.read_bytes(), original)
            self.assertFalse(list(root.glob("*.pending.epub")))
            # Source content changes must invalidate the cache even at the same path.
            with source.open("ab") as stream:
                stream.write(b"\n% source revision\n")
            run()
            self.assertEqual(engine.calls, 4)

    def test_page_range_only_processes_and_includes_selected_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            with pdfium.PdfDocument.new() as document:
                for _ in range(5):
                    with closing(document.new_page(72, 144)):
                        pass
                document.save(source)
            output = root / "book.epub"
            convert(source, output, root / "work", NumberedEngine(), "v1", validate_structure, page_range=(2, 3))
            with ZipFile(output) as archive:
                text = archive.read("EPUB/chapter.xhtml").decode()
            self.assertIn("페이지2본문", text)
            self.assertIn("페이지3본문", text)
            for excluded in (1, 4, 5):
                self.assertNotIn(f"페이지{excluded}본문", text)
            raw = sorted(p.name for p in root.rglob("raw_ocr/*.json"))
            self.assertEqual(raw, ["page_0002.json", "page_0003.json"])

    def test_page_range_reuses_cache_from_a_prior_full_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            with pdfium.PdfDocument.new() as document:
                for _ in range(3):
                    with closing(document.new_page(72, 144)):
                        pass
                document.save(source)
            output = root / "book.epub"
            engine = FakeEngine()
            convert(source, output, root / "work", engine, "v1", validate_structure)
            self.assertEqual(engine.calls, 3)
            convert(source, output, root / "work", engine, "v1", validate_structure, page_range=(2, 2))
            self.assertEqual(engine.calls, 3)

    def test_parentheses_kept_by_default_and_removed_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            with pdfium.PdfDocument.new() as document:
                with closing(document.new_page(72, 144)):
                    pass
                document.save(source)
            with_parens = root / "with.epub"
            convert(source, with_parens, root / "work", ParentheticalEngine(), "v1", validate_structure)
            with ZipFile(with_parens) as archive:
                text = archive.read("EPUB/chapter.xhtml").decode()
            self.assertIn("본문 내용이다(계2:5) 계속됩니다.", text)

            without_parens = root / "without.epub"
            convert(source, without_parens, root / "work", ParentheticalEngine(), "v1", validate_structure,
                     remove_parentheses=True)
            with ZipFile(without_parens) as archive:
                text = archive.read("EPUB/chapter.xhtml").decode()
            self.assertIn("본문 내용이다 계속됩니다.", text)
            self.assertNotIn("계2:5", text)
            # The cached "clean" JSON keeps Clean Text intact -- parenthesis
            # removal is a TTS-only transformation and must not overwrite it.
            clean_json = next(root.rglob("clean/page_0001.json")).read_text(encoding="utf-8")
            self.assertIn("계2:5", clean_json)

    def test_ai_enhancer_only_receives_paragraphs_the_local_pre_filter_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            with pdfium.PdfDocument.new() as document:
                with closing(document.new_page(72, 144)):
                    pass
                document.save(source)

            ordinary = "이 문장은 띄어쓰기와 마침표가 정상적인 평범한 본문입니다."
            enhancer = RecordingEnhancer(AIOptions(ocr_words=True))
            convert(source, root / "ordinary.epub", root / "work-ordinary",
                    SingleParagraphEngine(ordinary), "v1", validate_structure,
                    reconstruct_paragraphs=True, ai_enhancer=enhancer)
            self.assertEqual(enhancer.calls, [])

            glitched = "본문 중g간에 오식이 섞인 문장입니다."
            enhancer = RecordingEnhancer(AIOptions(ocr_words=True))
            convert(source, root / "glitched.epub", root / "work-glitched",
                    SingleParagraphEngine(glitched), "v1", validate_structure,
                    reconstruct_paragraphs=True, ai_enhancer=enhancer)
            self.assertEqual(enhancer.calls, [[glitched]])

    def test_invalid_page_range_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            with pdfium.PdfDocument.new() as document:
                for _ in range(3):
                    with closing(document.new_page(72, 144)):
                        pass
                document.save(source)
            output = root / "book.epub"
            engine = FakeEngine()
            with self.assertRaises(ValueError):
                convert(source, output, root / "work", engine, "v1", validate_structure, page_range=(2, 5))
            with self.assertRaises(ValueError):
                convert(source, output, root / "work", engine, "v1", validate_structure, page_range=(0, 2))
            with self.assertRaises(ValueError):
                convert(source, output, root / "work", engine, "v1", validate_structure, page_range=(3, 1))


class OcrOnlyTests(unittest.TestCase):
    """`ocr_only()` backs the GUI's chunked parallel-OCR scheduler: several
    calls covering disjoint page ranges of the same book must be able to
    populate one shared work-dir cache, which a single later `convert()`
    call (covering the full range) then reuses without re-running OCR."""

    def _book(self, root, pages=5):
        source = root / "input.pdf"
        with pdfium.PdfDocument.new() as document:
            for _ in range(pages):
                with closing(document.new_page(72, 144)):
                    pass
            document.save(source)
        return source

    def test_ocr_only_caches_only_the_requested_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._book(root)
            ocr_only(source, root / "work", NumberedEngine(), "v1", (2, 3))
            raw = sorted(p.name for p in root.rglob("raw_ocr/*.json"))
            self.assertEqual(raw, ["page_0002.json", "page_0003.json"])

    def test_ocr_only_skips_already_cached_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._book(root)
            engine = FakeEngine()
            ocr_only(source, root / "work", engine, "v1", (1, 2))
            self.assertEqual(engine.calls, 2)
            ocr_only(source, root / "work", engine, "v1", (2, 3))
            self.assertEqual(engine.calls, 3)  # only page 3 was new

    def test_two_disjoint_ocr_only_ranges_let_convert_skip_ocr_entirely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._book(root)
            engine = FakeEngine()
            ocr_only(source, root / "work", engine, "v1", (1, 2))
            ocr_only(source, root / "work", engine, "v1", (3, 5))
            self.assertEqual(engine.calls, 5)
            output = root / "book.epub"
            # The finalizing convert() call must not re-run OCR for any page.
            convert(source, output, root / "work", engine, "v1", validate_structure)
            self.assertEqual(engine.calls, 5)
            with ZipFile(output) as archive:
                text = archive.read("EPUB/chapter.xhtml").decode()
            self.assertIn("테스트 본문입니다.", text)

    def test_ocr_only_rejects_invalid_page_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._book(root, pages=3)
            with self.assertRaises(ValueError):
                ocr_only(source, root / "work", FakeEngine(), "v1", (2, 5))
