"""Testes do serviço do domínio prismas."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domains.forms.models import Form, FormStatus
from app.domains.prismas.service import PrismaService
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
