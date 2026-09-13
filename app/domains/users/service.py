"""Regra de negócio do domínio users (ADR-002, secao 2.2).

Esta camada não conhece HTTP nem detalhes de ORM. É onde a lógica vive,
isolada e testável — o mesmo padrão que os dashboards usarão para o
cálculo dos 5 prismas (ADR-001, secao 4.1).
"""

import uuid

from app.domains.users.models import RecordStatus, User
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import UserCreate
from app.shared.exceptions import ConflictError, NotFoundError


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

    async def get_active_user_by_email(self, email: str) -> User | None:
        user = await self.repository.get_user_by_email(email)

        if user is None or user.status is not RecordStatus.ACTIVE:
            return None

        return user

    async def create_user_service(self, request: UserCreate) -> User:
        already_exists = await self.repository.get_user_by_email(request.email)

        if already_exists is not None:
            raise ConflictError(f"Já existe usuário com o e-mail {request.email}")

        # `status` é decisão de produto (P-013), então mora aqui e não no model
        # — ADR-0004: "se muda quando o produto muda de ideia, é service". O
        # default do model é só a rede para quem construir um User por outro
        # caminho; em conflito, esta linha é a que vale.
        #
        # `role` fica de fora: o papel vem do vínculo, não do payload (P-008), e
        # `Vinculo` ainda não tem tabela. Vale o menor privilégio do model.
        user = User(
            keycloak_id=request.keycloak_id,
            name=request.name,
            email=request.email,
            status=RecordStatus.ACTIVE,
        )
        return await self.repository.create(user)

    async def delete_user_service(self, user_id: uuid.UUID) -> None:
        user = await self.repository.get_by_id(user_id)

        if user is None:
            raise NotFoundError(f"Usuário {user_id} não encontrado")

        await self.repository.delete(user)
