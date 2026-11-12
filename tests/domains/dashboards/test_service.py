"""Testes do serviço do domínio dashboards."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domains.dashboards.models import Dashboard
from app.domains.dashboards.repository import DashboardRepository
from app.domains.dashboards.schemas import DashboardCreate
from app.domains.dashboards.service import DashboardService
from app.domains.forms.models import Form, FormStatus
from app.domains.prismas.schemas import FormResponsePrismasRead
from app.shared.authorization import AuthenticatedUser
from app.shared.enums import Dimension, Prisma
from app.shared.exceptions import ForbiddenError, NotFoundError


@pytest.fixture
def fake_gestor() -> AuthenticatedUser:
    org_id = str(uuid.uuid4())
    return AuthenticatedUser(
        sub=str(uuid.uuid4()),
        email="gestor@empresa.com",
        roles=["gestor"],
        link_id=str(uuid.uuid4()),
        organization_id=org_id,
    )


@pytest.mark.asyncio
async def test_summary_raises_not_found_when_form_missing(
    fake_gestor: AuthenticatedUser,
) -> None:
    repo = AsyncMock()
    repo.get_form.return_value = None
    prismas_service = AsyncMock()

    service = DashboardService(repo, prismas_service)
    with pytest.raises(NotFoundError, match="não encontrado"):
        await service.calculate_company_summary(uuid.uuid4(), user=fake_gestor)


@pytest.mark.asyncio
async def test_summary_raises_forbidden_for_other_org(
    fake_gestor: AuthenticatedUser,
) -> None:
    repo = AsyncMock()
    form_id = uuid.uuid4()
    repo.get_form.return_value = Form(
        id=form_id,
        name="Teste",
        organization_id=uuid.uuid4(),  # Outra organização
        status=FormStatus.PUBLISHED,
    )
    prismas_service = AsyncMock()

    service = DashboardService(repo, prismas_service)
    with pytest.raises(ForbiddenError, match="Sem acesso"):
        await service.calculate_company_summary(form_id, user=fake_gestor)


@pytest.mark.asyncio
async def test_summary_empty_when_no_submissions(
    fake_gestor: AuthenticatedUser,
) -> None:
    repo = AsyncMock()
    form_id = uuid.uuid4()
    repo.get_form.return_value = Form(
        id=form_id,
        name="Teste",
        organization_id=fake_gestor.organization_uuid,
        status=FormStatus.PUBLISHED,
    )
    repo.get_organization_name.return_value = "Empresa XPTO"
    repo.count_organization_members.return_value = 10
    repo.get_submitted_form_response_ids.return_value = []

    prismas_service = AsyncMock()
    service = DashboardService(repo, prismas_service)

    result = await service.calculate_company_summary(form_id, user=fake_gestor)
    assert result.form_id == form_id
    assert result.nome_empresa == "Empresa XPTO"
    assert result.concluidos == 0
    assert result.convidados == 10
    assert result.taxa_conclusao == 0
    assert result.destaque.rotulo == "Sem dados"


@pytest.mark.asyncio
async def test_summary_calculates_aggregated_and_cards(
    fake_gestor: AuthenticatedUser,
) -> None:
    repo = AsyncMock()
    form_id = uuid.uuid4()
    repo.get_form.return_value = Form(
        id=form_id,
        name="Teste",
        organization_id=fake_gestor.organization_uuid,
        status=FormStatus.PUBLISHED,
    )
    repo.get_organization_name.return_value = "Empresa XPTO"
    repo.count_organization_members.return_value = 2

    resp_1 = uuid.uuid4()
    resp_2 = uuid.uuid4()
    repo.get_submitted_form_response_ids.return_value = [resp_1, resp_2]

    prismas_service = AsyncMock()
    prismas_service.repository.get_answers_with_dimensions.return_value = [
        (Dimension.S2, 4.0)
    ]

    # Mock das respostas calculadas
    prismas_service.calculate_for_form_response = AsyncMock(
        side_effect=[
            FormResponsePrismasRead(
                form_response_id=resp_1,
                form_id=form_id,
                vinculo_id=fake_gestor.link_uuid,
                scores={
                    Prisma.SEGURANCA_PSICOLOGICA.value: 4.5,
                    Prisma.LIDERANCA_ADAPTATIVA.value: 3.5,
                    Prisma.CULTURA_EMPREENDEDORA.value: 4.0,
                    Prisma.ADAPTABILIDADE_COGNITIVA.value: 3.0,
                    Prisma.NEUROINOVACAO_PRISMA.value: 3.8,
                },
                scores_100={
                    Prisma.SEGURANCA_PSICOLOGICA.value: 90.0,
                    Prisma.LIDERANCA_ADAPTATIVA.value: 70.0,
                    Prisma.CULTURA_EMPREENDEDORA.value: 80.0,
                    Prisma.ADAPTABILIDADE_COGNITIVA.value: 60.0,
                    Prisma.NEUROINOVACAO_PRISMA.value: 76.0,
                },
                dimensions={},
            ),
            FormResponsePrismasRead(
                form_response_id=resp_2,
                form_id=form_id,
                vinculo_id=fake_gestor.link_uuid,
                scores={
                    Prisma.SEGURANCA_PSICOLOGICA.value: 4.5,
                    Prisma.LIDERANCA_ADAPTATIVA.value: 3.5,
                    Prisma.CULTURA_EMPREENDEDORA.value: 4.0,
                    Prisma.ADAPTABILIDADE_COGNITIVA.value: 3.0,
                    Prisma.NEUROINOVACAO_PRISMA.value: 3.8,
                },
                scores_100={
                    Prisma.SEGURANCA_PSICOLOGICA.value: 90.0,
                    Prisma.LIDERANCA_ADAPTATIVA.value: 70.0,
                    Prisma.CULTURA_EMPREENDEDORA.value: 80.0,
                    Prisma.ADAPTABILIDADE_COGNITIVA.value: 60.0,
                    Prisma.NEUROINOVACAO_PRISMA.value: 76.0,
                },
                dimensions={},
            ),
        ]
    )

    service = DashboardService(repo, prismas_service)
    result = await service.calculate_company_summary(form_id, user=fake_gestor)

    assert result.concluidos == 2
    assert result.convidados == 2
    assert result.taxa_conclusao == 100
    assert result.destaque.rotulo == "Destaque"
    assert result.destaque.prisma == Prisma.SEGURANCA_PSICOLOGICA
    assert result.destaque.valor == 90.0
    assert result.oportunidade.rotulo == "Oportunidade"
    assert result.oportunidade.prisma == Prisma.ADAPTABILIDADE_COGNITIVA
    assert result.oportunidade.valor == 60.0


@pytest.mark.asyncio
async def test_criar_dashboard() -> None:
    repository = AsyncMock(spec=DashboardRepository)
    repository.create.side_effect = lambda dashboard: dashboard
    service = DashboardService(repository)

    request = DashboardCreate(
        user_id=uuid.uuid4(),
        form_id=uuid.uuid4(),
        is_private=True,
    )

    resultado = await service.create(request)

    repository.create.assert_awaited_once()
    dashboard_enviado = repository.create.await_args.args[0]

    assert isinstance(dashboard_enviado, Dashboard)
    assert dashboard_enviado.user_id == request.user_id
    assert dashboard_enviado.form_id == request.form_id
    assert dashboard_enviado.is_private is True
    assert resultado is dashboard_enviado


@pytest.mark.asyncio
async def test_dashboard_nao_encontrado_lanca_not_found_error() -> None:
    repository = AsyncMock(spec=DashboardRepository)
    repository.get_by_id.return_value = None
    service = DashboardService(repository)

    dashboard_id = uuid.uuid4()

    with pytest.raises(NotFoundError):
        await service.get(dashboard_id)

    repository.get_by_id.assert_awaited_once_with(dashboard_id)
