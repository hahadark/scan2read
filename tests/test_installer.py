import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts.windows_installer import install, install_runtime_dependencies


class OnlineInstallerTests(unittest.TestCase):
    def make_payload(self, root: Path) -> Path:
        payload = root / "payload-online.zip"
        with ZipFile(payload, "w") as archive:
            archive.writestr("runtime/python.exe", b"placeholder")
            archive.writestr("app/example.txt", "ok")
        return payload

    def test_dependency_install_uses_cpu_index_and_prepares_models(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            calls = []
            with patch("scripts.windows_installer.run_step",
                       side_effect=lambda command, status, env=None: calls.append((command, env))):
                install_runtime_dependencies(target)
            self.assertIn("ensurepip", calls[0][0])
            self.assertIn("paddlepaddle==3.3.1", calls[1][0])
            self.assertIn("https://www.paddlepaddle.org.cn/packages/stable/cpu/", calls[1][0])
            self.assertEqual(calls[2][1]["PYTHONPATH"], str(target / "app"))
            self.assertIn("PaddleEngine", calls[2][0][-1])

    def test_extract_only_writes_complete_uninstall_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = self.make_payload(root)
            target = root / "installed"
            with patch("scripts.windows_installer.payload_path", return_value=payload):
                install(target, shortcuts=False, download=False)
            manifest = json.loads((target / "installed-files.json").read_text(encoding="utf-8"))
            self.assertIn("app/example.txt", manifest)
            self.assertNotIn("uninstall.ps1", manifest)
            self.assertTrue((target / "uninstall.ps1").is_file())

    def test_failed_download_removes_partial_new_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = self.make_payload(root)
            target = root / "installed"
            with patch("scripts.windows_installer.payload_path", return_value=payload), \
                 patch("scripts.windows_installer.install_runtime_dependencies",
                       side_effect=RuntimeError("network failed")):
                with self.assertRaises(RuntimeError):
                    install(target, shortcuts=False)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
