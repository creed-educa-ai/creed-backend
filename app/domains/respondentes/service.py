"""Regra de negócio do domínio respondentes (ADR-002, secao 2.2).

Esta camada não conhece HTTP nem detalhes de ORM. É onde a lógica vive,
isolada e testável — o mesmo padrão que os dashboards usarão para o
cálculo dos 5 prismas (ADR-001, secao 4.1).
"""

import uuid

from app.domains.respondentes.models import Respondente
from app.domains.respondentes.repository import RespondenteRepository
from app.domains.respondentes.schemas import (
    RespondenteCreate,
    RespondenteUpdate,
)
from app.shared.exceptions import ConflictError, NotFoundError


class RespondenteService:
    def __init__(self, repository: RespondenteRepository) -> None:
        self.repository = repository

    async def obter(self, respondente_id: uuid.UUID) -> Respondente:
        respondente = await self.repository.get_by_id(respondente_id)
        if respondente is None:
            raise NotFoundError(f"Respondente {respondente_id} não encontrado")
        return respondente

    async def listar(
        self,
        *,
        pagina: int = 1,
        tamanho_pagina: int = 50,
        pais: str | None = None,
        regiao: str | None = None,
    ) -> tuple[list[Respondente], int]:
        offset = (pagina - 1) * tamanho_pagina
        return await self.repository.list_paginated(
            offset=offset, limit=tamanho_pagina, pais=pais, regiao=regiao
        )

    async def criar(self, dados: RespondenteCreate) -> Respondente:
        existente = await self.repository.get_by_email(dados.email)
        if existente is not None:
            raise ConflictError(f"Já existe respondente com o e-mail {dados.email}")

        respondente = Respondente(
            nome=dados.nome,
            email=dados.email,
            data_nascimento=dados.data_nascimento,
            genero=dados.genero,
            regiao=dados.regiao,
            pais=dados.pais.upper() if dados.pais else None,
        )
        return await self.repository.create(respondente)

    async def atualizar(
        self, respondente_id: uuid.UUID, dados: RespondenteUpdate
    ) -> Respondente:
        respondente = await self.obter(respondente_id)

        if dados.email and dados.email != respondente.email:
            existente = await self.repository.get_by_email(dados.email)
            if existente is not None:
                raise ConflictError(f"E-mail {dados.email} já está em uso")

        for campo, valor in dados.model_dump(exclude_unset=True).items():
            if campo == "pais" and valor:
                valor = valor.upper()
            setattr(respondente, campo, valor)

        # Não chamamos o repository para "salvar": o objeto veio da sessão desta
        # requisição, então mudar o atributo basta — quem faz o commit é o
        # get_db, no fim da requisição (conventions/camadas-do-back.md →
        # "Transação: quem fecha").
        return respondente

    async def remover(self, respondente_id: uuid.UUID) -> None:
        respondente = await self.obter(respondente_id)
        await self.repository.delete(respondente)
