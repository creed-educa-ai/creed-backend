"""Endpoints HTTP do domínio de User.

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui.
"""

from fastapi import APIRouter, HTTPException, status

from app.domains.users.dependencies import ServiceDep
from app.domains.users.schemas import UserCreate, UserDelete, UserResponse
from app.shared.exceptions import ConflictError

router = APIRouter(prefix="/users", tags=["user"])


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_router(
    data: UserCreate,
    service: ServiceDep,
) -> UserResponse:
    try:
        user = await service.create_user_service(data)
        return UserResponse.model_validate(user)

    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_router(
    data: UserDelete,
    service: ServiceDep,
) -> None:
    try:
        await service.delete_user_service(data)

    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc
