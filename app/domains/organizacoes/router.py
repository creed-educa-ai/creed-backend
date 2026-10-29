"""Endpoints HTTP do domínio organizacoes (ADR-0004).

Camada fina: recebe, valida via Pydantic, delega ao service e devolve. Nenhuma
regra de negócio aqui, e nenhum import de `models` — a montagem da resposta é
`OrganizationResponse.de_model()`, em `schemas.py`.

A guarda decide o papel: `admin` em todas as rotas, `gestor` só na consulta por
id. Que o `gestor` só vê a própria organização é regra do service, que recebe de
quem pede o papel e a organização do vínculo — a mesma divisão de `forms`.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.domains.organizacoes.dependencies import ServiceDep
from app.domains.organizacoes.schemas import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.shared.authorization import AuthenticatedUser, require_role
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.shared.paginacao import PaginaDe
from app.shared.schemas import ErrorResponse, ValidationErrorResponse

router = APIRouter(prefix="/organizacoes", tags=["organizacoes"])

LeitorDep = Annotated[AuthenticatedUser, Depends(require_role("admin", "gestor"))]

OrganizationIdPath = Annotated[
    uuid.UUID,
    Path(
        description="Identificador da organização.",
        examples=["5a1e9c3b-2f7d-4b8a-9e6c-0d4f1b2a3c5e"],
    ),
]

_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
}


def _forbidden(description: str, detail: str) -> dict[int | str, dict[str, Any]]:
    return {
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": description,
            "content": {"application/json": {"example": {"detail": detail}}},
        },
    }


_SO_ADMIN = _forbidden(
    "O usuário autenticado não tem o papel admin.", "Cargo insuficiente para acessar"
)

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Organização não encontrada.",
        "content": {
            "application/json": {
                "example": {
                    "detail": (
                        "Organização 5a1e9c3b-2f7d-4b8a-9e6c-0d4f1b2a3c5e não encontrada"
                    )
                }
            }
        },
    },
}


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("admin"))],
    summary="Cadastrar organização",
    description=(
        "Cadastra uma organização parceira. Ela nasce ativa. O documento precisa "
        "já existir e não pode estar ligado a outra organização. Exige o papel admin."
    ),
    response_description="Organização cadastrada.",
    operation_id="create_organization",
    responses={
        **_UNAUTHORIZED,
        **_SO_ADMIN,
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "O documento informado já pertence a outra organização.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "O documento 3b2f8c1a-6d4e-4f7a-9c5b-1e0d2a8f6b94 "
                            "já pertence a outra organização"
                        )
                    }
                }
            },
        },
        # Dois formatos no mesmo 422: o do service (`detail` texto) e o da
        # validação do Pydantic (`detail` lista).
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse | ValidationErrorResponse,
            "description": (
                "Documento inexistente: `detail` é texto. "
                "Nome ou endereço inválido, ou `document_id` malformado: `detail` é "
                "uma lista, um item por campo recusado."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Documento 3b2f8c1a-6d4e-4f7a-9c5b-1e0d2a8f6b94 "
                            "não encontrado"
                        )
                    }
                }
            },
        },
    },
)
async def create_organization(
    dados: OrganizationCreate, service: ServiceDep
) -> OrganizationResponse:
    try:
        return OrganizationResponse.de_model(await service.create(dados))
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.get(
    "",
    response_model=PaginaDe[OrganizationResponse],
    dependencies=[Depends(require_role("admin"))],
    summary="Listar organizações",
    description="Lista as organizações, paginado. Exige o papel admin.",
    response_description="Uma página de organizações e o total.",
    operation_id="list_organizations",
    responses={**_UNAUTHORIZED, **_SO_ADMIN},
)
async def list_organizations(
    service: ServiceDep,
    pagina: Annotated[int, Query(ge=1, description="Página, começando em 1.")] = 1,
    tamanho_pagina: Annotated[
        int, Query(ge=1, le=200, description="Itens por página.")
    ] = 50,
) -> PaginaDe[OrganizationResponse]:
    itens, total = await service.list_page(pagina, tamanho_pagina)
    return PaginaDe[OrganizationResponse](
        itens=[OrganizationResponse.de_model(item) for item in itens],
        total=total,
        pagina=pagina,
        tamanho_pagina=tamanho_pagina,
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
    summary="Consultar organização",
    description=(
        "Consulta uma organização pelo identificador. O admin consulta qualquer "
        "uma; o gestor, só a do próprio vínculo."
    ),
    response_description="Organização encontrada.",
    operation_id="get_organization",
    responses={
        **_UNAUTHORIZED,
        **_forbidden(
            "Papel sem permissão, ou gestor consultando outra organização.",
            "Sem acesso a organização de outro vínculo",
        ),
        **_NOT_FOUND,
    },
)
async def get_organization(
    organization_id: OrganizationIdPath, service: ServiceDep, user: LeitorDep
) -> OrganizationResponse:
    try:
        organization = await service.get(
            organization_id,
            role=user.role,
            own_organization_id=user.organization_uuid,
        )
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    return OrganizationResponse.de_model(organization)


@router.patch(
    "/{organization_id}",
    response_model=OrganizationResponse,
    dependencies=[Depends(require_role("admin"))],
    summary="Alterar organização",
    description=(
        "Altera nome, endereço ou status de uma organização. Só os campos "
        "enviados mudam. Exige o papel admin."
    ),
    response_description="Organização alterada.",
    operation_id="update_organization",
    responses={**_UNAUTHORIZED, **_SO_ADMIN, **_NOT_FOUND},
)
async def update_organization(
    organization_id: OrganizationIdPath,
    dados: OrganizationUpdate,
    service: ServiceDep,
) -> OrganizationResponse:
    try:
        return OrganizationResponse.de_model(await service.update(organization_id, dados))
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
