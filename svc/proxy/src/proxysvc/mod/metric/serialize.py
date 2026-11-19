from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import Metric
from qbrixstore.postgres.models import MetricVersion

from proxysvc.mod.change.proposal import HAPPENED
from proxysvc.mod.people import People


def window_label(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def metric_to_dict(metric: Metric) -> dict:
    current = metric.versions[-1]
    return {
        "id": metric.id,
        "name": metric.name,
        "type": metric.type,
        "range": (
            {"lo": metric.score_lo, "hi": metric.score_hi}
            if metric.score_lo is not None
            else None
        ),
        "version": f"{current.major}.{current.minor}",
        "semantic": current.semantic,
        "window_seconds": current.window_sec,
        "created_by": metric.created_by,
        "created_at": metric.created_at.isoformat() if metric.created_at else None,
        "updated_at": metric.updated_at.isoformat() if metric.updated_at else None,
    }


def _version_label(version: MetricVersion) -> str:
    return f"{version.major}.{version.minor}"


def _version_changes(older: MetricVersion | None, newer: MetricVersion) -> list[dict]:
    if older is None:
        return []
    changed = []
    if older.window_sec != newer.window_sec:
        changed.append(
            {
                "field": "window",
                "before": window_label(older.window_sec),
                "after": window_label(newer.window_sec),
            }
        )
    if older.semantic != newer.semantic:
        changed.append(
            {"field": "semantic", "before": older.semantic, "after": newer.semantic}
        )
    return changed


def metric_detail(metric: Metric, changes: list[Change], people: People) -> dict:
    """a metric with its versions, newest first. a version's reason is the one
    given by the change that made it; a reword is a change, not a version."""
    made_by: dict[str, Change] = {}
    for change in changes:
        if change.status not in HAPPENED or change.after is None:
            continue
        made = change.after.get("version")
        if made and (change.before or {}).get("version") != made:
            made_by.setdefault(made, change)
    versions = metric.versions
    return {
        **metric_to_dict(metric),
        "versions": [
            {
                "version": _version_label(version),
                "semantic": version.semantic,
                "window_seconds": version.window_sec,
                "created_by": {
                    "id": version.created_by,
                    "name": people.name(version.created_by),
                },
                "created_at": (
                    version.created_at.isoformat() if version.created_at else None
                ),
                "reason": getattr(made_by.get(_version_label(version)), "reason", None),
                "changed": _version_changes(
                    versions[index - 1] if index else None, version
                ),
            }
            for index, version in reversed(list(enumerate(versions)))
        ],
    }
