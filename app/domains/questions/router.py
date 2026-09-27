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

router = APIRouter(tags=["questions"])


@router.post(
    "/questions", response_model=QuestionResponse, status_code=status.HTTP_201_CREATED
)
async def create_question(dados: QuestionCreate, service: ServiceDep) -> QuestionResponse:
    try:
        return QuestionResponse.de_model(await service.create(dados))
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.get(
    "/forms/{form_id}/questions",
    response_model=list[QuestionResponse],
)
async def list_questions(
    form_id: uuid.UUID,
    service: ServiceDep,
    section: QuestionSection | None = None,
) -> list[QuestionResponse]:
    questions = await service.list_for_form(form_id, section)
    return [QuestionResponse.de_model(question) for question in questions]
