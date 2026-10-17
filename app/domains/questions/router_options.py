"""Endpoints HTTP das alternativas de pergunta (CREED-37, ADR-002, secao 2.2).

Camada fina de propósito: recebe, valida via Pydantic, delega ao service e
devolve. Nenhuma regra de negócio aqui, e nenhum import de `models`.

Sem prefixo próprio, como em `router.py`: o caminho inteiro está na rota, e o
prefixo `/api/v1` vem da configuração central, no registro em app/main.py.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.domains.questions.dependencies import OptionServiceDep
from app.domains.questions.schemas import (
    QuestionOptionCreate,
    QuestionOptionResponse,
)
from app.shared.authorization import AuthenticatedUser, require_role
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


@router.post(
    "/questions/{question_id}/options",
    response_model=QuestionOptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar alternativa de pergunta",
    description=(
        "Cadastra uma alternativa numa pergunta objetiva, na posição informada. "
        "A pergunta precisa já existir e ser objetiva. Exige o papel admin ou "
        "gestor; o gestor só cadastra em pergunta de formulário da própria "
        "organização."
    ),
    response_description="Alternativa criada.",
    operation_id="create_question_option",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": (
                "Papel sem permissão para cadastrar, ou pergunta de formulário "
                "de outra organização."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Sem acesso a formulário de outra organização"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Pergunta não encontrada.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Pergunta 00000000-0000-0000-0000-000000000001 não encontrada"
                        )
                    }
                }
            },
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Já existe alternativa na mesma posição da pergunta.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Já existe alternativa na posição 0 "
                            "da pergunta 00000000-0000-0000-0000-000000000001"
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
                "Pergunta descritiva: `detail` é texto. Corpo inválido: `detail` "
                "é uma lista, um item por campo recusado."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Pergunta 00000000-0000-0000-0000-000000000001 "
                            "é descritiva e não aceita alternativas"
                        )
                    }
                }
            },
        },
    },
)
async def create_question_option(
    question_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador da pergunta que receberá a alternativa.",
            examples=["00000000-0000-0000-0000-000000000001"],
        ),
    ],
    dados: QuestionOptionCreate,
    service: OptionServiceDep,
    user: EditorDep,
) -> QuestionOptionResponse:
    try:
        option = await service.create(
            question_id,
            dados,
            role=user.role,
            organization_id=user.organization_uuid,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    return QuestionOptionResponse.de_model(option)
