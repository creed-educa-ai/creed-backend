"""Acesso a dados do domínio prismas.

Esta camada NÃO contém regra de negócio: só queries e operações de persistência.
Lê respostas e dimensões via join (ADR-0004, item 4).
"""

import contextlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.forms.models import Form
from app.domains.questions.models import Question, QuestionOption
from app.domains.responses.models import Answer, FormResponse
from app.shared.enums import Dimension


class PrismaRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_form_response(self, form_response_id: uuid.UUID) -> FormResponse | None:
        """Busca uma resposta de formulário pelo identificador."""
        result = await self.db.execute(
            select(FormResponse).where(FormResponse.id == form_response_id)
        )
        return result.scalar_one_or_none()

    async def get_form(self, form_id: uuid.UUID) -> Form | None:
        """Busca o formulário associado para checagem de organização."""
        result = await self.db.execute(select(Form).where(Form.id == form_id))
        return result.scalar_one_or_none()

    async def get_answers_with_dimensions(
        self, form_response_id: uuid.UUID
    ) -> list[tuple[Dimension, float]]:
        """Busca respostas objetivas de uma submissão e extrai pares (dimensao, valor)."""
        stmt = (
            select(Answer, Question, QuestionOption)
            .join(Question, Answer.question_id == Question.id)
            .outerjoin(QuestionOption, Answer.option_id == QuestionOption.id)
            .where(Answer.form_response_id == form_response_id)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        collected: list[tuple[Dimension, float]] = []
        for answer, question, option in rows:
            if question.dimensao is None:
                continue

            valor: float | None = None
            if answer.value:
                with contextlib.suppress(ValueError):
                    valor = float(answer.value.strip())

            if valor is None and option is not None:
                if option.value:
                    with contextlib.suppress(ValueError):
                        valor = float(option.value.strip())
                if valor is None and option.order_index is not None:
                    valor = float(option.order_index)

            if valor is not None and 1.0 <= valor <= 5.0:
                collected.append((question.dimensao, valor))

        return collected
