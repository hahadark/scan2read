# AGENTS.md

## Project

This repository contains **Scan2Read**, a local-first application for converting scanned book PDFs into TTS-friendly EPUB3 ebooks.

The primary use case is listening to personally scanned books using a mobile ebook reader's TTS functionality, including while driving.

## Primary Product Principle

Optimize for **accurate and comfortable long-form listening** rather than exact visual reproduction of the scanned book.

Do not attempt to build a general-purpose PDF converter.

## Architecture Rule

Always preserve the following data separation:

```text
Raw OCR
    ↓
Clean Text
    ↓
TTS Text
```

Never overwrite Raw OCR. Never modify Clean Text solely for TTS pronunciation purposes. TTS-specific transformations must occur only in the TTS layer.

## Development Priority

Implement the core processing pipeline before GUI development.

Priority order:

1. PDF input
2. PDF rendering
3. OCR
4. OCR persistence
5. basic layout information
6. page-number removal
7. header/footer removal
8. line-break reconstruction
9. paragraph reconstruction
10. EPUB3 generation
11. EPUB validation
12. caching and resume

Do not begin GUI implementation until this pipeline works end-to-end.

## MVP Scope

The MVP targets:

- Korean books
- horizontal text
- normal printed books
- primarily single-column layouts
- approximately 100–500 pages
- Korean with occasional English text

Do not spend significant development effort on vertical writing, handwriting, comics, sheet music, advanced mathematical layout, historical documents, complex magazine layouts, perfect table reconstruction, or perfect two-column reconstruction during MVP.

## Coding Style

Use Python 3.12+.

Prefer:

- type hints
- dataclasses or Pydantic models where appropriate
- pathlib instead of manual path strings
- small focused modules
- explicit interfaces between pipeline stages
- dependency injection for OCR engines where practical

Avoid giant modules, hidden global state, tightly coupling OCR to EPUB creation, mixing UI code with processing logic, or destructive mutation of previous processing stages.

## Module Boundaries

- `pdf`: PDF inspection and page rendering
- `image`: image preprocessing
- `ocr`: OCR engine abstraction and OCR execution
- `document`: intermediate document representation and reading order
- `cleanup`: text cleanup and document reconstruction
- `tts`: TTS-only transformations
- `epub`: EPUB3 generation and validation
- `project`: caching, manifests, checkpoints, and resume state

## OCR Engine

OCR engines must be accessed through an abstraction.

```python
class OCREngine:
    def recognize(self, image_path: Path) -> OCRPage:
        ...
```

Do not spread vendor-specific result objects across the application. Convert engine output immediately into Scan2Read's internal OCR models.

## OCR Storage

Persist OCR output as structured data. Preserve page number, text block, bounding box, confidence, reading order, and block type when available.

## Cache

Any expensive stage should be cacheable. OCR is especially expensive. If OCR results already exist and the source page has not changed, reuse them. Do not silently repeat OCR for hundreds of pages.

## Resume

Long-running conversions must be resumable. If processing stops after page 217 of a 430-page book, restarting the command should continue from the last valid checkpoint whenever possible.

## Memory Usage

Do not load an entire book's rendered pages into memory simultaneously. Process pages individually or in small batches.

## Cleanup Philosophy

Cleanup must be conservative. Do not rewrite the author's prose. Correct structural OCR artifacts, not writing style.

Allowed examples:

- broken line joins
- obvious OCR character errors
- repeated headers
- repeated footers
- page numbers
- misplaced whitespace

Avoid speculative rewriting.

## Header and Footer Detection

Use approximate vertical position, repeated occurrence across pages, text similarity, and page sequence. Be careful not to remove legitimate chapter headings.

## Page Numbers

Detect page numbers using both text pattern and page position. Avoid deleting ordinary numbers inside body text.

## Paragraph Reconstruction

Use indentation, horizontal start position, vertical gaps, punctuation, line length, and blank lines. When confidence is low, prefer fewer transformations rather than inventing paragraph boundaries.

## TTS Layer

TTS transformations must be optional and must not modify Clean Text.

Examples:

```text
요 3:16
→
요한복음 3장 16절
```

```text
마 5:3-10
→
마태복음 5장 3절에서 10절
```

## EPUB

Generate EPUB3. Prefer reflowable XHTML. Avoid fixed-layout EPUB for the main product. Use semantic headings when chapter structure is known.

## EPUB Validation

Generated EPUB files should be validated. Validation failure should be treated as a build failure unless explicitly marked as a non-critical warning.

## Tests

Write tests alongside implementation. Every non-trivial cleanup algorithm should have test cases.

Especially test:

- page numbers
- headers
- footers
- line joins
- paragraph reconstruction
- cache behavior
- resume behavior
- EPUB packaging

Regression tests should be added whenever a real scanned book reveals a new failure case.

## Test Fixtures

Keep fixtures small. Do not commit copyrighted full books. Use synthetic pages, public-domain samples, minimal generated PDFs, or small anonymized OCR excerpts.

## AI Features

Do not add external AI APIs during the initial MVP unless explicitly requested. When AI support is eventually added:

- it must be optional
- local processing remains the default
- Raw OCR remains unchanged
- before/after data should be traceable
- large deletions or additions should be detectable

AI should repair OCR, not rewrite books.

## Privacy

Never automatically upload source PDFs, rendered pages, or images of book pages to remote services.

## CLI

Initial target:

```bash
scan2read convert book.pdf
```

Useful future subcommands:

```bash
scan2read init book.pdf
scan2read render PROJECT
scan2read ocr PROJECT
scan2read clean PROJECT
scan2read build PROJECT
scan2read validate PROJECT
scan2read status PROJECT
```

## Git Discipline

Make focused commits. Prefer commits corresponding to one functional unit.

Examples:

```text
feat: add PDF page renderer
feat: add OCR engine interface
feat: persist OCR page results
feat: add EPUB3 builder
test: add header detection fixtures
fix: preserve paragraph boundary after quotations
```

## Dependency Policy

Before adding a dependency:

1. verify it is actively maintained
2. verify its license
3. check Windows support
4. check macOS support
5. avoid large dependencies unless they materially improve OCR or document processing

Keep dependencies replaceable behind application interfaces when reasonable.

## Platform Goal

The architecture must remain capable of supporting Windows and macOS. Do not introduce platform-specific assumptions into the core processing modules.

## Definition of Done for MVP

The MVP is complete when:

1. a scanned Korean PDF can be supplied through CLI
2. pages are rendered
3. OCR results are persisted
4. basic cleanup is performed
5. a valid EPUB3 is generated
6. the EPUB opens in common ebook readers
7. TTS can read the text continuously
8. processing can resume after interruption
9. Raw OCR is preserved
10. automated tests cover the core pipeline

Main acceptance criterion:

**Would a user be able to listen to the converted book for an extended drive without frequent OCR or structural errors interrupting comprehension?**
