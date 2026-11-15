"""Endpoints HTTP do domínio dashboards (ADR-002, secao 2.2).

Esta camada é fina: valida entrada via Pydantic/FastAPI, delega ao service
e devolve o schema correspondente.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.domains.dashboards.dependencies import ServiceDep
from app.domains.dashboards.schemas import (
    CompanyDashboardRead,
    OverviewDashboardRead,
    UserDashboardRead,
)
from app.shared.authorization import CurrentUserDep
from app.shared.enums import DepartmentType
from app.shared.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
}


@router.get(
    "/me",
    response_model=UserDashboardRead,
    status_code=status.HTTP_200_OK,
    summary="Consultar o próprio resultado",
    description=(
        "Devolve o resultado de quem está logado num período: os 5 prismas e as 7 "
        "dimensões na escala 0 a 100, e a comparação com os outros períodos que a "
        "pessoa respondeu. Sem `period`, o período respondido mais recente. Os "
        "textos do Creed.ai vêm vazios até a esteira de IA existir. Qualquer papel; "
        "só o resultado do próprio vínculo."
    ),
    response_description="O resultado da pessoa no período.",
    operation_id="get_user_dashboard",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": (
                "A pessoa ainda não enviou nenhum questionário, ou não respondeu o "
                "período pedido."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Você ainda não tem resultado"}
                }
            },
        },
    },
)
async def get_user_dashboard(
    service: ServiceDep,
    user: CurrentUserDep,
    period: Annotated[
        uuid.UUID | None,
        Query(
            description="Período (formulário) a mostrar. Sem ele, o mais recente.",
            examples=["00000000-0000-0000-0003-000000000002"],
        ),
    ] = None,
) -> UserDashboardRead:
    try:
        return await service.get_user_dashboard(user=user, period=period)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc


@router.get(
    "/members/{member_id}",
    response_model=UserDashboardRead,
    status_code=status.HTTP_200_OK,
    summary="Consultar o resultado individual de um mentorando",
    description=(
        "Só da administradora. O mesmo dashboard individual que o mentorando vê: os "
        "5 prismas e as 7 dimensões de 0 a 100 num período, e a comparação com os "
        "outros períodos que ele respondeu. Sem `period`, o mais recente. "
        "`member_name` traz o nome dele."
    ),
    response_description="O resultado do mentorando no período.",
    operation_id="get_member_dashboard",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "Quem pede não é a administradora.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": (
                "O vínculo não é um mentorando da CREED, ele ainda não respondeu, "
                "ou não respondeu o período pedido."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "O mentorando ainda não tem resultado"}
                }
            },
        },
    },
)
async def get_member_dashboard(
    service: ServiceDep,
    user: CurrentUserDep,
    member_id: uuid.UUID,
    period: Annotated[
        uuid.UUID | None,
        Query(description="Período (formulário) a mostrar. Sem ele, o mais recente."),
    ] = None,
) -> UserDashboardRead:
    try:
        return await service.get_member_dashboard(
            user=user, member_id=member_id, period=period
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc


@router.get(
    "/company",
    response_model=CompanyDashboardRead,
    status_code=status.HTTP_200_OK,
    summary="Consultar o dashboard da empresa",
    description=(
        "Devolve o resultado da organização num período: os 5 prismas e as 7 "
        "dimensões de 0 a 100, o resumo executivo, o alinhamento da equipe, o mapa "
        "de setores e todas as comparações. Com `department` ou `member_id`, o "
        "recorte muda a página toda, menos o mapa, que é sempre a organização "
        "inteira. Sem `period`, o período mais recente com resposta. Gestores veem a "
        "própria organização; administradores informam `organization_id`."
    ),
    response_description="O resultado da organização no período e no recorte.",
    operation_id="get_company_dashboard",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "Respondente, ou gestor pedindo outra organização.",
            "content": {
                "application/json": {
                    "example": {"detail": "Sem acesso ao dashboard de outra organização"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": (
                "A organização ainda não tem resultado, o período pedido não tem, ou "
                "o recorte não tem resposta no período."
            ),
            "content": {
                "application/json": {"example": {"detail": "Ainda não há resultados"}}
            },
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": (
                "Setor e pessoa juntos, ou administradora sem `organization_id`."
            ),
        },
    },
)
async def get_company_dashboard(
    service: ServiceDep,
    user: CurrentUserDep,
    period: Annotated[
        uuid.UUID | None,
        Query(description="Período (formulário) a mostrar. Sem ele, o mais recente."),
    ] = None,
    organization_id: Annotated[
        uuid.UUID | None,
        Query(description="Organização a mostrar. Obrigatória para administradores."),
    ] = None,
    department: Annotated[
        DepartmentType | None, Query(description="Recorte por setor.")
    ] = None,
    member_id: Annotated[
        uuid.UUID | None, Query(description="Recorte por pessoa: o id do vínculo.")
    ] = None,
) -> CompanyDashboardRead:
    try:
        return await service.get_company_dashboard(
            user=user,
            organization_id=organization_id,
            period=period,
            department=department,
            member_id=member_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc


@router.get(
    "/overview",
    response_model=OverviewDashboardRead,
    status_code=status.HTTP_200_OK,
    summary="Consultar o retrato atual de todas as empresas ou mentorandos",
    description=(
        "Só da administradora. Cada pessoa entra uma vez, com a resposta mais "
        "recente que enviou, seja qual for o período: as empresas e os mentorandos "
        "respondem a qualquer hora. Com `kind=companies`, todas as empresas ativas, "
        "com a comparação e o mapa por empresa; com `kind=mentees`, os mentorandos "
        "da CREED."
    ),
    response_description="O retrato atual.",
    operation_id="get_dashboard_overview",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "Quem pede não é a administradora.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Ninguém respondeu ainda.",
            "content": {
                "application/json": {"example": {"detail": "Ainda não há resultados"}}
            },
        },
    },
)
async def get_dashboard_overview(
    service: ServiceDep,
    user: CurrentUserDep,
    kind: Annotated[
        Literal["companies", "mentees"],
        Query(description="Todas as empresas, ou todos os mentorandos."),
    ],
) -> OverviewDashboardRead:
    try:
        return await service.get_overview(user=user, kind=kind)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
