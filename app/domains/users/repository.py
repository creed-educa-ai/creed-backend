"""Acesso a dados do domínio respondentes (ADR-002, secao 2.2).

Esta camada NÃO contém regra de negócio: só queries e agregações.
Agregação pesada é empurrada para o Postgres, nunca feita em memória.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.users.models import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, user_email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == user_email))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        """Cria um usuário no banco."""
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        """Delete um usuário do banco."""
        try:
            await self.db.delete(user)
            await self.db.flush()
            await self.db.commit()

        except Exception as exc:
            await self.db.rollback()
            raise exc
