from __future__ import annotations

import re
import unicodedata

_KEPT_CATEGORIES = frozenset({"Nd", "Nl", "Pc"})
_INLINE_CODE = re.compile(r"`+([^`]*)`+")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*{1,3}|~~|(?<!\w)_{1,3})(\S(?:.*?\S)?)\1(?!\w)")
_TAG = re.compile(r"</?[A-Za-z][^>]*>")


def heading_text(raw: str) -> str:
    """a heading's text as the docs site sees it: markup dropped, words kept."""
    text = _IMAGE.sub("", raw)
    codes: list[str] = []

    def hold(match: re.Match[str]) -> str:
        codes.append(match.group(1))
        return f"\0{len(codes) - 1}\0"

    text = _INLINE_CODE.sub(hold, text)
    text = _LINK.sub(r"\1", text)
    text = _TAG.sub("", text)
    previous = None
    while previous != text:
        previous = text
        text = _EMPHASIS.sub(r"\2", text)
    return re.sub(r"\0(\d+)\0", lambda m: codes[int(m.group(1))], text).strip()


def _kept(char: str) -> bool:
    if char in "- ":
        return True
    category = unicodedata.category(char)
    return category[0] in "LM" or category in _KEPT_CATEGORIES


def slug(text: str) -> str:
    """github-slugger's slug: lowercase, punctuation and symbols dropped, each
    space a dash."""
    return "".join(c for c in text.lower() if _kept(c)).replace(" ", "-")


class Slugger:
    """github-slugger's per-page counter, so repeated headings get -1, -2."""

    def __init__(self) -> None:
        self._occurrences: dict[str, int] = {}

    def slug(self, text: str) -> str:
        original = slug(text)
        result = original
        while result in self._occurrences:
            self._occurrences[original] += 1
            result = f"{original}-{self._occurrences[original]}"
        self._occurrences[result] = 0
        return result
