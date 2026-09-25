"""Endpoints HTTP do domínio respostas (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `FormResponseResponse.de_model()`, em `schemas.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from app.domains.responses.dependencies import ServiceDep
from app.domains.responses.schemas import FormResponseCreate, FormResponseResponse
from app.shared.exceptions import ConflictError, NotFoundError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/form-responses", tags=["form-responses"])


@router.post(
    "",
    response_model=FormResponseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar resposta de formulário",
    description=(
        "Abre uma resposta em andamento para a combinação de formulário e vínculo. "
        "Cada vínculo pode abrir somente uma resposta por formulário."
    ),
    response_description="Resposta de formulário criada em andamento.",
    operation_id="create_form_response",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "A combinação de formulário e vínculo já possui resposta.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Já existe uma resposta para o formulário e vínculo"
                    }
                }
            },
        }
    },
)
async def criar_form_response(
    dados: FormResponseCreate, service: ServiceDep
) -> FormResponseResponse:
    try:
        form_response = await service.create_form_response(
            form_id=dados.form_id, vinculo_id=dados.vinculo_id
        )
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    return FormResponseResponse.de_model(form_response)


@router.patch(
    "/{form_response_id}",
    response_model=FormResponseResponse,
    summary="Submeter resposta de formulário",
    description=(
        "Finaliza uma resposta em andamento, alterando o status para `submitted` "
        "e registrando a data de submissão."
    ),
    response_description="Resposta finalizada com a data de submissão.",
    operation_id="submit_form_response",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Resposta de formulário não encontrada.",
            "content": {
                "application/json": {"example": {"detail": "FormResponse não encontrado"}}
            },
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "A resposta já foi submetida.",
            "content": {
                "application/json": {
                    "example": {"detail": "FormResponse já foi submetido"}
                }
            },
        },
    },
)
async def submeter_form_response(
    form_response_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador da resposta que será submetida.",
            examples=["3b1bb89a-471f-48b0-9025-cfda3b20d240"],
        ),
    ],
    service: ServiceDep,
) -> FormResponseResponse:
    try:
        form_response = await service.submit_form_response(form_response_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    return FormResponseResponse.de_model(form_response)
