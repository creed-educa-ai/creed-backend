"""Acesso a dados do domínio de insights.

Esta camada NÃO contém regra de negócio: só queries e operações de persistência.

Leitura de outro domínio, declarada em `tests/test_arquitetura.py`
(`LEITURA_ENTRE_DOMINIOS`): `get_form_scope` junta `form_responses` e `form` para
saber a organização e o período de uma resposta, e `list_descriptive_answers` junta
`answer` e `questions` para o pedido de insight. Só lê; nada fora de `insights` é
gravado aqui.
"""

import uuid
from typing import NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.forms.models import Form
from app.domains.insights.models import Insight, InsightPrisma
from app.domains.questions.models import Question, QuestionType
from app.domains.responses.models import Answer, FormResponse
from app.shared.enums import Prisma


class FormScope(NamedTuple):
    """A organização e o período (o formulário) a que uma resposta pertence."""

    organization_id: uuid.UUID
    form_id: uuid.UUID


class DescriptiveAnswer(NamedTuple):
    """Uma pergunta descritiva e o que a pessoa escreveu nela (CREED-803)."""

    section: str  # ex.: "S9"
    question: str  # texto da pergunta, em pt-BR
    answer: str | None  # como foi gravado; vazio quando a pessoa não escreveu


class InsightPrismaRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_insight(self, insight_id: uuid.UUID) -> Insight | None:
        """Busca o insight que a associação referencia."""
        result = await self.db.execute(select(Insight).where(Insight.id == insight_id))
        return result.scalar_one_or_none()

    async def get(self, insight_id: uuid.UUID, prisma: Prisma) -> InsightPrisma | None:
        """Busca uma associação pelo par que a identifica."""
        result = await self.db.execute(
            select(InsightPrisma).where(
                InsightPrisma.insight_id == insight_id,
                InsightPrisma.prisma == prisma,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_insight(self, insight_id: uuid.UUID) -> list[InsightPrisma]:
        """Lista os prismas associados a um insight."""
        result = await self.db.execute(
            select(InsightPrisma).where(InsightPrisma.insight_id == insight_id)
        )
        return list(result.scalars().all())

    async def insert(self, associacao: InsightPrisma) -> InsightPrisma | None:
        """Grava a associação.

        Devolve `None` se o par foi gravado entre a checagem do service e
        este `flush()` — corrida sem lock, fechada pela chave primária
        composta.
        """
        self.db.add(associacao)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "insight_prismas_pkey" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(associacao)
        return associacao

    async def delete(self, associacao: InsightPrisma) -> None:
        """Remove a associação."""
        await self.db.delete(associacao)
        await self.db.flush()


class InsightRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_form_scope(self, form_response_id: uuid.UUID) -> FormScope | None:
        """Organização e formulário da resposta, ou `None` se ela não existe."""
        result = await self.db.execute(
            select(Form.organization_id, FormResponse.form_id)
            .select_from(FormResponse)
            .join(Form, Form.id == FormResponse.form_id)
            .where(FormResponse.id == form_response_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return FormScope(organization_id=row.organization_id, form_id=row.form_id)

    async def list_descriptive_answers(
        self, form_response_id: uuid.UUID
    ) -> list[DescriptiveAnswer]:
        """As respostas às perguntas descritivas, na ordem do questionário.

        Traz a resposta como foi gravada, inclusive vazia: quem decide o que conta
        como respondida é o service.
        """
        result = await self.db.execute(
            select(Question.section, Question.text, Answer.value)
            .select_from(Answer)
            .join(Question, Question.id == Answer.question_id)
            .where(
                Answer.form_response_id == form_response_id,
                Question.type == QuestionType.DESCRIPTIVE,
            )
            .order_by(Question.section, Question.order_index)
        )
        return [
            DescriptiveAnswer(
                section=row.section.value, question=row.text, answer=row.value
            )
            for row in result.all()
        ]

    async def create(self, insight: Insight) -> Insight | None:
        """Grava o pedido.

        Devolve `None` se a resposta já tem insight. Quem recusa o segundo é a
        restrição única de `form_response_id`, sem conferência prévia: dois envios
        ao mesmo tempo passam juntos pela checagem de "em andamento" e só se
        esbarram aqui. Qualquer outra violação sobe.
        """
        self.db.add(insight)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_insights_form_response_id" not in str(exc.orig):
                raise
            return None
        # Traz o que o banco preenche sozinho (`next_attempt_at`, `created_at`).
        await self.db.refresh(insight)
        return insight

    async def delete_by_form_responses(self, form_response_ids: list[uuid.UUID]) -> None:
        """Apaga os insights das respostas e, antes, os prismas associados a eles.

        As duas tabelas são deste domínio, então a ordem mora aqui: a associação
        aponta para o insight, e o banco recusaria apagar o insight primeiro.
        """
        if not form_response_ids:
            return
        insights_of_responses = select(Insight.id).where(
            Insight.form_response_id.in_(form_response_ids)
        )
        await self.db.execute(
            delete(InsightPrisma).where(
                InsightPrisma.insight_id.in_(insights_of_responses)
            )
        )
        await self.db.execute(
            delete(Insight).where(Insight.form_response_id.in_(form_response_ids))
        )
