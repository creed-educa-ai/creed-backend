"""Acesso a dados do domínio de forms.

Esta camada NÃO contém regra de negócio: só queries e agregações.
Agregação pesada é empurrada para o Postgres, nunca feita em memória.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.forms.models import Form


class FormRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, table_id: uuid.UUID) -> Form | None:
        result = await self.db.execute(select(Form).where(Form.id == table_id))
        return result.scalar_one_or_none()

    async def get_form_by_organization_id(
        self, organization_id: uuid.UUID
    ) -> Form | None:
        result = await self.db.execute(
            select(Form).where(Form.organization_id == organization_id)
        )
        return result.scalar_one_or_none()
