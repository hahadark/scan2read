"""Optional Korean spacing; never change non-space characters."""
from collections.abc import Callable
import re


def correct_spacing(text: str, propose: Callable[[str], str]) -> str:
    candidate = propose(text)
    if text.replace(" ", "") != candidate.replace(" ", ""):
        return text
    # Keep English citations, numbers and punctuation boundaries exactly as supplied.
    chars = text.replace(" ", "")
    old_gaps = re.split(r"[^ ]", text)
    new_gaps = re.split(r"[^ ]", candidate)
    result = [old_gaps[0]]
    for i, char in enumerate(chars):
        result.append(char)
        korean_boundary = (i + 1 < len(chars) and "가" <= char <= "힣"
                           and "가" <= chars[i+1] <= "힣")
        result.append(new_gaps[i+1] if korean_boundary else old_gaps[i+1])
    return "".join(result)
