"""Regra de negócio do domínio vinculos (ADR-002, secao 2.2).

Esta camada não conhece HTTP nem detalhes de ORM.
"""

import uuid

from app.domains.vinculos.models import Vinculo
from app.domains.vinculos.repository import VinculoRepository
from app.domains.vinculos.schemas import VinculoCreate


class VinculoService:
    def __init__(self, repository: VinculoRepository) -> None:
        self.repository = repository

    async def create_vinculo_service(
        self, organization_id: uuid.UUID, request: VinculoCreate
    ) -> Vinculo:
        """Monta e grava o vínculo.

        Sem conflito para checar: o `.dbml` não define unicidade em `Vinculo`, e não
        há tabela de organização ou de participante para consultar (spec, "Abordagem
        técnica", item 6). O service só monta a entidade e delega ao repository.
        """
        vinculo = Vinculo(
            organization_id=organization_id,
            participant_id=request.participant_id,
            setor_id=request.setor_id,
            type=request.type,
            role=request.role,
        )
        return await self.repository.insert(vinculo)

    async def get_vinculo_by_id_service(self, vinculo_id: uuid.UUID) -> Vinculo | None:
        """Lê um vínculo pelo id, ou `None` se não existir.

        Não levanta `NotFoundError`: quem chama decide o que a ausência significa
        (404 no cadastro de usuário, 401 no login — task 4 e 5).
        """
        return await self.repository.get_by_id(vinculo_id)
