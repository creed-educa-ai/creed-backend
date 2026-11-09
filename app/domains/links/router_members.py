"""Endpoints HTTP dos membros de uma organização (CREED-6910, ADR-002, secao 2.2).

Um membro é um vínculo visto junto com a pessoa: nome, e-mail do login e setor. O
endereço é `/organizations/{organization_id}/members`, e não `.../links`, porque é o
recurso que a tela de membros enxerga. O dono continua sendo o domínio `links`: este
é o segundo router dele, como `questions/router_options.py` é o de `questions`. A
listagem (M-2) e a exclusão (M-3) de membros entram neste mesmo arquivo.

Camada fina de propósito: recebe, valida via Pydantic, delega ao service e devolve.
Nenhuma regra de negócio aqui, e nenhum import de `models`.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.domains.links.dependencies import ServiceDep
from app.domains.links.schemas import MemberDepartmentUpdate, MemberResponse
from app.shared.authorization import AuthenticatedUser, require_role
from app.shared.exceptions import ForbiddenError, NotFoundError
from app.shared.schemas import ErrorResponse, ValidationErrorResponse

router = APIRouter(prefix="/organizations/{organization_id}/members", tags=["members"])

# O recorte por organização (gestor só na própria) é regra do service, P-066.
ManagerDep = Annotated[AuthenticatedUser, Depends(require_role("admin", "gestor"))]

_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "Papel respondente, ou gestor pedindo em organização que não é a do "
            "próprio vínculo. Conferido antes da busca: a resposta não revela se o "
            "membro existe."
        ),
        "content": {
            "application/json": {
                "example": {"detail": "Sem acesso aos membros desta organização"}
            }
        },
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": (
            "O vínculo não existe, ou não é desta organização. A resposta é a mesma "
            "nos dois casos."
        ),
        "content": {
            "application/json": {
                "example": {
                    "detail": (
                        "Membro d40b7a55-b9cc-4b78-ae5d-ab325fd655e2 não encontrado na "
                        "organização 8f14e45f-ceea-467e-adde-3f81905dbc1c"
                    )
                }
            }
        },
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ValidationErrorResponse,
        "description": (
            "Corpo inválido: `department` ausente, fora dos cinco setores, ou campo "
            "a mais. `detail` é uma lista, um item por campo recusado."
        ),
    },
}


@router.patch(
    "/{link_id}",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
    summary="Trocar o setor de um membro",
    description=(
        "Escolhe, troca ou tira (`null`) o setor de um membro da organização. O setor "
        "é um dos cinco fixos; se a empresa ainda não tem aquele setor, ele é "
        "cadastrado na hora. O gestor troca o setor dos membros da própria "
        "organização, e o admin, de qualquer uma (P-066)."
    ),
    response_description="Membro com o setor atualizado.",
    operation_id="update_member_department",
    responses=_ERRORS,
)
async def update_member_department(
    organization_id: Annotated[
        uuid.UUID,
        Path(
            description="Organização do membro.",
            examples=["8f14e45f-ceea-467e-adde-3f81905dbc1c"],
        ),
    ],
    link_id: Annotated[
        uuid.UUID,
        Path(
            description="Vínculo do membro com a organização.",
            examples=["d40b7a55-b9cc-4b78-ae5d-ab325fd655e2"],
        ),
    ],
    request: MemberDepartmentUpdate,
    service: ServiceDep,
    user: ManagerDep,
) -> MemberResponse:
    try:
        member = await service.update_member_department(
            organization_id,
            link_id,
            request.department,
            role=user.role,
            own_organization_id=user.organization_uuid,
        )
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    return MemberResponse.from_model(
        member.link,
        name=member.name,
        email=member.email,
        department=member.department,
    )
