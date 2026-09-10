"""Conservative linguistic evidence for joining broken Korean paragraphs."""
from collections.abc import Callable
import re


_TERMINAL = re.compile(r"[.!?。！？][”’\"')\]}】》〉]*$")
_LEFT_DEPENDENT = re.compile(
    r"(?:의|을|를|은|는|이|가|에|에서|에게|께|으로|로|와|과|도|만|까지|부터|보다|처럼|하며|하고|하여|해서)$"
)
_RIGHT_DEPENDENT = re.compile(
    r"^(?:때문(?:에|이다)|따라|위해|통해|관하여|대하여|비해|뿐만|등(?:은|을|이|의|과))(?:\s|$)"
)
_STRONG_LEFT_TAGS = {"EC", "ETM", "JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ", "JX", "JC", "MM", "XPN"}
_STRONG_RIGHT_PREFIXES = ("E", "XS")


class ContextJoiner:
    """Join only when grammar says the left/right fragment cannot stand alone."""
    def __init__(self, analyze: Callable[[str], object] | None = None):
        self.analyze = analyze

    def _tags(self, text: str) -> list[str]:
        if self.analyze is None:
            return []
        try:
            result = self.analyze(text, top_n=1)
            tokens = result[0][0]
            return [token.tag for token in tokens]
        except (IndexError, TypeError, ValueError):
            return []

    def __call__(self, left: str, right: str) -> bool:
        left = left.rstrip()
        right = right.lstrip()
        if not left or not right or _TERMINAL.search(left):
            return False
        if left.endswith(("(", "[", "{", "〈", "《", "“", '"')):
            return True
        if right.startswith((")", "]", "}", "〉", "》", ",", ".", ":", ";")):
            return True
        left_tags = self._tags(left)
        right_tags = self._tags(right)
        if left_tags and left_tags[-1] in _STRONG_LEFT_TAGS:
            return True
        if right_tags and right_tags[0].startswith(_STRONG_RIGHT_PREFIXES):
            return True
        return bool(_LEFT_DEPENDENT.search(left) or _RIGHT_DEPENDENT.search(right))
