# Changelog

## AI context checking

- Added pre-conversion token estimates, maximum-cost display, actual usage and
  per-feature cost reporting, and a per-book USD limit with automatic local fallback.
- Added opt-in GPT-5.6 Luna checks for ambiguous Korean paragraph boundaries.
- Batched short text excerpts and required structured join/no-join responses; AI cannot rewrite OCR text.
- Added automatic local fallback, `store: false`, audit records, GUI controls, and CLI `--ai-context` support.
- Kept API keys out of saved preferences and process command lines.

Session-level log of what changed and why, for whichever agent (human or AI)
picks this project up next. Feature-level usage docs live in
[README.md](../README.md) and [WINDOWS.md](WINDOWS.md); this file is the
narrative of *how* things got to their current state, including real-book
findings and rejected approaches, which those reference docs don't carry.

## 2026-09-09

### HiDPI support

User asked, tersely, for HiDPI support ("hidpi에 대응시켜줘") right after the
sv-ttk/font work above. The PyInstaller-built exe carries no manifest
declaring DPI awareness, so Windows treats it as unaware by default and
covers for it the way it always does for unaware apps: render at 100% and
stretch the bitmap to fill the real display -- blurry text and UI on any
scaled display, independent of and in addition to the font issue just fixed.

- Added `dpi_scale()`: calls `ctypes.windll.shcore.SetProcessDpiAwareness(1)`
  (`PROCESS_SYSTEM_DPI_AWARE`, falling back to the older
  `user32.SetProcessDPIAware()` on Windows versions without `shcore`) to opt
  out of that stretching, then reads the real factor via
  `GetScaleFactorForDevice(0)` (150 for 150%, etc., divided by 100). Returns
  `1.0` on non-Windows or if any of this fails, making every caller's math
  downstream a no-op. Must run in `main()` *before* the first `tk.Tk()` is
  constructed -- DPI awareness can't be changed after a window exists.
- The factor feeds two genuinely different code paths, because Tk itself
  splits sizing the same way:
  - Point-based values (font sizes, ttk theme metrics) go through Tk's own
    `tk scaling` conversion to pixels -- set once via `window.tk.call("tk",
    "scaling", dpi_scale * 96/72)` in `Application.__init__` (96 = the DPI
    Tk assumes for its baseline "1.0" scaling; 72 = points per inch).
  - Raw pixel literals -- `geometry`/`minsize`, the Treeview's `rowheight`
    and column widths, several labels' `wraplength` -- pass straight
    through Tk unscaled regardless of `tk scaling`. Added `Application._px
    (value)` (`round(value * self.dpi_scale)`) and applied it at each of
    these call sites. Left the many small `padx`/`pady` constants scattered
    through the layout unscaled -- a few unscaled pixels of padding isn't
    visible, whereas an unscaled window fighting now-larger (correctly
    scaled) font content, or unscaled Treeview columns truncating text,
    would be.
  - `Application.__init__` gained a `dpi_scale: float = 1.0` parameter;
    tests construct `Application(window)` with the default and see exactly
    today's pixel values, so no existing layout assertion needed touching.
- Tests: `DpiScaleTests` mocks `ctypes.windll` to check the factor is read
  correctly, that the non-Windows branch always returns 1.0, and that
  either `SetProcessDpiAwareness`/`SetProcessDPIAware` or
  `GetScaleFactorForDevice` failing falls back to 1.0 rather than raising.
  `GuiTests` gained a case building a second, independent `Application` at
  `dpi_scale=1.5` and checking the *actual* resulting window geometry and
  Treeview column width via `update_idletasks()` + `.geometry()` /
  `.column(...)`, not just that `_px()` does the arithmetic right in
  isolation. 273 tests total.
- Not verified against a real scaled display -- no such monitor available
  to check by eye; correctness rests on the headless pixel-math tests above
  plus the underlying Win32 API contract, not a visual confirmation.
- Deployed: full PyInstaller rebuild (gui.py changed) synced into
  `dist/Scan2Read`; confirmed `dpi_scale`, `SetProcessDpiAwareness`,
  `GetScaleFactorForDevice`, and `_px` all present in the frozen exe's
  `scan2read.gui` bytecode, and `app/scan2read` still hashes identical to
  `src`. Installer untouched, per standing instruction.

### AI-judged redundant transliteration removal, and an sv-ttk theme

User was reading a real chapter (a Hebrew-original theology book) through
the "괄호 안 내용 제거" (remove-parenthetical) feature and asked what it
actually does. Walking through the code found the intended answer -- but
then the user pasted a real paragraph from their own book and asked what
survives. Running it through `remove_parenthetical()` showed the whole
paragraph came back byte-for-byte unchanged: 10 open parens, 11 close --
OCR had eaten exactly one open paren near a Hebrew transliteration
('하마스'oㅋ), so the balance check (correctly) refused to touch anything
in that paragraph at all, including several perfectly well-formed
citations elsewhere in the same text. User's diagnosis: Hebrew-original
books do this a lot, and asked for AI to catch it -- plus, separately, for
cases like "정의(체다카)" where the parens *are* balanced but the local
rule can't tell that the bracketed word is just a Hebrew transliteration of
the Korean word right before it, so TTS reads the same idea twice.

- Added a sixth `AIOptions` field, `glosses`, following the exact pattern
  of the five existing AI cleanup toggles in `ai_enhance.py`: a schema
  property (`remove_glosses`, an array of exact substrings to delete), a
  prompt clause, and a validated apply step.
- `AIEnhancer._apply_glosses()` is deliberately not a rename of
  `_apply_edits()` -- it's a pure deletion (no "after" text), so the
  existing safety net (a `difflib` similarity ratio against the edited
  text) doesn't transfer: a legitimate gloss deletion naturally scores
  *lower* than an edit of the same size would, since there's nothing to
  align against on one side. First attempt used a 0.85 ratio floor and
  rejected a real, correct example (`"이것이 정의(체다카)의 뜻이다."` ->
  ratio 0.83) outright. Replaced it with what the ratio was actually
  standing in for: the span must appear exactly once verbatim (so the
  model can't target the wrong occurrence or half-remember the text) and
  be at most a third of the paragraph's own length (a gloss is a short
  aside, not most of the sentence) -- a fraction of length is legible
  where a similarity ratio for a deletion isn't.
- `ai_filter.py`'s local pre-filter gained a signal for `glosses`: any
  paragraph containing a paren character (`(`, `)`, full-width variants
  included) is worth sending -- deliberately permissive, since a *lone*
  unmatched paren is exactly the OCR-damaged case the local deterministic
  remover can't touch and this feature exists to catch.
- Extracted `parentheses.py`'s whitespace cleanup (space-before-punctuation,
  double-space collapse) into a shared `tidy_whitespace()`, reused by both
  the local remover and the new AI deletion path -- a gap left by deleting
  a gloss mid-sentence needs the identical cleanup a fully-removed
  parenthetical does.
- Wired the new feature through the whole existing per-feature-toggle
  stack: `Preferences.ai_glosses`, CLI `--ai-glosses`, the GUI's 7th AI
  feature checkbox ("괄호·음역 중복 표현 삭제"), and `ai_usage.py`'s
  `FEATURE_LABELS`/`estimate_book_usage` (added at the same per-page output
  weight ballpark as `anomalies`, since both return a handful of short
  strings per page).
- Known, accepted composition limit (not a regression, an existing one
  inherited): if `spacing` and `glosses` both fire on the same paragraph,
  `spacing_text` was generated by the model against the *original* text,
  but gets validated against the text *after* `glosses` already deleted a
  span from it -- the whitespace-insensitive equality check then fails and
  the spacing update is silently skipped. This is the same tension that
  already existed between `ocr_words` and `spacing` (an ocr_edit that
  changes real characters, not just whitespace, has always caused the same
  silent skip) -- extended to a second feature rather than introduced.
- Tests: `test_ai_enhance.py` gained cases for a legitimate deletion, a
  span that would erase too much of the paragraph, and a span that's
  either absent or ambiguous (appears twice). `test_ai_filter.py` gained
  paren/no-paren/lone-unmatched-paren cases. `test_ai_usage.py` and
  `test_cli.py` got matching coverage for the new option and flag.

