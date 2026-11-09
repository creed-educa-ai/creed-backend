"""Endpoint HTTP do questionário atual da pessoa logada.

Mora em `responses`, apesar do caminho em `/forms`: a resposta junta formulário e
resposta de formulário, e é `responses` que já compõe com `forms`, não o contrário.

Precisa ser registrado antes do router de `forms` no `main.py`: senão
`/forms/{form_id}` captura "current" e devolve 422.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.domains.responses.dependencies import ServiceDep
from app.domains.responses.schemas import CurrentFormRead
from app.shared.authorization import CurrentUserDep
from app.shared.exceptions import NotFoundError
from app.shared.schemas import ErrorResponse

router = APIRouter(tags=["forms"])

_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Não há questionário aberto para a pessoa logada.",
        "content": {
            "application/json": {
                "example": {"detail": "Nenhum questionário disponível no momento"}
            }
        },
    },
}


@router.get(
    "/forms/current",
    response_model=CurrentFormRead,
    status_code=status.HTTP_200_OK,
    summary="Consultar questionário atual",
    description=(
        "Devolve o questionário aberto agora para a pessoa logada, da organização "
        "do vínculo dela, seja para todos ou só para ela, junto da resposta que "
        "ela tem nele. `form_response` nulo indica que ainda não começou."
    ),
    response_description="Questionário aberto e a resposta da pessoa nele.",
    operation_id="get_current_form",
    responses=_RESPONSES,
)
async def get_current_form(service: ServiceDep, user: CurrentUserDep) -> CurrentFormRead:
    try:
        return await service.get_current(
            link_id=user.link_uuid, organization_id=user.organization_uuid
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
