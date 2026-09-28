"""Endpoints HTTP do domínio users (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `UserResponse.de_model()`, em `schemas.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from app.domains.users.dependencies import ServiceDep
from app.domains.users.schemas import UserCreate, UserResponse
from app.shared.exceptions import ConflictError, NotFoundError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar usuário",
    description=(
        "Registra na plataforma um usuário já provisionado no Keycloak. "
        "O status inicial é ativo e o papel inicial é respondente."
    ),
    response_description="Usuário criado na plataforma.",
    operation_id="create_user",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Já existe um usuário com o e-mail informado.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Já existe usuário com o e-mail pessoa@exemplo.com"
                    }
                }
            },
        }
    },
)
async def create_user(dados: UserCreate, service: ServiceDep) -> UserResponse:
    try:
        return UserResponse.de_model(await service.create_user_service(dados))
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover usuário",
    description="Remove definitivamente um usuário da plataforma pelo identificador.",
    response_description="Usuário removido; a resposta não possui corpo.",
    operation_id="delete_user",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Usuário não encontrado.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Usuário d40b7a55-b9cc-4b78-ae5d-ab325fd655e2 não encontrado"
                        )
                    }
                }
            },
        }
    },
)
async def delete_user(
    user_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador do usuário que será removido.",
            examples=["d40b7a55-b9cc-4b78-ae5d-ab325fd655e2"],
        ),
    ],
    service: ServiceDep,
) -> None:
    try:
        await service.delete_user_service(user_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
