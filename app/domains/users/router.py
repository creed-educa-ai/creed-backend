from fastapi import APIRouter, HTTPException, status

from app.domains.users.dependencies import ServiceDep
from app.domains.users.models import User
from app.domains.users.schemas import UserCreate, UserResponse
from app.shared.exceptions import ConflictError

"""Endpoints HTTP do domínio respondentes (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui.
"""

router = APIRouter(prefix="/user", tags=["auth"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user_router(data: UserCreate, service: ServiceDep) -> User:
    try:
        return await service.create_user_service(data)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
