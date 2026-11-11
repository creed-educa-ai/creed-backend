"""Regra de negócio do domínio organizacoes (ADR-0004).

Esta camada não conhece HTTP nem detalhes de ORM. Documento é de outro domínio:
a pergunta "ele existe?", a leitura do número e a criação do documento do cadastro
público vão ao `DocumentService`, nunca ao model de `documents` — o mesmo caminho
de `participants/service.py`.

Quem pode o quê (CREED-38):
- `admin` cadastra, lista, lê e altera qualquer organização. Restringir cadastro,
  listagem e alteração a `admin` é do router (`require_role`).
- `gestor` só lê a própria organização. Essa regra mora aqui, porque compara o
  recurso com quem pede (P-033, a mesma regra de `forms`).
- Qualquer pessoa, sem login, cadastra a própria empresa (`sign_up`), que nasce
  `pending`.

Uma organização `pending` (empresa que se cadastrou e ainda não foi aprovada) só
sai desse estado pela aprovação ou pela rejeição: o PATCH não troca o status dela.
"""

import uuid
from dataclasses import dataclass

from app.domains.documents.service import (
    DOCUMENT_ALREADY_REGISTERED,
    DocumentService,
)
from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.domains.organizacoes.repository import OrganizationRepository
from app.domains.organizacoes.schemas import (
    OrganizationCreate,
    OrganizationSignUp,
    OrganizationUpdate,
)
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

ADMIN = "admin"

# 🟡 Premissa P-075 — o cadastro público não pede endereço; a administradora corrige
# pelo PATCH, como o da organização da CREED (P-059).
ADDRESS_TO_BE_INFORMED = "[A informar]"


@dataclass
class OrganizationWithDocument:
    """Uma organização com o documento dela: o que toda resposta da API mostra.

    `document_type` é o valor do `DocType` (`cpf`, `cnpj`...). O documento mora em
    `documents`, e este domínio não importa o model de lá.
    """

    organization: Organization
    document_type: str
    document_value: str


def _documento_em_uso(document_id: uuid.UUID) -> ConflictError:
    return ConflictError(f"O documento {document_id} já pertence a outra organização")


