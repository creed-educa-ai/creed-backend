"""A tabela `insights` e o pedido do envio, num Postgres de verdade (CREED-802).

RUN_POSTGRES_TESTS=1 habilita estes testes; usa as variáveis POSTGRES_* normais, como
`tests/domains/forms/test_periods_postgres.py`. Cada execução cria um schema
descartável e o apaga no fim: nenhuma tabela existente é modificada.

Existe porque os outros testes do domínio usam sessão falsa, e sessão falsa não prova
o que o banco decide: o JOIN que acha a organização e o período, a restrição única
de `form_response_id`, o `CHECK` entre `done` e `content` e o índice parcial do
insight da empresa. O `create_all` do fixture também prova que os literais `'DONE'` e
`'PENDING'` dessas regras existem no enum: com outro texto, a tabela nem sobe.
"""

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import models  # noqa: F401 — registra todas as FKs
from app.core.config import settings
from app.core.database import Base
from app.domains.documents.models import Document
from app.domains.forms.models import Form
from app.domains.insights.models import Insight, InsightStatus
from app.domains.insights.repository import (
    DescriptiveAnswer,
    FormScope,
    InsightRepository,
)
from app.domains.insights.service import InsightService
from app.domains.links.models import Link
from app.domains.organizacoes.models import Organization
from app.domains.participants.models import Participant
from app.domains.prismas.repository import PrismaRepository
from app.domains.prismas.service import PrismaService
from app.domains.questions.models import (
    Instrument,
    Question,
    QuestionSection,
    QuestionType,
)
from app.domains.responses.models import Answer, FormResponse, FormResponseStatus
from app.shared.enums import Dimension, LinkType, Prisma, Roles
from app.shared.exceptions import ConflictError
from app.shared.instrument import CREED_INSTRUMENT_ID

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1", reason="Requer PostgreSQL de teste"
)

# O texto do insight já validado. O banco só guarda: quem confere a forma é o schema.
CONTEUDO = {"analise": ["Um", "Dois"], "recomendacao": ["Uma"]}


@dataclass
class Cenario:
    """Uma organização com dois períodos e três respostas (sem insight nenhum)."""

    sessions: async_sessionmaker[AsyncSession]
    organization_id: uuid.UUID
    form_ids: list[uuid.UUID]  # dois períodos da mesma organização
    response_ids: list[uuid.UUID]  # [0] e [1] no período 0; [2] no período 1


