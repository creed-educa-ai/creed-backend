"""Regra de negócio do domínio dashboards.

Esta camada não conhece HTTP nem ORM. Agrega os resultados dos colaboradores,
calcula as métricas do grupo e elege os cards de Destaque, Oportunidade e Mais Comum.
"""

import uuid
from typing import TYPE_CHECKING

from app.domains.dashboards.models import Dashboard
from app.domains.dashboards.schemas import (
    CompanySummaryRead,
    DashboardCreate,
    MetricCardRead,
)
from app.shared.enums import Prisma
from app.shared.exceptions import ForbiddenError, NotFoundError

if TYPE_CHECKING:
    from app.domains.dashboards.repository import DashboardRepository
    from app.domains.prismas.service import PrismaService
    from app.shared.authorization import AuthenticatedUser

ADMIN_ROLE = "admin"

PRISMA_INFO: dict[Prisma, dict[str, str]] = {
    Prisma.SEGURANCA_PSICOLOGICA: {
        "titulo": "Segurança Psicológica",
        "descricao": (
            "A equipe demonstra abertura e confiança para compartilhar "
            "opiniões e experimentar."
        ),
    },
    Prisma.LIDERANCA_ADAPTATIVA: {
        "titulo": "Liderança Adaptativa",
        "descricao": (
            "Capacidade dos líderes e equipes de se adaptarem a mudanças rápidas "
            "de contexto."
        ),
    },
    Prisma.CULTURA_EMPREENDEDORA: {
        "titulo": "Cultura Empreendedora",
        "descricao": (
            "Estímulo à proatividade, senso de dono e busca contínua por inovação."
        ),
    },
    Prisma.ADAPTABILIDADE_COGNITIVA: {
        "titulo": "Adaptabilidade Cognitiva",
        "descricao": (
            "Flexibilidade cognitiva para solucionar problemas e aprender com "
            "novas situações."
        ),
    },
    Prisma.NEUROINOVACAO_PRISMA: {
        "titulo": "Neuroinovação",
        "descricao": (
            "Potencial de inteligência coletiva e geração de impacto relevante "
            "no mercado."
        ),
    },
}


