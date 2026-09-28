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

from fastapi import APIRouter, HTTPException, status

from app.domains.questions.dependencies import ServiceDep
from app.domains.questions.schemas import (
    QuestionCreate,
    QuestionResponse,
    QuestionSection,
)
from app.shared.exceptions import ConflictError
from app.shared.schemas import ErrorResponse

router = APIRouter(tags=["questions"])


@router.post(
    "/questions",
    response_model=QuestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar pergunta",
    description=(
        "Cadastra uma pergunta num formulário, na seção e posição informadas. "
        "Não confere se o formulário existe."
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
                            "Ja existe pergunta na posicao 0 "
                            "do formulario 00000000-0000-0000-0000-000000000001"
                        )
                    }
                }
            },
        }
    },
)
async def create_question(dados: QuestionCreate, service: ServiceDep) -> QuestionResponse:
    try:
        return QuestionResponse.de_model(await service.create(dados))
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.get(
    "/forms/{form_id}/questions",
    response_model=list[QuestionResponse],
    summary="Listar perguntas de um formulário",
    description=(
        "Lista as perguntas de um formulário em ordem de posição, com filtro "
        "opcional por seção. Formulário sem pergunta nenhuma devolve lista vazia."
    ),
    response_description="Perguntas do formulário, na seção pedida quando houver filtro.",
    operation_id="list_questions",
)
async def list_questions(
    form_id: uuid.UUID,
    service: ServiceDep,
    section: QuestionSection | None = None,
) -> list[QuestionResponse]:
    questions = await service.list_for_form(form_id, section)
    return [QuestionResponse.de_model(question) for question in questions]
