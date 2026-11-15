"""Acesso a dados do domínio de insights.

Esta camada NÃO contém regra de negócio: só queries e operações de persistência.

Leitura de outro domínio, declarada em `tests/test_arquitetura.py`
(`LEITURA_ENTRE_DOMINIOS`): `get_form_scope` junta `form_responses` e `form` para
saber a organização e o período de uma resposta, `list_descriptive_answers` junta
`answer` e `questions` para o pedido de insight, `get_response_owner` junta
`form_responses` e `links` para saber de quem é uma resposta, e
`count_submitted_with` conta as respostas enviadas de um período. Só lê; nada fora
de `insights` é gravado aqui.
"""

import uuid
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.forms.models import Form
from app.domains.insights.models import Insight, InsightPrisma, InsightStatus
from app.domains.links.models import Link
from app.domains.questions.models import Question, QuestionType
from app.domains.responses.models import Answer, FormResponse, FormResponseStatus
from app.shared.enums import LinkType, Prisma

# Chave da trava de transação que serializa "contar os em voo e reivindicar" entre
# workers (`lock_dispatch`). Qualquer número fixo serve, desde que só a esteira o use.
DISPATCH_LOCK_KEY = 804

# Primeira metade da chave da trava de um período (`lock_period`); a segunda vem do id
# do formulário. Chave de dois números não colide com a de um número só acima.
PERIOD_LOCK_NAMESPACE = 8013


class FormScope(NamedTuple):
    """A organização e o período (o formulário) a que uma resposta pertence."""

    organization_id: uuid.UUID
    form_id: uuid.UUID
    # Questionário de uma pessoa só (o formulário tem `link_id`), como o do mentorando
    # (P-048): não é um período da empresa.
    individual_form: bool