class DashboardService:
    def __init__(
        self,
        repository: "DashboardRepository",
        prismas_service: "PrismaService | None" = None,
    ) -> None:
        self.repository = repository
        self.prismas_service = prismas_service

    async def create(self, request: DashboardCreate) -> Dashboard:
        """Cria um novo dashboard."""
        dashboard = Dashboard(
            user_id=request.user_id,
            form_id=request.form_id,
            is_private=request.is_private,
        )
        return await self.repository.create(dashboard)

    async def get(self, dashboard_id: uuid.UUID) -> Dashboard:
        """Busca um dashboard pelo identificador."""
        dashboard = await self.repository.get_by_id(dashboard_id)

        if dashboard is None:
            raise NotFoundError(f"Dashboard {dashboard_id} não encontrado")

        return dashboard

    async def delete_for_member_removal(
        self, form_response_ids: list[uuid.UUID], user_id: uuid.UUID | None
    ) -> None:
        """Apaga os dashboards que impediriam a exclusão de membro (M-3).

        Os das respostas que saem e os do login que sai: as duas colunas são chave
        estrangeira, e o banco recusaria apagar a resposta ou o login primeiro.
        """
        await self.repository.delete_by_form_responses_or_user(form_response_ids, user_id)

    async def calculate_company_summary(
        self,
        form_id: uuid.UUID,
        *,
        user: "AuthenticatedUser",
    ) -> CompanySummaryRead:
        """Calcula o resumo executivo da organização para um formulário/período."""
        if self.prismas_service is None:
            raise RuntimeError("PrismaService não configurado no DashboardService")

        form = await self.repository.get_form(form_id)
        if form is None:
            raise NotFoundError(f"Formulário {form_id} não encontrado")

        if user.role != ADMIN_ROLE and form.organization_id != user.organization_uuid:
            raise ForbiddenError("Sem acesso ao dashboard de outra organização")

        nome_empresa = (
            await self.repository.get_organization_name(form.organization_id)
            or "Organização"
        )
        total_convidados = await self.repository.count_organization_members(
            form.organization_id
        )
        response_ids = await self.repository.get_submitted_form_response_ids(form_id)

        concluidos = len(response_ids)
        convidados = max(total_convidados, concluidos)
        taxa = round((concluidos / convidados) * 100) if convidados > 0 else 0

        # Se não há submissões, retorna estrutura neutra com valores base
        if concluidos == 0:
            default_prisma = Prisma.NEUROINOVACAO_PRISMA
            info = PRISMA_INFO[default_prisma]
            card_padrao = MetricCardRead(
                rotulo="Sem dados",
                titulo=info["titulo"],
                valor=0.0,
                descricao=info["descricao"],
                prisma=default_prisma,
            )
            return CompanySummaryRead(
                form_id=form.id,
                organization_id=form.organization_id,
                nome_empresa=nome_empresa,
                concluidos=0,
                convidados=convidados,
                taxa_conclusao=0,
                destaque=card_padrao,
                oportunidade=card_padrao,
                mais_comum=card_padrao,
                scores={p.value: 0.0 for p in Prisma},
                scores_100={p.value: 0.0 for p in Prisma},
            )

        # Agregação das pontuações de todos os formulários concluídos
        totals: dict[Prisma, float] = dict.fromkeys(Prisma, 0.0)
        totals_100: dict[Prisma, float] = dict.fromkeys(Prisma, 0.0)

        for resp_id in response_ids:
            res_prisma = await self.prismas_service.calculate_for_form_response(
                resp_id, user=user
            )
            for p in Prisma:
                totals[p] += res_prisma.scores.get(p.value, 0.0)
                totals_100[p] += res_prisma.scores_100.get(p.value, 0.0)

        avg_scores = {p: round(totals[p] / concluidos, 2) for p in Prisma}
        avg_scores_100 = {p: round(totals_100[p] / concluidos, 1) for p in Prisma}

        # Eleição dos prismas para os 3 cards
        destaque_prisma = max(avg_scores_100, key=lambda p: avg_scores_100[p])
        oportunidade_prisma = min(avg_scores_100, key=lambda p: avg_scores_100[p])

        # Mais comum: o prisma cuja nota está mais próxima da mediana das médias
        sorted_prisms = sorted(avg_scores_100.keys(), key=lambda p: avg_scores_100[p])
        mais_comum_prisma = sorted_prisms[len(sorted_prisms) // 2]

        destaque_card = MetricCardRead(
            rotulo="Destaque",
            titulo=PRISMA_INFO[destaque_prisma]["titulo"],
            valor=avg_scores_100[destaque_prisma],
            descricao=PRISMA_INFO[destaque_prisma]["descricao"],
            prisma=destaque_prisma,
        )

        oportunidade_card = MetricCardRead(
            rotulo="Oportunidade",
            titulo=PRISMA_INFO[oportunidade_prisma]["titulo"],
            valor=avg_scores_100[oportunidade_prisma],
            descricao=PRISMA_INFO[oportunidade_prisma]["descricao"],
            prisma=oportunidade_prisma,
        )

        mais_comum_card = MetricCardRead(
            rotulo="Mais Comum",
            titulo=PRISMA_INFO[mais_comum_prisma]["titulo"],
            valor=avg_scores_100[mais_comum_prisma],
            descricao=PRISMA_INFO[mais_comum_prisma]["descricao"],
            prisma=mais_comum_prisma,
        )

        return CompanySummaryRead(
            form_id=form.id,
            organization_id=form.organization_id,
            nome_empresa=nome_empresa,
            concluidos=concluidos,
            convidados=convidados,
            taxa_conclusao=taxa,
            destaque=destaque_card,
            oportunidade=oportunidade_card,
            mais_comum=mais_comum_card,
            scores={p.value: avg_scores[p] for p in Prisma},
            scores_100={p.value: avg_scores_100[p] for p in Prisma},
        )
