"""Endpoints HTTP do domínio questions (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de
`models` — os tipos de seção e idioma vêm de `schemas.py` (tests/test_arquitetura.py
reprova rota que importe de models.py).

Sem prefixo próprio: os endereços não compartilham um caminho comum
(`/questions`, `/forms/{form_id}/questions`, `/questions/{question_id}/translations`
e `/options/{option_id}/translations`), então cada rota escreve o caminho inteiro.
O prefixo `/api/v1` vem da configuração central, no registro em app/main.py.

Idiomas: o PT é o padrão e vive na própria pergunta/alternativa. Na leitura, o
`?lang=` aceita `pt`, `pt-BR`, `en` e `es` (omitido vale `pt`). Na escrita de
tradução, o corpo só aceita `en` e `es`: o PT não é tradução.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.domains.questions.dependencies import (
    QuestionOptionTranslationServiceDep,
    QuestionTranslationServiceDep,
    ServiceDep,
)
from app.domains.questions.schemas import (
    QuestionCreate,
    QuestionLangQuery,
    QuestionOptionTranslationCreate,
    QuestionOptionTranslationResponse,
    QuestionResponse,
    QuestionSection,
    QuestionTranslationCreate,
    QuestionTranslationResponse,
    QuestionWithOptionsResponse,
)
from app.shared.authorization import AuthenticatedUser, CurrentUserDep, require_role
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.shared.schemas import ErrorResponse, ValidationErrorResponse

router = APIRouter(tags=["questions"])

EditorDep = Annotated[AuthenticatedUser, Depends(require_role("admin", "gestor"))]

_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
}


def _forbidden(description: str) -> dict[int | str, dict[str, Any]]:
    return {
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": description,
            "content": {
                "application/json": {
                    "example": {"detail": "Sem acesso a formulário de outra organização"}
                }
            },
        },
    }


def _error(
    status_code: int, description: str, example: str
) -> dict[int | str, dict[str, Any]]:
    return {
        status_code: {
            "model": ErrorResponse,
            "description": description,
            "content": {"application/json": {"example": {"detail": example}}},
        },
    }


_INVALID_BODY: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ValidationErrorResponse,
        "description": (
            "Corpo inválido: `detail` é uma lista, um item por campo recusado "
            "(inclui idioma fora de `en`/`es`)."
        ),
    },
}


@router.post(
    "/questions",
    response_model=QuestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar pergunta",
    description=(
        "Cadastra uma pergunta num formulário, na seção e posição informadas. "
        "O formulário precisa já existir. Exige o papel admin ou gestor; o "
        "gestor só cadastra em formulário da própria organização. O texto é "
        "sempre o PT; traduções entram por `POST /questions/{id}/translations`."
    ),
    response_description="Pergunta criada.",
    operation_id="create_question",
    responses={
        **_UNAUTHORIZED,
        **_forbidden(
            "Papel sem permissão para cadastrar, ou formulário de outra organização."
        ),
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
async def create_question(
    dados: QuestionCreate, service: ServiceDep, user: EditorDep
) -> QuestionResponse:
    try:
        question = await service.create(
            dados, role=user.role, organization_id=user.organization_uuid
        )
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    return QuestionResponse.de_model(question)


@router.get(
    "/forms/{form_id}/questions",
    response_model=list[QuestionWithOptionsResponse],
    summary="Listar perguntas de um formulário",
    description=(
        "Lista as perguntas de um formulário em ordem de posição, cada uma com as "
        "suas alternativas (também em ordem de posição), com filtro opcional por "
        "seção. Com `lang`, o enunciado e o texto das alternativas saem traduzidos "
        "quando existir tradução naquele idioma; sem tradução, volta o PT, item a "
        "item. Formulário sem pergunta nenhuma devolve lista vazia; formulário "
        "inexistente devolve 404. Qualquer papel lê as perguntas de formulário da "
        "própria organização; o admin lê de qualquer uma."
    ),
    response_description="Perguntas do formulário, na seção pedida quando houver filtro.",
    operation_id="list_questions",
    responses={
        **_UNAUTHORIZED,
        **_forbidden("O formulário é de outra organização."),
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
        },
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
    user: CurrentUserDep,
    section: Annotated[
        QuestionSection | None,
        Query(
            description="Filtra as perguntas por seção do formulário.",
            examples=["assessment"],
        ),
    ] = None,
    lang: Annotated[
        QuestionLangQuery,
        Query(
            description=(
                "Idioma do enunciado e das alternativas: `pt` (ou `pt-BR`), `en` "
                "ou `es`. Omitido, vale `pt`; sem tradução no idioma pedido, "
                "também volta o PT."
            ),
            examples=["en"],
        ),
    ] = QuestionLangQuery.PT,
) -> list[QuestionWithOptionsResponse]:
    translation_lang = lang.translation_lang
    try:
        questions = await service.list_for_form(
            form_id,
            section,
            translation_lang,
            role=user.role,
            organization_id=user.organization_uuid,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    return [
        QuestionWithOptionsResponse.de_model(question, lang=translation_lang)
        for question in questions
    ]


@router.post(
    "/questions/{question_id}/translations",
    response_model=QuestionTranslationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Traduzir pergunta",
    description=(
        "Cadastra a tradução (`en` ou `es`) do enunciado de uma pergunta. No máximo "
        "uma tradução por idioma: repetir devolve 409. Exige o papel admin ou "
        "gestor; o gestor só traduz pergunta de formulário da própria organização."
    ),
    response_description="Tradução criada.",
    operation_id="create_question_translation",
    responses={
        **_UNAUTHORIZED,
        **_forbidden(
            "Papel sem permissão, ou pergunta de formulário de outra organização."
        ),
        **_error(
            status.HTTP_404_NOT_FOUND,
            "Pergunta não encontrada.",
            "Pergunta 7ae21494-975f-46ab-97cc-4c42b5ae7aaa não encontrada",
        ),
        **_error(
            status.HTTP_409_CONFLICT,
            "A pergunta já tem tradução nesse idioma.",
            (
                "Já existe tradução 'en' para a pergunta "
                "7ae21494-975f-46ab-97cc-4c42b5ae7aaa"
            ),
        ),
        **_INVALID_BODY,
    },
)
async def create_question_translation(
    question_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador da pergunta a traduzir.",
            examples=["7ae21494-975f-46ab-97cc-4c42b5ae7aaa"],
        ),
    ],
    dados: QuestionTranslationCreate,
    service: QuestionTranslationServiceDep,
    user: EditorDep,
) -> QuestionTranslationResponse:
    try:
        translation = await service.create(
            question_id,
            dados,
            role=user.role,
            organization_id=user.organization_uuid,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    return QuestionTranslationResponse.de_model(translation)


@router.post(
    "/options/{option_id}/translations",
    response_model=QuestionOptionTranslationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Traduzir alternativa",
    description=(
        "Cadastra a tradução (`en` ou `es`) do texto de uma alternativa. O `value` "
        "não é traduzido. No máximo uma tradução por idioma: repetir devolve 409. "
        "Exige o papel admin ou gestor; o gestor só traduz alternativa de "
        "formulário da própria organização."
    ),
    response_description="Tradução criada.",
    operation_id="create_question_option_translation",
    responses={
        **_UNAUTHORIZED,
        **_forbidden(
            "Papel sem permissão, ou alternativa de formulário de outra organização."
        ),
        **_error(
            status.HTTP_404_NOT_FOUND,
            "Alternativa não encontrada.",
            "Alternativa 7ae21494-975f-46ab-97cc-4c42b5ae7aab não encontrada",
        ),
        **_error(
            status.HTTP_409_CONFLICT,
            "A alternativa já tem tradução nesse idioma.",
            (
                "Já existe tradução 'en' para a alternativa "
                "7ae21494-975f-46ab-97cc-4c42b5ae7aab"
            ),
        ),
        **_INVALID_BODY,
    },
)
async def create_question_option_translation(
    option_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador da alternativa a traduzir.",
            examples=["7ae21494-975f-46ab-97cc-4c42b5ae7aab"],
        ),
    ],
    dados: QuestionOptionTranslationCreate,
    service: QuestionOptionTranslationServiceDep,
    user: EditorDep,
) -> QuestionOptionTranslationResponse:
    try:
        translation = await service.create(
            option_id,
            dados,
            role=user.role,
            organization_id=user.organization_uuid,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    return QuestionOptionTranslationResponse.de_model(translation)
