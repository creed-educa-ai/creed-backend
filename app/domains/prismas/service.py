"""Regra de negócio do domínio prismas.

Esta camada não conhece HTTP nem ORM. É onde o cálculo da Matriz CREED é aplicado
sobre as respostas validadas.
"""

import uuid
from typing import TYPE_CHECKING

from app.domains.prismas.schemas import FormResponsePrismasRead
from app.domains.prismas.utils import (
    NeuroinnovationPrism,
    calculate_all_prisms,
    dimension_averages,
)
from app.shared.enums import Dimension, Prisma
from app.shared.exceptions import ForbiddenError, NotFoundError, ValidationError

if TYPE_CHECKING:
    from app.domains.prismas.repository import PrismaRepository
    from app.shared.authorization import AuthenticatedUser

PRISMA_MAP: dict[NeuroinnovationPrism, Prisma] = {
    NeuroinnovationPrism.PSYCHOLOGICAL_SAFETY: Prisma.SEGURANCA_PSICOLOGICA,
    NeuroinnovationPrism.ADAPTIVE_LEADERSHIP: Prisma.LIDERANCA_ADAPTATIVA,
    NeuroinnovationPrism.ENTREPRENEURIAL_CULTURE: Prisma.CULTURA_EMPREENDEDORA,
    NeuroinnovationPrism.COGNITIVE_ADAPTABILITY: Prisma.ADAPTABILIDADE_COGNITIVA,
    NeuroinnovationPrism.NEUROINNOVATION: Prisma.NEUROINOVACAO_PRISMA,
}

ADMIN_ROLE = "admin"
GESTOR_ROLE = "gestor"


class PrismaService:
    def __init__(self, repository: "PrismaRepository") -> None:
        self.repository = repository

    async def calculate_for_form_response(
        self,
        form_response_id: uuid.UUID,
        *,
        user: "AuthenticatedUser",
    ) -> FormResponsePrismasRead:
        """Calcula os prismas individuais de um FormResponse finalizado."""
        form_response = await self.repository.get_form_response(form_response_id)
        if form_response is None:
            raise NotFoundError(
                f"Resposta de formulário {form_response_id} não encontrada"
            )

        form = await self.repository.get_form(form_response.form_id)
        if form is None:
            raise NotFoundError(f"Formulário {form_response.form_id} não encontrado")

        # Regra de acesso: admin vê tudo; gestor da org; membro a própria resposta
        if user.role != ADMIN_ROLE:
            if user.role == GESTOR_ROLE:
                if form.organization_id != user.organization_uuid:
                    raise ForbiddenError("Sem acesso a respostas de outra organização")
            else:
                if form_response.vinculo_id != user.link_uuid:
                    raise ForbiddenError("Sem acesso a resposta de outro respondente")

        status_val = getattr(form_response.status, "value", form_response.status)
        if status_val != "submitted":
            raise ValidationError(
                "O formulário precisa estar finalizado para calcular os prismas"
            )

        answers = await self.repository.get_answers_with_dimensions(form_response_id)
        if not answers:
            raise ValidationError(
                "Nenhuma resposta objetiva válida encontrada para calcular os prismas"
            )

        return self.compute_prisms_data(
            form_response_id=form_response.id,
            form_id=form_response.form_id,
            vinculo_id=form_response.vinculo_id,
            answers=answers,
        )

    def compute_prisms_data(
        self,
        *,
        form_response_id: uuid.UUID,
        form_id: uuid.UUID,
        vinculo_id: uuid.UUID,
        answers: list[tuple[Dimension, float]],
    ) -> FormResponsePrismasRead:
        """Aplica o algoritmo da Matriz CREED e monta o DTO de saída."""
        dim_averages = dimension_averages(answers)
        raw_prisms = calculate_all_prisms(dim_averages)

        scores: dict[str, float] = {}
        scores_100: dict[str, float] = {}
        for neuro_prism, val in raw_prisms.items():
            prisma_enum = PRISMA_MAP[neuro_prism]
            scores[prisma_enum.value] = round(val, 2)
            # Escala 0 a 100 baseada na pontuação de 1 a 5
            scores_100[prisma_enum.value] = round((val / 5.0) * 100.0, 1)

        dim_scores: dict[str, float] = {
            dim.value: round(val, 2) for dim, val in dim_averages.items()
        }

        return FormResponsePrismasRead(
            form_response_id=form_response_id,
            form_id=form_id,
            vinculo_id=vinculo_id,
            scores=scores,
            scores_100=scores_100,
            dimensions=dim_scores,
        )
