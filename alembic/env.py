"""Ambiente do Alembic (ADR-002, secao 2.4).

Roda em modo síncrono de propósito: migrations são operação pontual,
executada por um Job dedicado no deploy — não precisam de async.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.database import Base
from app.domains.respostas import models as respostas_models  # noqa: F401

# --- IMPORTANTE ---
# Todo model novo precisa ser importado aqui, senão o autogenerate não o enxerga
# e a migration sai vazia ou incompleta.
# from app.domains.respondentes import models as respondentes_models
from app.domains.users import models as users_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # compare_type detecta mudanças de tipo que passariam batido
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
