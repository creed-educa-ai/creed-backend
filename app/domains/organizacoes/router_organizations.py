"""Endpoints HTTP do ciclo da empresa em `/organizations` (CREED-69, E-2).

Segundo router do domínio, como `links/router_members.py` é o de `links`. Existe
porque as rotas novas de organização usam o prefixo em inglês, que o ADR-0005 manda
para todo identificador novo, e o `router.py` responde em `/organizacoes`, contrato
que o front já consome e que o ADR-0005 não renomeia. A aprovação e a exclusão de
empresa entram neste mesmo arquivo.

O cadastro (`/sign-up`) é público, como o login: não tem `require_role` e não olha
o token.

Camada fina de propósito: recebe, valida via Pydantic, delega ao service e devolve.
Nenhuma regra de negócio aqui, e nenhum import de `models` — a resposta é a mesma
`OrganizationResponse` do `router.py`, com o documento juntado por
`service.with_documents`.
"""

from fastapi import APIRouter, HTTPException, status

from app.domains.organizacoes.dependencies import ServiceDep
from app.domains.organizacoes.schemas import OrganizationResponse, OrganizationSignUp
from app.domains.organizacoes.service import OrganizationWithDocument
from app.shared.exceptions import ConflictError
from app.shared.schemas import ErrorResponse, ValidationErrorResponse

router = APIRouter(prefix="/organizations", tags=["organizacoes"])


def _response(item: OrganizationWithDocument) -> OrganizationResponse:
    return OrganizationResponse.de_model(
        item.organization, item.document_type, item.document_value
    )


@router.post(
    "/sign-up",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar a própria empresa",
    description=(
        "Cadastro público, sem login: cria o documento e a organização numa chamada "
        "só. A organização nasce `pending`, com o endereço `[A informar]`, e espera a "
        "aprovação da administradora. O documento chega com ou sem pontuação e é "
        "guardado só com os dígitos: 11 é CPF, 14 é CNPJ. O e-mail é gravado em "
        "minúsculas. Se qualquer gravação falhar, nada é criado."
    ),
    response_description="Empresa cadastrada, pendente de aprovação.",
    operation_id="sign_up_organization",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "Já existe documento com o mesmo tipo e número, com ou sem pontuação "
                "no pedido. Nada é criado."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Já existe um cadastro com este documento"}
                }
            },
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ValidationErrorResponse,
            "description": (
                "Campo ausente, vazio ou longo demais, caractere de controle no nome, "
                "no responsável ou no telefone, e-mail mal formado, responsável com "
                "menos de 2 caracteres, ou documento que não tem 11 nem 14 dígitos. "
                "`detail` é uma lista, um item por campo recusado."
            ),
        },
    },
)
async def sign_up_organization(
    dados: OrganizationSignUp, service: ServiceDep
) -> OrganizationResponse:
    try:
        organization = await service.sign_up(dados)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    (item,) = await service.with_documents([organization])
    return _response(item)
