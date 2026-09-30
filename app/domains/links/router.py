"""Endpoints HTTP do domínio links (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `LinkResponse.from_model()`, em `schemas.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.domains.links.dependencies import ServiceDep
from app.domains.links.schemas import LinkCreate, LinkResponse
from app.shared.authorization import require_role

# O prefixo descreve o endereço da rota, não o dono do arquivo: o vínculo é
# sub-recurso de organização na URL, mas `Organization` não tem tabela e este
# domínio segue sendo `links` (spec, "Abordagem técnica", item 5).
router = APIRouter(prefix="/organizations/{organization_id}/links", tags=["links"])


@router.post(
    "",
    response_model=LinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar vínculo",
    description=(
        "Cria o vínculo que liga um participante a uma organização, com o papel "
        "e o tipo informados. Só quem tem o papel admin pode chamar (P-008): "
        "criar um vínculo decide o acesso de alguém à plataforma."
    ),
    response_description="Vínculo criado.",
    operation_id="create_link",
    dependencies=[Depends(require_role("admin"))],
)
async def create_link(
    organization_id: Annotated[
        uuid.UUID,
        Path(
            description="Organização à qual o vínculo pertence.",
            examples=["8f14e45f-ceea-467e-adde-3f81905dbc1c"],
        ),
    ],
    request: LinkCreate,
    service: ServiceDep,
) -> LinkResponse:
    link = await service.create_link_service(organization_id, request)
    return LinkResponse.from_model(link)