User also said the GUI itself "looks too old" and asked for it to look
nicer. Checked what theme was actually active before guessing: Windows'
own ttk already defaults to `vista` here (confirmed via
`ttk.Style().theme_use()`), which is why plain built-in-theme tweaking
wouldn't have moved the needle much -- `vista` is Windows 7/10-era Aero
styling, not Windows 11's flat design language, and Tkinter ships no
built-in theme that matches the latter. Asked the user to choose between
restyling on top of the built-in theme (no new dependency, limited
ceiling) versus adding `sv-ttk` (a small, pure-Python, MIT-licensed
"Sun Valley" theme matching Windows 11's look); they picked `sv-ttk`.

- Added `sv-ttk>=2.6,<3` to `pyproject.toml` and installed it into both
  `.tools/paddle-env` (dev/test) and `.venv` (the PyInstaller build venv).
- `gui.py` imports it the same optional way `tkinterdnd2` already is (try/
  except `ImportError`), and calls `sv_ttk.set_theme("light", root=window)`
  as the very first thing in `Application.__init__`, before any widget is
  built, so everything picks up the theme from its first paint.
- `sv_ttk` loads its Sun Valley theme via a Tcl `source` call on a `.tcl`
  file plus PNG sprite sheets, resolved relative to the *installed
  package's own* `__file__` at runtime -- not something PyInstaller's
  pure-Python `Analysis` step picks up on its own. Added `datas =
  collect_data_files('sv_ttk')` to `Scan2Read.spec`; verified after the
  rebuild that `_internal/sv_ttk/` actually contains `sv.tcl`,
  `theme/{light,dark}.tcl`, and both sprite-sheet PNGs, not just the `.py`
  files a naive guess might have assumed were sufficient.
- Verification: launched the rebuilt exe and confirmed no `TclError` (the
  failure mode if the theme data were missing); confirmed headlessly that
  `ttk.Style().theme_use()` reports `sun-valley-light` after
  `Application.__init__` runs. A `computer-use` screenshot request to
  visually confirm the look was denied (dev exe isn't a named installed
  app, and the permission prompt was declined) -- reported this limitation
  plainly rather than describing an appearance never actually seen.
- Deployed: full PyInstaller rebuild (gui.py and its sv_ttk import both
  changed) synced into `dist/Scan2Read`. The installer was left untouched,
  per standing instruction.
- **Follow-up, same day**: user actually ran the rebuilt exe (confirming the
  theme *was* live, resolving the "never actually seen" gap above) and
  reported the font looked wrong -- "폰트 이상한거 하지 말고 그냥 맑은고딕
  해" (stop with the weird font, just use Malgun Gothic). Root cause:
  `sv_ttk`'s own `sv.tcl` creates eight named Tcl fonts (`SunValleyBodyFont`,
  `SunValleyCaptionFont`, and six bold/display variants) hardcoded to
  "Segoe UI Variable" -- a Windows 11 font whose Hangul fallback isn't
  reliable on every machine, and it clearly wasn't on this one. sv_ttk
  assigns these fonts to only a few specific styles directly (Treeview rows/
  headings, LabelFrame captions) -- most other widgets keep using Tk's
  ordinary `TkDefaultFont`, which was rendering Hangul fine the whole time,
  so the breakage was narrower than "the whole UI" but exactly where the
  user was looking (the file list and its column headers).
  - Added `_use_malgun_gothic(window)`: reconfigures all eight named
    `SunValley*Font` Tcl font objects in place (via `tkinter.font.Font(...,
    exists=True)`) to family "맑은 고딕", keeping sv_ttk's own sizes and
    using `weight="bold"` for the five variants sv_ttk names Strong/
    Semibold/Title/Display (Malgun Gothic has no separate "Semibold" family
    name the way Segoe UI Variable does). Called immediately after
    `sv_ttk.set_theme(...)`, before any widget is built.
  - Verified the actual font objects post-fix report family "맑은 고딕"
    (not just that the call didn't raise) via `tkfont.Font(...).actual()`,
    both standalone and through `test_gui.py`'s new regression test.
  - Deployed: rebuilt again, verified `_use_malgun_gothic` and
    `SunValleyBodyFont` both present in the frozen exe's `scan2read.gui`
    bytecode (`co_names`, not `co_consts` -- attribute names and imported
    module names live there, not in the constant pool a naive string scan
    would check), and that `app/scan2read` still hashes identical to `src`.
    267 tests total.

### Page-range parallel OCR, live GPU utilization, and a tabbed GUI

User noticed something: running several instances of the app at once used
more GPU than one instance alone. Each `scan2read convert` subprocess loads
its own independent PaddleOCR/CUDA context, so several processes really do
run in parallel on the GPU -- the fix was to make the GUI do automatically
what the user had just discovered by hand. The ask then got more specific
over two follow-up messages: split a single PDF's own page range across
processes (not just run different queued files at once, which does nothing
when the queue holds only one book), let the user pick how many processes,
and show live GPU utilization. Entered plan mode given the size (new
pipeline/CLI surface, a from-scratch GUI job scheduler, ~40 test changes) and
got sign-off before writing code.

- **`pipeline.py`** (pure extraction, no behavior change to `convert()`):
  pulled the per-page render/OCR/cache loop out of `convert()`'s inner
  closure into a module-level `_ocr_pages()`, and the cache-key hashing into
  `_settings_key()`/`_settings_dict()`. Added a new public `ocr_only(source,
  work_dir, engine, engine_key, page_range, ...)` that runs that same loop
  for one page range and stops -- no paragraph reconstruction, no EPUB, no
  manifest read/write. It targets the fixed `generations/initial` directory
  directly (skipping the manifest entirely) rather than reading/creating
  `project.json`, which sidesteps any question of concurrent writes: the
  cache key already excludes the page range, so several `ocr_only()` calls
  covering disjoint ranges of the same book -- or `ocr_only()` alongside a
  later `convert()` -- write to the same project directory safely, as long
  as nothing passes `force=True` (which reassigns the generation to a fresh
  UUID that `ocr_only()` doesn't know about; the GUI never passes `--force`
  in a batch run, so this is a documented constraint, not a live bug).
- **`cli.py`**: new `ocr-pages <file> --pages A-B ...` subcommand wrapping
  `ocr_only()`, and `gpu-usage` wrapping the new `gpu_utilization()`.
  Factored the engine-selection code (paddle vs. tesseract, two-column
  wrapping, `cache_identity()`) that `convert` and `ocr-pages` both need
  into shared `_add_engine_arguments()`/`_build_engine()` helpers.
- **`ocr/gpu.py`**: added `gpu_utilization()`, parsing `nvidia-smi
  --query-gpu=utilization.gpu,memory.used,memory.total` -- same
  no-package-dependency, `_NO_WINDOW`/timeout style as the existing
  `detect_nvidia_gpu()`.
- **`gui.py` job scheduler** (replaces the old one-`Popen`-at-a-time batch
  loop): a new `max_parallel_conversions` preference (1-4, default 2) sizes
  a pool of concurrently active subprocesses. At batch start, each file's
  page range is split into `min(max_parallel, pages // 15)` contiguous
  chunks (never smaller than 15 pages -- each chunk pays a fixed PaddleOCR
  model-load cost, so splitting too fine loses more than it gains) and
  queued as OCR-only jobs; a "finalize" job (the old full `convert` command,
  unchanged) is enqueued for a file only once all its OCR chunks finish.
  One flat queue and one `_fill_batch_slots()` keep exactly `max_parallel`
  jobs active regardless of whether they're chunks of one big book or
  finalize jobs for several smaller ones -- so a single queued file gets
  real parallelism too, not just multiple queued files. `max_parallel == 1`
  skips chunking entirely and reproduces the old one-job-per-file behavior
  byte-for-byte, so a user who never touches the new setting sees no change.
  - Progress display: the per-page log lines (`Rendering/OCR: n / total`)
    are untouched in the pipeline; the GUI now tracks each chunk's own
    last-reported page and sums `min(last, chunk_end) - chunk_start + 1`
    across a file's chunks to show "OCR 320/554쪽" in that file's row. The
    global progress bar's meaning changed from per-page to completed-files/
    total-files, since one bar can no longer represent several files'
    concurrent per-page progress.
  - Cancellation: `stop()` terminates every active process. A file is only
    marked "중단" once *all* of its own currently-active jobs have reported
    back -- not the first one -- since a sibling chunk of the same file can
    still be mid-flight when another one is terminated. The remaining
    unstarted queue is swept to "취소" only once every active job anywhere
    has finished. Caught and fixed this exact ordering bug while writing
    the test for it (first draft marked the file done on the *first*
    cancelled chunk, which is wrong when N>1 chunks are still running).
  - AI usage/progress display now aggregates per-file: `_show_ai_usage`
    keeps the latest snapshot per source and sums across all of them, so
    the shared status line shows a correct total when multiple finalize
    jobs (each running its own AI cleanup) happen to be active at once --
    without double-counting, since each snapshot is already that book's own
    running total.
- **GUI reorganized into three `ttk.Notebook` tabs** ("변환" / "변환 설정" /
  "AI 설정"), fixing a real problem: this session's earlier AI
  provider/model feature had pushed the start/stop buttons and the log box
  off the bottom of the window. Every widget kept its existing `self.xxx`
  attribute name -- only the parent frame each one packs into changed --
  so nearly all pre-existing tests needed no changes beyond the event-shape
  updates below. Shrank the default window from 1040x920 to 1000x700 now
  that the main tab is short again.
- **A real deployment mistake, caught by asking "런처 빌드 다 된거야?" before
  declaring done**: `Scan2Read.spec` freezes the *entire* `scan2read`
  package into the exe's own PYZ archive (confirmed by reading
  `build/Scan2Read/PYZ-00.toc`), so the GUI process runs whichever version
  of `cleanup/`, `ocr/`, etc. was on disk at the *last full PyInstaller
  build* -- not the live `app/scan2read` copy, which is what the CLI
  subprocess reads. Earlier this session, an `ai_providers.py` edit made
  after a launcher rebuild had silently shipped a stale build for a while.
  This time, code kept changing after the rebuild (the cancellation-order
  fix above landed after an initial build), so the launcher was rebuilt
  again and the fix confirmed present by re-extracting the PYZ. Documented
  the trap and the verification method in `CURRENT_SPEC.md`.
