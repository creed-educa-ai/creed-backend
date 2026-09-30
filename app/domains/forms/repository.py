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

    async def get_by_id(self, form_id: uuid.UUID) -> Form | None:
        result = await self.db.execute(select(Form).where(Form.id == form_id))
        return result.scalar_one_or_none()

    async def create(self, form: Form) -> Form:
        """Cria um formulário no banco."""
        self.db.add(form)
        await self.db.flush()
        await self.db.refresh(form)
        return form