@pytest.fixture
async def cenario() -> AsyncIterator[Cenario]:
    schema = f"test_insights_{uuid.uuid4().hex}"
    engine = create_async_engine(
        settings.database_url, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        organization_id = uuid.uuid4()
        form_ids = [uuid.uuid4(), uuid.uuid4()]
        response_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        async with sessions.begin() as session:
            session.add(Instrument(id=CREED_INSTRUMENT_ID, name="Inventário CREED"))
            document = Document(value=f"TEST-{organization_id}")
            session.add(document)
            await session.flush()
            session.add(
                Organization(
                    id=organization_id,
                    name="Empresa de teste",
                    address="Teste",
                    document_id=document.id,
                )
            )
            participant = Participant(name="Pessoa de teste")
            session.add(participant)
            await session.flush()
            links = []
            for _ in range(2):
                link = Link(
                    participant_id=participant.id,
                    organization_id=organization_id,
                    type=LinkType.EMPREGO,
                    role=Roles.RESPONDENTE,
                )
                session.add(link)
                links.append(link)
            for form_id in form_ids:
                session.add(
                    Form(id=form_id, name="Período", organization_id=organization_id)
                )
            await session.flush()
            for response_id, form_id, link in [
                (response_ids[0], form_ids[0], links[0]),
                (response_ids[1], form_ids[0], links[1]),
                (response_ids[2], form_ids[1], links[0]),
            ]:
                session.add(
                    FormResponse(id=response_id, form_id=form_id, vinculo_id=link.id)
                )
        yield Cenario(sessions, organization_id, form_ids, response_ids)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


def _service(session: AsyncSession) -> InsightService:
    return InsightService(
        InsightRepository(session), PrismaService(PrismaRepository(session))
    )


def um_insight(
    cenario: Cenario,
    *,
    form_index: int = 0,
    response_index: int | None = None,
    status: InsightStatus = InsightStatus.PENDING,
    content: dict[str, list[str]] | None = None,
) -> Insight:
    """Insight individual (com `response_index`) ou da empresa (sem ele)."""
    return Insight(
        organization_id=cenario.organization_id,
        form_id=cenario.form_ids[form_index],
        form_response_id=(
            None if response_index is None else cenario.response_ids[response_index]
        ),
        status=status,
        content=content,
    )


# --- O pedido que o envio grava -----------------------------------------------


async def test_pedido_nasce_pending_com_organizacao_e_periodo_da_resposta(
    cenario: Cenario,
) -> None:
    async with cenario.sessions.begin() as session:
        service = _service(session)
        pedido = await service.request_individual(cenario.response_ids[2])

    assert pedido.status is InsightStatus.PENDING
    assert pedido.attempts == 0
    assert pedido.organization_id == cenario.organization_id
    assert pedido.form_id == cenario.form_ids[1]
    assert pedido.form_response_id == cenario.response_ids[2]
    assert pedido.content is None
    assert pedido.next_attempt_at is not None


async def test_segundo_pedido_da_mesma_resposta_vira_conflict(cenario: Cenario) -> None:
    """O `unique` de verdade, com o nome que o repository procura na mensagem."""
    async with cenario.sessions.begin() as session:
        await _service(session).request_individual(cenario.response_ids[0])

    with pytest.raises(ConflictError):
        async with cenario.sessions.begin() as session:
            await _service(session).request_individual(cenario.response_ids[0])

    async with cenario.sessions() as session:
        total = await session.scalar(select(func.count()).select_from(Insight))
    assert total == 1


async def test_escopo_de_uma_resposta_vem_do_join(cenario: Cenario) -> None:
    async with cenario.sessions() as session:
        repository = InsightRepository(session)

        escopo = await repository.get_form_scope(cenario.response_ids[2])
        inexistente = await repository.get_form_scope(uuid.uuid4())

    assert escopo == FormScope(cenario.organization_id, cenario.form_ids[1])
    assert inexistente is None


async def test_exclusao_de_membro_apaga_o_pedido(cenario: Cenario) -> None:
    """A M-3 apaga por `form_response_id`, e a tabela ganhou colunas e restrições."""
    async with cenario.sessions.begin() as session:
        session.add(um_insight(cenario, response_index=0))
        session.add(um_insight(cenario, response_index=1))

    async with cenario.sessions.begin() as session:
        await InsightRepository(session).delete_by_form_responses(
            [cenario.response_ids[0]]
        )

    async with cenario.sessions() as session:
        restantes = (await session.scalars(select(Insight.form_response_id))).all()
    assert restantes == [cenario.response_ids[1]]


# --- As restrições da tabela --------------------------------------------------


async def test_insert_direto_de_segundo_insight_da_mesma_resposta_e_recusado(
    cenario: Cenario,
) -> None:
    async with cenario.sessions.begin() as session:
        session.add(um_insight(cenario, response_index=0))

    with pytest.raises(IntegrityError, match="uq_insights_form_response_id"):
        async with cenario.sessions.begin() as session:
            session.add(um_insight(cenario, response_index=0))


async def test_done_exige_content(cenario: Cenario) -> None:
    with pytest.raises(IntegrityError, match="ck_insights_done_has_content"):
        async with cenario.sessions.begin() as session:
            session.add(um_insight(cenario, response_index=0, status=InsightStatus.DONE))


@pytest.mark.parametrize(
    "status", [InsightStatus.PENDING, InsightStatus.DISPATCHED, InsightStatus.FAILED]
)
async def test_content_com_outro_estado_que_nao_done_e_recusado(
    cenario: Cenario, status: InsightStatus
) -> None:
    with pytest.raises(IntegrityError, match="ck_insights_done_has_content"):
        async with cenario.sessions.begin() as session:
            session.add(
                um_insight(cenario, response_index=0, status=status, content=CONTEUDO)
            )


async def test_done_com_content_grava_e_devolve_o_json(cenario: Cenario) -> None:
    async with cenario.sessions.begin() as session:
        session.add(
            um_insight(
                cenario,
                response_index=0,
                status=InsightStatus.DONE,
                content=CONTEUDO,
            )
        )

    async with cenario.sessions() as session:
        gravado = (await session.scalars(select(Insight))).one()
    assert gravado.content == CONTEUDO


async def test_so_um_pedido_da_empresa_espera_por_periodo(cenario: Cenario) -> None:
    async with cenario.sessions.begin() as session:
        session.add(um_insight(cenario))

    with pytest.raises(IntegrityError, match="uq_insights_organization_pending_per_form"):
        async with cenario.sessions.begin() as session:
            session.add(um_insight(cenario))


async def test_o_indice_parcial_so_vale_para_empresa_pendente(cenario: Cenario) -> None:
    """Cabem juntos, no mesmo período: um pedido da empresa pendente, outros da
    empresa já prontos ou falhos, os individuais pendentes e um pedido da empresa
    pendente no outro período."""
    async with cenario.sessions.begin() as session:
        session.add(um_insight(cenario))
        session.add(um_insight(cenario, status=InsightStatus.DONE, content=CONTEUDO))
        session.add(um_insight(cenario, status=InsightStatus.DONE, content=CONTEUDO))
        session.add(um_insight(cenario, status=InsightStatus.FAILED))
        session.add(um_insight(cenario, response_index=0))
        session.add(um_insight(cenario, response_index=1))
        session.add(um_insight(cenario, form_index=1))

    async with cenario.sessions() as session:
        total = await session.scalar(select(func.count()).select_from(Insight))
    assert total == 7


# --- O pedido que vai ao N8N (CREED-803) ---------------------------------------


async def responder(session: AsyncSession, cenario: Cenario) -> None:
    """A resposta 0 enviada: 4 nas sete objetivas e três descritivas, uma em branco.

    A resposta 1 também escreve numa descritiva, para provar que o JOIN não mistura
    respostas de pessoas diferentes.
    """
    objetivas = [
        Question(
            instrument_id=CREED_INSTRUMENT_ID,
            text=f"Objetiva de {dimension.value}",
            order_index=ordem,
            type=QuestionType.OBJECTIVE,
            section=QuestionSection(dimension.value),
            dimensao=dimension,
        )
        for ordem, dimension in enumerate(Dimension, start=1)
    ]
    # Fora de ordem de propósito: quem ordena é o `order_index`.
    segunda, primeira, em_branco = (
        Question(
            instrument_id=CREED_INSTRUMENT_ID,
            text=texto,
            order_index=ordem,
            type=QuestionType.DESCRIPTIVE,
            section=QuestionSection.S9,
        )
        for texto, ordem in [
            ("Segunda aberta", 20),
            ("Primeira aberta", 10),
            ("Deixada em branco", 30),
        ]
    )
    session.add_all([*objetivas, segunda, primeira, em_branco])
    await session.flush()

    resposta, outra = cenario.response_ids[0], cenario.response_ids[1]
    session.add_all(
        [
            Answer(form_response_id=resposta, question_id=q.id, value="4")
            for q in objetivas
        ]
        + [
            Answer(form_response_id=resposta, question_id=segunda.id, value="Texto B"),
            Answer(form_response_id=resposta, question_id=primeira.id, value="Texto A"),
            Answer(form_response_id=resposta, question_id=em_branco.id, value=""),
            Answer(form_response_id=outra, question_id=primeira.id, value="De outra"),
        ]
    )
    enviada = await session.get(FormResponse, resposta)
    assert enviada is not None
    enviada.status = FormResponseStatus.SUBMITTED
    await session.flush()


async def test_descritivas_da_resposta_vem_do_join_na_ordem_do_questionario(
    cenario: Cenario,
) -> None:
    async with cenario.sessions.begin() as session:
        await responder(session, cenario)

        respostas = await InsightRepository(session).list_descriptive_answers(
            cenario.response_ids[0]
        )

    # Sem as objetivas e sem a da outra pessoa; a em branco vem, e o service a tira.
    assert respostas == [
        DescriptiveAnswer("S9", "Primeira aberta", "Texto A"),
        DescriptiveAnswer("S9", "Segunda aberta", "Texto B"),
        DescriptiveAnswer("S9", "Deixada em branco", ""),
    ]


async def test_pedido_montado_com_o_banco_de_verdade(cenario: Cenario) -> None:
    """O caminho inteiro: cálculo do `PrismaService` e descritivas, pelo JOIN real."""
    async with cenario.sessions.begin() as session:
        await responder(session, cenario)
        pedido = um_insight(cenario, response_index=0)
        session.add(pedido)
        await session.flush()

        payload = await _service(session).build_individual_payload(pedido)

    # Média 4 em tudo: (4 - 1) / 4 * 100 = 75 em cada nota.
    assert payload.result.prismas.model_dump() == dict.fromkeys(
        (prisma.value for prisma in Prisma), 75.0
    )
    assert payload.result.dimensions.S8 == 75.0
    # Empate geral: a ordem dos prismas decide, como no dashboard.
    assert payload.result.destaque is Prisma.SEGURANCA_PSICOLOGICA
    assert [item.answer for item in payload.open_answers] == ["Texto A", "Texto B"]
    assert payload.attempt == 1
