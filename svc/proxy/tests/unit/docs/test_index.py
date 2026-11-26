from __future__ import annotations

import time
from pathlib import Path

import pytest

from proxysvc.config import ProxySettings
from proxysvc.mod.docs.index import ANSWER_CAP_CHARS
from proxysvc.mod.docs.index import SUPERSEDED
from proxysvc.mod.docs.index import DocsIndex

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
DOCKERFILE = REPO / "svc" / "proxy" / "Dockerfile"
QUERIES = [
    "record an outcome",
    "create an experiment from a pool",
    "configure a feature gate",
    "choose a policy",
    "thompson sampling",
    "select with a context",
    "send feedback reward",
    "python sdk",
    "getting started",
    "api reference",
]


@pytest.fixture(scope="module")
def docs() -> DocsIndex:
    return DocsIndex.load(REPO)


def _page(root: Path, folder: str, slug: str, title: str, body: str) -> None:
    (root / folder).mkdir(parents=True, exist_ok=True)
    (root / folder / f"{slug}.mdx").write_text(
        f"---\ntitle: {title}\ndescription: d\norder: 1\n---\n\n{body}\n"
    )


def test_a_next_page_replaces_the_page_with_its_slug(tmp_path: Path):
    _page(tmp_path, "docs-next", "sdks", "SDKs next", "## Install\n\nnext words")
    _page(tmp_path, "docs", "sdks", "SDKs", "## Install\n\nold words")
    _page(tmp_path, "docs", "self-hosting", "Self-hosting", "## Run\n\ncompose")
    _page(tmp_path, "docs", "policies", "Policies", "## Policies\n\nold api")

    docs = DocsIndex.load(tmp_path)

    assert [page.slug for page in docs.pages] == ["sdks", "self-hosting"]
    assert docs.page("sdks").sections[0].text == "next words"
    assert docs.page("policies") is None


@pytest.mark.parametrize("folder", ["docs", "docs-next"])
def test_a_missing_folder_fails_at_load(tmp_path: Path, folder: str):
    other = "docs" if folder == "docs-next" else "docs-next"
    _page(tmp_path, other, "sdks", "SDKs", "words")

    with pytest.raises(RuntimeError, match=f"no docs pages in .*{folder}$"):
        DocsIndex.load(tmp_path)


def test_every_superseded_page_exists_in_docs():
    assert SUPERSEDED <= {path.stem for path in (REPO / "docs").glob("*.mdx")}


@pytest.mark.parametrize("query", QUERIES)
def test_no_answer_teaches_the_api_next_replaced(docs: DocsIndex, query: str):
    assert not {s.slug for s in docs.search(query).sections} & SUPERSEDED


def test_record_an_outcome_finds_metrics_and_outcomes_from_docs_next(
    docs: DocsIndex,
):
    answer = docs.search("record an outcome")

    assert answer.sections[0].slug == "metrics-and-outcomes"
    assert (REPO / "docs-next" / "metrics-and-outcomes.mdx").exists()


def test_a_page_comes_whole_with_its_outline(docs: DocsIndex):
    answer = docs.page("mcp-server")

    assert answer.truncated is False
    assert [s.anchor for s in answer.outline] == [s.anchor for s in answer.sections]
    assert "tools" in [s.anchor for s in answer.outline]


def test_the_cap_is_about_five_thousand_tokens():
    assert ANSWER_CAP_CHARS == 20_000


def test_every_answer_stays_under_the_cap(docs: DocsIndex):
    answers = [docs.search(q) for q in QUERIES + ["loop", "the"]]
    answers += [docs.page(page.slug) for page in docs.pages]

    for answer in answers:
        assert sum(len(s.text) for s in answer.sections) <= ANSWER_CAP_CHARS
    assert any(answer.truncated for answer in answers)


def test_a_long_page_is_cut_and_its_outline_kept_whole(docs: DocsIndex):
    answer = docs.page("loops")

    assert answer.truncated is True
    assert len(answer.outline) > len(answer.sections)


def test_words_only_qbrix_ignores_find_nothing(docs: DocsIndex):
    assert docs.search("xyzzy plugh").sections == ()
    assert docs.search("the and of").sections == ()


def test_the_index_builds_in_under_a_second():
    started = time.perf_counter()
    DocsIndex.load(REPO)

    assert time.perf_counter() - started < 1


def test_the_image_ships_the_docs_where_the_proxy_reads_them(tmp_path: Path):
    default = Path(ProxySettings.model_fields["docs_path"].default)
    lines = DOCKERFILE.read_text().splitlines()
    workdir = Path([l.split()[1] for l in lines if l.startswith("WORKDIR")][-1])
    copies = {
        parts[1]: workdir / parts[2]
        for parts in (l.split() for l in lines if l.startswith("COPY docs"))
    }

    assert copies == {"docs": default / "docs", "docs-next": default / "docs-next"}
    for source, target in copies.items():
        (tmp_path / target.relative_to("/")).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / target.relative_to("/")).symlink_to(REPO / source)
    assert DocsIndex.load(tmp_path / default.relative_to("/")).pages
