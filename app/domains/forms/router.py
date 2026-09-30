"""Endpoints HTTP do domínio forms (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `FormRead.de_model()`, em `schemas.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from app.domains.forms.dependencies import ServiceDep
from app.domains.forms.schemas import FormCreate, FormRead
from app.shared.exceptions import NotFoundError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/forms", tags=["forms"])


@router.post(
    "",
    response_model=FormRead,
    status_code=status.HTTP_201_CREATED,
    summary="Criar formulário",
    description="Cria um formulário. O estado inicial é sempre rascunho.",
    response_description="Formulário criado, em rascunho.",
    operation_id="create_form",
)
async def create_form(dados: FormCreate, service: ServiceDep) -> FormRead:
    return FormRead.de_model(await service.create(dados))


@router.get(
    "/{form_id}",
    response_model=FormRead,
    status_code=status.HTTP_200_OK,
    summary="Consultar formulário",
    description="Consulta um formulário pelo identificador.",
    response_description="Formulário encontrado.",
    operation_id="get_form",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Formulário não encontrado.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Formulário d40b7a55-b9cc-4b78-ae5d-ab325fd655e2 "
                            "não encontrado"
                        )
                    }
                }
            },
        }
    },
)
async def get_form(
    form_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador do formulário.",
            examples=["d40b7a55-b9cc-4b78-ae5d-ab325fd655e2"],
        ),
    ],
    service: ServiceDep,
) -> FormRead:
    try:
        return FormRead.de_model(await service.get(form_id))
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
