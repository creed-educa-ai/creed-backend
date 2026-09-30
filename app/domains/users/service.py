"""Regra de negócio do domínio users (ADR-002, secao 2.2).

Esta camada não conhece HTTP nem detalhes de ORM. É onde a lógica vive,
isolada e testável — o mesmo padrão que os dashboards usarão para o
cálculo dos 5 prismas (ADR-001, secao 4.1).

`users` conversa com `links` só pelo `LinkService`, injetado (spec da
CREED-32, "Abordagem técnica", item 8) — nunca com `LinkRepository` nem com
`Link` direto, que manteria o acoplamento na tabela e não no contrato do
domínio dono.
"""

import uuid
from dataclasses import dataclass

from app.domains.links.service import LinkService
from app.domains.users.models import User
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import UserCreate
from app.shared.enums import RecordStatus
from app.shared.exceptions import ConflictError, NotFoundError


@dataclass
class CreatedUser:
    """O que o router precisa para montar o `UserResponse` do cadastro.

    `role` e `organization_id` vêm do `Link` que o service já consultou
    para validar o cadastro — não faz sentido o router buscá-los de novo.
    """

    user: User
    role: str
    organization_id: uuid.UUID


@dataclass
class UserAccess:
    """O que a guarda e o login precisam saber sobre um login autenticado.

    `role` e `organization_id` são os do vínculo, não os de `user.role` —
    é o contrato que a task 5 vai consumir.
    """

    id: uuid.UUID
    email: str
    role: str
    link_id: uuid.UUID
    organization_id: uuid.UUID


class UserService:
    def __init__(self, repository: UserRepository, links: LinkService) -> None:
        self.repository = repository
        self.links = links

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        """O que a guarda e o login usam para saber quem está logado.

        `None` cobre usuário inexistente, inativo, sem `link_id`, e
        `link_id` que o `LinkService` não encontra — a guarda e o login
        tratam todos os quatro como "sem acesso" (401), sem distinguir.
        """
        user = await self.repository.get_user_by_email(email)

        if user is None or user.status is not RecordStatus.ACTIVE or user.link_id is None:
            return None

        link = await self.links.get_link_by_id_service(user.link_id)
        if link is None:
            return None

        return UserAccess(
            id=user.id,
            email=user.email,
            role=link.role.value,
            link_id=user.link_id,
            organization_id=link.organization_id,
        )

    async def create_user_service(self, request: UserCreate) -> CreatedUser:
        already_exists = await self.repository.get_user_by_email(request.email)

        if already_exists is not None:
            raise ConflictError(f"Já existe usuário com o e-mail {request.email}")

        link = await self.links.get_link_by_id_service(request.link_id)
        if link is None:
            raise NotFoundError(f"Vínculo {request.link_id} não encontrado")

        link_in_use = await self.repository.get_by_link_id(request.link_id)
        if link_in_use is not None:
            raise ConflictError(f"Vínculo {request.link_id} já está em uso")

        # `status` é decisão de produto (P-013), então mora aqui e não no model
        # — ADR-0004: "se muda quando o produto muda de ideia, é service". O
        # default do model é só a rede para quem construir um User por outro
        # caminho; em conflito, esta linha é a que vale.
        #
        # `role` fica de fora: a partir da CREED-32 o papel é o do vínculo, e
        # ninguém mais lê a coluna. O default do model (`respondente`) só
        # preenche a linha porque ela ainda é `NOT NULL` — sai na task 6.
        user = User(
            keycloak_id=request.keycloak_id,
            name=request.name,
            email=request.email,
            status=RecordStatus.ACTIVE,
            link_id=request.link_id,
        )
        created = await self.repository.create(user)
        return CreatedUser(
            user=created, role=link.role.value, organization_id=link.organization_id
        )

    async def delete_user_service(self, user_id: uuid.UUID) -> None:
        user = await self.repository.get_by_id(user_id)

        if user is None:
            raise NotFoundError(f"Usuário {user_id} não encontrado")

        await self.repository.delete(user)
