"""Regra de negócio do domínio dashboards.

Esta camada não conhece HTTP nem ORM. O repository traz, numa consulta por
período, a média de 1 a 5 de cada pessoa em cada dimensão; daqui para a frente é
tudo em memória: a nota de cada pessoa (pelo `PrismaService`), a média de um grupo,
o recorte, as comparações, o resumo, o alinhamento e o mapa de setores.
"""

import logging
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from typing import TYPE_CHECKING, Literal

from app.domains.dashboards.models import Dashboard
from app.domains.dashboards.schemas import (
    AlignmentBandsRead,
    CompanyDashboardRead,
    CompanySummaryRead,
    ComparisonOptionsRead,
    CreedSummaryRead,
    DashboardCreate,
    DashboardMemberRead,
    DepartmentRowRead,
    HighlightRead,
    OverviewDashboardRead,
    OverviewGroupRead,
    PeriodOptionRead,
    PrismaAlignmentRead,
    PrismaComparisonRead,
    TeamAlignmentRead,
    UserDashboardRead,
)
from app.shared.enums import DepartmentType, Dimension, LinkType, Prisma
from app.shared.exceptions import ForbiddenError, NotFoundError, ValidationError

if TYPE_CHECKING:
    from app.domains.dashboards.repository import DashboardRepository, DimensionAverage
    from app.domains.forms.models import Form
    from app.domains.prismas.service import PrismaService
    from app.shared.authorization import AuthenticatedUser

logger = logging.getLogger(__name__)

ADMIN_ROLE = "admin"
GESTOR_ROLE = "gestor"

# 🟡 Premissa P-061 — faixas de nota do card de alinhamento, de 0 a 100.
BAIXA_ATE = 40
MEDIA_ATE = 70
# 🟡 Premissa P-062 — dividido quando baixa e alta passam de 30% cada; alinhado
# quando uma faixa sozinha tem 70% ou mais; moderado no resto.
DIVIDIDO_ACIMA_DE = 0.30
ALINHADO_A_PARTIR_DE = 0.70

# A empresa toda como referência de comparação, ao lado dos setores.
ORGANIZATION_SCOPE = "organization"


@dataclass(frozen=True)
class PersonScores:
    """A nota de uma pessoa num período: 5 prismas e 7 dimensões, de 0 a 100."""

    form_id: uuid.UUID
    link_id: uuid.UUID
    department: DepartmentType | None
    prismas: dict[Prisma, float]
    dimensions: dict[Dimension, float]


@dataclass(frozen=True)
class GroupScores:
    """A média de um grupo de pessoas: a média das notas de cada uma (D6)."""

    prismas: dict[Prisma, float]
    dimensions: dict[Dimension, float]


def group_average(people: Iterable[PersonScores]) -> GroupScores | None:
    """A média do grupo, prisma a prisma e dimensão a dimensão. Grupo vazio é None:
    zero seria uma nota, e o grupo não tem nenhuma."""
    people = list(people)
    if not people:
        return None
    return GroupScores(
        prismas={p: mean(person.prismas[p] for person in people) for p in Prisma},
        dimensions={
            d: mean(person.dimensions[d] for person in people) for d in Dimension
        },
    )


def _rounded[K](scores: dict[K, float]) -> dict[K, float]:
    """Em número inteiro, como a tela mostra."""
    return {key: float(round(value)) for key, value in scores.items()}


def _variation(
    shown: dict[Prisma, float], reference: dict[Prisma, float]
) -> dict[Prisma, float]:
    """Exibido menos referência, sobre os valores já arredondados: a tela mostra
    "62 / 59, aumentou 3", nunca "aumentou 4"."""
    shown, reference = _rounded(shown), _rounded(reference)
    return {p: shown[p] - reference[p] for p in Prisma}


def _highest_and_lowest(prismas: dict[Prisma, float]) -> tuple[Prisma, Prisma]:
    """Destaque e oportunidade. Empate: a ordem de `Prisma` desempata (decisão 7)."""
    ordem = list(Prisma)
    destaque = max(ordem, key=lambda p: (prismas[p], -ordem.index(p)))
    oportunidade = min(ordem, key=lambda p: (prismas[p], ordem.index(p)))
    return destaque, oportunidade


