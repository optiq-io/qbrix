from __future__ import annotations

from qbrixstore.postgres.session import get_session

from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.serialize import change_to_dict


class ChangeService:
    """reads the change log. writes record their own change, inside their own
    transaction, through ChangeRepository."""

    async def list_changes(
        self, tenant_id: str, target_type: str, target_id: str, limit: int = 50
    ) -> list[dict]:
        async with get_session() as session:
            repo = ChangeRepository(session, tenant_id)
            changes = await repo.list_for(target_type, target_id, limit=limit)
            return [change_to_dict(change) for change in changes]

    async def get_change(self, tenant_id: str, change_id: str) -> dict | None:
        async with get_session() as session:
            repo = ChangeRepository(session, tenant_id)
            change = await repo.get(change_id)
            return change_to_dict(change) if change else None
