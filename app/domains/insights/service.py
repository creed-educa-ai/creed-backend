"""Regra de negócio do domínio insights.

Esta camada não conhece HTTP nem detalhes de ORM.
"""

import uuid

from app.domains.insights.models import Insight, InsightPrisma
from app.domains.insights.repository import InsightPrismaRepository, InsightRepository
from app.shared.enums import Prisma
from app.shared.exceptions import ConflictError, NotFoundError


class InsightPrismaService:
    def __init__(self, repository: InsightPrismaRepository) -> None:
        self.repository = repository

    async def associate(self, insight_id: uuid.UUID, prisma: Prisma) -> InsightPrisma:
        """Associa um prisma a um insight.

        Um insight pode ter vários prismas, mas não o mesmo duas vezes. A
        checagem prévia cobre o caso comum; quem fecha a corrida de duas
        chamadas simultâneas é a chave primária composta, e o `None` que o
        repository devolve nesse caso é traduzido aqui.
        """
        insight = await self.repository.get_insight(insight_id)
        if insight is None:
            raise NotFoundError(f"Insight {insight_id} não encontrado")

        existente = await self.repository.get(insight_id, prisma)
        if existente is not None:
            raise self._conflito_de_associacao(insight_id, prisma)

        associacao = InsightPrisma(insight_id=insight_id, prisma=prisma)
        criada = await self.repository.insert(associacao)

        if criada is None:
            raise self._conflito_de_associacao(insight_id, prisma)

        return criada

    def _conflito_de_associacao(
        self, insight_id: uuid.UUID, prisma: Prisma
    ) -> ConflictError:
        return ConflictError(
            f"O insight {insight_id} já está associado ao prisma {prisma.value}"
        )

    async def list_prismas(self, insight_id: uuid.UUID) -> list[InsightPrisma]:
        """Lista os prismas de um insight."""
        insight = await self.repository.get_insight(insight_id)
        if insight is None:
            raise NotFoundError(f"Insight {insight_id} não encontrado")

        return await self.repository.list_by_insight(insight_id)

    async def dissociate(self, insight_id: uuid.UUID, prisma: Prisma) -> None:
        """Remove a associação entre um insight e um prisma."""
        associacao = await self.repository.get(insight_id, prisma)

        if associacao is None:
            raise NotFoundError(
                f"O insight {insight_id} não está associado ao prisma {prisma.value}"
            )

        await self.repository.delete(associacao)


class InsightService:
    def __init__(self, repository: InsightRepository) -> None:
        self.repository = repository

    async def request_individual(self, form_response_id: uuid.UUID) -> Insight:
        """Grava o pedido de insight de uma resposta que acabou de ser enviada.

        Quem chama é o envio da resposta, na transação dele: se a gravação falhar,
        a resposta não fica enviada. O pedido nasce `pending`, e o worker o
        despacha ao N8N (ADR-0010). Receber só o id, e não o `FormResponse`, evita
        importar o model de `responses`: organização e período saem do banco.

        🟡 Premissa P-042 — uma resposta enviada, um insight. Confirmar na próxima
        reunião.
        """
        scope = await self.repository.get_form_scope(form_response_id)
        if scope is None:
            raise NotFoundError(f"FormResponse {form_response_id} não encontrado")

        insight = Insight(
            organization_id=scope.organization_id,
            form_id=scope.form_id,
            form_response_id=form_response_id,
        )
        created = await self.repository.create(insight)

        if created is None:
            raise ConflictError(f"A resposta {form_response_id} já tem insight")

        return created

    async def delete_for_form_responses(self, form_response_ids: list[uuid.UUID]) -> None:
        """Apaga os insights das respostas que a exclusão de membro (M-3) remove."""
        await self.repository.delete_by_form_responses(form_response_ids)
