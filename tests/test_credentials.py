import json
import os
from pathlib import Path
import tempfile
import unittest

from scan2read.project.credentials import load_api_key, save_api_key


@unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
class CredentialTests(unittest.TestCase):
    def test_round_trip_is_encrypted_and_empty_key_deletes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"credentials.json"
            save_api_key(path,"openai","sk-test-secret")
            self.assertEqual(load_api_key(path,"openai"),"sk-test-secret")
            self.assertNotIn("sk-test-secret",path.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"],2)
            save_api_key(path,"openai","")
            self.assertFalse(path.exists())

    def test_different_providers_are_stored_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"credentials.json"
            save_api_key(path,"openai","openai-key")
            save_api_key(path,"anthropic","claude-key")
            self.assertEqual(load_api_key(path,"openai"),"openai-key")
            self.assertEqual(load_api_key(path,"anthropic"),"claude-key")
            self.assertEqual(load_api_key(path,"google"),"")
            save_api_key(path,"openai","")
            self.assertEqual(load_api_key(path,"openai"),"")
            self.assertEqual(load_api_key(path,"anthropic"),"claude-key")
            self.assertTrue(path.exists())  # anthropic's key still needs the file

    def test_v1_single_key_file_is_read_as_the_openai_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"credentials.json"
            save_api_key(path,"openai","legacy-key")
            record=json.loads(path.read_text(encoding="utf-8"))
            path.write_text(json.dumps({"version":1,"ciphertext":record["keys"]["openai"]["ciphertext"]}),
                             encoding="utf-8")
            self.assertEqual(load_api_key(path,"openai"),"legacy-key")
            self.assertEqual(load_api_key(path,"anthropic"),"")
