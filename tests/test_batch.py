from pathlib import Path
import tempfile
import unittest
from scan2read.project.batch import Preferences, output_name, plan_outputs


class BatchTests(unittest.TestCase):
    def test_rules_and_invalid_paths(self):
        self.assertEqual(output_name(Path('books/test.pdf'), '{index:03d}_{folder}_{name}', 2), '002_books_test.epub')
        self.assertEqual(output_name(Path('book.pdf'), '{name}.epub', 1), 'book.epub')
        for rule in ('../{name}', '{bad}', '{name.__class__}', '{index:999999d}', 'CON', '', 'foo/bar'):
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                output_name(Path('book.pdf'), rule, 1)

    def test_collisions_across_sources_and_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'book.epub').touch()
            paths=plan_outputs([root/'a/book.pdf',root/'b/book.pdf'],directory,'{name}')
            self.assertEqual([p.name for p in paths],['book (2).epub','book (3).epub'])
            paths=plan_outputs([root/'a/book.pdf',root/'b/book.pdf'],'','{name}')
            self.assertEqual([p.parent for p in paths],[root/'a',root/'b'])

    def test_invalid_settings_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            for content in ('invalid', '[]', '{"spacing":"false", "columns":"wrong"}'):
                path.write_text(content)
                self.assertEqual(Preferences.load(path),Preferences())