class ResponseOwner(NamedTuple):
    """O vínculo que respondeu, e a organização e o tipo dele (CREED-805)."""

    link_id: uuid.UUID
    link_type: LinkType
    organization_id: uuid.UUID


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
            select(Form.organization_id, FormResponse.form_id, Form.link_id)
            .select_from(FormResponse)
            .join(Form, Form.id == FormResponse.form_id)
            .where(FormResponse.id == form_response_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return FormScope(
            organization_id=row.organization_id,
            form_id=row.form_id,
            individual_form=row.link_id is not None,
        )

    # --- O insight da empresa (CREED-8013) ---------------------------------------

    async def lock_period(self, form_id: uuid.UUID) -> None:
        """Trava o agendamento do insight da empresa deste período até o fim da
        transação.

        Sem ela, dois envios ao mesmo tempo, no piso exato, contariam cada um as
        enviadas de antes mais ele mesmo, nenhum chegaria ao piso, e o período ficaria
        sem insight. Com ela, o segundo espera o commit do primeiro e conta os dois.
        A trava se solta sozinha no commit ou no rollback.
        """
        await self.db.execute(
            select(
                func.pg_advisory_xact_lock(
                    PERIOD_LOCK_NAMESPACE, func.hashtext(str(form_id))
                )
            )
        )

    async def count_submitted_with(
        self, form_id: uuid.UUID, form_response_id: uuid.UUID
    ) -> int:
        """As respostas enviadas do período, contando também `form_response_id`.

        O envio pede o insight antes de marcar a resposta como enviada, e a marcação
        só chega ao banco no commit: sem o `OR`, a resposta que está sendo enviada
        ficaria fora da conta.
        """
        result = await self.db.execute(
            select(func.count())
            .select_from(FormResponse)
            .where(
                FormResponse.form_id == form_id,
                or_(
                    FormResponse.status == FormResponseStatus.SUBMITTED,
                    FormResponse.id == form_response_id,
                ),
            )
        )
        return int(result.scalar_one())

    async def schedule_organization(
        self, organization_id: uuid.UUID, form_id: uuid.UUID, delay: timedelta
    ) -> bool:
        """Grava o pedido da empresa para daqui a `delay`, pelo relógio do banco.

        Devolve `False` se o período já tem um pedido da empresa esperando: quem
        recusa o segundo é o índice parcial, com `ON CONFLICT DO NOTHING`, e o envio
        segue sem erro.
        """
        result = await self.db.execute(
            insert(Insight)
            .values(
                id=uuid.uuid4(),
                organization_id=organization_id,
                form_id=form_id,
                form_response_id=None,
                next_attempt_at=func.now() + delay,
            )
            .on_conflict_do_nothing(
                index_elements=[Insight.organization_id, Insight.form_id],
                # O predicado do índice `uq_insights_organization_pending_per_form`.
                index_where=text("form_response_id IS NULL AND status = 'PENDING'"),
            )
            .returning(Insight.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_response_owner(
        self, form_response_id: uuid.UUID
    ) -> ResponseOwner | None:
        """Quem respondeu, ou `None` se a resposta não existe."""
        result = await self.db.execute(
            select(Link.id, Link.type, Link.organization_id)
            .select_from(FormResponse)
            .join(Link, Link.id == FormResponse.vinculo_id)
            .where(FormResponse.id == form_response_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return ResponseOwner(
            link_id=row.id, link_type=row.type, organization_id=row.organization_id
        )

    async def get_by_form_response(self, form_response_id: uuid.UUID) -> Insight | None:
        """O insight de uma resposta (P-042: no máximo um)."""
        result = await self.db.execute(
            select(Insight).where(Insight.form_response_id == form_response_id)
        )
        return result.scalar_one_or_none()

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

    # --- O worker da esteira (CREED-804, ADR-0010 item 3) ------------------------

    async def lock_dispatch(self) -> None:
        """Trava a reivindicação até o fim da transação.

        Sem ela, dois ciclos ao mesmo tempo contariam os mesmos `dispatched` e
        passariam juntos do teto. Com ela, o segundo espera o primeiro gravar e conta
        de novo. A trava se solta sozinha no commit ou no rollback.
        """
        await self.db.execute(select(func.pg_advisory_xact_lock(DISPATCH_LOCK_KEY)))

    async def database_now(self) -> datetime:
        """A hora do banco, a mesma `now()` com que `claim_due` e `list_stale`
        comparam as datas. No Postgres, é a do início da transação."""
        result = await self.db.execute(select(func.now()))
        return result.scalar_one()

    async def count_dispatched(self) -> int:
        """Quantos pedidos foram ao N8N e ainda esperam a volta."""
        result = await self.db.execute(
            select(func.count())
            .select_from(Insight)
            .where(Insight.status == InsightStatus.DISPATCHED)
        )
        return int(result.scalar_one())

    async def claim_due(self, limit: int) -> list[Insight]:
        """Os `pending` vencidos, individuais e da empresa, os mais antigos primeiro,
        travados nesta transação.

        `SKIP LOCKED` pula as linhas que outra transação já travou: dois workers
        nunca pegam o mesmo pedido. O "vencido" é pelo relógio do banco.
        """
        result = await self.db.execute(
            select(Insight)
            .where(
                Insight.status == InsightStatus.PENDING,
                Insight.next_attempt_at <= func.now(),
            )
            .order_by(Insight.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def list_stale(self, older_than_seconds: int) -> list[Insight]:
        """Os `dispatched` sem volta há mais de `older_than_seconds`, travados."""
        limit = func.now() - timedelta(seconds=older_than_seconds)
        result = await self.db.execute(
            select(Insight)
            .where(
                Insight.status == InsightStatus.DISPATCHED,
                Insight.dispatched_at < limit,
            )
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def flush(self) -> None:
        """Manda ao banco o que mudou nos insights carregados, sem commitar."""
        await self.db.flush()

    async def get_for_update(self, insight_id: uuid.UUID) -> Insight | None:
        """O insight, travado até o fim da transação: a volta do N8N pode chegar
        enquanto o worker registra a falha do disparo."""
        result = await self.db.execute(
            select(Insight).where(Insight.id == insight_id).with_for_update()
        )
        return result.scalar_one_or_none()

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
