"""Regra de negócio do domínio Users.

Esta camada não conhece HTTP nem detalhes de ORM. É onde a lógica vive,
isolada e testável — o mesmo padrão que os dashboards usarão para o
cálculo dos 5 prismas (ADR-001, secao 4.1).
"""

from app.domains.users.models import RecordStatus, User
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import UserCreate, UserDelete
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

        if already_exists:
            raise ConflictError("Usuário já existe")

        user = User(
            email=request.email,
            hash_password=request.password,
        )

        return await self.repository.create(user)

    async def delete_user_service(self, request: UserDelete) -> None:
        user = await self.repository.get_by_id(request.id)

        if not user:
            raise NotFoundError(f"Usuário não existente para o Id: {request.id}")

        await self.repository.delete(user)
