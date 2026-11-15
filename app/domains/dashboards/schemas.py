"""Schemas Pydantic do domínio dashboards (ADR-002, secao 2.3)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.dashboards.models import Dashboard
from app.shared.enums import DepartmentType, Dimension, Prisma


class DashboardCreate(BaseModel):
    """Dados necessários para criar um dashboard."""

    user_id: uuid.UUID = Field(
        description="Identificador do usuário associado ao dashboard."
    )
    form_id: uuid.UUID = Field(
        description="Identificador da resposta de formulário associada ao dashboard."
    )
    is_private: bool = Field(description="Indica se o dashboard é privado.")


class DashboardResponse(BaseModel):
    """Representação de saída de um dashboard."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="Identificador do dashboard.")
    user_id: uuid.UUID = Field(
        description="Identificador do usuário associado ao dashboard."
    )
    form_id: uuid.UUID = Field(
        description="Identificador da resposta de formulário associada ao dashboard."
    )
    is_private: bool = Field(description="Indica se o dashboard é privado.")
    created_at: datetime = Field(description="Data e hora de criação do dashboard.")

    @classmethod
    def de_model(cls, dashboard: Dashboard) -> "DashboardResponse":
        """Monta a saída a partir do model SQLAlchemy."""
        return cls(
            id=dashboard.id,
            user_id=dashboard.user_id,
            form_id=dashboard.form_id,
            is_private=dashboard.is_private,
            created_at=dashboard.created_at,
        )


# ---------------------------------------------------------------------------
# GET /dashboards/me e GET /dashboards/company — o contrato do `UserDashboard`
# e do `CompanyDashboard` do front
# (creed-frontend/src/features/dashboards/dashboardsApi.ts). Os nomes dos campos
# seguem os do front, inclusive os em português (decisão D5 da tarefa
# dashboard-integracao). Toda nota está na escala 0 a 100, em número inteiro: é
# como a tela mostra.
# ---------------------------------------------------------------------------

PrismaScores = dict[Prisma, float]
DimensionScores = dict[Dimension, float]


class PeriodOptionRead(BaseModel):
    """Um período que o filtro do topo oferece. O rótulo é do front, pelas datas."""

    id: uuid.UUID = Field(description="Identificador do formulário do período.")
    opens_at: datetime = Field(description="Quando o período abriu.")
    closes_at: datetime = Field(description="Quando o período fechou (ou fecha).")


class ComparisonOptionsRead(BaseModel):
    """O que dá para escolher nos botões de comparação."""

    periods: list[uuid.UUID] = Field(
        description="Todos os períodos, do mais recente ao mais antigo."
    )
    departments: list[DepartmentType] = Field(
        description="Setores para comparar. Sempre vazio no dashboard individual."
    )
    default_period: uuid.UUID | None = Field(
        description="O período anterior ao exibido; nulo quando ele é o mais antigo."
    )


class PrismaComparisonRead(BaseModel):
    """O resultado exibido comparado a outra referência. Nulo é "o mesmo"."""

    period: uuid.UUID | None = Field(description="Período da referência.")
    scope: str | None = Field(
        description="Setor ou `organization`; nulo é o mesmo recorte exibido."
    )
    scores: PrismaScores = Field(description="Os 5 prismas da referência.")
    variation: PrismaScores = Field(
        description="Exibido menos referência, prisma a prisma."
    )
    dimensions: DimensionScores = Field(description="As 7 dimensões da referência.")


class CreedSummaryRead(BaseModel):
    """O resumo do Creed.ai. Os textos vêm vazios até a esteira de IA existir."""

    model_config = ConfigDict(populate_by_name=True)

    analiseTexto: list[str] = Field(description="Parágrafos da análise.")  # noqa: N815
    recomendacaoTexto: list[str] = Field(  # noqa: N815
        description="Parágrafos da recomendação."
    )
    prismas: dict[Prisma, str] = Field(description="Um texto curto por prisma.")
    destaque: Prisma = Field(description="O prisma de maior nota.")
    oportunidade: Prisma = Field(description="O prisma de menor nota.")


class DashboardResultRead(BaseModel):
    """O que os dois dashboards têm em comum."""

    organization_name: str
    periods: list[PeriodOptionRead] = Field(
        description="Os períodos com resultado, do mais recente ao mais antigo."
    )
    period: uuid.UUID = Field(description="O período que esta resposta mostra.")
    scores: PrismaScores = Field(description="Os 5 prismas, de 0 a 100.")
    dimensions: DimensionScores = Field(description="As 7 dimensões, de 0 a 100.")
    comparison_options: ComparisonOptionsRead
    comparisons: list[PrismaComparisonRead]
    creed_summary: CreedSummaryRead


class UserDashboardRead(DashboardResultRead):
    """O resultado individual de uma pessoa num período: a de quem está logado, ou
    um mentorando visto pela administradora."""

    member_name: str | None = Field(
        default=None,
        description=(
            "O nome do mentorando, quando a administradora vê o resultado dele. "
            "Nulo no próprio resultado."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "organization_name": "Empresa Exemplo",
                    "periods": [
                        {
                            "id": "00000000-0000-0000-0003-000000000002",
                            "opens_at": "2026-10-01T12:00:00Z",
                            "closes_at": "2026-10-15T12:00:00Z",
                        }
                    ],
                    "period": "00000000-0000-0000-0003-000000000002",
                    "scores": {"seguranca_psicologica": 62},
                    "dimensions": {"S6": 58},
                    "comparison_options": {
                        "periods": ["00000000-0000-0000-0003-000000000002"],
                        "departments": [],
                        "default_period": None,
                    },
                    "comparisons": [],
                    "creed_summary": {
                        "analiseTexto": [],
                        "recomendacaoTexto": [],
                        "prismas": {},
                        "destaque": "adaptabilidade_cognitiva",
                        "oportunidade": "lideranca_adaptativa",
                    },
                }
            ]
        }
    )


