"""Acesso a dados do domínio form_responses.

Esta camada NÃO contém regra de negócio: só queries e operações
de persistência da entidade FormResponse.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.responses.models import FormResponse


class FormResponseRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, form_response_id: uuid.UUID) -> FormResponse | None:
        result = await self.db.execute(
            select(FormResponse).where(FormResponse.id == form_response_id)
        )
        return result.scalar_one_or_none()

    async def get_by_form_and_vinculo(
        self,
        form_id: uuid.UUID,
        vinculo_id: uuid.UUID,
    ) -> FormResponse | None:
        result = await self.db.execute(
            select(FormResponse).where(
                FormResponse.form_id == form_id,
                FormResponse.vinculo_id == vinculo_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, form_response: FormResponse) -> FormResponse:
        """Cria uma resposta de formulário no banco."""
        self.db.add(form_response)
        await self.db.flush()
        await self.db.refresh(form_response)
        return form_response
