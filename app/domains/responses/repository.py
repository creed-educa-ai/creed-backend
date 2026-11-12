"""Acesso a dados do domínio form_responses.

Esta camada NÃO contém regra de negócio: só queries e operações
de persistência da entidade FormResponse.
"""

import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.responses.models import Answer, FormResponse


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

    async def list_ids_by_link_or_forms(
        self, link_id: uuid.UUID, form_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]:
        """As respostas do vínculo, mais as de qualquer vínculo nestes formulários."""
        result = await self.db.execute(
            select(FormResponse.id).where(
                or_(
                    FormResponse.vinculo_id == link_id,
                    FormResponse.form_id.in_(form_ids),
                )
            )
        )
        return list(result.scalars().all())

    async def list_ids_by_forms(self, form_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        """As respostas destes formulários, de qualquer vínculo."""
        if not form_ids:
            return []
        result = await self.db.execute(
            select(FormResponse.id).where(FormResponse.form_id.in_(form_ids))
        )
        return list(result.scalars().all())

    async def delete_by_ids(self, form_response_ids: list[uuid.UUID]) -> None:
        if not form_response_ids:
            return
        await self.db.execute(
            delete(FormResponse).where(FormResponse.id.in_(form_response_ids))
        )


class AnswerRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, answer_id: uuid.UUID) -> Answer | None:
        result = await self.db.execute(select(Answer).where(Answer.id == answer_id))
        return result.scalar_one_or_none()

    async def get_by_form_response_and_question(
        self, form_response_id: uuid.UUID, question_id: uuid.UUID
    ) -> Answer | None:
        """`first()`, não `scalar_one_or_none()`: sem `unique` no banco, uma corrida
        pode ter gravado duas linhas, e isso não deve virar erro 500 aqui."""
        result = await self.db.execute(
            select(Answer).where(
                Answer.form_response_id == form_response_id,
                Answer.question_id == question_id,
            )
        )
        return result.scalars().first()

    async def list_by_form_response(self, form_response_id: uuid.UUID) -> list[Answer]:
        """Em ordem de gravação."""
        result = await self.db.execute(
            select(Answer)
            .where(Answer.form_response_id == form_response_id)
            .order_by(Answer.created_at)
        )
        return list(result.scalars().all())

    async def insert(self, answer: Answer) -> Answer:
        """Grava a resposta. O id e o created_at vêm do banco."""
        self.db.add(answer)
        await self.db.flush()
        await self.db.refresh(answer)
        return answer

    async def delete_by_form_responses(self, form_response_ids: list[uuid.UUID]) -> None:
        if not form_response_ids:
            return
        await self.db.execute(
            delete(Answer).where(Answer.form_response_id.in_(form_response_ids))
        )
