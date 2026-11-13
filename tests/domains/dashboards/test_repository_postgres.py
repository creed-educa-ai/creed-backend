"""A consulta agregada do dashboard, em Postgres de verdade e schema descartável.

A média por pessoa e dimensão é feita no banco (princípio 1), e o que só o banco
prova é que o agrupamento, o CAST e os filtros de status e de vínculo estão certos.

RUN_POSTGRES_TESTS=1 habilita estes testes; usa as variáveis POSTGRES_* normais.
"""

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401 — registra todas as FKs
from app.core.config import settings
from app.core.database import Base
from app.domains.dashboards.repository import DashboardRepository
from app.domains.department.models import Department
from app.domains.documents.models import Document
from app.domains.forms.models import Form
from app.domains.links.models import Link
from app.domains.organizacoes.models import Organization
from app.domains.participants.models import Participant
from app.domains.questions.models import (
    Instrument,
    Question,
    QuestionOption,
    QuestionSection,
    QuestionType,
)
from app.domains.responses.models import Answer, FormResponse, FormResponseStatus
from app.shared.enums import DepartmentType, Dimension, LinkType, Roles
from app.shared.instrument import CREED_INSTRUMENT_ID

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1", reason="Requer PostgreSQL de teste"
)

INICIO = datetime(2026, 8, 1, 12, tzinfo=UTC)
SETEMBRO = datetime(2026, 9, 1, 12, tzinfo=UTC)
OUTUBRO = datetime(2026, 10, 1, 12, tzinfo=UTC)
AGORA = datetime(2026, 11, 13, 12, tzinfo=UTC)


