"""Regra de negócio do domínio forms

Esta camada não conhece HTTP nem detalhes de ORM. É onde a lógica vive,
isolada e testável.

O formulário pertence a uma organização, e é aqui que mora a regra de quem age
em qual organização. `questions` (`check_organization`, P-033) e `responses`
(`check_same_organization`, P-031) a usam pela composição, em vez de repetir a
comparação. Se a organização existe, quem responde é o `OrganizationService`.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.domains.forms.models import Form, FormStatus
from app.domains.forms.repository import FormRepository
from app.domains.forms.schemas import FormCreate, PeriodCreate, PeriodRead, PeriodStatus
from app.domains.organizacoes.service import OrganizationService
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PeriodClosedError,
    ValidationError,
)

ADMIN = "admin"


class PeriodLinkService(Protocol):
    async def get_member_link(
        self, organization_id: uuid.UUID, link_id: uuid.UUID
    ) -> object: ...


def period_status(form: Form, now: datetime) -> PeriodStatus:
    """A mesma janela de `get_current`: `opens_at <= agora < closes_at`.

    Pública porque `links` a usa para o período de cada membro (CREED-697).
    """
    if now < form.opens_at:  # type: ignore[operator]
        return PeriodStatus.SCHEDULED
    if now >= form.closes_at:  # type: ignore[operator]
        return PeriodStatus.PAST
    return PeriodStatus.OPEN


@dataclass
class DatedPeriod:
    """Um período com as duas datas garantidas: o `Form` as tem como opcionais.

    É o que `pick_period` devolve, para quem usa o período (o `links`, na lista de
    membros) ler as datas sem conferir nulo de novo, e a situação já calculada.
    """

    form: Form
    opens_at: datetime
    closes_at: datetime
    status: PeriodStatus


def pick_period(
    periods: list[Form], link_id: uuid.UUID, now: datetime
) -> DatedPeriod | None:
    """O período que vale para um membro agora, ou `None` se não houver nenhum.

    🟡 Premissa P-068: nesta ordem, o período aberto; se não houver, o próximo
    agendado (o que abre primeiro); se não houver, o último que fechou. Entre dois
    abertos, o individual vem antes do "para todos" e, depois, o que abriu por
    último (a mesma ordem do `FormRepository.get_open_for_link`). Confirmar na
    próxima reunião.

    Só contam os períodos que valem para o vínculo: os da organização inteira
    (`link_id` nulo) e os individuais dele. Formulário sem datas não é período.
    """
    open_now: list[DatedPeriod] = []
    scheduled: list[DatedPeriod] = []
    past: list[DatedPeriod] = []

    for form in periods:
        if form.opens_at is None or form.closes_at is None:
            continue
        if form.link_id is not None and form.link_id != link_id:
            continue

        status = period_status(form, now)
        period = DatedPeriod(
            form=form, opens_at=form.opens_at, closes_at=form.closes_at, status=status
        )
        if status is PeriodStatus.OPEN:
            open_now.append(period)
        elif status is PeriodStatus.SCHEDULED:
            scheduled.append(period)
        else:
            past.append(period)

    if open_now:
        individual = [p for p in open_now if p.form.link_id is not None]
        candidates = individual or open_now
        return max(candidates, key=_opens_at)
    if scheduled:
        return min(scheduled, key=_opens_at)
    if past:
        return max(past, key=_closes_at)
    return None


def _opens_at(period: DatedPeriod) -> datetime:
    return period.opens_at


def _closes_at(period: DatedPeriod) -> datetime:
    return period.closes_at


class FormService:
    def __init__(
        self,
        repository: FormRepository,
        organizations: OrganizationService,
        links: PeriodLinkService | None = None,
    ) -> None:
        self.repository = repository
        self.organizations = organizations
        self.links = links

    async def create(
        self, request: FormCreate, *, role: str, organization_id: uuid.UUID
    ) -> Form:
        """`role` e `organization_id` são de quem pede, não do formulário.

        A permissão vem antes da existência: um `gestor` que cadastra em
        organização alheia recebe 403 mesmo se ela não existir, para a resposta não
        revelar quais organizações existem (a mesma ordem de
        `OrganizationService.get`). A organização veio no corpo: inexistente é
        `ValidationError` (422).
        """
        self.check_organization(
            request.organization_id, role=role, organization_id=organization_id
        )

        if not await self.organizations.organization_exists(request.organization_id):
            raise ValidationError(f"Organização {request.organization_id} não encontrada")

        form = Form(
            name=request.name,
            organization_id=request.organization_id,
            status=FormStatus.DRAFT,
        )
        return await self.repository.create(form)

    async def get(self, form_id: uuid.UUID) -> Form:
        """Só "existe?". Sem regra de acesso: é o que os outros domínios usam."""
        form = await self.repository.get_by_id(form_id)

        if form is None:
            raise NotFoundError(f"Formulário {form_id} não encontrado")

        return form

    async def get_for_user(
        self, form_id: uuid.UUID, *, role: str, organization_id: uuid.UUID
    ) -> Form:
        """O formulário, se quem pede pode vê-lo: 404 antes de 403."""
        form = await self.get(form_id)
        self.check_organization(
            form.organization_id, role=role, organization_id=organization_id
        )
        return form

    async def get_current(
        self, *, link_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Form:
        """O formulário aberto agora para o vínculo de quem está logado.

        Vale a organização do vínculo, inclusive para o `admin` (P-031), e o status
        não é conferido (P-030).
        """
        form = await self.repository.get_open_for_link(
            organization_id, link_id, datetime.now(UTC)
        )

        if form is None:
            raise NotFoundError("Nenhum questionário disponível no momento")

        return form

    async def list_periods(
        self,
        target_organization_id: uuid.UUID,
        *,
        link_id: uuid.UUID | None,
        role: str,
        organization_id: uuid.UUID,
    ) -> list[PeriodRead]:
        """Os períodos da organização: "para todos", ou os de uma pessoa com `link_id`.

        `role` e `organization_id` são de quem pede. Só na organização do próprio
        vínculo, sem a exceção da P-033: o vínculo do `admin` é o da organização da
        CREED (P-048), onde estão os mentorandos. O `gestor` só vê os "para todos".
        """
        self.check_same_organization(
            target_organization_id, organization_id=organization_id
        )

        if link_id is not None and role != ADMIN:
            raise ForbiddenError("Só o admin consulta os períodos de uma pessoa")

        forms = await self.repository.list_periods(target_organization_id, link_id)
        now = datetime.now(UTC)

        return [PeriodRead.de_form(form, period_status(form, now)) for form in forms]

    async def create_period(
        self,
        target_organization_id: uuid.UUID,
        request: PeriodCreate,
        *,
        role: str,
        organization_id_user: uuid.UUID,
    ) -> Form:
        """Cria um formulário com período, para a organização ou um mentorando.

        A mesma audiência não pode ter períodos sobrepostos; intervalos que apenas
        se encostam também conflitam.
        """
        self.check_same_organization(
            target_organization_id, organization_id=organization_id_user
        )

        link_id = request.link_id
        if role == ADMIN and link_id is None:
            raise ForbiddenError("Admin precisa informar o link_id do mentorando")
        if role != ADMIN and link_id is not None:
            raise ForbiddenError("Só o admin pode criar período para um mentorando")

        if not await self.organizations.organization_exists(target_organization_id):
            raise NotFoundError(f"Organização {target_organization_id} não encontrada")

        if request.opens_at < datetime.now(UTC):
            raise ValidationError("opens_at não pode estar no passado")

        if link_id is not None:
            if self.links is None:
                raise RuntimeError("Serviço de vínculos não foi configurado")
            try:
                await self.links.get_member_link(target_organization_id, link_id)
            except NotFoundError as exc:
                raise ValidationError(exc.message) from exc

        if await self.repository.has_overlapping_period(
            target_organization_id,
            link_id,
            request.opens_at,
            request.closes_at,
        ):
            raise ConflictError("Já existe período para este público nesse intervalo")

        form = Form(
            name=(
                f"Questionário {request.opens_at:%Y-%m-%d} a {request.closes_at:%Y-%m-%d}"
            ),
            organization_id=target_organization_id,
            status=FormStatus.DRAFT,
            opens_at=request.opens_at,
            closes_at=request.closes_at,
            link_id=link_id,
        )
        return await self.repository.create(form)

    async def list_individual_form_ids(self, link_id: uuid.UUID) -> list[uuid.UUID]:
        """Os questionários feitos só para esta pessoa (os períodos individuais).

        Sem regra de acesso: é o que a exclusão de membro (M-3) usa, depois de
        conferir quem pede.
        """
        return await self.repository.list_ids_by_link(link_id)

    async def delete_individual_forms(self, form_ids: list[uuid.UUID]) -> None:
        """Apaga os questionários individuais da exclusão de membro (M-3).

        Quem chama já apagou as respostas e as perguntas deles: as duas tabelas
        apontam para `form`, e o banco recusaria a exclusão.
        """
        await self.repository.delete_by_ids(form_ids)

    async def check_accepts_answers(
        self, form_id: uuid.UUID, *, link_id: uuid.UUID
    ) -> None:
        """Só o público do questionário escreve, e só dentro do período.

        O público vem antes (403): quem não é o público não precisa saber do
        período. A janela é a mesma de `get_current`: `opens_at <= agora < closes_at`.
        Sem período, não aceita: não há exceção para formulário sem datas.
        """
        form = await self.get(form_id)

        if form.link_id is not None and form.link_id != link_id:
            raise ForbiddenError("Este questionário é destinado a outra pessoa")

        now = datetime.now(UTC)

        if form.opens_at is None or form.closes_at is None:
            raise PeriodClosedError("Este questionário não tem período definido")

        if now < form.opens_at:
            raise PeriodClosedError("O período deste questionário ainda não começou")

        if now >= form.closes_at:
            raise PeriodClosedError("O período deste questionário terminou")

    def check_organization(
        self,
        form_organization_id: uuid.UUID,
        *,
        role: str,
        organization_id: uuid.UUID,
    ) -> None:
        """Levanta `ForbiddenError` se quem pede não pode agir nessa organização.

        🟡 Premissa P-033 — o `admin` age em qualquer organização; `gestor` e
        `respondente`, só na do próprio vínculo. Confirmar na próxima reunião.
        """
        if role == ADMIN or form_organization_id == organization_id:
            return

        raise ForbiddenError("Sem acesso a formulário de outra organização")

    def check_same_organization(
        self, form_organization_id: uuid.UUID, *, organization_id: uuid.UUID
    ) -> None:
        """Como `check_organization`, mas sem exceção para o `admin`.

        É a regra de quem responde (P-031): a resposta sai com o vínculo do login,
        e o vínculo tem uma organização só, qualquer que seja o papel.
        """
        if form_organization_id != organization_id:
            raise ForbiddenError("Sem acesso a formulário de outra organização")