class OrganizationService:
    def __init__(
        self, repository: OrganizationRepository, documents: DocumentService
    ) -> None:
        self.repository = repository
        self.documents = documents

    async def create(self, request: OrganizationCreate) -> Organization:
        if not await self.documents.document_exists(request.document_id):
            raise ValidationError(f"Documento {request.document_id} não encontrado")

        if await self.repository.get_by_document_id(request.document_id) is not None:
            raise _documento_em_uso(request.document_id)

        organization = Organization(
            name=request.name,
            address=request.address,
            document_id=request.document_id,
            status=OrganizationStatus.ACTIVE,
        )
        created = await self.repository.create(organization)

        # `None`: outro cadastro ligou o mesmo documento entre a checagem acima e
        # a gravação. Para quem chamou, é o mesmo conflito.
        if created is None:
            raise _documento_em_uso(request.document_id)

        return created

    async def sign_up(self, request: OrganizationSignUp) -> Organization:
        """Cadastro público: cria o documento e a organização `pending`.

        As duas gravações estão na mesma transação da requisição (`get_db`): se a
        segunda falha, a primeira é desfeita junto.

        🟡 Premissa P-076 — documento já cadastrado é 409, e quem levanta é o
        `DocumentService`, antes de a organização existir.
        🟡 Premissa P-077 — não confere se o e-mail já tem acesso; quem confere é a
        aprovação.
        """
        document = await self.documents.create_brazilian_document(request.document)

        organization = Organization(
            name=request.name,
            address=ADDRESS_TO_BE_INFORMED,
            document_id=document.id,
            status=OrganizationStatus.PENDING,
            email=request.email.lower(),
            contact_name=request.contact_name,
            phone=request.phone,
        )
        created = await self.repository.create(organization)

        # `None` seria outra organização com este documento, que acabou de nascer
        # nesta transação e nenhuma outra enxerga. Tratado como o mesmo conflito do
        # documento repetido, como `create` faz, e sem mostrar o id numa rota pública.
        if created is None:
            raise ConflictError(DOCUMENT_ALREADY_REGISTERED)

        return created

    async def get(
        self, organization_id: uuid.UUID, *, role: str, own_organization_id: uuid.UUID
    ) -> Organization:
        """`role` e `own_organization_id` são de quem pede.

        A checagem de acesso vem antes da busca: um `gestor` que pede uma
        organização alheia recebe 403 mesmo se ela não existir, para a resposta
        não revelar quais organizações existem.
        """
        if role != ADMIN and organization_id != own_organization_id:
            raise ForbiddenError("Sem acesso a organização de outro vínculo")

        organization = await self.repository.get_by_id(organization_id)
        if organization is None:
            raise NotFoundError(f"Organização {organization_id} não encontrada")

        return organization

    async def with_documents(
        self, organizations: list[Organization]
    ) -> list[OrganizationWithDocument]:
        """Junta a cada organização o documento dela, na ordem recebida.

        Uma chamada ao `DocumentService` para a lista inteira, qualquer que seja o
        tamanho dela: uma página de organizações não vira uma consulta por linha.

        Documento ausente levanta `RuntimeError` (500), e não é pulado nem trocado
        por vazio: `document_id` é `NOT NULL` com chave estrangeira, então só falta
        com o banco inconsistente, e esconder isso mostraria uma empresa sem
        documento na tela da administradora.
        """
        document_ids = [organization.document_id for organization in organizations]
        documents = await self.documents.list_by_ids(document_ids)
        documents_by_id = {document.id: document for document in documents}

        result: list[OrganizationWithDocument] = []
        for organization in organizations:
            document = documents_by_id.get(organization.document_id)
            if document is None:
                raise RuntimeError(
                    f"Organização {organization.id} aponta para o documento "
                    f"{organization.document_id}, que não existe"
                )
            result.append(
                OrganizationWithDocument(
                    organization=organization,
                    document_type=document.type.value,
                    document_value=document.value,
                )
            )
        return result

    async def organization_exists(self, organization_id: uuid.UUID) -> bool:
        """Só "existe?", sem regra de acesso: é o que `links`, `department` e
        `forms` usam para conferir a organização que recebem."""
        return await self.repository.get_by_id(organization_id) is not None

    async def list_page(
        self, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Organization], int]:
        """Uma página e o total. `pagina` começa em 1."""
        offset = (pagina - 1) * tamanho_pagina
        itens = await self.repository.list_page(offset, tamanho_pagina)
        total = await self.repository.count()
        return itens, total

    async def update(
        self, organization_id: uuid.UUID, request: OrganizationUpdate
    ) -> Organization:
        """Altera só os campos enviados: o que não veio no PATCH fica como está.

        Numa organização `pending`, o corpo com `status` é recusado inteiro
        (`ConflictError`), antes de qualquer campo mudar: ela só sai desse estado
        pela aprovação ou pela rejeição. 🟡 Premissa P-075 — nome e endereço dela
        continuam editáveis, que é como a administradora corrige o endereço.
        """
        organization = await self.repository.get_by_id(organization_id)
        if organization is None:
            raise NotFoundError(f"Organização {organization_id} não encontrada")

        changes = request.model_dump(exclude_unset=True)

        if "status" in changes:
            if organization.status is OrganizationStatus.PENDING:
                raise ConflictError(
                    "A empresa está pendente: aprove ou rejeite o cadastro"
                )
            # O PATCH recebe `RecordStatus` (`active`/`inactive`); a coluna é do
            # enum da organização, que tem os mesmos valores e mais o `pending`.
            changes["status"] = OrganizationStatus(changes["status"].value)

        for campo, valor in changes.items():
            setattr(organization, campo, valor)

        return await self.repository.save(organization)
