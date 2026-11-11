"""Endpoints HTTP dos períodos de uma organização.

Período é um formulário com datas, então mora em `forms`. Fica fora do `router.py`
porque o caminho não começa em `/forms`.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.domains.forms.dependencies import ServiceDep
from app.domains.forms.schemas import FormRead, PeriodCreate, PeriodRead
from app.shared.authorization import AuthenticatedUser, require_role
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/organizations/{organization_id}/periods", tags=["forms"])

EditorDep = Annotated[AuthenticatedUser, Depends(require_role("admin", "gestor"))]

_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "Papel sem permissão, organização que não é a do vínculo, ou gestor "
            "consultando os períodos de uma pessoa."
        ),
        "content": {
            "application/json": {
                "example": {"detail": "Sem acesso a formulário de outra organização"}
            }
        },
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Organização não encontrada.",
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "Já existe período sobreposto para o mesmo público.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "Datas inválidas ou vínculo fora da organização.",
    },
}


@router.post(
    "",
    response_model=FormRead,
    status_code=status.HTTP_201_CREATED,
    summary="Criar período",
    description=(
        "Cria um questionário com período para a organização ou para um mentorando. "
        "Gestores criam para a organização; admins informam `link_id` para criar "
        "para um mentorando."
    ),
    operation_id="create_period",
    responses=_RESPONSES,
)
async def create_period(
    dados: PeriodCreate,
    organization_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador da organização.",
            examples=["e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339"],
        ),
    ],
    service: ServiceDep,
    user: EditorDep,
) -> FormRead:
    try:
        form = await service.create_period(
            target_organization_id=organization_id,
            request=dados,
            role=user.role,
            organization_id_user=user.organization_uuid,
        )
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    return FormRead.de_model(form)


@router.get(
    "",
    response_model=list[PeriodRead],
    status_code=status.HTTP_200_OK,
    summary="Listar períodos",
    description=(
        "Lista os períodos da organização do vínculo de quem pede, do mais recente "
        'ao mais antigo. Sem `link_id`, os períodos "para todos"; com `link_id`, '
        "os daquela pessoa, o que é exclusivo do admin. `period_status` diz se o "
        "período já passou, está aberto ou está agendado."
    ),
    response_description="Períodos encontrados; lista vazia se não houver nenhum.",
    operation_id="list_periods",
    responses=_RESPONSES,
)
async def list_periods(
    organization_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador da organização.",
            examples=["e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339"],
        ),
    ],
    service: ServiceDep,
    user: EditorDep,
    link_id: Annotated[
        uuid.UUID | None,
        Query(description="Vínculo da pessoa cujos períodos serão listados."),
    ] = None,
) -> list[PeriodRead]:
    try:
        return await service.list_periods(
            organization_id,
            link_id=link_id,
            role=user.role,
            organization_id=user.organization_uuid,
        )
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
