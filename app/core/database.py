"""Sessão SQLAlchemy 2.0 async e base declarativa (ADR-002, secao 2.3)."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base declarativa. Todos os models de domínio herdam daqui.

    Importante para o Alembic: os models precisam ser importados em
    alembic/env.py para que o autogenerate os enxergue (ADR-002, secao 2.4).
    """


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Sessão da requisição. Os domínios a recebem por `SessionDep`, não direto."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# `scope="function"`: o que vem depois do `yield` (o commit) roda quando a rota
# termina, ANTES de a resposta sair. No escopo padrão o FastAPI envia a resposta
# primeiro e só então fecha a sessão: o cliente recebia 201 com o commit ainda
# por fazer, e um commit que falhasse ali não virava erro para ninguém
# (CREED-364). Todo `dependencies.py` usa este tipo — tests/test_arquitetura.py
# reprova `Depends(get_db)` solto.
SessionDep = Annotated[AsyncSession, Depends(get_db, scope="function")]
