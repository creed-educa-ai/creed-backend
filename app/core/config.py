"""Configuração da aplicação via variáveis de ambiente (ADR-002, secao 2.3).

A config vem sempre do ambiente — nunca hardcoded — porque o deploy é em
container numa EC2 (ADR-0007), onde os valores chegam pelo ambiente do
container e os segredos vêm do gerenciador de segredo da AWS.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Aplicação ---
    PROJECT_NAME: str = "CREED.ai Educa API"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: Literal["local", "dev", "staging", "production"] = "local"
    DEBUG: bool = False

    # --- Banco (RDS PostgreSQL, ADR-001) ---
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "creed"
    # Sem default de propósito: a aplicação deve falhar no boot se o Secret não
    # chegar, em vez de subir silenciosamente com uma senha conhecida.
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "creed"

    # --- Esteira de IA (N8N self-hosted, ADR-001 secao 2.1) ---
    N8N_WEBHOOK_URL: str = ""
    N8N_CALLBACK_SECRET: str = ""
    N8N_TIMEOUT_SECONDS: int = 10

    # --- Keycloak (CREED-23, decisoes D1 e D3) ---
    # O realm local sobe pelo docker-compose a partir de docker/keycloak/realm-creed.json.
    KEYCLOAK_SERVER_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "creed"
    KEYCLOAK_CLIENT_ID: str = "creed-backend"
    # Sem default, mesmo motivo do POSTGRES_PASSWORD: melhor falhar no boot do que
    # subir com um segredo conhecido e descobrir isso em producao.
    KEYCLOAK_CLIENT_SECRET: str
    KEYCLOAK_TIMEOUT_SECONDS: int = 10
    # TTL do cache da chave publica do realm (JWKS). A chave so muda quando o realm
    # roda as chaves; reler a cada requisicao poria o Keycloak no caminho critico
    # de toda rota protegida.
    KEYCLOAK_JWKS_CACHE_SECONDS: int = 3600

    # --- CORS ---
    # NoDecode desliga o parse JSON que o pydantic-settings faz em campo de tipo
    # complexo ANTES de qualquer validator: sem ele o valor vindo do .env vai para
    # json.loads, e a lista separada por vírgula do .env.example estoura na leitura
    # da config. Com NoDecode a string crua chega ao _split_origins abaixo.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def database_url(self) -> str:
        """DSN async para o SQLAlchemy (driver asyncpg)."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @property
    def database_url_sync(self) -> str:
        """DSN sincrono — usado apenas pelo Alembic (ADR-002, secao 2.4)."""
        return self.database_url.replace("postgresql+asyncpg", "postgresql+psycopg")


@lru_cache
def get_settings() -> Settings:
    """Cacheado: as settings são lidas uma vez por processo."""
    return Settings()


settings = get_settings()
