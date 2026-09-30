"""Endpoints HTTP do domínio questions (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de
`models` — o tipo da seção vem de `schemas.py` (tests/test_arquitetura.py
reprova rota que importe de models.py).

Sem prefixo próprio: os dois endereços não compartilham um caminho comum
(`/questions` e `/forms/{form_id}/questions`), então cada rota escreve o
caminho inteiro. O prefixo `/api/v1` vem da configuração central, no
registro em app/main.py.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.domains.questions.dependencies import ServiceDep
from app.domains.questions.schemas import (
    QuestionCreate,
    QuestionResponse,
    QuestionSection,
)
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError
from app.shared.schemas import ErrorResponse, ValidationErrorResponse

router = APIRouter(tags=["questions"])


@router.post(
    "/questions",
    response_model=QuestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar pergunta",
    description=(
        "Cadastra uma pergunta num formulário, na seção e posição informadas. "
        "O formulário precisa já existir."
    ),
    response_description="Pergunta criada.",
    operation_id="create_question",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Já existe pergunta na mesma posição do formulário.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Já existe pergunta na posição 0 "
                            "do formulário 00000000-0000-0000-0000-000000000001"
                        )
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
                            "Formulário 00000000-0000-0000-0000-000000000001 "
                            "não encontrado"
                        )
                    }
                }
            },
        },
    },
)
async def create_question(dados: QuestionCreate, service: ServiceDep) -> QuestionResponse:
    try:
        return QuestionResponse.de_model(await service.create(dados))
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.get(
    "/forms/{form_id}/questions",
    response_model=list[QuestionResponse],
    summary="Listar perguntas de um formulário",
    description=(
        "Lista as perguntas de um formulário em ordem de posição, com filtro "
        "opcional por seção. Formulário sem pergunta nenhuma devolve lista vazia; "
        "formulário inexistente devolve 404."
    ),
    response_description="Perguntas do formulário, na seção pedida quando houver filtro.",
    operation_id="list_questions",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Formulário não encontrado.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Formulário 00000000-0000-0000-0000-000000000001 "
                            "não encontrado"
                        )
                    }
                }
            },
        }
    },
)
async def list_questions(
    form_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador do formulário cujas perguntas serão listadas.",
            examples=["00000000-0000-0000-0000-000000000001"],
        ),
    ],
    service: ServiceDep,
    section: Annotated[
        QuestionSection | None,
        Query(
            description="Filtra as perguntas por seção do formulário.",
            examples=["assessment"],
        ),
    ] = None,
) -> list[QuestionResponse]:
    try:
        questions = await service.list_for_form(form_id, section)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    return [QuestionResponse.de_model(question) for question in questions]
