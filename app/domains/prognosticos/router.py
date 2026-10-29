"""Endpoints HTTP do domínio prognosticos.

STUB — seguir a estrutura de app/domains/users como referência
(ADR-002, secao 2.2): router fino, service com a regra, repository com as queries.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/prognosticos", tags=["prognosticos"])
