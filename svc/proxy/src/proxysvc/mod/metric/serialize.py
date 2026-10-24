from qbrixstore.postgres.models import Metric


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
