"""Endpoint HTTP do convite de membro de uma organização (CREED-23.8, D8).

Camada fina de propósito: recebe, valida via Pydantic, delega ao `MemberService` e
devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` — a resposta é
a mesma `UserResponse` do `POST /users`, montada por `de_model()`.

Sem prefixo próprio, como `questions/router_options.py`: o caminho inteiro está na
rota, e o prefixo `/api/v1` vem do registro em app/main.py.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.domains.users.dependencies import MemberServiceDep
from app.domains.users.schemas import MemberInvite, UserResponse
from app.shared.authorization import AuthenticatedUser, require_role
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.shared.schemas import ErrorResponse

router = APIRouter(tags=["users"])

# 🟡 Premissa P-045 — o respondente não convida. O recorte do gestor (organização e
# papel) é do service, porque compara o pedido com quem pede.
InviterDep = Annotated[AuthenticatedUser, Depends(require_role("admin", "gestor"))]


@router.post(
    "/organizations/{organization_id}/members",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Convidar membro da organização",
    description=(
        "Numa chamada só, cadastra a pessoa como participante, cria o vínculo dela "
        "com a organização, com o papel e o tipo informados, cria o acesso na "
        "plataforma e no provedor de identidade, sem senha, e envia o e-mail de "
        "convite para a pessoa definir a senha. Sem `type`, o vínculo é `emprego`. "
        "Se qualquer passo falhar, no banco nada é criado. Se o provedor falhar no "
        "meio, o acesso pode sobrar lá, e a nova tentativa responde 409 até a "
        "limpeza manual. O e-mail é comparado e gravado em minúsculas. Exige o "
        "papel admin ou gestor: o admin convida em qualquer organização e com "
        "qualquer papel; o gestor, só na organização do próprio vínculo e só como "
        "gestor ou respondente."
    ),
    response_description="Membro convidado; a resposta é o acesso criado.",
    operation_id="invite_member",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token ausente, inválido ou expirado.",
            "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": (
                "Papel sem permissão para convidar (respondente), organização de "
                "outro vínculo, ou gestor convidando com o papel admin."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Sem acesso a organização de outro vínculo"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "A organização informada não existe.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Organização 8f14e45f-ceea-467e-adde-3f81905dbc1c "
                            "não encontrada"
                        )
                    }
                }
            },
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "Já existe um acesso com o e-mail informado (sem distinguir "
                "maiúsculas), aqui ou no provedor de identidade. Nada é criado."
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
async def invite_member(
    organization_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador da organização que recebe o membro.",
            examples=["8f14e45f-ceea-467e-adde-3f81905dbc1c"],
        ),
    ],
    dados: MemberInvite,
    service: MemberServiceDep,
    user: InviterDep,
) -> UserResponse:
    try:
        created = await service.invite_member_service(
            organization_id,
            dados,
            role=user.role,
            own_organization_id=user.organization_uuid,
        )
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, exc.message) from exc

    return UserResponse.de_model(
        created.user,
        role=created.role,
        link_id=created.user.link_id,
        organization_id=created.organization_id,
    )