@pytest.fixture
async def cenario():  # type: ignore[no-untyped-def]
    """Uma organização com duas pessoas e outra organização com uma.

    - `marketing`: setor Marketing; enviou setembro e tem outubro em andamento.
    - `sem_setor`: sem setor; enviou setembro e outubro.
    - `de_fora`: outra organização; enviou o período dela.

    Duas perguntas na S2 (alternativas 2 e 4, média 3) e uma em cada outra
    dimensão, mais uma aberta, que não entra na média.
    """
    schema = f"test_dashboards_{uuid.uuid4().hex}"
    engine = create_async_engine(
        settings.database_url, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        ids: dict[str, uuid.UUID] = {}

        async with sessions.begin() as session:
            session.add(Instrument(id=CREED_INSTRUMENT_ID, name="Inventário CREED"))
            orgs = []
            for nome in ("empresa", "outra"):
                document = Document(value=f"TEST-{nome}-{uuid.uuid4()}")
                session.add(document)
                await session.flush()
                org = Organization(name=nome, address="Teste", document_id=document.id)
                session.add(org)
                await session.flush()
                orgs.append(org)
            empresa, outra = orgs

            setor = Department(organization_id=empresa.id, type=DepartmentType.MARKETING)
            participante = Participant(name="Pessoa de teste")
            session.add_all([setor, participante])
            await session.flush()

            for nome, org, department_id in [
                ("marketing", empresa, setor.id),
                ("sem_setor", empresa, None),
                ("de_fora", outra, None),
            ]:
                link = Link(
                    participant_id=participante.id,
                    organization_id=org.id,
                    department_id=department_id,
                    type=LinkType.EMPREGO,
                    role=Roles.RESPONDENTE,
                    # Antes dos períodos: senão não são do público deles.
                    start_at=INICIO,
                    created_at=INICIO,
                )
                session.add(link)
                await session.flush()
                ids[nome] = link.id

            perguntas: list[tuple[Question, Dimension | None]] = []
            # As alternativas de cada pergunta, pelo valor. Sem passar pela relação
            # `Question.options`: na sessão assíncrona ela tentaria carregar do banco.
            alternativas: dict[uuid.UUID, dict[str, QuestionOption]] = {}
            posicoes = [Dimension.S2, *Dimension, None]
            for posicao, dimensao in enumerate(posicoes):
                pergunta = Question(
                    instrument_id=CREED_INSTRUMENT_ID,
                    text=f"Pergunta {posicao}",
                    order_index=posicao,
                    type=QuestionType.OBJECTIVE if dimensao else QuestionType.DESCRIPTIVE,
                    section=QuestionSection(dimensao.value if dimensao else "S9"),
                    dimensao=dimensao,
                )
                session.add(pergunta)
                await session.flush()
                if dimensao is not None:
                    alternativas[pergunta.id] = {
                        str(v): QuestionOption(
                            question_id=pergunta.id,
                            label=str(v),
                            value=str(v),
                            order_index=v,
                        )
                        for v in range(1, 6)
                    }
                    session.add_all(alternativas[pergunta.id].values())
                perguntas.append((pergunta, dimensao))
            await session.flush()

            forms = {}
            for nome, org, abre in [
                ("setembro", empresa, SETEMBRO),
                ("outubro", empresa, OUTUBRO),
                ("da_outra", outra, SETEMBRO),
            ]:
                form = Form(
                    name=nome,
                    organization_id=org.id,
                    opens_at=abre,
                    closes_at=abre.replace(day=15),
                )
                session.add(form)
                await session.flush()
                forms[nome] = form
                ids[nome] = form.id

            # Dois que não são resultado da empresa: o individual de uma pessoa e
            # um "para todos" que ainda não abriu.
            for nome, abre, link_id in [
                ("individual", OUTUBRO, ids["marketing"]),
                ("agendado", datetime(2030, 1, 1, 12, tzinfo=UTC), None),
            ]:
                form = Form(
                    name=nome,
                    organization_id=empresa.id,
                    opens_at=abre,
                    closes_at=abre.replace(day=15),
                    link_id=link_id,
                )
                session.add(form)
                await session.flush()
                forms[nome] = form
                ids[nome] = form.id
            ids["empresa"] = empresa.id
            ids["outra"] = outra.id

            def responder(
                form: Form, link_id: uuid.UUID, status: FormResponseStatus
            ) -> FormResponse:
                resposta = FormResponse(
                    form_id=form.id, vinculo_id=link_id, status=status
                )
                session.add(resposta)
                return resposta

            respostas = [
                responder(
                    forms["setembro"], ids["marketing"], FormResponseStatus.SUBMITTED
                ),
                responder(
                    forms["outubro"], ids["marketing"], FormResponseStatus.IN_PROGRESS
                ),
                responder(
                    forms["setembro"], ids["sem_setor"], FormResponseStatus.SUBMITTED
                ),
                responder(
                    forms["outubro"], ids["sem_setor"], FormResponseStatus.SUBMITTED
                ),
                responder(
                    forms["da_outra"], ids["de_fora"], FormResponseStatus.SUBMITTED
                ),
            ]
            await session.flush()

            for resposta in respostas:
                vez_da_s2 = 0
                for pergunta, dimensao in perguntas:
                    if dimensao is None:
                        session.add(
                            Answer(
                                form_response_id=resposta.id,
                                question_id=pergunta.id,
                                value="Texto aberto",
                            )
                        )
                        continue
                    # S2: alternativas 2 e 4 (média 3); o resto, alternativa 5.
                    if dimensao is Dimension.S2:
                        valor = "2" if vez_da_s2 == 0 else "4"
                        vez_da_s2 += 1
                    else:
                        valor = "5"
                    alternativa = alternativas[pergunta.id][valor]
                    session.add(
                        Answer(
                            form_response_id=resposta.id,
                            question_id=pergunta.id,
                            option_id=alternativa.id,
                        )
                    )

        yield sessions, ids
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def test_media_por_pessoa_e_dimensao_so_das_respostas_enviadas(cenario) -> None:  # type: ignore[no-untyped-def]
    sessions, ids = cenario
    async with sessions() as session:
        linhas = await DashboardRepository(session).list_dimension_averages(
            [ids["setembro"], ids["outubro"]]
        )

    # Setembro: as duas pessoas. Outubro: só quem enviou (`marketing` está em
    # andamento). A outra organização não entra: o período dela não foi pedido.
    pessoas = {(linha.form_id, linha.link_id) for linha in linhas}
    assert pessoas == {
        (ids["setembro"], ids["marketing"]),
        (ids["setembro"], ids["sem_setor"]),
        (ids["outubro"], ids["sem_setor"]),
    }
    assert len(linhas) == 3 * len(Dimension)

    s2 = next(
        linha
        for linha in linhas
        if linha.link_id == ids["marketing"] and linha.dimension is Dimension.S2
    )
    assert s2.average == 3.0
    assert all(
        linha.average == 5.0 for linha in linhas if linha.dimension is not Dimension.S2
    )


async def test_linha_traz_o_setor_do_vinculo(cenario) -> None:  # type: ignore[no-untyped-def]
    sessions, ids = cenario
    async with sessions() as session:
        linhas = await DashboardRepository(session).list_dimension_averages(
            [ids["setembro"]]
        )

    setores = {linha.link_id: linha.department for linha in linhas}
    assert setores == {
        ids["marketing"]: DepartmentType.MARKETING,
        ids["sem_setor"]: None,
    }


async def test_com_link_id_so_as_respostas_daquele_vinculo(cenario) -> None:  # type: ignore[no-untyped-def]
    sessions, ids = cenario
    async with sessions() as session:
        linhas = await DashboardRepository(session).list_dimension_averages(
            [ids["setembro"], ids["outubro"]], link_id=ids["sem_setor"]
        )

    assert {linha.link_id for linha in linhas} == {ids["sem_setor"]}
    assert {linha.form_id for linha in linhas} == {ids["setembro"], ids["outubro"]}


async def test_sem_periodos_nao_consulta_e_devolve_vazio(cenario) -> None:  # type: ignore[no-untyped-def]
    sessions, _ = cenario
    async with sessions() as session:
        assert await DashboardRepository(session).list_dimension_averages([]) == []


async def test_periodos_respondidos_do_mais_recente_ao_mais_antigo(cenario) -> None:  # type: ignore[no-untyped-def]
    sessions, ids = cenario
    async with sessions() as session:
        repository = DashboardRepository(session)
        sem_setor = await repository.list_answered_forms(ids["sem_setor"])
        marketing = await repository.list_answered_forms(ids["marketing"])

    assert [form.id for form in sem_setor] == [ids["outubro"], ids["setembro"]]
    # Outubro em andamento não conta como respondido.
    assert [form.id for form in marketing] == [ids["setembro"]]


async def test_periodos_da_empresa_so_os_para_todos_que_ja_abriram(cenario) -> None:  # type: ignore[no-untyped-def]
    sessions, ids = cenario
    async with sessions() as session:
        forms = await DashboardRepository(session).list_company_forms(
            ids["empresa"], AGORA
        )

    # Sem o individual, sem o agendado e sem o da outra organização.
    assert [form.id for form in forms] == [ids["outubro"], ids["setembro"]]


async def test_publico_do_periodo_com_o_setor(cenario) -> None:  # type: ignore[no-untyped-def]
    sessions, ids = cenario
    async with sessions() as session:
        repository = DashboardRepository(session)
        setembro = await repository.list_invited_links(
            await session.get(Form, ids["setembro"])  # type: ignore[arg-type]
        )
        individual = await repository.list_invited_links(
            await session.get(Form, ids["individual"])  # type: ignore[arg-type]
        )

    assert {(c.link_id, c.department) for c in setembro} == {
        (ids["marketing"], DepartmentType.MARKETING),
        (ids["sem_setor"], None),
    }
    # O período individual tem uma pessoa só no público.
    assert [c.link_id for c in individual] == [ids["marketing"]]


async def test_setores_nomes_e_vinculo_da_organizacao(cenario) -> None:  # type: ignore[no-untyped-def]
    sessions, ids = cenario
    async with sessions() as session:
        repository = DashboardRepository(session)
        setores = await repository.list_departments(ids["empresa"])
        nomes = await repository.list_member_names([ids["marketing"], ids["de_fora"]])
        dela = await repository.link_in_organization(ids["marketing"], ids["empresa"])
        de_fora = await repository.link_in_organization(ids["de_fora"], ids["empresa"])

    assert setores == [DepartmentType.MARKETING]
    assert nomes == {
        ids["marketing"]: "Pessoa de teste",
        ids["de_fora"]: "Pessoa de teste",
    }
    assert dela is True
    assert de_fora is False


async def test_retrato_empresas_periodos_e_vinculos_por_tipo(cenario) -> None:  # type: ignore[no-untyped-def]
    sessions, ids = cenario
    async with sessions() as session:
        repository = DashboardRepository(session)
        empresas = await repository.list_companies(exclude_id=ids["outra"])
        abertos = await repository.list_opened_forms([ids["empresa"]], AGORA)
        nenhum = await repository.list_opened_forms([], AGORA)
        emprego = await repository.list_link_ids(ids["empresa"], LinkType.EMPREGO)
        mentoria = await repository.list_link_ids(ids["empresa"], LinkType.MENTORIA)

    # Só a ativa e diferente da excluída.
    assert [empresa_id for empresa_id, _ in empresas] == [ids["empresa"]]
    # Os "para todos" e o individual que já abriram; o agendado fica de fora.
    assert {form.id for form in abertos} == {
        ids["setembro"],
        ids["outubro"],
        ids["individual"],
    }
    assert nenhum == []
    assert set(emprego) == {ids["marketing"], ids["sem_setor"]}
    assert mentoria == []
