"""Endpoints HTTP do domínio sector.

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de models.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.domains.sector.dependencies import ServiceDep
from app.domains.sector.schemas import SectorCreate, SectorResponse
from app.shared.authorization import CurrentUserDep, require_role
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/sectors", tags=["sectors"])


@router.post(
    "",
    response_model=SectorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar setor",
    description="Registra um novo setor na plataforma.",
    response_description="Setor criado na plataforma.",
    operation_id="create_sector",
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
    },
)
async def create_sector(
    dados: SectorCreate,
    service: ServiceDep,
) -> SectorResponse:
    created = await service.create(dados.to_model())
    return SectorResponse.de_model(created)


@router.get(
    "/{sector_id}",
    response_model=SectorResponse,
    summary="Buscar setor",
    description="Busca um setor pelo identificador.",
    response_description="Dados do setor encontrado.",
    operation_id="get_sector",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token ausente, inválido ou expirado.",
            "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Setor não encontrado.",
        },
    },
)
async def get_sector(
    sector_id: Annotated[
        uuid.UUID,
        Path(description="Identificador do setor."),
    ],
    user: CurrentUserDep,
    service: ServiceDep,
) -> SectorResponse:
    sector = await service.get_by_id(sector_id)

    if sector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setor {sector_id} não encontrado",
        )

    return SectorResponse.de_model(sector)
