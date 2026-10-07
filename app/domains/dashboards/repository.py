"""Acesso a dados do domínio de dashboards.

Esta camada NÃO contém regra de negócio: só queries e operações de persistência.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.dashboards.models import Dashboard


class DashboardRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, dashboard_id: uuid.UUID) -> Dashboard | None:
        """Busca um dashboard pelo seu identificador."""
        result = await self.db.execute(
            select(Dashboard).where(Dashboard.id == dashboard_id)
        )
        return result.scalar_one_or_none()

    async def create(self, dashboard: Dashboard) -> Dashboard:
        """Cria um dashboard no banco."""
        self.db.add(dashboard)
        await self.db.flush()
        await self.db.refresh(dashboard)
        return dashboard
