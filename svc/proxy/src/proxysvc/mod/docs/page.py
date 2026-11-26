from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from proxysvc.mod.docs.slug import Slugger
from proxysvc.mod.docs.slug import heading_text

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_TAG_LINE = re.compile(r"^\s*<(/?)([A-Z][A-Za-z]*)\b([^>]*?)(/?)>\s*$")
_INLINE_TAG = re.compile(r"</?[A-Z][A-Za-z]*\b[^>]*?/?>")
_INLINE_CODE = re.compile(r"(`+)[^`]*?\1")
_ATTRIBUTE = re.compile(r'([a-z]+)="([^"]*)"')
_SELF_CLOSING_TEXT = (
    "method",
    "path",
    "title",
    "label",
    "detail",
    "caption",
    "description",
)
_OPENING_TEXT = ("title", "description")


@dataclass(frozen=True)
class Section:
    slug: str
    page_title: str
    path: tuple[str, ...]
    anchor: str
    text: str


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    description: str
    sections: tuple[Section, ...]
    anchors: tuple[str, ...]


def _frontmatter(lines: list[str], source: Path) -> tuple[dict[str, str], int]:
    if not lines or lines[0].strip() != "---":
        raise RuntimeError(f"docs page {source} has no frontmatter")
    fields: dict[str, str] = {}
    for number, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return fields, number + 1
        key, sep, value = line.partition(":")
        if sep and key.strip():
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            fields[key.strip()] = value
    raise RuntimeError(f"docs page {source} never closes its frontmatter")


def _strip_inline_tags(line: str) -> str:
    out: list[str] = []
    last = 0
    for code in _INLINE_CODE.finditer(line):
        out.append(_INLINE_TAG.sub("", line[last : code.start()]))
        out.append(code.group(0))
        last = code.end()
    out.append(_INLINE_TAG.sub("", line[last:]))
    return "".join(out)


def _tag_line(match: re.Match[str]) -> str:
    closing, _, attributes, self_closing = match.groups()
    if closing:
        return ""
    kept = _SELF_CLOSING_TEXT if self_closing else _OPENING_TEXT
    values = dict(_ATTRIBUTE.findall(attributes))
    return " · ".join(values[name] for name in kept if values.get(name))


def parse_page(source: Path) -> Page:
    lines = source.read_text(encoding="utf-8").splitlines()
    fields, start = _frontmatter(lines, source)
    title = fields.get("title", "")
    if not title:
        raise RuntimeError(f"docs page {source} has no title")
    slug = source.stem
    slugger = Slugger()

    sections: list[Section] = []
    anchors: list[str] = []
    path: list[tuple[int, str]] = []
    anchor = ""
    body: list[str] = []
    fence: str | None = None

    def close() -> None:
        text = "\n".join(body).strip()
        if text:
            sections.append(
                Section(
                    slug=slug,
                    page_title=title,
                    path=tuple(name for _, name in path),
                    anchor=anchor,
                    text=re.sub(r"\n{3,}", "\n\n", text),
                )
            )
        body.clear()

    for line in lines[start:]:
        opened = _FENCE.match(line)
        if fence is not None:
            body.append(line)
            if (
                opened
                and opened.group(1)[0] == fence[0]
                and len(opened.group(1)) >= len(fence)
            ):
                if line.strip() == opened.group(1):
                    fence = None
            continue
        if opened:
            fence = opened.group(1)
            body.append(line)
            continue
        heading = _HEADING.match(line)
        if heading:
            close()
            level = len(heading.group(1))
            name = heading_text(heading.group(2))
            anchor = slugger.slug(name)
            anchors.append(anchor)
            path = [(depth, kept) for depth, kept in path if depth < level]
            path.append((level, name))
            continue
        tag = _TAG_LINE.match(line)
        if tag:
            kept = _tag_line(tag)
            if kept:
                body.append(kept)
            continue
        body.append(_strip_inline_tags(line))
    close()

    return Page(
        slug=slug,
        title=title,
        description=fields.get("description", ""),
        sections=tuple(sections),
        anchors=tuple(anchors),
    )
