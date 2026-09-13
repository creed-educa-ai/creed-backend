"""Endpoints HTTP do domínio users (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `UserResponse.de_model()`, em `schemas.py`.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.domains.users.dependencies import ServiceDep
from app.domains.users.schemas import UserCreate, UserResponse
from app.shared.exceptions import ConflictError, NotFoundError

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(dados: UserCreate, service: ServiceDep) -> UserResponse:
    try:
        return UserResponse.de_model(await service.create_user_service(dados))
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, service: ServiceDep) -> None:
    try:
        await service.delete_user_service(user_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
