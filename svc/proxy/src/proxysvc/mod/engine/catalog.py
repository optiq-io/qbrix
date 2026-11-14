from __future__ import annotations

from qbrixcore.engine import ENGINES


def engine_catalog() -> list[dict]:
    """the engines a cycle can run, in product words, the default first."""
    names = sorted(ENGINES.names, key=lambda name: name != ENGINES.DEFAULT)
    catalog = []
    for name in names:
        latest = ENGINES.get(name)
        catalog.append(
            {
                "name": name,
                "title": latest.title(),
                "default": name == ENGINES.DEFAULT,
                "latest": str(latest.version),
                "versions": [str(engine.version) for engine in ENGINES.versions(name)],
                "suits": latest.suits,
                "learns_from": latest.learns_from,
                "needs": latest.needs,
                "needs_context": latest.needs_context,
            }
        )
    return catalog
