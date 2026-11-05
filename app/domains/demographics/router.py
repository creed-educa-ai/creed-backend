"""Endpoints do perfil demográfico da pessoa autenticada."""

from fastapi import APIRouter, HTTPException, status

from app.domains.demographics.dependencies import ServiceDep
from app.domains.demographics.schemas import DemographicCreate, DemographicResponse
from app.domains.demographics.service import DemographicProfile
from app.shared.authorization import CurrentUserDep
from app.shared.exceptions import NotFoundError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/demographics", tags=["demographics"])


def _response(profile: DemographicProfile) -> DemographicResponse:
    return DemographicResponse.de_model(
        profile.demographic,
        ethnicities=profile.ethnicities,
        religions=profile.religions,
    )


@router.get(
    "/me",
    response_model=DemographicResponse,
    summary="Consultar meu perfil demográfico",
    description=(
        "Devolve o perfil demográfico ligado ao participante do vínculo da sessão. "
        "Retorna 404 quando a pessoa ainda não concluiu nem pulou o onboarding."
    ),
    response_description="Perfil demográfico da pessoa autenticada.",
    operation_id="get_my_demographics",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_my_demographics(
    current_user: CurrentUserDep, service: ServiceDep
) -> DemographicResponse:
    try:
        return _response(await service.get_my_profile(current_user.link_uuid))
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc


@router.put(
    "/me",
    response_model=DemographicResponse,
    summary="Salvar meu perfil demográfico",
    description=(
        "Cria ou substitui integralmente o perfil da pessoa autenticada. Listas "
        "omitidas ou vazias removem as escolhas anteriores; corpo vazio registra "
        "que o onboarding foi pulado."
    ),
    response_description="Perfil demográfico gravado.",
    operation_id="save_my_demographics",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def save_my_demographics(
    data: DemographicCreate,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> DemographicResponse:
    try:
        return _response(await service.save_my_profile(current_user.link_uuid, data))
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
