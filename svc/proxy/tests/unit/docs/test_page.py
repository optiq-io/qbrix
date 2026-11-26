from __future__ import annotations

from pathlib import Path

import pytest

from proxysvc.mod.docs.page import parse_page

pytestmark = pytest.mark.unit

PAGE = """---
title: "Wiring: a loop"
description: How code calls a loop — select, then outcome.
order: 2
---

A loop decides one product choice.

<Callout type="info" title="Before you start">
Create the loop **first**.
</Callout>

## Select

<CodeTabs>
<CodeTab label="python">
```python
# not a heading
client.select("checkout-headline")
```
</CodeTab>
</CodeTabs>

<Endpoint method="POST" path="/api/v1/select" description="Ask for a decision" />
<BurstTestNote />

### `select()` with a <Badge>context</Badge>

Pass the properties.

## Select

Again.
"""


@pytest.fixture
def page(tmp_path: Path):
    source = tmp_path / "wiring.mdx"
    source.write_text(PAGE)
    return parse_page(source)


def test_reads_the_frontmatter(page):
    assert page.slug == "wiring"
    assert page.title == "Wiring: a loop"
    assert page.description == "How code calls a loop — select, then outcome."


def test_text_before_the_first_heading_leads_under_the_page_title(page):
    lead = page.sections[0]
    assert lead.path == ()
    assert lead.anchor == ""
    assert lead.text.startswith("A loop decides one product choice.")


def test_keeps_a_components_words_and_drops_its_tags(page):
    lead = page.sections[0].text
    assert "Before you start" in lead
    assert "Create the loop **first**." in lead
    assert "<Callout" not in lead and "</Callout>" not in lead


def test_a_comment_in_a_fence_is_not_a_heading(page):
    select = page.sections[1]
    assert select.path == ("Select",)
    assert "# not a heading" in select.text
    assert "```python" in select.text


def test_a_self_closing_component_keeps_what_it_says(page):
    select = page.sections[1].text
    assert "POST · /api/v1/select · Ask for a decision" in select
    assert "BurstTestNote" not in select


def test_headings_nest_and_take_the_sites_anchors(page):
    assert [s.path for s in page.sections[2:]] == [
        ("Select", "select() with a context"),
        ("Select",),
    ]
    assert page.anchors == ("select", "select-with-a-context", "select-1")
    assert [s.anchor for s in page.sections] == [
        "",
        "select",
        "select-with-a-context",
        "select-1",
    ]


def test_a_page_without_a_title_fails(tmp_path: Path):
    source = tmp_path / "broken.mdx"
    source.write_text("---\ndescription: x\n---\n\nBody.\n")

    with pytest.raises(RuntimeError, match="has no title"):
        parse_page(source)
