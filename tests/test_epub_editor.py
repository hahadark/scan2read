import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scan2read.epub.builder import build_epub
from scan2read.epub.editor import Block, read_blocks, write_edited


def sample(directory: Path) -> Path:
    return build_epub(directory / "book.epub", "테스트 책",
                      [("제1장", "heading", 1), "첫 문단입니다.", "T ←", "둘째 문단입니다."])


class EpubEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_blocks_are_read_in_reading_order(self):
        blocks = read_blocks(sample(self.directory))
        self.assertEqual([block.text for block in blocks],
                         ["테스트 책", "제1장", "첫 문단입니다.", "T ←", "둘째 문단입니다."])
        self.assertTrue(all(block.document.endswith("chapter.xhtml") for block in blocks))

    def test_replacing_and_deleting_blocks(self):
        source = sample(self.directory)
        blocks = {block.text: block for block in read_blocks(source)}
        target = write_edited(source, self.directory / "edited.epub", {
            blocks["첫 문단입니다."].key: "첫 문단을 고쳤습니다.",
            blocks["T ←"].key: None,
        })
        self.assertEqual([block.text for block in read_blocks(target)],
                         ["테스트 책", "제1장", "첫 문단을 고쳤습니다.", "둘째 문단입니다."])

    def test_untouched_members_are_copied_through_byte_for_byte(self):
        source = sample(self.directory)
        blocks = read_blocks(source)
        target = write_edited(source, self.directory / "edited.epub", {blocks[2].key: "바뀐 문단"})
        with ZipFile(source) as original, ZipFile(target) as edited:
            self.assertEqual(original.namelist(), edited.namelist())
            for name in original.namelist():
                if name.endswith("chapter.xhtml"):
                    continue
                with self.subTest(name=name):
                    self.assertEqual(original.read(name), edited.read(name))

    def test_source_file_is_never_modified(self):
        source = sample(self.directory)
        before = source.read_bytes()
        blocks = read_blocks(source)
        write_edited(source, self.directory / "edited.epub", {blocks[2].key: "바뀐 문단"})
        self.assertEqual(source.read_bytes(), before)

    def test_html_entities_do_not_break_parsing(self):
        source = self.directory / "entity.epub"
        original = sample(self.directory)
        with ZipFile(original) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        chapter = [name for name in members if name.endswith("chapter.xhtml")][0]
        members[chapter] = members[chapter].replace(b"<p>", b"<p>&nbsp;", 1)
        with ZipFile(source, "w") as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        self.assertTrue(any("첫 문단입니다." in block.text for block in read_blocks(source)))

    def test_empty_blocks_are_not_offered_for_editing(self):
        source = build_epub(self.directory / "sparse.epub", "제목", ["", "   ", "진짜 문단"])
        self.assertEqual([block.text for block in read_blocks(source)], ["제목", "진짜 문단"])


    def test_a_file_that_is_not_an_epub_raises_a_clear_error(self):
        broken = self.directory / "broken.epub"
        broken.write_bytes(b"not a zip at all")
        with self.assertRaises(ValueError):
            read_blocks(broken)
        with self.assertRaises(ValueError):
            write_edited(broken, self.directory / "out.epub", {})


class BlockTests(unittest.TestCase):
    def test_key_identifies_document_and_position(self):
        self.assertEqual(Block("EPUB/a.xhtml", 3, "text").key, ("EPUB/a.xhtml", 3))


if __name__ == "__main__":
    unittest.main()
