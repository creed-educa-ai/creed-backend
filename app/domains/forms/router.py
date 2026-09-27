"""Endpoints HTTP do domínio users (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `UserResponse.de_model()`, em `schemas.py`.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/forms", tags=["forms"])
