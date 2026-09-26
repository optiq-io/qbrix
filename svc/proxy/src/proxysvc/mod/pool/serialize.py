from qbrixstore.postgres.models import Pool


def pool_to_dict(pool: Pool) -> dict:
    return {
        "id": pool.id,
        "name": pool.name,
        "created_at": pool.created_at.isoformat() if pool.created_at else None,
        "updated_at": pool.updated_at.isoformat() if pool.updated_at else None,
        "arms": [
            {
                "id": arm.id,
                "name": arm.name,
                "index": arm.index,
                "is_active": arm.is_active,
                "metadata": arm.metadata_ or {},
            }
            for arm in sorted(pool.arms, key=lambda a: a.index)
        ],
    }