def _most_common(people: list[PersonScores], group: GroupScores) -> Prisma:
    """🟡 O prisma que mais vezes é o maior de cada pessoa (a moda). Empate: a maior
    média do grupo, e depois a ordem de `Prisma`."""
    ordem = list(Prisma)
    maiores = Counter(_highest_and_lowest(person.prismas)[0] for person in people)
    return max(
        ordem,
        key=lambda p: (maiores[p], group.prismas[p], -ordem.index(p)),
    )


def _alignment(people: list[PersonScores]) -> TeamAlignmentRead:
    """Quantas pessoas em cada faixa, prisma a prisma, e a leitura (P-061, P-062)."""
    if not people:
        return TeamAlignmentRead(respondents=0, prismas=None)

    total = len(people)
    prismas = {}
    for prisma in Prisma:
        notas = [round(person.prismas[prisma]) for person in people]
        bands = AlignmentBandsRead(
            baixa=sum(nota <= BAIXA_ATE for nota in notas),
            media=sum(BAIXA_ATE < nota <= MEDIA_ATE for nota in notas),
            alta=sum(nota > MEDIA_ATE for nota in notas),
        )
        level: Literal["alinhado", "moderado", "dividido"]
        if (
            bands.baixa / total > DIVIDIDO_ACIMA_DE
            and bands.alta / total > DIVIDIDO_ACIMA_DE
        ):
            level = "dividido"
        elif max(bands.baixa, bands.media, bands.alta) / total >= ALINHADO_A_PARTIR_DE:
            level = "alinhado"
        else:
            level = "moderado"
        prismas[prisma] = PrismaAlignmentRead(bands=bands, level=level)
    return TeamAlignmentRead(respondents=total, prismas=prismas)


def _creed_summary(group: GroupScores) -> CreedSummaryRead:
    """Textos vazios até a esteira de IA existir (D3); só as marcas dos cards."""
    destaque, oportunidade = _highest_and_lowest(group.prismas)
    return CreedSummaryRead(
        analiseTexto=[],
        recomendacaoTexto=[],
        prismas={},
        destaque=destaque,
        oportunidade=oportunidade,
    )


def _period_options(forms: list["Form"]) -> list[PeriodOptionRead]:
    return [
        PeriodOptionRead(id=form.id, opens_at=form.opens_at, closes_at=form.closes_at)
        for form in forms
    ]


def _default_period(forms: list["Form"], shown: "Form") -> uuid.UUID | None:
    """O período anterior ao exibido, ou None se ele é o mais antigo."""
    position = forms.index(shown)
    return forms[position + 1].id if position + 1 < len(forms) else None


