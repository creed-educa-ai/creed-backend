"""Acesso a dados do dominio questions.

Esta camada NAO contem regra de negocio: so queries. Ordenacao e filtro por
secao sao feitos na propria consulta (ADR: filtro/ordenacao no banco, nunca
em memoria) — por isso list_by_form recebe `section` e monta o where
condicionalmente, em vez de devolver tudo e deixar o service filtrar.

`insert` devolve `None` quando a UniqueConstraint recusa a gravacao — isto
NAO e decisao de negocio, e devolver `None` (nao levantar) e o que
`test_arquitetura.py` exige desta camada: quem decide o que `None` significa
e o service.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.questions.models import (
    Question,
    QuestionOption,
    QuestionSection,
)


class QuestionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(self, question: Question) -> Question | None:
        """Grava uma pergunta no banco.

        Devolve `None` se a posicao foi ocupada entre a checagem do service
        e este `flush()` — corrida sem lock, fechada pela UniqueConstraint.
        """
        self.db.add(question)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_questions_form_id_order_index" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(question)
        return question

    async def get_by_id(self, question_id: uuid.UUID) -> Question | None:
        result = await self.db.execute(select(Question).where(Question.id == question_id))
        return result.scalar_one_or_none()

    async def list_by_form(
        self, form_id: uuid.UUID, section: QuestionSection | None = None
    ) -> list[Question]:
        query = select(Question).where(Question.form_id == form_id)

        if section is not None:
            query = query.where(Question.section == section)

        query = query.order_by(Question.order_index)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_required(self, form_id: uuid.UUID) -> list[Question]:
        """Obrigatorias do formulario, em ordem de posicao; o filtro e no banco."""
        result = await self.db.execute(
            select(Question)
            .where(
                Question.form_id == form_id,
                Question.required.is_(True),
            )
            .order_by(Question.order_index)
        )
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


class QuestionOptionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(self, option: QuestionOption) -> QuestionOption | None:
        """Grava uma alternativa no banco.

        Devolve `None` se a posição foi ocupada entre a checagem do service e este
        `flush()`: a UniqueConstraint fecha a corrida que a checagem sozinha não fecha.
        """
        self.db.add(option)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_question_options_question_id_order_index" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(option)
        return option

    async def get_by_id(self, option_id: uuid.UUID) -> QuestionOption | None:
        result = await self.db.execute(
            select(QuestionOption).where(QuestionOption.id == option_id)
        )
        return result.scalar_one_or_none()

    async def get_by_question_and_order(
        self, question_id: uuid.UUID, order_index: int
    ) -> QuestionOption | None:
        result = await self.db.execute(
            select(QuestionOption).where(
                QuestionOption.question_id == question_id,
                QuestionOption.order_index == order_index,
            )
        )
        return result.scalar_one_or_none()
