"""Endpoints HTTP do domínio dashboards (ADR-002, secao 2.2).

Esta camada é fina: valida entrada via Pydantic/FastAPI, delega ao service
e devolve o schema correspondente.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, status

from app.domains.dashboards.dependencies import ServiceDep
from app.domains.dashboards.schemas import CompanySummaryRead
from app.shared.authorization import CurrentUserDep
from app.shared.exceptions import ForbiddenError, NotFoundError
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
    "/company/{form_id}",
    response_model=CompanySummaryRead,
    status_code=status.HTTP_200_OK,
    summary="Consultar o resumo consolidado do dashboard da empresa",
    description=(
        "Calcula e consolida as métricas da organização para um formulário: "
        "taxa de conclusão, notas dos 5 prismas na escala 1 a 5 e 0 a 100, e "
        "os cards de Destaque, Oportunidade e Mais Comum. "
        "Exige papel gestor da organização dona do formulário ou administrador."
    ),
    response_description="Resumo executivo do dashboard consolidado.",
    operation_id="get_company_dashboard_summary",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "Sem permissão para acessar o dashboard de outra organização.",
            "content": {
                "application/json": {
                    "example": {"detail": "Sem acesso ao dashboard de outra organização"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Formulário não encontrado.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Formulário d40b7a55-b9cc-4b78-ae5d-ab325fd655e2 "
                            "não encontrado"
                        )
                    }
                }
            },
        },
    },
)
async def get_company_dashboard_summary(
    form_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador do formulário da organização.",
            examples=["d40b7a55-b9cc-4b78-ae5d-ab325fd655e2"],
        ),
    ],
    service: ServiceDep,
    user: CurrentUserDep,
) -> CompanySummaryRead:
    try:
        return await service.calculate_company_summary(form_id, user=user)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