def _pick_period(forms: list["Form"], period: uuid.UUID | None) -> "Form":
    """O período pedido, ou o mais recente. `forms` não pode vir vazio."""
    if period is None:
        return forms[0]
    found = next((form for form in forms if form.id == period), None)
    if found is None:
        raise NotFoundError(f"Sem resultado no período {period}")
    return found


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

    def _person_scores(self, rows: Iterable["DimensionAverage"]) -> list[PersonScores]:
        """Uma `PersonScores` por resposta, a partir das linhas da consulta agregada.

        Quem não tem as 7 dimensões fica de fora, com aviso: com todas as objetivas
        obrigatórias, não acontece numa resposta enviada.
        """
        if self.prismas_service is None:
            raise RuntimeError("PrismaService não configurado no DashboardService")

        grouped: dict[
            tuple[uuid.UUID, uuid.UUID],
            tuple[DepartmentType | None, dict[Dimension, float]],
        ] = {}
        for row in rows:
            _, averages = grouped.setdefault(
                (row.form_id, row.link_id), (row.department, {})
            )
            averages[row.dimension] = row.average

        people = []
        for (form_id, link_id), (department, averages) in grouped.items():
            try:
                prismas, dimensions = self.prismas_service.scores_from_dimension_averages(
                    averages
                )
            except ValidationError as exc:
                logger.warning(
                    "Vínculo %s fora do período %s por dimensão faltando: %s",
                    link_id,
                    form_id,
                    exc,
                )
                continue
            people.append(
                PersonScores(
                    form_id,
                    link_id,
                    department,
                    {p: prismas[p] for p in Prisma},
                    # Na ordem do questionário: o JSON sai sempre igual.
                    {d: dimensions[d] for d in Dimension},
                )
            )
        return people

    async def get_user_dashboard(
        self, *, user: "AuthenticatedUser", period: uuid.UUID | None
    ) -> UserDashboardRead:
        """O resultado de quem está logado: o período pedido (ou o mais recente que a
        pessoa respondeu) e a comparação com os outros que ela respondeu."""
        result = await self._individual_dashboard(
            user.link_uuid, user.organization_uuid, period
        )
        if result is None:
            raise NotFoundError("Você ainda não tem resultado")
        return result

    async def get_member_dashboard(
        self,
        *,
        user: "AuthenticatedUser",
        member_id: uuid.UUID,
        period: uuid.UUID | None,
    ) -> UserDashboardRead:
        """O resultado individual de um mentorando, visto pela administradora: o
        mesmo dashboard que ele vê, com os períodos que ele respondeu."""
        if user.role != ADMIN_ROLE:
            raise ForbiddenError("Só a administradora vê o resultado de um mentorando")
        creed = user.organization_uuid
        # Os mentorandos são vínculos de mentoria da CREED (P-048).
        mentees = await self.repository.list_link_ids(creed, LinkType.MENTORIA)
        if member_id not in mentees:
            raise NotFoundError(f"Mentorando {member_id} não encontrado")
        result = await self._individual_dashboard(member_id, creed, period)
        if result is None:
            raise NotFoundError("O mentorando ainda não tem resultado")
        names = await self.repository.list_member_names([member_id])
        return result.model_copy(update={"member_name": names.get(member_id)})

    async def _individual_dashboard(
        self,
        link_id: uuid.UUID,
        organization_id: uuid.UUID,
        period: uuid.UUID | None,
    ) -> UserDashboardRead | None:
        """O dashboard individual de um vínculo. Nulo se ele não respondeu nada."""
        forms = await self.repository.list_answered_forms(link_id)
        rows = await self.repository.list_dimension_averages(
            [form.id for form in forms], link_id=link_id
        )
        by_form = {person.form_id: person for person in self._person_scores(rows)}
        # Só período com nota: resposta sem as 7 dimensões não vira período na tela.
        answered = [form for form in forms if form.id in by_form]

        if not answered:
            return None
        try:
            shown = _pick_period(answered, period)
        except NotFoundError as exc:
            raise NotFoundError(f"Sem resultado seu no período {period}") from exc

        current = by_form[shown.id]
        group = GroupScores(current.prismas, current.dimensions)

        return UserDashboardRead(
            organization_name=await self._organization_name(organization_id),
            periods=_period_options(answered),
            period=shown.id,
            scores=_rounded(current.prismas),
            dimensions=_rounded(current.dimensions),
            comparison_options=ComparisonOptionsRead(
                periods=[form.id for form in answered],
                departments=[],
                default_period=_default_period(answered, shown),
            ),
            comparisons=[
                PrismaComparisonRead(
                    period=form.id,
                    scope=None,
                    scores=_rounded(by_form[form.id].prismas),
                    variation=_variation(current.prismas, by_form[form.id].prismas),
                    dimensions=_rounded(by_form[form.id].dimensions),
                )
                for form in answered
                if form.id != shown.id
            ],
            creed_summary=_creed_summary(group),
        )

    async def get_company_dashboard(
        self,
        *,
        user: "AuthenticatedUser",
        organization_id: uuid.UUID | None,
        period: uuid.UUID | None,
        department: DepartmentType | None,
        member_id: uuid.UUID | None,
    ) -> CompanyDashboardRead:
        """O resultado da organização num período, recortado por setor ou por pessoa.

        O recorte muda a página toda (notas, resumo, alinhamento e comparações),
        menos o mapa de setores, que é sempre a organização inteira no período.
        Entra nas médias só quem é do público do período (`list_invited_links`), a
        mesma regra dos convidados.
        """
        if department is not None and member_id is not None:
            raise ValidationError("Escolha um setor ou uma pessoa, não os dois")
        org_id = self._organization_for(user, organization_id)

        if member_id is not None:
            # O resultado individual é anônimo para a empresa: a gestora vê só o
            # dela. A admin (a CREED) vê o de qualquer pessoa.
            if user.role != ADMIN_ROLE and member_id != user.link_uuid:
                raise ForbiddenError("A gestora vê só o próprio resultado individual")
            if not await self.repository.link_in_organization(member_id, org_id):
                raise NotFoundError(f"Membro {member_id} não é desta organização")
            forms = [
                form
                for form in await self.repository.list_answered_forms(member_id)
                if form.organization_id == org_id
            ]
        else:
            forms = await self.repository.list_company_forms(org_id, datetime.now(UTC))

        rows = await self.repository.list_dimension_averages([f.id for f in forms])
        people = self._person_scores(rows)
        invited = {
            form.id: await self.repository.list_invited_links(form) for form in forms
        }
        by_form = {
            form.id: [
                person
                for person in people
                if person.form_id == form.id
                and person.link_id in {link.link_id for link in invited[form.id]}
            ]
            for form in forms
        }

        def in_view(person: PersonScores) -> bool:
            if member_id is not None:
                return person.link_id == member_id
            if department is not None:
                return person.department == department
            return True

        # Período com resultado é o que tem alguém respondido na organização (ou a
        # pessoa do recorte, que pode ter períodos individuais).
        if member_id is not None:
            answered = [f for f in forms if any(map(in_view, by_form[f.id]))]
        else:
            answered = [f for f in forms if by_form[f.id]]
        if not answered:
            raise NotFoundError("Ainda não há resultados")
        shown = _pick_period(answered, period)

        shown_people = by_form[shown.id]
        view_people = [person for person in shown_people if in_view(person)]
        current = group_average(view_people)
        if current is None:
            raise NotFoundError("Sem respostas deste recorte no período")

        all_departments = await self.repository.list_departments(org_id)
        with_answers = {person.department for person in shown_people}
        departments = [d for d in all_departments if d in with_answers]
        # As pessoas do filtro do topo: todas para a admin; para a gestora, só ela
        # (se respondeu o período). Uma empresa pode ter várias gestoras: cada
        # uma vê só a si mesma.
        visible = {
            person.link_id
            for person in shown_people
            if user.role == ADMIN_ROLE or person.link_id == user.link_uuid
        }
        names = await self.repository.list_member_names(list(visible))

        invited_in_view = [
            link
            for link in invited[shown.id]
            if (member_id is None or link.link_id == member_id)
            and (department is None or link.department == department)
        ]
        destaque, oportunidade = _highest_and_lowest(current.prismas)
        mais_comum = _most_common(view_people, current)
        rounded = _rounded(current.prismas)

        return CompanyDashboardRead(
            organization_name=await self._organization_name(org_id),
            periods=_period_options(answered),
            period=shown.id,
            scores=rounded,
            dimensions=_rounded(current.dimensions),
            comparison_options=ComparisonOptionsRead(
                periods=[form.id for form in answered],
                departments=departments,
                default_period=_default_period(answered, shown),
            ),
            comparisons=self._company_comparisons(
                answered,
                shown,
                by_form,
                current,
                in_view,
                department,
                member_id,
                departments,
            ),
            creed_summary=_creed_summary(current),
            department=department,
            member_id=member_id,
            departments=departments,
            members=sorted(
                (
                    DashboardMemberRead(id=link_id, label=names.get(link_id, ""))
                    for link_id in visible
                ),
                key=lambda member: member.label,
            ),
            company_summary=CompanySummaryRead(
                concluidos=len(view_people),
                convidados=max(len(invited_in_view), len(view_people)),
                destaque=HighlightRead(prisma=destaque, valor=rounded[destaque]),
                oportunidade=HighlightRead(
                    prisma=oportunidade, valor=rounded[oportunidade]
                ),
                maisComum=HighlightRead(prisma=mais_comum, valor=rounded[mais_comum]),
            ),
            alignment=None if member_id is not None else _alignment(view_people),
            department_matrix=self._department_matrix(all_departments, shown_people),
        )

    async def get_overview(
        self,
        *,
        user: "AuthenticatedUser",
        kind: Literal["companies", "mentees"],
    ) -> OverviewDashboardRead:
        """O retrato atual: cada pessoa entra uma vez, com a resposta mais recente
        que enviou, seja qual for o período. Só da administradora.

        As empresas e os mentorandos respondem a qualquer hora, e não há período
        em comum entre eles: juntar por período misturaria grupos diferentes e
        pareceria evolução. A evolução no tempo fica dentro de cada empresa.
        """
        if user.role != ADMIN_ROLE:
            raise ForbiddenError("Só a administradora vê o retrato de todos")

        creed = user.organization_uuid
        if kind == "companies":
            companies = dict(await self.repository.list_companies(exclude_id=creed))
            organization_ids = list(companies)
            allowed: set[uuid.UUID] | None = None
        else:
            companies = {}
            organization_ids = [creed]
            allowed = set(await self.repository.list_link_ids(creed, LinkType.MENTORIA))

        forms = {
            form.id: form
            for form in await self.repository.list_opened_forms(
                organization_ids, datetime.now(UTC)
            )
        }
        rows = await self.repository.list_dimension_averages(list(forms))
        invited = {
            form.id: {
                link.link_id for link in await self.repository.list_invited_links(form)
            }
            for form in forms.values()
        }
        if allowed is not None:
            invited = {form_id: links & allowed for form_id, links in invited.items()}

        # A resposta mais recente de cada pessoa, entre os períodos em que ela era
        # do público.
        latest: dict[uuid.UUID, PersonScores] = {}
        for person in self._person_scores(rows):
            if person.link_id not in invited[person.form_id]:
                continue
            current = latest.get(person.link_id)
            if current is None or (
                forms[person.form_id].closes_at > forms[current.form_id].closes_at  # type: ignore[operator]
            ):
                latest[person.link_id] = person
        snapshot = list(latest.values())

        overall = group_average(snapshot)
        if overall is None:
            raise NotFoundError("Ainda não há resultados")

        # Uma linha por empresa, ou por mentorando: o mapa, a comparação e a
        # lista do filtro do topo saem daqui.
        if kind == "companies":
            labels = companies

            def key_of(person: PersonScores) -> uuid.UUID:
                return forms[person.form_id].organization_id
        else:
            names = await self.repository.list_member_names(list(latest))
            labels = dict(sorted(names.items(), key=lambda item: item[1]))

            def key_of(person: PersonScores) -> uuid.UUID:
                return person.link_id

        groups = []
        comparisons = []
        for group_id, name in labels.items():
            members = [p for p in snapshot if key_of(p) == group_id]
            group = group_average(members)
            if group is None:
                continue
            groups.append(
                OverviewGroupRead(
                    id=group_id,
                    label=name,
                    respondents=len(members),
                    scores=_rounded(group.prismas),
                    difference=_variation(group.prismas, overall.prismas),
                )
            )
            comparisons.append(
                PrismaComparisonRead(
                    period=None,
                    scope=str(group_id),
                    scores=_rounded(group.prismas),
                    variation=_variation(overall.prismas, group.prismas),
                    dimensions=_rounded(group.dimensions),
                )
            )

        used = [forms[p.form_id] for p in snapshot]
        destaque, oportunidade = _highest_and_lowest(overall.prismas)
        mais_comum = _most_common(snapshot, overall)
        rounded = _rounded(overall.prismas)
        everyone = set().union(*invited.values()) if invited else set()

        return OverviewDashboardRead(
            kind=kind,
            responses_from=min(form.opens_at for form in used),  # type: ignore[type-var]
            responses_to=max(form.closes_at for form in used),  # type: ignore[type-var]
            scores=rounded,
            dimensions=_rounded(overall.dimensions),
            company_summary=CompanySummaryRead(
                concluidos=len(snapshot),
                convidados=max(len(everyone), len(snapshot)),
                destaque=HighlightRead(prisma=destaque, valor=rounded[destaque]),
                oportunidade=HighlightRead(
                    prisma=oportunidade, valor=rounded[oportunidade]
                ),
                maisComum=HighlightRead(prisma=mais_comum, valor=rounded[mais_comum]),
            ),
            alignment=_alignment(snapshot),
            groups=groups,
            comparisons=comparisons,
            creed_summary=_creed_summary(overall),
        )

    def _company_comparisons(
        self,
        answered: list["Form"],
        shown: "Form",
        by_form: dict[uuid.UUID, list[PersonScores]],
        current: GroupScores,
        in_view: Callable[[PersonScores], bool],
        department: DepartmentType | None,
        member_id: uuid.UUID | None,
        departments: list[DepartmentType],
    ) -> list[PrismaComparisonRead]:
        """Todas as combinações de período e escopo (D4). Escopo nulo é o mesmo
        recorte; um setor; ou a empresa toda. Referência sem ninguém respondido
        fica de fora: a tela mostra "sem comparação".

        O próprio recorte no período exibido também fica de fora: ele contra ele
        mesmo. Como escopo, o recorte é o setor dele, ou a empresa toda na
        organização inteira; em outro período, ele é uma comparação como as
        outras (é o que a tela usa ao escolher o próprio recorte na lista).
        """
        scopes: list[DepartmentType | str | None] = [
            None,
            *departments,
            ORGANIZATION_SCOPE,
        ]
        own_scope: DepartmentType | str | None = (
            department
            if department is not None
            else (None if member_id is not None else ORGANIZATION_SCOPE)
        )

        comparisons = []
        for form in answered:
            for scope in scopes:
                same_period = form.id == shown.id
                if same_period and (scope is None or scope == own_scope):
                    continue  # é o próprio recorte exibido
                people = by_form[form.id]
                if scope is None:
                    reference = [person for person in people if in_view(person)]
                elif scope == ORGANIZATION_SCOPE:
                    reference = people
                else:
                    reference = [p for p in people if p.department == scope]
                group = group_average(reference)
                if group is None:
                    continue
                comparisons.append(
                    PrismaComparisonRead(
                        period=None if same_period else form.id,
                        scope=scope.value if isinstance(scope, DepartmentType) else scope,
                        scores=_rounded(group.prismas),
                        variation=_variation(current.prismas, group.prismas),
                        dimensions=_rounded(group.dimensions),
                    )
                )
        return comparisons

    def _department_matrix(
        self, departments: list[DepartmentType], people: list[PersonScores]
    ) -> list[DepartmentRowRead]:
        """Uma linha por setor com resposta no período: a nota do setor e a
        diferença para a organização inteira. Setor sem resposta fica de fora,
        como no filtro do topo e na comparação. Quem não tem setor entra só na
        organização."""
        organization = group_average(people)
        rows = []
        for department in departments:
            of_department = [p for p in people if p.department == department]
            group = group_average(of_department)
            if group is None:
                continue
            rows.append(
                DepartmentRowRead(
                    department=department,
                    respondents=len(of_department),
                    scores=_rounded(group.prismas) if group else None,
                    difference=(
                        _variation(group.prismas, organization.prismas)
                        if group and organization
                        else None
                    ),
                )
            )
        return rows

    def _organization_for(
        self, user: "AuthenticatedUser", organization_id: uuid.UUID | None
    ) -> uuid.UUID:
        """A organização que o dashboard mostra. A admin escolhe (a dela é a CREED,
        não a empresa que quer ver); a gestora vê só a do próprio vínculo."""
        if user.role == ADMIN_ROLE:
            if organization_id is None:
                raise ValidationError("A administradora precisa informar a organização")
            return organization_id
        if user.role == GESTOR_ROLE:
            if organization_id not in (None, user.organization_uuid):
                raise ForbiddenError("Sem acesso ao dashboard de outra organização")
            return user.organization_uuid
        raise ForbiddenError("Só gestores e administradores veem o dashboard da empresa")

    async def _organization_name(self, organization_id: uuid.UUID) -> str:
        return (
            await self.repository.get_organization_name(organization_id) or "Organização"
        )
