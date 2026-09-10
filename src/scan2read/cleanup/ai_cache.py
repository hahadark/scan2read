"""Content-addressed cache for GPT paragraph-level cleanup decisions.

Keyed by model, a prompt/schema version, the active feature set, and the
paragraph's own text -- an exact-input hit reuses the prior decision at zero
new API cost. Bumping SCHEMA_VERSION (whenever the prompt or JSON schema in
ai_enhance.py changes) invalidates every prior entry automatically, since
the version is part of the key. Shared across books: the same paragraph
text recurs across different source PDFs (boilerplate, quoted scripture,
front matter) and within the same book across a --force reprocess.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 1


def cache_key(model: str, features: tuple[str, ...], text: str) -> str:
    payload = json.dumps(
        {"model": model, "schema": SCHEMA_VERSION, "features": sorted(features), "text": text},
        ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class AIResultCache:
    """One JSON file per entry under `directory`; safe to share across runs."""
    directory: Path

    def get(self, key: str) -> dict | None:
        try:
            return json.loads((self.directory / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def set(self, key: str, value: dict) -> None:
        # A unique temp name (not a fixed `.tmp` suffix) so two threads
        # writing the same key concurrently -- the same paragraph text
        # recurring across different batches -- never race on one file.
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{key}.json"
        temporary = self.directory / f"{key}.{uuid4().hex}.tmp"
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
