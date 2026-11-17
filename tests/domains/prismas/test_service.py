"""Testes do serviço do domínio prismas."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domains.forms.models import Form, FormStatus
from app.domains.prismas.service import PrismaService, highest_and_lowest
from app.domains.responses.models import FormResponse, FormResponseStatus
from app.shared.authorization import AuthenticatedUser
from app.shared.enums import Dimension, Prisma
from app.shared.exceptions import ForbiddenError, NotFoundError, ValidationError


@pytest.fixture
def fake_user() -> AuthenticatedUser:
    link_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    return AuthenticatedUser(
        sub=str(uuid.uuid4()),
        email="dev@creed.ai",
        roles=["respondente"],
        link_id=link_id,
        organization_id=org_id,
    )


@pytest.fixture
def fake_admin() -> AuthenticatedUser:
    return AuthenticatedUser(
        sub=str(uuid.uuid4()),
        email="admin@creed.ai",
        roles=["admin"],
        link_id=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
    )


@pytest.mark.asyncio
async def test_calculate_raises_not_found_when_form_response_missing(
    fake_user: AuthenticatedUser,
) -> None:
    repo = AsyncMock()
    repo.get_form_response.return_value = None
    service = PrismaService(repo)

    with pytest.raises(NotFoundError, match="não encontrada"):
        await service.calculate_for_form_response(uuid.uuid4(), user=fake_user)


@pytest.mark.asyncio
async def test_calculate_raises_forbidden_for_other_user(
    fake_user: AuthenticatedUser,
) -> None:
    repo = AsyncMock()
    resp_id = uuid.uuid4()
    form_id = uuid.uuid4()
    other_link = uuid.uuid4()

    repo.get_form_response.return_value = FormResponse(
        id=resp_id,
        form_id=form_id,
        vinculo_id=other_link,
        status=FormResponseStatus.SUBMITTED,
    )
    repo.get_form.return_value = Form(
        id=form_id,
        name="Teste",
        organization_id=fake_user.organization_uuid,
        status=FormStatus.PUBLISHED,
    )

    service = PrismaService(repo)
    with pytest.raises(ForbiddenError, match="Sem acesso"):
        await service.calculate_for_form_response(resp_id, user=fake_user)


@pytest.mark.asyncio
async def test_calculate_raises_validation_error_when_not_submitted(
    fake_user: AuthenticatedUser,
) -> None:
    repo = AsyncMock()
    resp_id = uuid.uuid4()
    form_id = uuid.uuid4()

    repo.get_form_response.return_value = FormResponse(
        id=resp_id,
        form_id=form_id,
        vinculo_id=fake_user.link_uuid,
        status=FormResponseStatus.IN_PROGRESS,
    )
    repo.get_form.return_value = Form(
        id=form_id,
        name="Teste",
        organization_id=fake_user.organization_uuid,
        status=FormStatus.PUBLISHED,
    )

    service = PrismaService(repo)
    with pytest.raises(ValidationError, match="finalizado"):
        await service.calculate_for_form_response(resp_id, user=fake_user)


@pytest.mark.asyncio
async def test_calculate_success_returns_all_prisms(
    fake_user: AuthenticatedUser,
) -> None:
    repo = AsyncMock()
    resp_id = uuid.uuid4()
    form_id = uuid.uuid4()

    repo.get_form_response.return_value = FormResponse(
        id=resp_id,
        form_id=form_id,
        vinculo_id=fake_user.link_uuid,
        status=FormResponseStatus.SUBMITTED,
    )
    repo.get_form.return_value = Form(
        id=form_id,
        name="Teste",
        organization_id=fake_user.organization_uuid,
        status=FormStatus.PUBLISHED,
    )

    # 4.0 em todas as 7 dimensões
    answers = [(dim, 4.0) for dim in Dimension]
    repo.get_answers_with_dimensions.return_value = answers

    service = PrismaService(repo)
    result = await service.calculate_for_form_response(resp_id, user=fake_user)

    assert result.form_response_id == resp_id
    assert result.form_id == form_id
    assert result.vinculo_id == fake_user.link_uuid
    assert len(result.scores) == 5
    assert result.scores[Prisma.SEGURANCA_PSICOLOGICA.value] == 4.0
    # (4 - 1) / 4 * 100: a escala vai de 0 (média 1) a 100 (média 5).
    assert result.scores_100[Prisma.SEGURANCA_PSICOLOGICA.value] == 75.0
    assert result.dimensions[Dimension.S2.value] == 4.0


def test_scores_from_dimension_averages_usa_a_escala_0_a_100() -> None:
    averages = dict.fromkeys(Dimension, 3.0) | {Dimension.S6: 5.0, Dimension.S7: 1.0}

    prismas, dimensions = PrismaService(AsyncMock()).scores_from_dimension_averages(
        averages
    )

    assert set(prismas) == set(Prisma)
    # SP = média de S6 e S7 = 3, que é o meio da escala.
    assert prismas[Prisma.SEGURANCA_PSICOLOGICA] == 50.0
    assert dimensions[Dimension.S6] == 100.0
    assert dimensions[Dimension.S7] == 0.0


# --- Destaque e oportunidade: a regra que o dashboard e o insight dividem -------


def test_destaque_e_oportunidade_sao_o_maior_e_o_menor_prisma() -> None:
    notas = dict.fromkeys(Prisma, 50.0) | {
        Prisma.CULTURA_EMPREENDEDORA: 90.0,
        Prisma.ADAPTABILIDADE_COGNITIVA: 10.0,
    }

    destaque, oportunidade = highest_and_lowest(notas)

    assert destaque is Prisma.CULTURA_EMPREENDEDORA
    assert oportunidade is Prisma.ADAPTABILIDADE_COGNITIVA


def test_empate_em_destaque_e_oportunidade_segue_a_ordem_dos_prismas() -> None:
    destaque, oportunidade = highest_and_lowest(dict.fromkeys(Prisma, 50.0))

    assert destaque is Prisma.SEGURANCA_PSICOLOGICA
    assert oportunidade is Prisma.SEGURANCA_PSICOLOGICA


# --- O cálculo do pedido de insight: sem usuário (CREED-803) ----------------------


def _resposta(status: FormResponseStatus) -> FormResponse:
    return FormResponse(
        id=uuid.uuid4(), form_id=uuid.uuid4(), vinculo_id=uuid.uuid4(), status=status
    )


@pytest.mark.asyncio
async def test_calculo_do_pedido_dispensa_usuario_e_usa_a_escala_0_a_100() -> None:
    repo = AsyncMock()
    resposta = _resposta(FormResponseStatus.SUBMITTED)
    repo.get_form_response.return_value = resposta
    # 4 em todas as dimensões, menos S6 e S7, que entram na segurança psicológica.
    repo.get_answers_with_dimensions.return_value = [
        (dim, 4.0) for dim in Dimension if dim not in (Dimension.S6, Dimension.S7)
    ] + [(Dimension.S6, 5.0), (Dimension.S7, 5.0)]

    prismas, dimensions = await PrismaService(repo).calculate_for_dispatch(resposta.id)

    assert set(prismas) == set(Prisma)
    assert set(dimensions) == set(Dimension)
    assert prismas[Prisma.SEGURANCA_PSICOLOGICA] == 100.0
    assert dimensions[Dimension.S2] == 75.0
    # Sem guarda de acesso: nem o formulário é lido para conferir a organização.
    repo.get_form.assert_not_awaited()


@pytest.mark.asyncio
async def test_calculo_do_pedido_e_o_mesmo_da_tela() -> None:
    """As notas do texto têm que ser as do dashboard para as mesmas respostas."""
    repo = AsyncMock()
    resposta = _resposta(FormResponseStatus.SUBMITTED)
    repo.get_form_response.return_value = resposta
    respostas = [(dim, 2.0) for dim in Dimension] + [(dim, 5.0) for dim in Dimension]
    repo.get_answers_with_dimensions.return_value = respostas
    service = PrismaService(repo)

    do_pedido = await service.calculate_for_dispatch(resposta.id)

    assert do_pedido == service.scores_from_dimension_averages(
        dict.fromkeys(Dimension, 3.5)
    )


@pytest.mark.asyncio
async def test_calculo_do_pedido_de_resposta_inexistente_e_not_found() -> None:
    repo = AsyncMock()
    repo.get_form_response.return_value = None

    with pytest.raises(NotFoundError, match="não encontrada"):
        await PrismaService(repo).calculate_for_dispatch(uuid.uuid4())


@pytest.mark.asyncio
async def test_calculo_do_pedido_de_resposta_em_andamento_e_recusado() -> None:
    repo = AsyncMock()
    repo.get_form_response.return_value = _resposta(FormResponseStatus.IN_PROGRESS)

    with pytest.raises(ValidationError, match="finalizado"):
        await PrismaService(repo).calculate_for_dispatch(uuid.uuid4())

    repo.get_answers_with_dimensions.assert_not_awaited()


@pytest.mark.asyncio
async def test_calculo_do_pedido_sem_resposta_objetiva_e_recusado() -> None:
    repo = AsyncMock()
    repo.get_form_response.return_value = _resposta(FormResponseStatus.SUBMITTED)
    repo.get_answers_with_dimensions.return_value = []

    with pytest.raises(ValidationError, match="Nenhuma resposta objetiva"):
        await PrismaService(repo).calculate_for_dispatch(uuid.uuid4())


@pytest.mark.asyncio
async def test_calculo_do_pedido_com_dimensao_faltando_e_recusado() -> None:
    """Sem uma das sete, não há prisma: o pedido não sai com nota inventada."""
    repo = AsyncMock()
    repo.get_form_response.return_value = _resposta(FormResponseStatus.SUBMITTED)
    repo.get_answers_with_dimensions.return_value = [
        (dim, 4.0) for dim in Dimension if dim is not Dimension.S8
    ]

    with pytest.raises(ValidationError, match="S8"):
        await PrismaService(repo).calculate_for_dispatch(uuid.uuid4())