- Event schema change (internal, not user-facing): `("log", line)` and
  `("done", code)` became `("log", (job_key, line))` and `("done",
  (job_key, code))`, where `job_key` is `(file, "ocr", chunk_index)` or
  `(file, "finalize")`. `self.process` (a single `Popen`) became
  `self.active: dict[job_key, {"process", "job"}]`.
- Tests: `tests/test_pipeline.py` gained `OcrOnlyTests` (partial-range
  caching, skip-already-cached, and the key integration case -- two
  disjoint `ocr_only()` ranges followed by one `convert()` that does zero
  further OCR calls). `tests/test_cli.py` gained `ocr-pages`/`gpu-usage`
  coverage. `tests/test_gpu.py` gained `GpuUtilizationTests`.
  `tests/test_gui.py`'s batch tests were split: ones asserting naming/status
  text (not concurrency itself) pin `max_parallel_conversions` to `'1'` to
  keep exercising strict sequential behavior; new tests cover chunk
  splitting, chunk-then-finalize ordering, cross-file slot sharing,
  terminate-all-on-stop, the cancellation-ordering fix, and aggregated
  row progress text. A `tearDown()` bug was fixed in the process: it reset
  `self.app.process = None`, an attribute that no longer exists post-rewrite
  -- `close()` now checks `self.active`, so leftover mock processes from a
  test that never sent a "done" event caused a real (unmocked, blocking)
  `messagebox.askyesno` confirmation dialog in every subsequent test's
  teardown, hanging the whole suite. 258 tests total.
- Deployed: full PyInstaller rebuild (`gui.py` changed) synced into
  `dist/Scan2Read`, exe launch confirmed, and the three-tab structure with
  widgets in their correct tabs confirmed headlessly (Tk widgets are
  real even off-screen, so this checks more precisely than a screenshot
  would). Not yet verified against a real multi-process GPU run with an
  actual book -- unit-tested only, per `CURRENT_SPEC.md`'s limitations note.
  The installer was left untouched, per standing instruction.

### Full model registry for all three providers, with real published rates

User asked to search out and add every current model across Gemini, GPT, and
Claude ("그냥 제미나이 gpt 클로드 모든 모델을 선택할 수 있게 검색해서 추가해"),
after the `gpt-6-astra` exchange showed that the placeholder prices from the
day before were guesses.

- Researched each vendor's September 2026 lineup and published per-token
  rates, and replaced the 5-entry placeholder registry with real models:
  - OpenAI: `gpt-5.6-terra` (2.00/0.20/12.00), `gpt-5.6-luna`
    (0.20/0.02/1.20). `gpt-6-astra` and `gpt-5.6-sol` were added first, then
    **removed at the user's call after the cost test priced them** -- see the
    measured-cost entry below.
  - Anthropic: `claude-fable-5-1` (10.00/0.25/50.00), `claude-opus-5`
    (5.00/0.50/25.00), `claude-sonnet-5` (3.00/0.30/15.00),
    `claude-haiku-4-5-20251001` (1.00/0.10/5.00).
  - Google: `gemini-3.8-flash` (0.75/·/3.75), `gemini-3.6-flash`
    (1.50/·/7.50), `gemini-2.5-pro` (1.25/·/10.00), `gemini-2.5-flash`
    (0.30/0.075/2.50), `gemini-2.5-flash-lite` (0.10/·/0.40).
  - Input/output rates are all published values. Cached-input rates are
    published for OpenAI and Anthropic; Google's are derived from the 25%
    context-caching ratio Google publishes for 2.5 Flash. Two real
    irregularities worth keeping: Fable 5.1's cache read is 2.5% of input
    (Anthropic cut it), not the usual 10%; and `gemini-3.8-flash` is on
    introductory pricing that doubles on 2027-01-01.
- Several of the previous day's guesses were wrong in the expensive
  direction -- `claude-opus-5` was registered at 15.00/75.00 against a real
  5.00/25.00, so the budget would have cut a book off at a third of the
  spend the user actually authorized.
- **Caught a real regression this change introduced**: three call sites
  (`gui.py:_refresh_model_choices`, `cli.py`'s default when `--ai-model` is
  omitted, and `resolve_model`'s fallback) all used "first model of this
  provider" as their implicit default. With the registry ordered
  flagship-first, merely switching providers in the GUI would have silently
  selected a 50x pricier model. Added an explicit `DEFAULT_MODEL_FOR`
  (luna / sonnet-5 / gemini-2.5-flash) and a `default_model(provider)`
  helper, and wired both the GUI and CLI to it.
  - `resolve_model()`'s fallback for an unregistered, user-typed model ID
    now deliberately borrows the provider's *worst case* rather than
    whichever model came first: for a spending guard, overestimating only
    stops the run early, while underestimating overspends silently. Each
    rate is maxed independently, because the priciest input and priciest
    output are not always the same model -- for Google that is
    `gemini-3.6-flash` ($1.50 in) and `gemini-2.5-pro` ($10.00 out), so
    copying either model's whole row would understate the other rate.
- **`gpt-6-astra` never actually worked until the cost test ran it.** Every
  request returned HTTP 400: `OpenAIProvider` hard-codes
  `reasoning.effort: "none"` (a cost optimization -- reasoning tokens bill
  as output, and cleanup is a mechanical rewrite that needs none of it),
  but Astra rejects that value: *"Supported values are: 'low', 'medium',
  'high', 'xhigh', and 'max'"*. Unit tests never caught it because they
  assert our payload shape against a fake transport, which cannot know what
  the real API rejects. Added `ModelSpec.reasoning_effort` -- "none" for the
  5.6 family, "low" for Astra -- and `OpenAIProvider` now omits the field
  entirely for a model it doesn't carry (guessing a value it may reject is
  worse than letting the server default apply).
