"""Acesso a dados do domínio de links.

Esta camada NÃO contém regra de negócio: só queries e agregações.
Agregação pesada é empurrada para o Postgres, nunca feita em memória.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.links.models import Link


class LinkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(self, link: Link) -> Link:
        """Grava um vínculo no banco."""
        self.db.add(link)
        await self.db.flush()
        await self.db.refresh(link)
        return link

    async def get_by_id(self, link_id: uuid.UUID) -> Link | None:
        result = await self.db.execute(select(Link).where(Link.id == link_id))
        return result.scalar_one_or_none()
