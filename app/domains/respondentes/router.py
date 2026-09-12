"""Endpoints HTTP do domínio respondentes (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `RespondenteResponse.de_model()`, em `schemas.py`.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.domains.respondentes.dependencies import ServiceDep
from app.domains.respondentes.schemas import (
    RespondenteCreate,
    RespondenteResponse,
    RespondenteUpdate,
)
from app.shared.exceptions import ConflictError, NotFoundError
from app.shared.paginacao import PaginaDe

router = APIRouter(prefix="/respondentes", tags=["respondentes"])


@router.get("", response_model=PaginaDe[RespondenteResponse])
async def listar_respondentes(
    service: ServiceDep,
    pagina: int = Query(default=1, ge=1),
    tamanho_pagina: int = Query(default=50, ge=1, le=200),
    pais: str | None = Query(default=None, min_length=2, max_length=2),
    regiao: str | None = Query(default=None),
) -> PaginaDe[RespondenteResponse]:
    itens, total = await service.listar(
        pagina=pagina, tamanho_pagina=tamanho_pagina, pais=pais, regiao=regiao
    )
    return PaginaDe[RespondenteResponse](
        itens=[RespondenteResponse.de_model(item) for item in itens],
        total=total,
        pagina=pagina,
        tamanho_pagina=tamanho_pagina,
    )


@router.get("/{respondente_id}", response_model=RespondenteResponse)
async def obter_respondente(
    respondente_id: uuid.UUID, service: ServiceDep
) -> RespondenteResponse:
    try:
        return RespondenteResponse.de_model(await service.obter(respondente_id))
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc


@router.post("", response_model=RespondenteResponse, status_code=status.HTTP_201_CREATED)
async def criar_respondente(
    dados: RespondenteCreate, service: ServiceDep
) -> RespondenteResponse:
    try:
        return RespondenteResponse.de_model(await service.criar(dados))
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.patch("/{respondente_id}", response_model=RespondenteResponse)
async def atualizar_respondente(
    respondente_id: uuid.UUID, dados: RespondenteUpdate, service: ServiceDep
) -> RespondenteResponse:
    try:
        return RespondenteResponse.de_model(
            await service.atualizar(respondente_id, dados)
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.delete("/{respondente_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_respondente(respondente_id: uuid.UUID, service: ServiceDep) -> None:
    try:
        await service.remover(respondente_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
