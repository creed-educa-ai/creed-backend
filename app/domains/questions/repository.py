"""Acesso a dados do dominio questions.

Esta camada NAO contem regra de negocio: so queries. Ordenacao e filtro por
secao sao feitos na propria consulta (ADR: filtro/ordenacao no banco, nunca
em memoria) — por isso list_by_form recebe `section` e monta o where
condicionalmente, em vez de devolver tudo e deixar o service filtrar.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.questions.models import Question, QuestionSection


class QuestionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(self, question: Question) -> Question:
        """Grava uma pergunta no banco."""
        self.db.add(question)
        await self.db.flush()
        await self.db.refresh(question)
        return question

    async def list_by_form(
        self, form_id: uuid.UUID, section: QuestionSection | None = None
    ) -> list[Question]:
        query = select(Question).where(Question.form_id == form_id)

        if section is not None:
            query = query.where(Question.section == section)

        query = query.order_by(Question.order_index)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_form_and_order(
        self, form_id: uuid.UUID, order_index: int
    ) -> Question | None:
        result = await self.db.execute(
            select(Question).where(
                Question.form_id == form_id,
                Question.order_index == order_index,
            )
        )
        return result.scalar_one_or_none()
