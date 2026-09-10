"""Local pre-filter: decide which paragraphs are worth an AI cleanup call.

Cuts API cost/latency by skipping paragraphs that no currently active
feature has a plausible reason to check. Purely a routing decision -- it
never edits paragraph text. A paragraph that slips through unflagged simply
keeps its local (non-AI) text, exactly as if AI cleanup were off for it, so
under-filtering only costs missed polish, never correctness.
"""
import re

from scan2read.cleanup.ai_enhance import AIOptions
from scan2read.pdf.text_layer import has_corruption_markers

# A short run of Latin letters/digits fused directly onto Hangul with no
# separating space is a classic OCR misread (a jamo or stroke misread as a
# Latin glyph); a real Latin word or citation next to Hangul text is set off
# by a space, so this does not fire on ordinary mixed-language prose.
_MIXED_SCRIPT_GLITCH = re.compile(
    r"[가-힣][A-Za-z0-9]{1,2}(?![A-Za-z0-9])|(?<![A-Za-z0-9])[A-Za-z0-9]{1,2}[가-힣]")
_REPEATED_GLYPH = re.compile(r"(.)\1{3,}")
_TERMINAL_PUNCTUATION = re.compile(r"[.!?。」』\"'’”)\]]$")
_HANGUL_RUN = re.compile(r"[가-힣]+")
# A parenthetical gloss needs a bracket -- real ")(（）" or, since OCR often
# mangles one side of the pair, a lone one still counts (that is exactly the
# damaged case worth sending to AI, since the local deterministic remover
# requires a balanced pair and skips it entirely).
_HAS_PAREN = re.compile(r"[()（）]")


def needs_ai_review(text: str, kind: str, options: AIOptions) -> bool:
    """True if some active feature in `options` has a reason to check `text`."""
    if not text.strip():
        return False
    if options.anomalies and has_corruption_markers(text):
        return True
    if options.ocr_words and (_MIXED_SCRIPT_GLITCH.search(text) or _REPEATED_GLYPH.search(text)):
        return True
    if options.spacing and _spacing_is_uncertain(text):
        return True
    if (options.structure or options.headings) and _looks_like_heading_candidate(text, kind):
        return True
    if options.glosses and _HAS_PAREN.search(text):
        return True
    return False


def _spacing_is_uncertain(text: str) -> bool:
    """A long unbroken Hangul run is the case local spacing models handle
    least reliably; short or already-spaced runs are low risk either way."""
    return any(len(run) >= 12 for run in _HANGUL_RUN.findall(text))


def _looks_like_heading_candidate(text: str, kind: str) -> bool:
    if kind == "heading":
        return True
    return len(text) <= 60 and not _TERMINAL_PUNCTUATION.search(text.rstrip())
