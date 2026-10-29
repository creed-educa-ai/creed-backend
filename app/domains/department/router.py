"""Endpoints HTTP do domínio department.

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de models.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.domains.department.dependencies import ServiceDep
from app.domains.department.schemas import DepartmentCreate, DepartmentResponse
from app.shared.authorization import CurrentUserDep, require_role
from app.shared.exceptions import NotFoundError, ValidationError
from app.shared.schemas import ErrorResponse, ValidationErrorResponse

router = APIRouter(prefix="/department", tags=["department"])


@router.post(
    "",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar setor",
    description="Registra um novo setor numa organização já cadastrada na plataforma.",
    response_description="Setor criado na plataforma.",
    operation_id="create_department",
    dependencies=[Depends(require_role("admin"))],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token ausente, inválido ou expirado.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "O usuário autenticado não tem o papel admin.",
        },
        # Dois formatos no mesmo 422, como em `links`: o do service (`detail`
        # texto) e o da validação do Pydantic (`detail` lista).
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse | ValidationErrorResponse,
            "description": (
                "Organização inexistente: `detail` é texto. Corpo inválido: "
                "`detail` é uma lista, um item por campo recusado."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Organização 00000000-0000-0000-0000-000000000001 "
                            "não encontrada"
                        )
                    }
                }
            },
        },
    },
)
async def create_department(
    dados: DepartmentCreate,
    service: ServiceDep,
) -> DepartmentResponse:
    try:
        created = await service.create(dados)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    return DepartmentResponse.de_model(created)


@router.get(
    "/{department_id}",
    response_model=DepartmentResponse,
    summary="Buscar setor",
    description="Busca um setor pelo identificador. Requer autenticação.",
    response_description="Dados do setor encontrado.",
    operation_id="get_department",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token ausente, inválido ou expirado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Não autenticado"},
                },
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Setor não encontrado.",
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ValidationErrorResponse,
            "description": "Identificador fora do formato UUID.",
        },
    },
)
async def get_department(
    department_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador do setor.",
            examples=["00000000-0000-0000-0000-000000000001"],
        ),
    ],
    user: CurrentUserDep,
    service: ServiceDep,
) -> DepartmentResponse:
    try:
        department = await service.get_by_id(department_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc

    return DepartmentResponse.de_model(department)
