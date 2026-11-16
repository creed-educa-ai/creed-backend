"""Regra de negócio do domínio insights.

Esta camada não conhece HTTP nem detalhes de ORM.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.domains.dashboards.service import DashboardService
from app.domains.insights.models import Insight, InsightPrisma, InsightStatus
from app.domains.insights.repository import (
    InsightPrismaRepository,
    InsightRepository,
    ResponseOwner,
)
from app.domains.insights.schemas import (
    InsightCallbackDone,
    InsightCallbackFailed,
    InsightStatusRead,
)
from app.domains.prismas.service import PrismaService, highest_and_lowest
from app.external_services.n8n.client import N8NClient
from app.external_services.n8n.exceptions import N8NUnavailableError
from app.external_services.n8n.schemas import (
    AlignmentByPrisma,
    DepartmentScores,
    DimensionScores,
    IndividualInsightRequest,
    InsightRequest,
    InsightResult,
    OpenAnswer,
    OrganizationInsightRequest,
    Participation,
    Period,
    PrismaScores,
)
from app.shared.enums import LinkType, Prisma
from app.shared.exceptions import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from app.shared.authorization import AuthenticatedUser

logger = logging.getLogger(__name__)

ADMIN_ROLE = "admin"

# A espera dobra a cada falha, a partir daqui: 30 s, 1 min, 2 min, 4 min (ADR-0010).
FIRST_RETRY_DELAY = timedelta(seconds=30)

# 🟡 Premissa P-089 — a empresa recebe um insight por período só com 5 ou mais
# respostas enviadas, regerado no máximo a cada 30 min enquanto chegam respostas. O
# mesmo piso vale para cada setor no pedido. Confirmar na próxima reunião.
ORGANIZATION_MIN_RESPONSES = 5
ORGANIZATION_DEBOUNCE = timedelta(minutes=30)


@dataclass(frozen=True)
class DispatchLimits:
    """Os números do worker, que moram em `settings` (ADR-0010, item 3).

    Chegam de quem chama, o worker, como os parâmetros de uma rota chegam do router:
    nenhum domínio lê `settings` direto.
    """

    batch_size: int
    max_in_flight: int
    max_attempts: int
    dispatch_timeout_seconds: int


def _as_on_screen(score: float) -> float:
    """A nota em número inteiro, como o dashboard mostra (o `_rounded` de lá).

    O texto da IA não pode citar 61,3 para quem vê 61 na tela.
    """
    return float(round(score))


def _can_read_insight(owner: ResponseOwner, user: "AuthenticatedUser") -> bool:
    """O dono da resposta lê o próprio insight. A administradora lê também o dos
    mentorandos, que são os vínculos de mentoria da CREED (P-048).

    🟡 Premissa P-086 — a gestora não lê o insight individual de ninguém, nem o dos
    membros da própria empresa: o resultado individual é anônimo para a empresa.
    Confirmar na próxima reunião.
    """
    if owner.link_id == user.link_uuid:
        return True
    return (
        user.role == ADMIN_ROLE
        and owner.link_type is LinkType.MENTORIA
        and owner.organization_id == user.organization_uuid
    )


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
    def __init__(
        self,
        repository: InsightRepository,
        prismas: PrismaService,
        n8n: N8NClient | None = None,
        dashboards: DashboardService | None = None,
    ) -> None:
        self.repository = repository
        self.prismas = prismas
        # Só o worker passa o client e os dashboards: o envio da resposta e a
        # exclusão de membro usam este service sem falar com o N8N e sem montar
        # pedido.
        self.n8n = n8n
        self.dashboards = dashboards

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

    async def request_organization(self, form_response_id: uuid.UUID) -> None:
        """Agenda o insight da empresa do período desta resposta, se o período chegou
        ao piso (CREED-8013).

        Quem chama é o envio da resposta, na transação dele, logo depois do pedido
        individual. Com o piso atingido, grava um pedido `pending` para daqui a
        `ORGANIZATION_DEBOUNCE`, e só se o período ainda não tem um esperando. Assim
        um pico de envios vira um pedido só, e o texto acompanha o período com até
        30 min de atraso. Um pedido já `dispatched` não segura o próximo.
        """
        scope = await self.repository.get_form_scope(form_response_id)
        if scope is None:
            raise NotFoundError(f"FormResponse {form_response_id} não encontrado")
        if scope.individual_form:
            # O questionário do mentorando é de uma pessoa só: não há grupo para ler.
            return

        # A trava vem antes da contagem: é ela que faz o segundo de dois envios
        # simultâneos contar o primeiro.
        await self.repository.lock_period(scope.form_id)
        submitted = await self.repository.count_submitted_with(
            scope.form_id, form_response_id
        )
        if submitted < ORGANIZATION_MIN_RESPONSES:
            return

        await self.repository.schedule_organization(
            scope.organization_id, scope.form_id, ORGANIZATION_DEBOUNCE
        )

    async def build_individual_payload(
        self, insight: Insight
    ) -> IndividualInsightRequest:
        """Monta o pedido `insight-v1` de um insight individual (CREED-803, P-087).

        O payload é montado na hora do disparo, não no envio: a resposta enviada não
        muda (P-032). As notas, o destaque e a oportunidade vêm do cálculo do back,
        nunca da IA (princípio 1). O pedido não leva nada que identifique a pessoa
        (P-091): só o id do insight, as notas e as respostas descritivas como foram
        escritas.
        """
        form_response_id = insight.form_response_id
        if form_response_id is None:
            # Erro de quem chama: o insight da empresa tem pedido próprio (CREED-8013).
            raise ValueError(f"O insight {insight.id} é da empresa, não de uma resposta")

        prismas, dimensions = await self.prismas.calculate_for_dispatch(form_response_id)
        # Sobre as notas sem arredondar, como o dashboard faz.
        destaque, oportunidade = highest_and_lowest(prismas)
        descriptive = await self.repository.list_descriptive_answers(form_response_id)

        return IndividualInsightRequest(
            contract_version="insight-v1",
            scope="individual",
            insight_id=insight.id,
            # A reivindicação já contou esta tentativa (ADR-0010, item 3).
            attempt=insight.attempts,
            language="pt-BR",  # P-092: o back ainda não guarda o idioma da pessoa
            result=InsightResult(
                prismas=PrismaScores.model_validate(
                    {prisma.value: _as_on_screen(s) for prisma, s in prismas.items()}
                ),
                dimensions=DimensionScores.model_validate(
                    {dim.value: _as_on_screen(s) for dim, s in dimensions.items()}
                ),
                destaque=destaque,
                oportunidade=oportunidade,
            ),
            # Pergunta descritiva deixada em branco não é resposta: não vai.
            open_answers=[
                OpenAnswer(
                    section=item.section, question=item.question, answer=item.answer
                )
                for item in descriptive
                if item.answer is not None and item.answer.strip()
            ],
        )

    async def build_organization_payload(
        self, insight: Insight
    ) -> OrganizationInsightRequest:
        """Monta o pedido `insight-v1` do insight da empresa (CREED-8013).

        Os números são os do dashboard da empresa no período, sem recorte, pedidos na
        hora do disparo: o texto fala do que a tela mostra. Só vão os setores com o
        piso de respostas (P-089), e nenhuma resposta aberta (P-090).

        O piso da empresa é conferido de novo aqui, e não só no agendamento: nos 30
        min de espera, a exclusão de membro (M-3) pode apagar respostas, e a conta do
        agendamento não é a do dashboard (lá contam todas as enviadas; aqui, só as do
        público com nota). Sem esta conferência, o texto sairia sobre 4 pessoas, ou
        sobre 1, e a gestora leria o resultado individual de alguém (P-086).
        """
        if insight.form_response_id is not None:
            # Erro de quem chama: o insight de uma resposta tem pedido próprio.
            raise ValueError(f"O insight {insight.id} é de uma resposta, não da empresa")

        numbers = await self._dashboards().company_period_numbers(
            insight.organization_id, insight.form_id
        )
        if numbers is None:
            raise ValidationError(
                f"O período {insight.form_id} não tem resultado da empresa"
            )
        if numbers.submitted < ORGANIZATION_MIN_RESPONSES:
            raise ValidationError(
                f"O período {insight.form_id} tem {numbers.submitted} respostas, "
                f"abaixo do piso de {ORGANIZATION_MIN_RESPONSES}"
            )

        return OrganizationInsightRequest(
            contract_version="insight-v1",
            scope="organization",
            insight_id=insight.id,
            # A reivindicação já contou esta tentativa (ADR-0010, item 3).
            attempt=insight.attempts,
            language="pt-BR",  # P-092
            period=Period(opens_at=numbers.opens_at, closes_at=numbers.closes_at),
            participation=Participation(
                submitted=numbers.submitted, invited=numbers.invited
            ),
            result=InsightResult(
                prismas=PrismaScores.model_validate(
                    {prisma.value: score for prisma, score in numbers.scores.items()}
                ),
                dimensions=DimensionScores.model_validate(
                    {dim.value: score for dim, score in numbers.dimensions.items()}
                ),
                destaque=numbers.destaque,
                oportunidade=numbers.oportunidade,
            ),
            departments=[
                DepartmentScores(
                    department=row.department,
                    submitted=row.respondents,
                    prismas=PrismaScores.model_validate(
                        {prisma.value: score for prisma, score in row.scores.items()}
                    ),
                )
                for row in numbers.departments
                if row.scores is not None
                and row.respondents >= ORGANIZATION_MIN_RESPONSES
            ],
            alignment=AlignmentByPrisma.model_validate(
                {
                    prisma.value: alignment.model_dump()
                    for prisma, alignment in numbers.alignment.items()
                }
            ),
        )

    async def delete_for_form_responses(self, form_response_ids: list[uuid.UUID]) -> None:
        """Apaga os insights das respostas que a exclusão de membro (M-3) remove."""
        await self.repository.delete_by_form_responses(form_response_ids)

    # --- O ciclo do worker (CREED-804, ADR-0010 item 3) ----------------------------
    # Dois passos, cada um na sua unidade de trabalho, que o worker abre: reivindicar
    # (e gravar a reivindicação) e só depois disparar. Assim um pedido nunca sai sem
    # estar marcado `dispatched`, e uma queda no meio cai na varredura.

    async def claim_due_batch(self, limits: DispatchLimits) -> list[InsightRequest]:
        """Reivindica os pedidos que podem sair agora e devolve os payloads.

        Devolve à fila os `dispatched` esquecidos, confere o teto de pedidos em voo,
        reivindica até `batch_size` `pending` vencidos e os marca `dispatched`, com
        `attempts + 1`. Sem esteira configurada, não mexe em nada.
        """
        if not self._n8n().is_configured:
            logger.debug(
                "Esteira de insights desligada: "
                "N8N_WEBHOOK_URL ou N8N_WEBHOOK_TOKEN vazio."
            )
            return []

        await self.repository.lock_dispatch()
        # As datas gravadas aqui saem do relógio do banco, o mesmo com que
        # `claim_due` e `list_stale` as comparam depois.
        now = await self.repository.database_now()

        stale = await self.repository.list_stale(limits.dispatch_timeout_seconds)
        for insight in stale:
            self._retry_or_fail(
                insight,
                f"sem volta do N8N em {limits.dispatch_timeout_seconds} s",
                limits.max_attempts,
                now,
            )
        # A contagem abaixo precisa enxergar os que a varredura acabou de soltar.
        await self.repository.flush()

        free_slots = limits.max_in_flight - await self.repository.count_dispatched()
        if free_slots <= 0:
            return []

        claimed = await self.repository.claim_due(min(limits.batch_size, free_slots))
        payloads: list[InsightRequest] = []
        for insight in claimed:
            insight.status = InsightStatus.DISPATCHED
            insight.attempts += 1
            insight.dispatched_at = now
            try:
                payloads.append(await self._build_payload(insight))
            except (DomainError, ValueError) as exc:
                # A resposta não vira pedido, e tentar de novo não muda isso. O
                # `ValueError` cobre também o `ValidationError` do Pydantic, que herda
                # dele. Sem este `except`, a exceção desfaria a reivindicação inteira,
                # e o mesmo pedido voltaria primeiro na fila a cada ciclo, travando os
                # outros. Erro de banco não é pego: desfaz o ciclo, e o próximo tenta.
                logger.warning("Pedido do insight %s não montado: %s", insight.id, exc)
                self._fail(insight, f"pedido não montado: {exc}")
        return payloads

    async def dispatch(self, payload: InsightRequest, limits: DispatchLimits) -> None:
        """Entrega ao N8N um pedido já reivindicado.

        Se o N8N não recebe, o pedido volta à fila com espera, ou vira `failed` no
        limite. Se recebe, nada muda aqui: o texto chega pela volta (CREED-805).
        """
        try:
            await self._n8n().dispatch(payload)
        except N8NUnavailableError as exc:
            logger.warning(
                "Insight %s não entregue ao N8N: %s", payload.insight_id, exc.message
            )
            insight = await self.repository.get_for_update(payload.insight_id)
            # A falha só vale para a tentativa que falhou. Se a volta chegou antes (o
            # N8N recebeu e só a resposta HTTP se perdeu), ou se a varredura já o
            # soltou e outro ciclo o reivindicou de novo, o pedido já está em outra
            # tentativa, e registrar a falha desta o devolveria à fila em pleno voo.
            if (
                insight is not None
                and insight.status is InsightStatus.DISPATCHED
                and insight.attempts == payload.attempt
            ):
                now = await self.repository.database_now()
                self._retry_or_fail(insight, exc.message, limits.max_attempts, now)

    # --- A volta da esteira (CREED-805, spec da CREED-80 "Volta: N8N → back") ------

    async def complete(
        self,
        callback: InsightCallbackDone | InsightCallbackFailed,
        max_attempts: int,
    ) -> None:
        """Aplica a volta do N8N ao insight, pela tabela de idempotência da spec.

        O N8N pode reenviar, e um `failed` pode chegar depois de um `done`. Quem
        terminou antes não muda: o primeiro `done` vence, e um `failed` não desfaz
        nada. Um `failed` só vale para a tentativa em voo, como no `dispatch`. O
        insight fica travado até o fim da transação, para dois callbacks ao mesmo
        tempo não passarem juntos pela conferência do estado.

        `max_attempts` vem de quem chama, como os limites do worker (`DispatchLimits`).
        """
        insight = await self.repository.get_for_update(callback.insight_id)
        if insight is None:
            logger.warning(
                "Volta do N8N para um insight desconhecido: %s", callback.insight_id
            )
            raise NotFoundError(f"Insight {callback.insight_id} não encontrado")

        if insight.status is InsightStatus.DONE:
            return

        now = await self.repository.database_now()

        if isinstance(callback, InsightCallbackDone):
            # Vale também sobre `failed`: um texto que chega atrasado é melhor que a
            # tela dizer "indisponível".
            insight.status = InsightStatus.DONE
            insight.content = callback.content.model_dump(mode="json")
            insight.model_id = callback.model_id
            insight.prompt_version = callback.prompt_version
            insight.completed_at = now
            return

        # A falha de uma tentativa que já terminou não vale. Se a varredura soltou a
        # tentativa 1 e o worker mandou a 2, um `failed` atrasado da 1 devolveria à
        # fila, ou encerraria, um pedido com a 2 ainda em voo. Também não vale sobre
        # `pending`: quem o pôs lá já contou a falha daquela tentativa.
        if (
            insight.status is not InsightStatus.DISPATCHED
            or insight.attempts != callback.attempt
        ):
            logger.info(
                "Falha da tentativa %s do insight %s ignorada: ele está %s, na "
                "tentativa %s",
                callback.attempt,
                insight.id,
                insight.status.value,
                insight.attempts,
            )
            return

        error = f"N8N devolveu falha: {callback.error}"
        if callback.retryable:
            self._retry_or_fail(insight, error, max_attempts, now)
        else:
            # Recusa do modelo: tentar de novo não muda o resultado.
            self._fail(insight, error)

    async def get_status(
        self, form_response_id: uuid.UUID, *, user: "AuthenticatedUser"
    ) -> InsightStatusRead:
        """O estado do insight de uma resposta, para quem pode lê-lo: 404 antes de 403.

        Resposta que existe mas não tem insight (ainda em andamento, ou enviada antes
        de a esteira existir) também é 404: não há o que mostrar.
        """
        owner = await self.repository.get_response_owner(form_response_id)
        if owner is None:
            raise NotFoundError(
                f"Resposta de formulário {form_response_id} não encontrada"
            )
        if not _can_read_insight(owner, user):
            raise ForbiddenError("Sem acesso ao insight de outro respondente")

        insight = await self.repository.get_by_form_response(form_response_id)
        if insight is None:
            raise NotFoundError(f"A resposta {form_response_id} não tem insight")
        return InsightStatusRead.de_model(insight)

    def _retry_or_fail(
        self, insight: Insight, error: str, max_attempts: int, now: datetime
    ) -> None:
        """A regra de falha da esteira: nova tentativa com espera, ou `failed` no
        limite. `attempts` já conta a tentativa que falhou, e `now` é o relógio do
        banco."""
        if insight.attempts >= max_attempts:
            self._fail(insight, error)
            return
        insight.status = InsightStatus.PENDING
        insight.last_error = error
        insight.next_attempt_at = now + FIRST_RETRY_DELAY * 2 ** (insight.attempts - 1)

    def _fail(self, insight: Insight, error: str) -> None:
        insight.status = InsightStatus.FAILED
        insight.last_error = error

    async def _build_payload(self, insight: Insight) -> InsightRequest:
        """O pedido do escopo do insight: sem resposta, é o da empresa."""
        if insight.form_response_id is None:
            return await self.build_organization_payload(insight)
        return await self.build_individual_payload(insight)

    def _n8n(self) -> N8NClient:
        if self.n8n is None:
            raise RuntimeError("N8NClient não configurado no InsightService")
        return self.n8n

    def _dashboards(self) -> DashboardService:
        if self.dashboards is None:
            raise RuntimeError("DashboardService não configurado no InsightService")
        return self.dashboards