- **Raised the request timeout from 60s to 300s** (`REQUEST_TIMEOUT`), the
  second thing the cost test exposed: with Astra's 400 fixed, both
  `gpt-5.6-sol` and `gpt-6-astra` then *timed out* on a real 5-page
  enhancement batch. A batch can request up to 32k output tokens and the
  larger models take minutes to produce that. The failure mode was bad out
  of proportion to the cause: a socket timeout is an `OSError`, which by
  this project's own retry classification disables AI cleanup for the whole
  rest of the book -- so the timeout silently downgraded conversions on
  exactly the expensive models the user chose deliberately. Both models
  completed normally at the longer timeout.
- GUI: since rates now span 50x within a single provider, the model status
  line always shows the selected model's input/output rate (grey), and
  switches to the orange warning text only for an unregistered model ID.
- Tests: registry tests now assert every entry has published rates and sane
  ordering (output > input, cached < input), that each provider offers a
  choice of models, that an unknown ID is approximated from the worst-case
  same-provider rates, and that no provider's default is its flagship.
  `test_gui.py` gained a provider-switch-picks-cheap-default case.

### Measured real cost per OpenAI model, and dropping the expensive two

User asked to price every GPT model on 5 real pages before trusting the new
registry. Ran "고대 근동 문화" pages 100-104 with all six AI features on,
reusing cached OCR, with an empty AI cache so every model made real calls,
and a per-run `--ai-cost-limit-usd` cap.

| model | real cost | in/out tokens | vs Luna |
|---|---:|---|---:|
| gpt-5.6-luna | $0.0048 | 5,911 / 3,436 | 1x |
| gpt-5.6-terra | $0.0613 | 5,706 / 4,595 | 13x |
| gpt-5.6-sol | $0.1712 | 5,740 / 4,749 | 36x |
| gpt-6-astra | never completed | — | — |

- **User's call: dropped `gpt-6-astra` and `gpt-5.6-sol` from the registry
  and standardised on Luna.** Extrapolated to a 554-page book that is roughly
  $0.5 (Luna) against $19 (Sol) for the same mechanical cleanup, which
  doesn't pay for itself. They are removed deliberately, not by oversight --
  a test asserts their absence so a future edit doesn't quietly restore them,
  and the free-text model box still accepts them as unlisted models.
- Two side notes from the run, both harmless but worth recording:
  - The first attempt failed on every model with `FileNotFoundError` on a
    `.tmp` write. Not a product bug: the scratch work-dir path put the
    temp files at 260-261 characters, right at the Windows `MAX_PATH`
    limit. Re-ran from a short path.
  - The GPU warns that Paddle is built against CUDNN 9.9 while the machine
    has 9.5. Pre-existing, unrelated to this work, OCR output unaffected.

## 2026-09-08

### AI provider selection: OpenAI, Claude, and Gemini

