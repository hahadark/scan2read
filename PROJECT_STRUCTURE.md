# Scan2Read 권장 폴더 구조

```text
scan2read/
├─ README.md
├─ AGENTS.md
├─ CODEX_FIRST_PROMPT.md
├─ pyproject.toml
├─ .gitignore
│
├─ src/
│  └─ scan2read/
│     ├─ __init__.py
│     ├─ __main__.py
│     ├─ cli.py
│     │
│     ├─ config/
│     │  ├─ __init__.py
│     │  ├─ defaults.py
│     │  └─ models.py
│     │
│     ├─ pdf/
│     │  ├─ __init__.py
│     │  ├─ reader.py
│     │  └─ renderer.py
│     │
│     ├─ image/
│     │  ├─ __init__.py
│     │  └─ preprocess.py
│     │
│     ├─ ocr/
│     │  ├─ __init__.py
│     │  ├─ base.py
│     │  ├─ models.py
│     │  └─ engines/
│     │     ├─ __init__.py
│     │     └─ tesseract.py
│     │
│     ├─ document/
│     │  ├─ __init__.py
│     │  ├─ models.py
│     │  ├─ structure.py
│     │  └─ reading_order.py
│     │
│     ├─ cleanup/
│     │  ├─ __init__.py
│     │  ├─ headers.py
│     │  ├─ page_numbers.py
│     │  ├─ linebreaks.py
│     │  └─ paragraphs.py
│     │
│     ├─ tts/
│     │  ├─ __init__.py
│     │  └─ optimizer.py
│     │
│     ├─ epub/
│     │  ├─ __init__.py
│     │  ├─ builder.py
│     │  └─ validator.py
│     │
│     ├─ project/
│     │  ├─ __init__.py
│     │  ├─ cache.py
│     │  ├─ manifest.py
│     │  └─ resume.py
│     │
│     └─ utils/
│        ├─ __init__.py
│        └─ logging.py
│
├─ tests/
│  ├─ fixtures/
│  ├─ unit/
│  └─ integration/
│
├─ samples/
│
└─ docs/
   ├─ architecture.md
   └─ roadmap.md
```