class HighlightRead(BaseModel):
    """Um card do resumo: o prisma e a nota. Título e descrição são do i18n do front."""

    prisma: Prisma
    valor: float = Field(description="A nota do prisma no recorte, de 0 a 100.")


class CompanySummaryRead(BaseModel):
    """O resumo executivo do recorte exibido."""

    model_config = ConfigDict(populate_by_name=True)

    concluidos: int = Field(ge=0, description="Respostas enviadas no recorte.")
    convidados: int = Field(ge=0, description="O público do recorte no período.")
    destaque: HighlightRead = Field(description="O prisma de maior nota.")
    oportunidade: HighlightRead = Field(description="O prisma de menor nota.")
    maisComum: HighlightRead = Field(  # noqa: N815
        description="O prisma que mais vezes é o maior de cada pessoa."
    )


class AlignmentBandsRead(BaseModel):
    """Quantas pessoas em cada faixa de nota (P-061)."""

    baixa: int = Field(ge=0, description="Nota até 40.")
    media: int = Field(ge=0, description="Nota acima de 40 e até 70.")
    alta: int = Field(ge=0, description="Nota acima de 70.")


class PrismaAlignmentRead(BaseModel):
    """A distribuição de um prisma e a leitura dela (P-062)."""

    bands: AlignmentBandsRead
    level: Literal["alinhado", "moderado", "dividido"]


class TeamAlignmentRead(BaseModel):
    respondents: int = Field(ge=0, description="Pessoas do recorte com resposta.")
    prismas: dict[Prisma, PrismaAlignmentRead] | None = Field(
        description="Nulo quando o recorte não tem resposta."
    )


class DepartmentRowRead(BaseModel):
    """Um setor no mapa de setores e prismas, sempre da organização inteira."""

    department: DepartmentType
    respondents: int = Field(ge=0)
    scores: PrismaScores | None = Field(description="Nulo: setor sem resposta.")
    difference: PrismaScores | None = Field(
        description="Setor menos organização, prisma a prisma. Nulo: sem resposta."
    )


class DashboardMemberRead(BaseModel):
    """Uma pessoa no filtro de funcionário."""

    id: uuid.UUID = Field(description="O vínculo da pessoa (`member_id`).")
    label: str = Field(description="O nome da pessoa.")


class CompanyDashboardRead(DashboardResultRead):
    """O resultado da organização num período, com recorte por setor ou pessoa."""

    department: DepartmentType | None = Field(description="O setor do recorte.")
    member_id: uuid.UUID | None = Field(description="A pessoa do recorte.")
    departments: list[DepartmentType] = Field(
        description="Os setores com resposta no período, para o filtro do topo."
    )
    members: list[DashboardMemberRead] = Field(
        description=(
            "As pessoas com resposta no período, para o filtro do topo. Para a "
            "gestora, só ela mesma: o resultado individual é anônimo para a empresa."
        )
    )
    company_summary: CompanySummaryRead
    alignment: TeamAlignmentRead | None = Field(
        description="Nulo no recorte de uma pessoa: uma pessoa só não tem dispersão."
    )
    department_matrix: list[DepartmentRowRead] = Field(
        description=(
            "Uma linha por setor com resposta no período, da organização inteira. "
            "Setor cadastrado sem resposta fica de fora."
        )
    )


# ---------------------------------------------------------------------------
# GET /dashboards/overview — o retrato atual, só da administradora. Cada pessoa
# entra uma vez, com a resposta mais recente que enviou, seja qual for a data:
# as empresas e os mentorandos respondem a qualquer hora, e não há período em
# comum entre eles. A evolução no tempo fica dentro de cada empresa.
# ---------------------------------------------------------------------------


class OverviewGroupRead(BaseModel):
    """Uma empresa (ou um mentorando) no mapa do retrato atual."""

    id: uuid.UUID = Field(
        description="A organização; nos mentorandos, o vínculo do mentorando."
    )
    label: str = Field(description="O nome da organização ou do mentorando.")
    respondents: int = Field(ge=0, description="Pessoas no retrato.")
    scores: PrismaScores
    difference: PrismaScores = Field(
        description="O grupo menos a média geral, prisma a prisma."
    )


class OverviewDashboardRead(BaseModel):
    """O retrato atual de todas as empresas ou de todos os mentorandos."""

    kind: Literal["companies", "mentees"]
    responses_from: datetime = Field(
        description="Quando abriu o período mais antigo que entra no retrato."
    )
    responses_to: datetime = Field(
        description="Quando fechou o período mais recente que entra no retrato."
    )
    scores: PrismaScores = Field(description="Os 5 prismas, de 0 a 100.")
    dimensions: DimensionScores = Field(description="As 7 dimensões, de 0 a 100.")
    company_summary: CompanySummaryRead = Field(
        description=(
            "`concluidos`: pessoas no retrato; `convidados`: pessoas do público de "
            "algum período."
        )
    )
    alignment: TeamAlignmentRead
    groups: list[OverviewGroupRead] = Field(
        description="Uma linha por empresa (ou por mentorando) com resposta."
    )
    comparisons: list[PrismaComparisonRead] = Field(
        description=(
            "Uma por empresa (ou por mentorando), com `period` nulo e `scope` o id "
            "do grupo."
        )
    )
    creed_summary: CreedSummaryRead