User asked to add model selection, specifically Claude and Gemini as
alternatives to the existing OpenAI-only support ("ai 모델 선택 기능
넣어줘 / 클로드와 제미나이 api도 선택할 수 있게 해줘"). Clarified scope
before coding: one provider for the whole book (not per-feature), models
Astra/Opus/Sonnet/Gemini 2.5 Flash, plan reviewed and approved before any
code was written.

- Added `cleanup/ai_providers.py`, a thin `AIProvider` abstraction mirroring
  `ocr/base.py`'s `OCREngine(Protocol)` pattern -- one method,
  `complete(instructions, input_json, schema, max_output_tokens) ->
  ProviderResponse`, so `ai_context.py`/`ai_enhance.py` stay fully
  vendor-agnostic. All existing batching, local pre-filter, cache, budget
  reservation, retry classification, and progress reporting kept working
  unchanged regardless of which vendor is selected.
- Implemented three real request/response shapes from scratch with raw
  `urllib` (no SDKs):
  - `OpenAIProvider`: moved the existing `/v1/responses` logic in as-is
    (`store:false`, `reasoning.effort:none`, `text.format.json_schema`
    strict mode) -- pure relocation, no behavior change.
  - `AnthropicProvider`: Messages API. Claude has no separate strict-JSON
    response mode, so structured output is obtained via a single **forced
    tool call** (`tool_choice:{"type":"tool","name":"emit_result"}`) with
    our schema as the tool's `input_schema`.
  - `GoogleProvider`: Gemini `generateContent` with
    `responseMimeType:"application/json"` + `responseSchema`; strips
    `additionalProperties` recursively since Gemini's schema dialect
    rejects it.
- `ai_providers.MODELS` registry: `openai:gpt-5.6-luna` was already
  `verified=True` (real, previously-confirmed pricing). At implementation
  time the other four -- `openai:gpt-6-astra` (model ID confirmed by the
  user mid-session, pricing was a guess), `anthropic:claude-opus-5`,
  `anthropic:claude-sonnet-5`, `google:gemini-2.5-flash` -- were all
  `verified=False`, surfaced as an explicit orange warning label in the
  GUI. `resolve_model()` lets a user type any model ID not in the registry
  (the GUI's model field is free-text) by borrowing another same-provider
  model's pricing as an approximation, rather than crashing.
  - **Follow-up, same day**: the user asked directly whether I actually
    knew what `gpt-6-astra` was -- I didn't (outside my knowledge cutoff),
    and said so. A web search confirmed it's real: OpenAI released GPT-6
    Astra on 2026-09-03/04, and the API model ID and published pricing
    ($10.00 input / $1.00 cached input / $50.00 output per million tokens,
    1.1M context) both check out. Updated `MODELS["openai:gpt-6-astra"]`
    to those real rates and flipped it to `verified=True`.
  - **Follow-up 2 (2026-09-09)**: user then asked to search out and add
    *every* model across all three providers. See the next entry.
- Renamed `OpenAILunaContextJoiner`/`OpenAILunaEnhancer` ->
  `AIContextJoiner`/`AIEnhancer`; both now take a `provider: AIProvider`
  instead of `api_key`/`model`/`transport`/`endpoint`. `AICostBudget`/
  `token_cost`/`estimate_book_usage` now take a `ModelSpec` so cost math
  uses whichever provider's real rate applies.
- Per-provider encrypted credential storage: migrated `project/credentials.py`
  from a single-key DPAPI file to `{"version":2,"keys":{provider:
  {"ciphertext":...}}}`, with an old v1 file transparently read as the
  "openai" key on first load (existing users' saved OpenAI key isn't lost).
- GUI: provider combobox (OpenAI/Claude(Anthropic)/Gemini(Google)) next to
  an editable model combobox; switching providers reloads that provider's
  own stored key into the API key field; "연결 확인" calls a new
  `ai_providers.check_access()` (free GET lookup for OpenAI/Google, a
  minimal-cost POST completion for Anthropic since it has no free
  auth-check endpoint); unverified models show the warning label described
  above.
- CLI: added `--ai-provider {openai,anthropic,google}` (default `openai`,
  so existing users see no change) and `--ai-model ID`; each provider reads
  its own env var (`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`GOOGLE_API_KEY`).
- Tests: new `tests/test_ai_providers.py` (15 cases -- request shape,
  response parsing, and error cases for all three providers, plus registry
  and `check_access` behavior). Updated `test_ai_context.py`,
  `test_ai_enhance.py`, `test_ai_usage.py`, `test_credentials.py`,
  `test_cli.py`, and `test_gui.py` for the new constructors/signatures and
  added provider-switching/CLI-flag coverage. 225 tests total.
- Only OpenAI was exercised against a real API key this session (existing
  stored key); Claude and Gemini are unit-tested against fake transports
  only -- their model IDs and prices need real-world verification before
  the cost limit can be trusted for those providers.
- Deployed: `gui.py` changed, so the launcher needed a full PyInstaller
  rebuild (not just a source copytree), synced into `dist/Scan2Read`, and
  smoke-tested. The installer was left untouched, per `CURRENT_SPEC.md`'s
  standing instruction.

### Two real-book AI cleanup bugs: output truncation and one-failure-kills-the-book

User ran a real 554-page book (고대 근동 문화) through the GUI with AI cleanup
on and reported two warnings straight from the log.

- `AI enhancement failed: Unterminated string starting at...`: the batch-size
  increase to 24 (this session, earlier today) exposed a pre-existing
  `min(5000, ...)` cap in `ai_enhance.py`'s `max_output_tokens` formula --
  once a real 24-item batch's own linear estimate legitimately exceeded
  5000, the cap silently clamped the *request* below what the code's own
  formula said was needed, guaranteeing the response would be cut off
  mid-JSON-string. The observed truncation point (~8721 characters) lines up
  almost exactly with a ~5000-token response. Raised the cap to 32000 (a
  sanity ceiling, not the expected typical size) and the per-item baseline
  180->220.
- `AI context check failed: ...omitted or added boundary IDs`: looked like
  81% of boundary decisions failing (3406/4194), but tracing the audit trail
  showed only **one** real failure, on the very first batch of the book.
  Both `ai_context.py` and `ai_enhance.py` treated *any* exception --
  connection failure or a single malformed response -- as reason to
  permanently disable AI cleanup for the rest of that `decide_many()`/
  `enhance()` call, so the other 3405 decisions across the remaining ~550
  pages all silently fell back, re-using the same error label and making it
  look like a systemic outage. Split the exception handling in both files:
  `OSError` (network/HTTP-level, likely to keep failing) still disables the
  rest of the book; `ValueError`/`KeyError`/`TypeError`/`JSONDecodeError`
  (the request reached the service fine, this one response just didn't
  parse or validate) now only falls back *that batch* -- the next batch
  gets a fresh attempt.
- Tests: `tests/test_ai_enhance.py` gained a real-size-batch token-ceiling
  regression case and a case proving a malformed response doesn't disable
  later batches (while a connection failure still does); `tests/test_ai_context.py`
  gained the matching per-batch-recovery case. 201 tests total.
- Deployed to `dist/Scan2Read/app/scan2read` (pure `cleanup/` change).

### Real-book verification and AI-phase progress display

- Verified the whole AI cleanup stack (filter, cache, bigger batches,
  parallel requests, nullable short responses) against a real book using the
  user's own saved API key, at their explicit go-ahead and with a hard
  `--ai-cost-limit-usd` cap each time. "기독교 위험한 사상 1", cached pages
  100-120 (reused existing OCR, no new rendering cost):
  - 5 pages, 30 paragraphs: filter sent only 17 (13 skipped locally), all in
    one batch/one API call. Real cost $0.0014 vs a $0.0279 conservative
    pre-estimate (~20x lower). 13 paragraphs got real spacing corrections,
    5 got reclassified as headings. EPUBCheck passed.
  - Full 21 pages: paragraph count crossed the batch_size=24 boundary, so 2
    batches ran (2 requests per feature in `ai_usage.json`). Real cost
    $0.0051 against a $0.3 cap. EPUBCheck passed.
  - Not yet observed for real: 3+ batches running truly concurrently (this
    sample only produced 2), so `max_parallel=3` is verified in unit tests
    with an artificial delay but not yet on an actual large book.
- Added API-phase progress reporting, closing out the last item on
  `CURRENT_SPEC.md`'s priority list. Both `OpenAILunaEnhancer.enhance()`
  (parallel batches) and `OpenAILunaContextJoiner.decide_many()` (sequential
  batches) now accept a `progress` callback, invoked once before any batch
  is sent (`0/N`) and again after each batch finishes, with
  `{stage, completed_batches, total_batches, elapsed_seconds,
  estimated_remaining_seconds}` -- the ETA is the average per-batch time so
  far times the batches remaining.
  - Found and fixed a real ordering bug while writing the concurrent-path
    test: incrementing the completed-batch counter and invoking the
    callback as two separate lock-protected steps lets two threads finish
    at nearly the same time and race to invoke the callback in whichever
    order the OS schedules them -- producing an out-of-order sequence (e.g.
    completed=2 reported before completed=1) even though each individual
    count was correct. Fixed by making the whole increment-then-callback
    section one atomic critical section, so callbacks fire in strictly the
    order their batches actually completed.
  - `cli.py` prints `SCAN2READ_AI_PROGRESS {json}` (same convention as the
    existing `SCAN2READ_AI_USAGE` line). The GUI parses it into a new status
    label ("문단 경계 검사 진행률: 2/2 묶음 · 예상 남은 시간 Ns") without
    the raw line leaking into the visible log text box.
- Tests: progress-callback cases added to `tests/test_ai_enhance.py` and
  `tests/test_ai_context.py` (initial 0/N report, strictly increasing
  completion order under real thread concurrency verified across repeated
  runs, zero-candidates case), and to `tests/test_gui.py` (status text and
  log-line parsing). 197 tests total.
- Deployed: this session's `gui.py` change means the launcher itself needed
  a real PyInstaller rebuild (`--distpath build/launcher`), not just a
  source copytree -- rebuilt, synced into `dist/Scan2Read`, and
  smoke-tested that the exe launches. The installer
  (`Scan2Read-Setup.exe`/`payload.zip`/`payload-online.zip`) was left
  untouched, per `CURRENT_SPEC.md`'s standing instruction.

### AI cleanup: bigger batches, bounded parallel requests, shorter no-change responses

User asked directly for the remaining items from `CURRENT_SPEC.md`'s priority
list (3-5), plus a fourth improvement (nullable "unchanged" response fields)
not on that list but aimed at the same stated bottleneck.

- `OpenAILunaEnhancer`'s default `batch_size` is now 24 (was 12), still
  overridable via the constructor.
- Added `max_parallel` (default 3): batches now run through a
  `ThreadPoolExecutor`, up to that many concurrent API calls. Made this safe
  by adding `AICostBudget.reserve()`/`record(..., reserved=...)`, both under
  a `threading.Lock`: a batch reserves its own conservative maximum cost
  *before* sending, so two threads can never both pass a check-then-call gap
  and jointly exceed the book's limit -- the second reservation attempt sees
  the first's already-locked-in amount and is correctly rejected. A rejected
  reservation flips `disabled=True`; already-in-flight requests still
  complete, only *new* batches stop being sent. `can_call()` (no reservation,
  used by `ai_context.py`'s always-sequential path) is unchanged in
  behavior, just now also lock-protected for consistency.
- The `spacing_text` response field is now nullable
  (`{"type": ["string", "null"]}`, still required by the strict JSON
  schema) and the prompt instructs the model to return `null` instead of
  re-emitting the whole paragraph when no spacing change is needed --
  directly targeting what `CURRENT_SPEC.md` identified as the single
  largest output-token/latency cost. `ocr_edits` and `anomalies` already
  expressed "nothing to report" as an empty array, and `kind` already had an
  `"unchanged"` enum value, so neither needed a schema change.
- `AIResultCache.set()` now writes through a `uuid4()`-suffixed temp file
  instead of a fixed `.tmp` name, since two parallel batches can now
  legitimately write the same cache key at once (the same paragraph text
  recurring across different batches) -- the old fixed name would have let
  one thread's temp file clobber another's mid-write.
- Tests: 3 new `AICostBudget.reserve()`/`record()` cases in
  `tests/test_ai_usage.py`; 4 new cases in `tests/test_ai_enhance.py`
  (default batch size, null `spacing_text` applying as "no change", genuine
  concurrent execution up to `max_parallel` measured via a locked counter in
  the mock transport, and a shared budget that a 6-batch/3-parallel run
  never exceeds even though every batch races to reserve first). 191 tests
  total, run 3x to rule out thread-timing flakiness before trusting it.
- Not yet measured against a real book, same as the filter/cache work above:
  next session should compare `ai_usage.json` request counts and wall-clock
  time before/after on an actual conversion.
- Deployed to `dist/Scan2Read/app/scan2read` only (same reasoning as the
  filter/cache entry above -- pure `cleanup/`+`ai_usage.py` change, installer
  untouched).

### AI cleanup: local pre-filter and cross-book result cache

Implemented the two safest items from `docs/CURRENT_SPEC.md`'s API performance
follow-up list, in the order it recommended (filter first, cache second),
since both reduce cost/request count without touching parallelism's shared
budget-locking problem.

- `cleanup/ai_filter.py`: `needs_ai_review(text, kind, options)` runs in
  `pipeline.py` before `ai_enhancer.enhance()` is ever called, and only
  forwards a paragraph when some *active* feature has a concrete reason to
  look at it: `anomalies` reuses the existing, already-verified corruption
  regex from `pdf/text_layer.py` (now exported as `has_corruption_markers()`)
  instead of inventing a second "looks wrong" heuristic; `ocr_words` fires on
  a Hangul-Latin/digit script glitch fused with no space, or 4+ repeated
  identical characters; `spacing` fires on a 12+ character unbroken Hangul
  run; `structure`/`headings` fire on anything already tagged `heading` or
  short (<=60 chars) and not ending in terminal punctuation. The filter never
  edits text -- a paragraph that doesn't qualify just keeps its local
  (non-AI) text, exactly as if AI cleanup were off for it, so under-filtering
  costs missed polish, never correctness.
- `cleanup/ai_cache.py`: `AIResultCache`, a flat one-JSON-file-per-entry
  store keyed by `cache_key(model, features, text)` -- model, a
  `SCHEMA_VERSION` constant (bump it whenever the prompt/JSON schema in
  `ai_enhance.py` changes, which invalidates every prior entry for free),
  the sorted active feature set, and the paragraph's own text.
  `OpenAILunaEnhancer.enhance()` now checks the cache per-paragraph before
  batching (partial hits within one batch are supported -- only the misses
  go to the API), applies a hit through the same validated `_apply_item()`
  path used for fresh responses (audited as `source: "cache"`), and stores
  every fresh API result back into the cache keyed by that paragraph's
  pre-edit text. The cache lives at `<work-dir>/_ai_cache/`, sibling to the
  per-book hash folders, so it is shared across different books and across
  a `--force` reprocess of the same book -- not scoped to one generation.
- Wired into `cli.py`: `OpenAILunaEnhancer(..., cache=AIResultCache(args.work_dir/"_ai_cache"))`.
  The GUI needed no change since it drives this through the CLI subprocess.
- Tests: `tests/test_ai_filter.py` and `tests/test_ai_cache.py` (new), two
  cache-reuse cases added to `tests/test_ai_enhance.py` (including reuse
  across a brand-new `OpenAILunaEnhancer` instance, proving the cache is
  genuinely persistent rather than an in-object memo), and an end-to-end
  `tests/test_pipeline.py` case confirming an ordinary well-formed paragraph
  never reaches `ai_enhancer.enhance()` while a paragraph with an injected
  script glitch does. 184 tests pass total.
- Not yet measured against a real book: `docs/CURRENT_SPEC.md` flags that the
  next session should compare `ai_usage.json` request counts before/after on
  an actual conversion to confirm the expected cost/latency reduction shows
  up in practice, not just in unit tests.
- Deployed to `dist/Scan2Read/app/scan2read` only (pure `cleanup/`+`pipeline.py`
  +`cli.py` change, no `gui.py` touch, so no launcher rebuild needed). Left
  the installer (`Scan2Read-Setup.exe`, `payload.zip`, `payload-online.zip`)
  untouched per `CURRENT_SPEC.md`'s standing instruction not to rebuild it
  without an explicit request.

### Small online Windows installer

- Added a 123MB `Scan2Read-Setup.exe` that contains only the GUI launcher,
  Python base runtime, Java, EPUBCheck, and application code. The previous
  all-in-one payload was 2.49GB because it copied the complete GPU development
  environment, including 2.32GB of NVIDIA CUDA libraries.
- During installation, the target runtime now bootstraps pip, downloads pinned
  CPU packages (`paddlepaddle 3.3.1`, `paddleocr 3.7.0`, `pypdfium2 5.13.0`,
  `Pillow 12.3.0`, and `kiwipiepy 0.23.2`), and initializes the two Korean OCR
  models. The CPU wheel comes from Paddle's official CPU index; other packages
  come from PyPI. A fresh installation uses about 1.2GB on disk.
- Failed dependency downloads remove a newly created partial install. The
  uninstall manifest is regenerated after downloads so dynamically installed
  files are removed correctly. CUDA remains an explicit later download through
  the existing GPU button.
- Verified a real clean install under `%LOCALAPPDATA%`: PaddlePaddle 3.3.1 CPU,
  PaddleOCR 3.7.0, Kiwi 0.23.2, no `paddlepaddle-gpu` distribution, no NVIDIA
  package directory, and successful local context analysis. Also smoke-tested
  extraction from the final one-file installer.

### Context-aware line and paragraph reconstruction

- PDF text layers that expose one block per word/run are now coalesced into
  visual lines before paragraph heuristics run. Every original page/block ID
  remains attached to the resulting Clean Text paragraph.
- The existing reconstruction option now uses local Kiwi morphology to join
  only boundaries with strong continuation evidence, such as a Korean particle,
  connective ending, or adnominal ending at the left edge. Terminal sentences,
  headings, and list items remain separate. No API or network service is used.
- The GUI label is now `문맥·줄바꿈·문단 보정`. Raw OCR remains immutable and
  spacing correction still runs as its own later Clean Text step.
- Full-cache verification on `고대 근동 역사.pdf` reduced 113,853 word/run
  blocks to 5,266 geometry paragraphs and then 4,742 context paragraphs across
  482 pages. A source-to-output character audit found zero non-whitespace
  differences.

### PDF folder drop

- Dropping a folder onto the GUI now adds PDF files directly inside that
  folder, sorted case-insensitively by filename. Mixed file/folder drops are
  supported and still use the existing canonical-path deduplication.
- Folder expansion is intentionally non-recursive so dropping a library root
  cannot unexpectedly queue every PDF in its subfolders. Added a matching
  `폴더 추가` picker and clear feedback for empty folders or duplicate-only
  drops.

### GPU render-ahead applied

- GPU conversion now starts one bounded worker process that prepares at most
  the next uncached page while the main process performs OCR on the current
  page. PDFium stays isolated in that worker process; no PDF document is
  shared across threads or processes.
- The worker performs rendering/text-layer inspection only. Raw OCR remains
  serialized and atomically persisted by the main process, so resume behavior
  and Raw OCR ownership are unchanged. Cached pages are never submitted.
- The GUI already enables this path only with `--gpu`; CPU conversion retains
  the previous low-overhead sequential path. Cancellation terminates the CLI,
  and a parent-sentinel watcher prevents an orphan preparation worker.
- Two real-book benchmark rounds over pages 28-35 measured 5.423 s sequential
  versus 4.160 s render-ahead (23.3% less processing time; 17.3% including
  worker startup for this short sample), with byte-identical rendered images
  and identical complete OCR JSON. See `docs/gpu-prefetch-benchmark.md`.

### Follow-up: isolated 1-2 character OCR noise, and a major fragmentation bug found while validating it

- User asked to verify a new real book ("기독교 위험한 사상 1", 279 pages).
  First finding: the existing EPUB only covered pages 100-120 -- the cache
  had just that range, not the full book. Flagged to the user before going
  further.
- In that 21-page sample, 4 one-off (non-repeating) noise blocks survived as
  their own spoken paragraphs: a decorative section divider misread as `;`
  (p.101), a caption/credit fragment `c` under a full-page portrait (p.105),
  top-margin scan-edge noise `'`/`S` on the page right after that portrait
  (p.106), and a 10x10px detector blob misread as `8` (p.113, physically
  smaller than any real glyph at this scan resolution). Unlike the earlier
  header/footer and footnote bugs, none of these repeat or have a matching
  note -- they cannot be caught by repetition- or marker-based detection,
  only by geometry/content implausibility.
- Added `cleanup/noise.py`: drops a paragraph only when it is **exactly one
  OCR block that never merged with any neighbor** and that block's entire
  content is 1-2 characters that are either physically smaller than any real
  glyph (< 35% of the page's own body-line height/width) or contain no
  Hangul, digit, or Roman numeral. Wired into both `cleanup/text.py`'s
  `clean_page()` and `cleanup/reconstruction.py`'s `reconstruct()` via a new
  `sole_bbox` field on `Paragraph` (cleared the moment a second block merges
  into it) -- always on, not opt-in, since no legitimate standalone Korean
  paragraph is ever a lone punctuation mark or dust speck.
- **Critical to how this was validated**: an earlier draft checked
  block-level noise *before* paragraph joining decided what merges with what.
  Tested against the real cache, this deleted real content everywhere --
  captions and mid-sentence PDF-text-layer punctuation runs (`,` `.` `M.`
  `J.`) that were meant to glue into the surrounding sentence during joining,
  not stand alone. Moved the check to run only on a paragraph confirmed to
  be a single, never-merged block; re-verified against every real cached
  page of both books actually delivered so far -- exactly the 5 known noise
  blocks removed, zero other paragraphs touched (spot-checked survivors:
  `CLC`, digit-only OCR page-number leaks, `I`/`II`/`III`/`IV` roman-numeral
  headings all correctly kept).
- **Found in the process, NOT fixed, needs its own investigation**: several
  other real cached books (고대 근동 역사, 고대 이스라엘 역사, 성서유니온
  모세오경 -- all `pdf/text_layer.py`-extracted, block ids like
  `text-N-<hash>`) fragment into 100-200+ "paragraphs" per page instead of
  15-25, because the PDF's own text layer emits one block per word/run
  rather than one per line for these particular files, and `clean_page()`/
  `reconstruct()`'s paragraph-joining heuristics assume line-granularity
  blocks (e.g. `reconstruct()`'s "indented" check compares x0 to the
  region's own left margin, which only means "new paragraph" when a block
  IS a full line). One book measured 103,016 "paragraphs" from 482 pages.
  This makes text-layer-mode output for those PDFs essentially unlistenable
  and is a much bigger, separate problem from today's noise fix -- likely
  worth an audit-report tool (proposed, not yet built) to surface
  per-book paragraph-count anomalies like this quickly instead of requiring
  a manual cache dig every time.

### Follow-up: superscript reference geometry was too tight for real OCR noise

- User-reported real failure: `98`/`36`-style footnote reference numbers still
  leaked into the middle of body sentences in the actual "고대 근동 문화"
  conversion (e.g. "...발휘하였다\n98 이 혁신은..."), despite the earlier
  superscript-matching fix. Traced against the real cached OCR
  (`%LOCALAPPDATA%\Scan2Read\work\589f867...5331e`, page 102): the genuine
  superscript `98` measured 0.745x its body line's height and sat 23px to the
  *left* of that line's own right edge — both just outside the `find_footnote_block_ids()`
  reference-matching thresholds (0.7 height ratio, 0.3·height left margin),
  which had only ever been tuned against synthetic test geometry.
- Loosened to 0.85 height ratio and 0.6·height left margin
  (`cleanup/footnotes.py`). Re-ran detection across all 116 real cached pages
  of that book before and after: exactly 2 new true positives recovered
  (page 102's `98`, page 78's `36`, both confirmed against their matching
  same-page notes), zero blocks lost, zero other pages affected. Also also
  deployed to the packaged app (`app/scan2read` copytree + repack — pure
  `cleanup/` change, no launcher rebuild needed).
- Note: also confirmed the *previous* session's packaged `Scan2Read.exe` had
  fallen behind `src/` — `gui.py`'s file-list/output-folder redesign was
  committed to source but the launcher exe was never rebuilt, so the actual
  shipped app still ran the old single-file-dialog GUI. Rebuilt via
  `pyinstaller Scan2Read.spec --distpath build/launcher --noconfirm` +
  `stage_windows.py --repack` and smoke-tested the resulting exe launches
  with the new GUI before trusting it.

### Batch desktop workflow and long footnotes

- Follow-up: a detached superscript `18` in the sample remained as its own
  spoken paragraph after note removal. Small superscript boxes attached to a
  body line now disappear with their matching same-page note; ordinary body
  numbers and unmatched references are preserved. The reviewed EPUB was
  rebuilt with only this additional block removed, and EPUBCheck passed.

- Replaced file-save dialogs with a shared output-folder picker and filename
  templates (`{name}`, `{folder}`, `{index:03d}`). The visible file table shows
  predicted filenames and per-file status. Additions are cumulative and
  deduplicated; selected entries can be removed. Existing filenames receive
  numeric suffixes. Batch options are fixed during conversion.
- Persist all conversion preferences with validated defaults and an atomic
  settings file. GPU detection preserves the user's saved GPU preference.
- Long footnotes in the supplied 고대 근동 문화 sample started above the old
  72% cutoff; some markers had no following space, and some notes continued
  on the next page without another marker. Detection now uses local body
  size, separation, dense smaller lines, and column boundaries. Synthetic
  regressions protect ordinary headings, body lists and centered imprints.
  Cached 40-page sample: 104 footnote blocks identified without rerunning OCR.

### Follow-up: cache mode isolation and Clean Text preservation

- Added `text_layer` (`auto`/`off`) to the processing cache identity. Switching
  to forced OCR no longer reuses text extracted from the PDF, and switching
  back reuses that mode's own cache. Older caches without a recorded mode are
  preserved but not reused because their provenance is ambiguous; a warning
  explains the one-time reprocessing when such a cache is found.
- Moved parenthesis removal to a shared output generator after Clean Text
  persistence. Both reconstruction and basic cleanup now retain parentheses
  in clean JSON and apply removal only to the EPUB text.
- Regression tests cover switching modes in both directions, repeated cache
  reuse, Raw OCR preservation, and toggling parenthesis removal with spacing
  enabled in both cleanup paths.

Driven by real user books (김회권 사무엘상/하, 쾌도난마 요한계시록1 — a 345-page,
32-short-chapter commentary). Every fix below was verified against that
project's actual cached OCR data in `%LOCALAPPDATA%\Scan2Read\work`, not just
synthetic tests, before being trusted.

### PDF text layer reuse (skip OCR when the PDF already has real text)

- New `pdf/text_layer.py`: `extract_text_layer()` pulls a page's own
  embedded text via pypdfium2 instead of OCR-ing the rendered image.
  `analyze_text_layer()` scans a whole PDF up front (used by `scan2read
  inspect` and the GUI's pre-flight text-layer preview).
- Corruption handling: `find_corrupted_blocks()` flags only *unambiguous*
  encoding damage (replacement char, PUA codepoints, bare Hangul
  compatibility jamo) — never "this word looks wrong" guessing. Only those
  specific blocks get cropped and re-OCR'd via `correct_with_ocr()`; the
  rest of the page's real text layer is trusted as-is.
- `--text-layer {auto,off}` CLI flag; GUI checkbox "텍스트 레이어 무시하고
  항상 OCR" to force full OCR even when a text layer exists (the PDF's own
  embedded text can itself be the product of low-quality third-party OCR).
- Bug found via real book: `ocr/columns.py`'s two-column gutter-detection
  (`gutter()`) crashed with `min() iterable argument is empty` when handed a
  narrow crop (the correction path renders single-line crops, not full
  pages). Fixed by returning `None` for too-narrow images and falling back
  to single-column treatment.

### Header/footer (running title + page number) removal — two real bugs, fixed in sequence

This is the one that took multiple real-book iterations to get right; see
`cleanup/headers.py` and its tests for the full picture.

1. **Text fused with page number, no space.** A PDF's own text layer (or
   OCR) sometimes emits "저자 서문9" as one block — header title and page
   number glued together, no separating space. Naive exact-text repetition
   matching never saw this as "the same header repeating" because the
   trailing number changes every page. Fixed by comparing after stripping a
   leading/trailing 1-4 digit run (`_MARGIN_DIGITS`), while still removing
   the whole original block (header text and embedded number together).
2. **Margin zone was too narrow.** The zone used to decide "is this block
   near enough to the top/bottom edge to even be a margin candidate" was a
   guessed 7%/93%. A real book's own header/footer measured at ~13%/89% —
   entirely outside that band, so it was never considered at all,
   independent of bug #1. Widened to a shared `MARGIN_ZONE = 0.15` constant,
   reused by both `repeated_margins()` and `is_page_number()` (the latter
   had drifted to its own stale 8%/92%, also fixed). Widening is safe
   because the actual filter is the repetition check, not the zone width —
   ordinary body text essentially never repeats verbatim at a stable
   position across 3+ nearby pages regardless of how wide the candidate
   band is. (Verified against real body-text-first-line blocks that *do*
   land inside the widened top zone on some pages — they never matched
   because their text differs every page.)
3. **Label text changes every chapter.** A 32-short-chapter commentary
   book's footer label is the *current chapter's title*, not a constant
   book title — so the literal-text repetition check (bug #1's fix) only
   ever saw 2-3 occurrences of any one chapter's label before it changed
   again, short of the "3+ nearby pages" threshold. Added a second,
   independent detection pass: track the embedded page number's offset
   from the actual PDF page index (e.g. printed-page = pdf-page − 1) —
   if that offset stays constant across 3+ nearby pages *regardless of the
   surrounding label text*, it's recognized as one continuous running
   footer. A citation that coincidentally ends in a number (e.g.
   "계22:13") has a effectively-random offset each time and doesn't
   collide with this check. Real-data result: 149 → 185 header/footer
   blocks correctly caught in a 60-page sample; the remaining 10 "kept"
   instances were manually checked and are all genuine body text (scripture
   quotes, one-off subtitles).

### GPU acceleration (opt-in, NVIDIA only)

- `ocr/gpu.py`: `detect_nvidia_gpu()` (via `nvidia-smi`), `gpu_paddle_installed()`,
  `install_gpu_support()` (uninstalls CPU `paddlepaddle`, installs the
  matching `paddlepaddle-gpu` from PaddlePaddle's own package index — order
  matters, installing gpu-over-cpu without uninstalling first corrupts the
  install since both distributions claim the same files).
- `ocr/paddle.py`: `PaddleEngine(device=...)`. Real measurement on this
  machine (RTX 3070 vs Ryzen 5 5600): ~26x faster per page (1.1s vs 28.8s
  recognize call). GPU/CPU results can differ by a character in rare cases
  (floating-point nondeterminism), so `device` is part of `cache_identity()`
  — switching devices correctly invalidates the OCR cache instead of mixing
  results from both.
- `text_recognition_batch_size=16` (was implicitly 1): PaddleOCR recognizes
  one detected line per model call by default, which starves the GPU
  between tiny kernel launches (~20-30% utilization). Batching lines
  measurably helps (~25% faster) and is also in `cache_identity()` for the
  same nondeterminism reason. Diminishing returns past ~16 on typical pages.
- Explicitly investigated and rejected: feeding multiple *pages* per
  `predict()` call (no speedup — detection processes images one at a time
  internally regardless); a bigger detection model, `PP-OCRv5_server_det`
  (17% *slower*, no accuracy gain on a clean test page, and doesn't touch
  recognition anyway); CPU+GPU split work-stealing (26x speed gap means the
  theoretical max gain is ~4%, not worth the complexity or the CPU
  contention with page rendering); render-ahead prefetching in a background
  thread (unsafe — PDFium is explicitly documented as not thread-safe;
  doing it safely needs a separate process, deferred since the user
  considered current performance sufficient).
- Korean has no PaddleOCR "server"-size recognition model at all (checked
  the full `paddlex/configs/modules/text_recognition/` model list) — Baidu
  never released one. This is a hard ceiling on Korean recognition accuracy
  until upstream ships one; not something fixable in this codebase.
- CLI: `scan2read gpu-status`, `scan2read gpu-install`, `convert --gpu`. GUI:
  install button appears only when an NVIDIA GPU is detected; ~2GB download
  requires explicit confirmation.

### EPUB output correctness

- `epub/builder.py`: `_sanitize()` strips characters XML 1.0 forbids outright
  (control chars, lone surrogates, U+FFFE/FFFF) before writing chapter text
  and the title. Root cause of a real failure: `ERROR: Invalid EPUB
  structure: not well-formed (invalid token)` — `html.escape()` does not
  touch these characters, and OCR occasionally produces one from a garbled
  image region. Applied at the final serialization boundary only (Raw OCR
  and the cached "clean" JSON are untouched), consistent with the project's
  Raw OCR → Clean Text → TTS Text layering.

### New opt-in text transforms

- `cleanup/parentheses.py` (`--remove-parentheses`): strips `(...)`/`（...）`
  spans, e.g. citation asides like "지라(계2:5)". Depth-counts parens first;
  if a paragraph's parens are unbalanced (common after an OCR misread) it is
  left completely untouched rather than risk deleting to the end of the
  paragraph. This is a **TTS Text**-layer transform — applied only to what
  reaches `build_epub()`, never written into the cached "clean" JSON, per
  the "never modify Clean Text for TTS reasons" rule in AGENTS.md.
- `--pages START-END`: process only a page range; the OCR cache is still
  keyed per page number, so a later full-book run reuses whatever the range
  already computed.
- Batch processing (GUI only, `gui.py`): selecting/dropping 2+ PDFs queues
  them for sequential conversion, each saved next to its own source file. A
  per-file failure doesn't stop the batch. `_launch()` was extracted out of
  `start()` so both the single-file and batch code paths share one command-
  building/subprocess-launch implementation.

### GUI polish

- Drag-and-drop (`tkinterdnd2`); note `tk.splitlist()` on a dropped-path
  string corrupts bare Windows paths (backslash sequences get interpreted as
  Tcl escapes) — `parse_dropped_paths()` in `gui.py` parses the `<<Drop>>`
  payload manually instead.
- "결과 파일 위치 열기": opens Explorer with the file itself pre-selected.
  `explorer /select,"path"` must be passed as a single string to
  `subprocess.run`, not as `["explorer", "/select,"+path]` — the list form
  lets Python's own argv-quoting wrap the whole token (including
  "/select,") whenever the path has a space, which Explorer silently fails
  to parse and falls back to opening Documents instead.
- Output folder default: always the source PDF's own folder. A previously
  tried "remember the last output folder and default to it" design was
  reverted per user feedback — the remembered folder is now only offered as
  the starting point in the "찾아보기" save dialog, never a silent default.

### Process notes for whoever builds next

- The packaged app has two rebuild paths depending on what changed:
  - **Corrected 2026-09-09:** the rule below used to say "only `gui.py`
    changes need a rebuild". That is wrong and it cost a wasted deploy.
    `Scan2Read.spec` analyses `scripts/gui_launcher.py` with
    `pathex=['src']`, so the **entire `scan2read` package is frozen into
    the exe's PYZ archive** (`scan2read.cleanup.ai_providers` is listed in
    `build/Scan2Read/PYZ-00.toc`). The GUI process therefore runs the
    bundled snapshot, *not* `app/scan2read` — that copy is only what the
    CLI subprocess imports. So: if the change touches anything the GUI
    process itself imports (`cleanup/`, `project/`, `ocr/`, not just
    `gui.py`), the launcher must be rebuilt or the GUI silently keeps
    running the old code. To verify a build really picked a change up,
    read the PYZ back: `CArchiveReader(exe)` → extract the `.pyz` →
    `ZlibArchiveReader(...).extract('scan2read.cleanup.ai_providers')` and
    inspect `co_consts`.
  - Pure pipeline changes that only the CLI subprocess runs can get away
    with `shutil.copytree('src/scan2read', 'dist/Scan2Read/app/scan2read',
    ...)` + `scripts/stage_windows.py`'s `pack()`, but when in doubt
    rebuild — the copytree is cheap and the silent-stale-GUI failure is not.
  - A full PyInstaller rebuild of the launcher is
    `pyinstaller Scan2Read.spec --distpath build/launcher --noconfirm` (
    **always pass `--distpath build/launcher`** — the bare default
    `dist/Scan2Read` is the *already-staged full runtime* with Java/models/
    epubcheck in it, and PyInstaller will silently `rm -rf` and replace it
    with just the bare launcher output if you don't redirect it there).
  - Either way, finish with `python scripts/stage_windows.py --repack` to
    refresh `build/payload.zip`.
  - Both `dist/Scan2Read/Scan2Read.exe` and `build/launcher/Scan2Read/Scan2Read.exe`
    get locked while the app is running; check `tasklist` for `Scan2Read.exe`
    and ask the user before closing it if a launcher rebuild is needed.
- Dev GPU testing uses `.tools/paddle-env` (a separate venv from the
  project's own `.venv`), invoked via
  `PYTHONPATH=src PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True .tools/paddle-env/Scripts/python.exe -m scan2read ...`
  — this lets you re-run a real conversion against `src/` (with in-progress
  fixes) while reusing that project's already-cached OCR in
  `%LOCALAPPDATA%\Scan2Read\work`, without touching the packaged app at all.
