"""Endpoints HTTP do domínio respostas (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `FormResponseResponse.de_model()`, em `schemas.py`.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.domains.responses.dependencies import ServiceDep
from app.domains.responses.schemas import FormResponseCreate, FormResponseResponse
from app.shared.exceptions import NotFoundError

router = APIRouter(prefix="/form-responses", tags=["form-responses"])


@router.post("", response_model=FormResponseResponse, status_code=status.HTTP_201_CREATED)
async def criar_form_response(
    dados: FormResponseCreate, service: ServiceDep
) -> FormResponseResponse:
    form_response = await service.create_form_response(
        form_id=dados.form_id, vinculo_id=dados.vinculo_id
    )
    return FormResponseResponse.de_model(form_response)


@router.patch("/{form_response_id}", response_model=FormResponseResponse)
async def submeter_form_response(
    form_response_id: uuid.UUID, service: ServiceDep
) -> FormResponseResponse:
    try:
        form_response = await service.submit_form_response(form_response_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    return FormResponseResponse.de_model(form_response)
