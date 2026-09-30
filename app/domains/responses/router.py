"""Endpoints HTTP do domínio respostas (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `FormResponseResponse.de_model()`, em `schemas.py`.

Qualquer papel responde (P-031), então a guarda é só `CurrentUserDep`. O vínculo
de quem responde vem do login, nunca do corpo.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, status

from app.domains.responses.dependencies import ServiceDep
from app.domains.responses.schemas import FormResponseCreate, FormResponseResponse
from app.shared.authorization import CurrentUserDep
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.shared.schemas import ErrorResponse, ValidationErrorResponse

router = APIRouter(prefix="/form-responses", tags=["form-responses"])

_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
}


@router.post(
    "",
    response_model=FormResponseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar resposta de formulário",
    description=(
        "Abre uma resposta em andamento para o formulário, com o vínculo de quem "
        "está logado. Cada vínculo pode abrir somente uma resposta por formulário. "
        "O formulário precisa já existir e ser da organização do vínculo, "
        "qualquer que seja o papel. O corpo leva só `form_id`: um `vinculo_id` "
        "enviado é ignorado, sem erro."
    ),
    response_description="Resposta de formulário criada em andamento.",
    operation_id="create_form_response",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "O formulário é de outra organização.",
            "content": {
                "application/json": {
                    "example": {"detail": "Sem acesso a formulário de outra organização"}
                }
            },
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "O vínculo já possui resposta para este formulário.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Já existe uma resposta para o formulário e vínculo"
                    }
                }
            },
        },
        # Dois formatos no mesmo 422: o do service (`detail` texto) e o da
        # validação do Pydantic (`detail` lista).
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse | ValidationErrorResponse,
            "description": (
                "Formulário inexistente: `detail` é texto. Corpo inválido: "
                "`detail` é uma lista, um item por campo recusado."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Formulário 7d94e9bb-25ca-4df9-9c08-d90251dd8d68 "
                            "não encontrado"
                        )
                    }
                }
            },
        },
    },
)
async def criar_form_response(
    dados: FormResponseCreate, service: ServiceDep, user: CurrentUserDep
) -> FormResponseResponse:
    try:
        form_response = await service.create_form_response(
            dados.form_id,
            link_id=user.link_uuid,
            organization_id=user.organization_uuid,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    return FormResponseResponse.de_model(form_response)


@router.patch(
    "/{form_response_id}",
    response_model=FormResponseResponse,
    summary="Submeter resposta de formulário",
    description=(
        "Finaliza uma resposta em andamento, alterando o status para `submitted` "
        "e registrando a data de submissão. Só o vínculo que abriu a resposta "
        "pode submetê-la."
    ),
    response_description="Resposta finalizada com a data de submissão.",
    operation_id="submit_form_response",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "A resposta de formulário é de outro vínculo.",
            "content": {
                "application/json": {
                    "example": {"detail": "FormResponse pertence a outro vínculo"}
                }
            },
        },
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
    user: CurrentUserDep,
) -> FormResponseResponse:
    try:
        form_response = await service.submit_form_response(
            form_response_id, link_id=user.link_uuid
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    return FormResponseResponse.de_model(form_response)
