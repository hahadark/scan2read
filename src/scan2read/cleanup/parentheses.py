"""Optional removal of parenthetical asides, for smoother TTS listening.

Commentaries often interleave scripture citations and other asides in
parentheses -- e.g. "지라(계2:5)" -- which read awkwardly aloud and are easy
to skip when listening rather than reading. This is a pure text
transformation (no OCR position analysis needed), and like footnote
removal it is opt-in: some books use parentheses for content that *is*
meant to be heard (a clarifying phrase, a translation), and this cannot
tell the difference. When a paragraph's parentheses are unbalanced --
common after an OCR misread -- it is left completely untouched rather than
risk deleting real content up to the end of the paragraph.
"""
import re

_OPEN = "(（"
_CLOSE = ")）"
_WHITESPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,!?、。])")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def tidy_whitespace(text: str) -> str:
    """Clean up the whitespace left behind by deleting a span from the middle
    of a sentence (a stray space before punctuation, a run of spaces where
    words used to be joined). Shared with `ai_enhance.py`'s AI-judged span
    removal, which leaves the same kind of gap `remove_parenthetical` does."""
    text = _WHITESPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


def remove_parenthetical(text: str) -> str:
    """Strip every "(...)" (or full-width "（...）") span, nesting included."""
    depth = 0
    for char in text:
        if char in _OPEN:
            depth += 1
        elif char in _CLOSE:
            depth -= 1
            if depth < 0:
                return text  # a stray closing paren -- unbalanced, leave untouched
    if depth != 0:
        return text  # an unclosed opening paren -- unbalanced, leave untouched

    kept = []
    depth = 0
    for char in text:
        if char in _OPEN:
            depth += 1
        elif char in _CLOSE:
            depth -= 1
        elif depth == 0:
            kept.append(char)
    cleaned = "".join(kept)
    return tidy_whitespace(cleaned)
