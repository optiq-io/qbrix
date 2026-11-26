from __future__ import annotations

import functools
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from qbrixlog import get_logger

from proxysvc.mod.docs.page import Page
from proxysvc.mod.docs.page import Section
from proxysvc.mod.docs.page import parse_page

logger = get_logger(__name__)

DOCS_URL = "https://qbrix.io/docs"
NEXT_FOLDER = "docs-next"
DOCS_FOLDER = "docs"
# about 5K tokens, at four characters a token
ANSWER_CAP_CHARS = 20_000
SEARCH_SECTIONS = 8
HEADING_WEIGHT = 3
_K1 = 1.2
_B = 0.75
_TOKEN = re.compile(r"[a-z0-9_]+")
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it its of on or "
    "so that the this to what when where which with you your".split()
)

# pages of docs/ that teach the api next replaces: experiments, pools, gates,
# policies, rewards, and the recipes and sdk pages built on them
SUPERSEDED = frozenset(
    {
        "api-reference",
        "auto-policy",
        "checkout-conversion",
        "console-event-log",
        "console-experiments",
        "contexts",
        "feature-gates",
        "feature-rollouts",
        "feedback-and-rewards",
        "getting-started",
        "introduction",
        "javascript-sdk",
        "llm-routing",
        "personalization-by-segment",
        "policies",
        "pools-and-experiments",
        "pricing-and-discounts",
        "python-sdk",
        "recommendations-and-ranking",
        "use-cases",
    }
)


def _stem(token: str) -> str:
    for suffix in ("ing", "ed"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def link(section: Section) -> str:
    url = f"{DOCS_URL}/{section.slug}"
    return f"{url}#{section.anchor}" if section.anchor else url


@dataclass(frozen=True)
class Answer:
    sections: tuple[Section, ...]
    truncated: bool
    outline: tuple[Section, ...] | None = None


def _capped(sections: list[Section]) -> tuple[tuple[Section, ...], bool]:
    kept: list[Section] = []
    used = 0
    for section in sections:
        if used + len(section.text) <= ANSWER_CAP_CHARS:
            kept.append(section)
            used += len(section.text)
            continue
        if not kept:
            cut = section.text[:ANSWER_CAP_CHARS].rsplit("\n", 1)[0]
            kept.append(
                Section(
                    slug=section.slug,
                    page_title=section.page_title,
                    path=section.path,
                    anchor=section.anchor,
                    text=cut,
                )
            )
        return tuple(kept), True
    return tuple(kept), False


class DocsIndex:
    """the install's docs as heading sections, searched in memory.

    docs-next replaces a page of docs with the same slug, and the pages next
    supersedes are left out, so an agent never reads the api it replaced.
    """

    def __init__(self, pages: list[Page]):
        self._pages = {page.slug: page for page in pages}
        self._sections = [s for page in pages for s in page.sections]
        self._terms: list[Counter[str]] = []
        self._lengths: list[int] = []
        for section in self._sections:
            terms = Counter(_tokens(section.text))
            for name in (section.page_title, *section.path):
                for token in _tokens(name):
                    terms[token] += HEADING_WEIGHT
            self._terms.append(terms)
            self._lengths.append(sum(terms.values()))
        self._average = sum(self._lengths) / max(len(self._lengths), 1)
        frequency: Counter[str] = Counter()
        for terms in self._terms:
            frequency.update(terms.keys())
        total = len(self._sections)
        self._idf = {
            term: math.log(1 + (total - n + 0.5) / (n + 0.5))
            for term, n in frequency.items()
        }

    @classmethod
    def load(cls, root: Path) -> DocsIndex:
        pages: dict[str, Page] = {}
        for folder in (NEXT_FOLDER, DOCS_FOLDER):
            files = sorted((root / folder).glob("*.mdx"))
            if not files:
                raise RuntimeError(f"no docs pages in {root / folder}")
            for source in files:
                if source.stem in pages:
                    continue
                if folder == DOCS_FOLDER and source.stem in SUPERSEDED:
                    continue
                pages[source.stem] = parse_page(source)
        return cls(list(pages.values()))

    @property
    def pages(self) -> list[Page]:
        return sorted(self._pages.values(), key=lambda page: page.title.lower())

    @property
    def section_count(self) -> int:
        return len(self._sections)

    def _score(self, index: int, query: list[str]) -> float:
        terms = self._terms[index]
        norm = _K1 * (1 - _B + _B * self._lengths[index] / self._average)
        score = 0.0
        for term in query:
            count = terms.get(term, 0)
            if count:
                score += self._idf[term] * count * (_K1 + 1) / (count + norm)
        return score

    def search(self, query: str) -> Answer:
        terms = list(dict.fromkeys(_tokens(query)))
        if not terms:
            return Answer(sections=(), truncated=False)
        scores = {i: self._score(i, terms) for i in range(len(self._sections))}
        ranked = sorted(
            (i for i, s in scores.items() if s > 0), key=lambda i: -scores[i]
        )
        best, truncated = _capped([self._sections[i] for i in ranked[:SEARCH_SECTIONS]])
        order: dict[str, int] = {}
        for section in best:
            order.setdefault(section.slug, len(order))
        grouped = sorted(best, key=lambda section: order[section.slug])
        return Answer(sections=tuple(grouped), truncated=truncated)

    @classmethod
    @functools.cache
    def at(cls, root: str) -> DocsIndex:
        """the index of the docs under root, built once per process."""
        started = time.perf_counter()
        index = cls.load(Path(root))
        logger.info(
            "docs index built: %d pages, %d sections in %.0f ms",
            len(index.pages),
            index.section_count,
            (time.perf_counter() - started) * 1000,
        )
        return index

    def page(self, slug: str) -> Answer | None:
        page = self._pages.get(slug)
        if page is None:
            return None
        sections, truncated = _capped(list(page.sections))
        return Answer(sections=sections, truncated=truncated, outline=page.sections)
