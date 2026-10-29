"""Endpoints HTTP do domínio users (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `UserResponse.de_model()`, em `schemas.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.domains.users.dependencies import ServiceDep
from app.domains.users.schemas import UserCreate, UserResponse
from app.shared.authorization import require_role
from app.shared.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar usuário",
    description=(
        "Cria o acesso de uma pessoa a partir de um vínculo existente: registra o "
        "usuário na plataforma e no provedor de identidade, sem senha, e envia o "
        "e-mail de convite para a pessoa definir a senha. Se o convite não puder "
        "ser enviado, no banco nada é criado. Se o provedor falhar no meio, o "
        "acesso pode sobrar lá, e a nova tentativa responde 409 até a limpeza "
        "manual. O e-mail é comparado e gravado em minúsculas, como o provedor de "
        "identidade guarda: a resposta o devolve assim, e o 409 de e-mail repetido "
        "não distingue maiúsculas. O status inicial é ativo, e o papel é o do "
        "vínculo informado. Exige o papel admin (P-008): amarrar um login a um "
        "vínculo decide o acesso de alguém à plataforma."
    ),
    response_description="Usuário criado na plataforma.",
    operation_id="create_user",
    dependencies=[Depends(require_role("admin"))],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token ausente, inválido ou expirado.",
            "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "O usuário autenticado não tem o papel admin.",
            "content": {
                "application/json": {
                    "example": {"detail": "Cargo insuficiente para acessar"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "O vínculo informado não existe.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Vínculo 3f9a2b1c-4d5e-4f6a-8b7c-9d0e1f2a3b4c não encontrado"
                        )
                    }
                }
            },
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "Já existe um usuário com o e-mail informado (sem distinguir "
                "maiúsculas), aqui ou no provedor de identidade, ou o vínculo já "
                "está em uso por outro usuário."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Já existe usuário com o e-mail pessoa@exemplo.com"
                    }
                }
            },
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": (
                "O provedor de identidade ou o envio de e-mail não respondeu. No "
                "banco, nada é criado. Se o provedor falhar no meio, o acesso pode "
                "sobrar lá, e a nova tentativa responde 409 até a limpeza manual."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Não foi possível criar o acesso agora. Tente de novo."
                    }
                }
            },
        },
    },
)
async def create_user(dados: UserCreate, service: ServiceDep) -> UserResponse:
    try:
        created = await service.create_user_service(dados)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, exc.message) from exc

    return UserResponse.de_model(
        created.user,
        role=created.role,
        link_id=dados.link_id,
        organization_id=created.organization_id,
    )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover usuário",
    description=(
        "Remove definitivamente um usuário da plataforma e do provedor de "
        "identidade, pelo identificador. Depois disso, o mesmo e-mail pode ser "
        "convidado de novo. Exige o papel admin, o mesmo do cadastro."
    ),
    response_description="Usuário removido; a resposta não possui corpo.",
    operation_id="delete_user",
    dependencies=[Depends(require_role("admin"))],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token ausente, inválido ou expirado.",
            "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "O usuário autenticado não tem o papel admin.",
            "content": {
                "application/json": {
                    "example": {"detail": "Cargo insuficiente para acessar"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Usuário não encontrado.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Usuário d40b7a55-b9cc-4b78-ae5d-ab325fd655e2 não encontrado"
                        )
                    }
                }
            },
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": (
                "O provedor de identidade não respondeu. O usuário continua no "
                "banco, mas pode já ter saído do provedor; repetir a remoção resolve."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Não foi possível remover o acesso agora. Tente de novo."
                        )
                    }
                }
            },
        },
    },
)
async def delete_user(
    user_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador do usuário que será removido.",
            examples=["d40b7a55-b9cc-4b78-ae5d-ab325fd655e2"],
        ),
    ],
    service: ServiceDep,
) -> None:
    try:
        await service.delete_user_service(user_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, exc.message) from exc
