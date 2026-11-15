"""Testes dos services do domínio insights.

O repository é simulado para testar as regras de negócio
sem acessar o banco de dados.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import TypeAdapter

from app.domains.dashboards.schemas import (
    AlignmentBandsRead,
    DepartmentRowRead,
    PrismaAlignmentRead,
)
from app.domains.dashboards.service import CompanyPeriodNumbers, DashboardService
from app.domains.insights.models import Insight, InsightPrisma, InsightStatus
from app.domains.insights.repository import (
    DescriptiveAnswer,
    FormScope,
    InsightPrismaRepository,
    InsightRepository,
    ResponseOwner,
)
from app.domains.insights.schemas import InsightCallbackDone, InsightCallbackFailed
from app.domains.insights.service import (
    DispatchLimits,
    InsightPrismaService,
    InsightService,
)
from app.domains.prismas.service import PrismaService
from app.external_services.n8n.client import N8NClient
from app.external_services.n8n.exceptions import N8NUnavailableError
from app.external_services.n8n.schemas import (
    IndividualInsightRequest,
    InsightRequest,
    OpenAnswer,
    OrganizationInsightRequest,
)
from app.shared.authorization import AuthenticatedUser
from app.shared.enums import DepartmentType, Dimension, LinkType, Prisma
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from scripts.exportar_contrato_n8n import CONTRACT_DIR


def _um_insight(insight_id: uuid.UUID) -> Insight:
    return Insight(
        id=insight_id,
        form_response_id=uuid.uuid4(),
        content="texto da analise",
    )


async def test_associar_prisma_a_insight_existente() -> None:
    insight_id = uuid.uuid4()
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.get.return_value = None
    repository.insert.side_effect = lambda associacao: associacao
    service = InsightPrismaService(repository)

    resultado = await service.associate(insight_id, Prisma.SEGURANCA_PSICOLOGICA)

    repository.insert.assert_awaited_once()
    enviado = repository.insert.await_args.args[0]

    assert isinstance(enviado, InsightPrisma)
    assert enviado.insight_id == insight_id
    assert enviado.prisma == Prisma.SEGURANCA_PSICOLOGICA
    assert resultado is enviado


async def test_mesmo_insight_aceita_varios_prismas() -> None:
    """A relação é N:N: o insight pode encostar em mais de uma dimensão."""
    insight_id = uuid.uuid4()
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.get.return_value = None
    repository.insert.side_effect = lambda associacao: associacao
    service = InsightPrismaService(repository)

    await service.associate(insight_id, Prisma.SEGURANCA_PSICOLOGICA)
    await service.associate(insight_id, Prisma.LIDERANCA_ADAPTATIVA)

    assert repository.insert.await_count == 2


async def test_associacao_duplicada_lanca_conflict_error() -> None:
    insight_id = uuid.uuid4()
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.get.return_value = InsightPrisma(
        insight_id=insight_id, prisma=Prisma.CULTURA_EMPREENDEDORA
    )
    service = InsightPrismaService(repository)

    with pytest.raises(ConflictError):
        await service.associate(insight_id, Prisma.CULTURA_EMPREENDEDORA)

    repository.insert.assert_not_awaited()


async def test_associar_a_insight_inexistente_lanca_not_found_error() -> None:
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = None
    service = InsightPrismaService(repository)

    insight_id = uuid.uuid4()

    with pytest.raises(NotFoundError):
        await service.associate(insight_id, Prisma.NEUROINOVACAO_PRISMA)

    repository.get_insight.assert_awaited_once_with(insight_id)
    repository.insert.assert_not_awaited()


async def test_listar_prismas_de_um_insight() -> None:
    insight_id = uuid.uuid4()
    associacoes = [
        InsightPrisma(insight_id=insight_id, prisma=Prisma.SEGURANCA_PSICOLOGICA),
        InsightPrisma(insight_id=insight_id, prisma=Prisma.LIDERANCA_ADAPTATIVA),
    ]
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.list_by_insight.return_value = associacoes
    service = InsightPrismaService(repository)

    resultado = await service.list_prismas(insight_id)

    assert resultado == associacoes


async def test_listar_de_insight_inexistente_lanca_not_found_error() -> None:
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = None
    service = InsightPrismaService(repository)

    with pytest.raises(NotFoundError):
        await service.list_prismas(uuid.uuid4())


async def test_remover_associacao_existente() -> None:
    insight_id = uuid.uuid4()
    associacao = InsightPrisma(
        insight_id=insight_id, prisma=Prisma.ADAPTABILIDADE_COGNITIVA
    )
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get.return_value = associacao
    service = InsightPrismaService(repository)

    await service.dissociate(insight_id, Prisma.ADAPTABILIDADE_COGNITIVA)

    repository.delete.assert_awaited_once_with(associacao)


async def test_remover_associacao_inexistente_lanca_not_found_error() -> None:
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get.return_value = None
    service = InsightPrismaService(repository)

    with pytest.raises(NotFoundError):
        await service.dissociate(uuid.uuid4(), Prisma.SEGURANCA_PSICOLOGICA)

    repository.delete.assert_not_awaited()


async def test_colisao_no_flush_vira_conflict_error() -> None:
    """Quando o par foi gravado entre a checagem e o flush, o repository
    devolve `None` e é aqui que isso vira erro de domínio."""
    insight_id = uuid.uuid4()
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.get.return_value = None
    repository.insert.return_value = None
    service = InsightPrismaService(repository)

    with pytest.raises(ConflictError):
        await service.associate(insight_id, Prisma.SEGURANCA_PSICOLOGICA)

    repository.insert.assert_awaited_once()


# --- InsightService: o pedido que o envio da resposta grava (CREED-802) --------


async def test_pedido_individual_leva_organizacao_e_periodo_da_resposta() -> None:
    resposta, organizacao, formulario = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    repository = AsyncMock(spec=InsightRepository)
    repository.get_form_scope.return_value = FormScope(organizacao, formulario, False)
    repository.create.side_effect = lambda insight: insight
    service = InsightService(repository, AsyncMock(spec=PrismaService))

    resultado = await service.request_individual(resposta)

    repository.get_form_scope.assert_awaited_once_with(resposta)
    enviado = repository.create.await_args.args[0]
    assert isinstance(enviado, Insight)
    assert enviado.organization_id == organizacao
    assert enviado.form_id == formulario
    assert enviado.form_response_id == resposta
    # Sem texto e sem estado escolhido aqui: o `pending` é o padrão do model.
    assert enviado.content is None
    assert resultado is enviado


async def test_pedido_de_resposta_inexistente_vira_not_found() -> None:
    repository = AsyncMock(spec=InsightRepository)
    repository.get_form_scope.return_value = None
    service = InsightService(repository, AsyncMock(spec=PrismaService))

    with pytest.raises(NotFoundError):
        await service.request_individual(uuid.uuid4())

    repository.create.assert_not_awaited()


async def test_resposta_que_ja_tem_insight_vira_conflict() -> None:
    """P-042: uma resposta, um insight. O repository devolve `None` na corrida."""
    repository = AsyncMock(spec=InsightRepository)
    repository.get_form_scope.return_value = FormScope(uuid.uuid4(), uuid.uuid4(), False)
    repository.create.return_value = None
    service = InsightService(repository, AsyncMock(spec=PrismaService))

    with pytest.raises(ConflictError):
        await service.request_individual(uuid.uuid4())


# --- InsightService: o pedido que vai ao N8N (CREED-803) ------------------------


def _notas(
    **prismas: float,
) -> tuple[dict[Prisma, float], dict[Dimension, float]]:
    """Notas de 0 a 100 como o `PrismaService` devolve: sem arredondar."""
    notas = {
        Prisma.SEGURANCA_PSICOLOGICA: 85.4,
        Prisma.LIDERANCA_ADAPTATIVA: 72.6,
        Prisma.CULTURA_EMPREENDEDORA: 80.0,
        Prisma.ADAPTABILIDADE_COGNITIVA: 61.3,
        Prisma.NEUROINOVACAO_PRISMA: 74.6,
    }
    notas |= {Prisma(chave): valor for chave, valor in prismas.items()}
    return notas, dict.fromkeys(Dimension, 70.25)


def _pedido(attempts: int = 1) -> Insight:
    """Um insight já reivindicado: a reivindicação soma a tentativa antes de montar
    o pedido (ADR-0010, item 3)."""
    return Insight(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        form_id=uuid.uuid4(),
        form_response_id=uuid.uuid4(),
        attempts=attempts,
    )


def _service_do_pedido(
    descritivas: list[DescriptiveAnswer],
    notas: tuple[dict[Prisma, float], dict[Dimension, float]] | None = None,
) -> tuple[InsightService, AsyncMock]:
    repository = AsyncMock(spec=InsightRepository)
    repository.list_descriptive_answers.return_value = descritivas
    prismas = AsyncMock(spec=PrismaService)
    prismas.calculate_for_dispatch.return_value = notas or _notas()
    return InsightService(repository, prismas), prismas


def _forma(valor: Any) -> Any:
    """As chaves e os tipos de um JSON, em qualquer profundidade, sem os valores."""
    if isinstance(valor, dict):
        return {chave: _forma(item) for chave, item in valor.items()}
    if isinstance(valor, list):
        return [_forma(valor[0])] if valor else []
    return type(valor).__name__


ABERTAS = [
    DescriptiveAnswer("S9", "Quais desafios você observa?", "Reuniões dominadas."),
    DescriptiveAnswer("S9", "Outras recomendações e sugestões.", "Mais trocas."),
]


async def test_pedido_tem_a_forma_do_exemplo_do_kit() -> None:
    """O N8N roda com o `exemplo-ida-individual.json` fixado: o back tem que mandar
    a mesma forma, campo a campo e tipo a tipo."""
    service, _ = _service_do_pedido(ABERTAS)
    pedido = _pedido()

    payload = await service.build_individual_payload(pedido)

    corpo = payload.model_dump(mode="json")
    exemplo = json.loads(
        (CONTRACT_DIR / "exemplo-ida-individual.json").read_text(encoding="utf-8")
    )
    assert _forma(corpo) == _forma(exemplo)
    assert IndividualInsightRequest.model_validate(corpo) == payload
    assert payload.insight_id == pedido.id
    assert payload.language == "pt-BR"


@pytest.mark.parametrize(
    "descritivas",
    [
        [],
        [DescriptiveAnswer("S9", "Pergunta deixada em branco", None)],
        [DescriptiveAnswer("S9", "Pergunta só com espaços", "   ")],
    ],
    ids=["sem descritiva", "resposta nula", "resposta em branco"],
)
async def test_sem_resposta_aberta_o_pedido_vai_com_lista_vazia(
    descritivas: list[DescriptiveAnswer],
) -> None:
    service, _ = _service_do_pedido(descritivas)

    payload = await service.build_individual_payload(_pedido())

    assert payload.open_answers == []
    IndividualInsightRequest.model_validate(payload.model_dump(mode="json"))


async def test_resposta_aberta_vai_como_foi_escrita() -> None:
    escrita = "  Falta tempo.\nE espaço para errar.  "
    service, _ = _service_do_pedido(
        [
            DescriptiveAnswer("S9", "Primeira pergunta", escrita),
            DescriptiveAnswer("S9", "Segunda pergunta", ""),
        ]
    )

    payload = await service.build_individual_payload(_pedido())

    assert payload.open_answers == [
        OpenAnswer(section="S9", question="Primeira pergunta", answer=escrita)
    ]


async def test_notas_sao_as_do_calculo_inteiras_como_na_tela() -> None:
    service, prismas = _service_do_pedido([])
    pedido = _pedido()

    payload = await service.build_individual_payload(pedido)

    prismas.calculate_for_dispatch.assert_awaited_once_with(pedido.form_response_id)
    notas = payload.result.prismas
    assert notas.seguranca_psicologica == 85.0
    assert notas.lideranca_adaptativa == 73.0
    assert notas.adaptabilidade_cognitiva == 61.0
    assert notas.neuroinovacao_prisma == 75.0
    assert payload.result.dimensions.S5A == 70.0


async def test_destaque_e_oportunidade_saem_das_notas_sem_arredondar() -> None:
    """Arredondadas, as duas maiores empatam em 80 e a ordem dos prismas daria a
    segurança psicológica. O dashboard decide antes de arredondar, e o pedido também."""
    notas = _notas(
        seguranca_psicologica=80.2,
        cultura_empreendedora=80.4,
        lideranca_adaptativa=10.4,
        adaptabilidade_cognitiva=10.2,
    )
    service, _ = _service_do_pedido([], notas)

    payload = await service.build_individual_payload(_pedido())

    assert payload.result.destaque is Prisma.CULTURA_EMPREENDEDORA
    assert payload.result.oportunidade is Prisma.ADAPTABILIDADE_COGNITIVA


@pytest.mark.parametrize("attempts", [1, 4])
async def test_tentativa_e_a_que_a_reivindicacao_contou(attempts: int) -> None:
    service, _ = _service_do_pedido([])

    payload = await service.build_individual_payload(_pedido(attempts))

    assert payload.attempt == attempts


async def test_pedido_nao_leva_identificador_da_pessoa_nem_da_empresa() -> None:
    """P-091: o `insight_id` é a única correlação que vai ao N8N."""
    service, _ = _service_do_pedido(ABERTAS)
    pedido = _pedido()

    corpo = (await service.build_individual_payload(pedido)).model_dump_json()

    assert str(pedido.form_response_id) not in corpo
    assert str(pedido.organization_id) not in corpo
    assert str(pedido.form_id) not in corpo


async def test_insight_da_empresa_nao_tem_pedido_individual() -> None:
    service, prismas = _service_do_pedido([])
    da_empresa = _pedido()
    da_empresa.form_response_id = None

    with pytest.raises(ValueError, match="é da empresa"):
        await service.build_individual_payload(da_empresa)

    prismas.calculate_for_dispatch.assert_not_awaited()


# --- O ciclo do worker (CREED-804) ----------------------------------------------

LIMITES = DispatchLimits(
    batch_size=5, max_in_flight=5, max_attempts=5, dispatch_timeout_seconds=600
)

# A hora que o repository devolve como a do banco: as datas do ciclo saem dela.
AGORA = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def _n8n(*, configurado: bool = True) -> AsyncMock:
    n8n = AsyncMock(spec=N8NClient)
    n8n.is_configured = configurado
    return n8n


def _insight(status: InsightStatus, attempts: int = 0) -> Insight:
    return Insight(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        form_id=uuid.uuid4(),
        form_response_id=uuid.uuid4(),
        status=status,
        attempts=attempts,
    )


def _service_do_ciclo(
    *,
    reivindicados: list[Insight] | None = None,
    esquecidos: list[Insight] | None = None,
    em_voo: int = 0,
    n8n: AsyncMock | None = None,
    dashboards: AsyncMock | None = None,
) -> tuple[InsightService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=InsightRepository)
    repository.database_now.return_value = AGORA
    repository.list_stale.return_value = esquecidos or []
    repository.count_dispatched.return_value = em_voo
    repository.claim_due.return_value = reivindicados or []
    repository.list_descriptive_answers.return_value = []
    prismas = AsyncMock(spec=PrismaService)
    prismas.calculate_for_dispatch.return_value = _notas()
    service = InsightService(repository, prismas, n8n or _n8n(), dashboards)
    return service, repository, prismas


def _payload_do_kit() -> IndividualInsightRequest:
    return IndividualInsightRequest.model_validate_json(
        (CONTRACT_DIR / "exemplo-ida-individual.json").read_text(encoding="utf-8")
    )


def _payload_de(insight: Insight) -> IndividualInsightRequest:
    """O pedido que a reivindicação montou para este insight, nesta tentativa."""
    return _payload_do_kit().model_copy(
        update={"insight_id": insight.id, "attempt": insight.attempts}
    )


async def test_esteira_desligada_nao_mexe_em_nada(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """O estado do ambiente local: sem URL, nada é reivindicado nem gasta tentativa."""
    service, repository, _ = _service_do_ciclo(n8n=_n8n(configurado=False))

    with caplog.at_level(logging.DEBUG, logger="app.domains.insights.service"):
        payloads = await service.claim_due_batch(LIMITES)

    assert payloads == []
    assert repository.mock_calls == []
    assert "esteira de insights desligada" in caplog.text.lower()


async def test_reivindica_marca_dispatched_e_conta_a_tentativa() -> None:
    novo, de_novo = _insight(InsightStatus.PENDING), _insight(InsightStatus.PENDING, 2)
    service, repository, _ = _service_do_ciclo(reivindicados=[novo, de_novo])

    payloads = await service.claim_due_batch(LIMITES)

    assert [p.insight_id for p in payloads] == [novo.id, de_novo.id]
    assert [p.attempt for p in payloads] == [1, 3]
    assert novo.status is de_novo.status is InsightStatus.DISPATCHED
    assert novo.dispatched_at == AGORA  # a hora do banco, não a do worker
    # A trava vem antes de contar e reivindicar: é ela que segura o teto.
    chamadas = [nome for nome, *_ in repository.mock_calls]
    assert chamadas.index("lock_dispatch") < chamadas.index("count_dispatched")
    repository.claim_due.assert_awaited_once_with(5)


@pytest.mark.parametrize(("em_voo", "cabem"), [(0, 5), (3, 2), (4, 1)])
async def test_reivindica_so_o_que_cabe_no_teto(em_voo: int, cabem: int) -> None:
    service, repository, _ = _service_do_ciclo(em_voo=em_voo)

    await service.claim_due_batch(LIMITES)

    repository.claim_due.assert_awaited_once_with(cabem)


async def test_teto_cheio_nao_reivindica() -> None:
    service, repository, _ = _service_do_ciclo(em_voo=5)

    assert await service.claim_due_batch(LIMITES) == []

    repository.claim_due.assert_not_awaited()


async def test_pedido_que_nao_monta_vira_failed_e_nao_trava_os_outros() -> None:
    quebrado, bom = _insight(InsightStatus.PENDING), _insight(InsightStatus.PENDING)
    service, _, prismas = _service_do_ciclo(reivindicados=[quebrado, bom])
    prismas.calculate_for_dispatch.side_effect = [
        ValidationError("Dimensoes sem resposta: S8"),
        _notas(),
    ]

    payloads = await service.claim_due_batch(LIMITES)

    assert [p.insight_id for p in payloads] == [bom.id]
    assert quebrado.status is InsightStatus.FAILED
    assert quebrado.last_error is not None and "S8" in quebrado.last_error
    assert bom.status is InsightStatus.DISPATCHED


async def test_pedido_que_quebra_fora_do_dominio_vira_failed_e_nao_trava_a_fila() -> None:
    """Sem isso, a exceção desfaria a reivindicação inteira, e o mesmo pedido voltaria
    primeiro na fila a cada ciclo, travando todos os outros."""
    quebrado, bom = _insight(InsightStatus.PENDING), _insight(InsightStatus.PENDING)
    service, repository, _ = _service_do_ciclo(reivindicados=[quebrado, bom])
    # O `OpenAnswer` recusa a pergunta vazia com o `ValidationError` do Pydantic.
    repository.list_descriptive_answers.side_effect = [
        [DescriptiveAnswer("S9", "", "Uma resposta")],
        [],
    ]

    payloads = await service.claim_due_batch(LIMITES)

    assert [p.insight_id for p in payloads] == [bom.id]
    assert quebrado.status is InsightStatus.FAILED
    assert quebrado.last_error is not None
    assert quebrado.last_error.startswith("pedido não montado:")
    assert bom.status is InsightStatus.DISPATCHED


async def test_varredura_solta_o_esquecido_antes_de_contar() -> None:
    esquecido = _insight(InsightStatus.DISPATCHED, attempts=2)
    service, repository, _ = _service_do_ciclo(esquecidos=[esquecido])

    await service.claim_due_batch(LIMITES)

    repository.list_stale.assert_awaited_once_with(600)
    assert esquecido.status is InsightStatus.PENDING
    assert esquecido.last_error == "sem volta do N8N em 600 s"
    assert esquecido.next_attempt_at == AGORA + timedelta(minutes=1)
    # Sem o flush, a contagem ainda enxergaria o esquecido como em voo.
    chamadas = [nome for nome, *_ in repository.mock_calls]
    assert chamadas.index("flush") < chamadas.index("count_dispatched")


async def test_varredura_no_limite_de_tentativas_vira_failed() -> None:
    esquecido = _insight(InsightStatus.DISPATCHED, attempts=5)
    service, _, _ = _service_do_ciclo(esquecidos=[esquecido])

    await service.claim_due_batch(LIMITES)

    assert esquecido.status is InsightStatus.FAILED


async def test_entrega_aceita_nao_muda_nada() -> None:
    service, repository, _ = _service_do_ciclo()

    await service.dispatch(_payload_do_kit(), LIMITES)

    repository.get_for_update.assert_not_awaited()


@pytest.mark.parametrize(
    ("attempts", "espera"),
    [
        (1, timedelta(seconds=30)),
        (2, timedelta(minutes=1)),
        (3, timedelta(minutes=2)),
        (4, timedelta(minutes=4)),
    ],
)
async def test_falha_na_entrega_volta_a_fila_esperando_cada_vez_mais(
    attempts: int, espera: timedelta
) -> None:
    insight = _insight(InsightStatus.DISPATCHED, attempts)
    n8n = _n8n()
    n8n.dispatch.side_effect = N8NUnavailableError("N8N respondeu 503: fora")
    service, repository, _ = _service_do_ciclo(n8n=n8n)
    repository.get_for_update.return_value = insight

    await service.dispatch(_payload_de(insight), LIMITES)

    assert insight.status is InsightStatus.PENDING
    assert insight.last_error == "N8N respondeu 503: fora"
    assert insight.next_attempt_at == AGORA + espera


async def test_quinta_falha_na_entrega_vira_failed() -> None:
    insight = _insight(InsightStatus.DISPATCHED, attempts=5)
    n8n = _n8n()
    n8n.dispatch.side_effect = N8NUnavailableError("N8N não respondeu: ReadTimeout")
    service, repository, _ = _service_do_ciclo(n8n=n8n)
    repository.get_for_update.return_value = insight

    await service.dispatch(_payload_de(insight), LIMITES)

    assert insight.status is InsightStatus.FAILED
    assert insight.last_error == "N8N não respondeu: ReadTimeout"


async def test_falha_de_uma_tentativa_antiga_nao_mexe_na_tentativa_em_voo() -> None:
    """A tentativa 1 demorou a falhar; nesse meio-tempo o pedido voltou à fila e
    outro ciclo o reivindicou como tentativa 2, que está em voo."""
    em_voo = _insight(InsightStatus.DISPATCHED, attempts=2)
    tentativa_antiga = _payload_de(em_voo).model_copy(update={"attempt": 1})
    n8n = _n8n()
    n8n.dispatch.side_effect = N8NUnavailableError("N8N não respondeu: ReadTimeout")
    service, repository, _ = _service_do_ciclo(n8n=n8n)
    repository.get_for_update.return_value = em_voo

    await service.dispatch(tentativa_antiga, LIMITES)

    assert em_voo.status is InsightStatus.DISPATCHED
    assert em_voo.last_error is None


async def test_falha_na_entrega_nao_desfaz_a_volta_que_chegou_antes() -> None:
    """O N8N recebeu e respondeu pelo callback: só a resposta HTTP do disparo se
    perdeu."""
    pronto = _insight(InsightStatus.DONE, attempts=1)
    n8n = _n8n()
    n8n.dispatch.side_effect = N8NUnavailableError("N8N não respondeu: ReadTimeout")
    service, repository, _ = _service_do_ciclo(n8n=n8n)
    repository.get_for_update.return_value = pronto

    await service.dispatch(_payload_do_kit(), LIMITES)

    assert pronto.status is InsightStatus.DONE
    assert pronto.last_error is None


async def test_service_sem_client_nao_entra_no_ciclo() -> None:
    service = InsightService(
        AsyncMock(spec=InsightRepository), AsyncMock(spec=PrismaService)
    )

    with pytest.raises(RuntimeError, match="N8NClient"):
        await service.claim_due_batch(LIMITES)


# --- A volta do N8N (CREED-805) ---------------------------------------------------
# Uma linha da tabela de idempotência da spec por teste ("Volta: N8N → back").


def _done_do_kit() -> InsightCallbackDone:
    return InsightCallbackDone.model_validate_json(
        (CONTRACT_DIR / "exemplo-volta-done.json").read_text(encoding="utf-8")
    )


def _failed_do_kit(*, retryable: bool) -> InsightCallbackFailed:
    falha = InsightCallbackFailed.model_validate_json(
        (CONTRACT_DIR / "exemplo-volta-failed.json").read_text(encoding="utf-8")
    )
    return falha.model_copy(update={"retryable": retryable})


def _service_da_volta(insight: Insight | None) -> tuple[InsightService, AsyncMock]:
    repository = AsyncMock(spec=InsightRepository)
    repository.get_for_update.return_value = insight
    repository.database_now.return_value = AGORA
    return InsightService(repository, AsyncMock(spec=PrismaService)), repository


@pytest.mark.parametrize(
    "antes", [InsightStatus.PENDING, InsightStatus.DISPATCHED, InsightStatus.FAILED]
)
async def test_done_grava_o_texto_sobre_pending_dispatched_e_failed(
    antes: InsightStatus,
) -> None:
    """Sobre `failed` também: um texto atrasado vale mais que "indisponível"."""
    insight = _insight(antes, attempts=2)
    done = _done_do_kit()
    service, repository = _service_da_volta(insight)

    await service.complete(done, max_attempts=5)

    # A trava vem do `get_for_update`: dois callbacks ao mesmo tempo se enfileiram.
    repository.get_for_update.assert_awaited_once_with(done.insight_id)
    assert insight.status is InsightStatus.DONE
    assert insight.content == done.content.model_dump(mode="json")
    assert insight.model_id == "anthropic.claude-opus-5-5"
    assert insight.prompt_version == "individual-v1+dossie-v1"
    assert insight.completed_at == AGORA  # a hora do banco


async def test_done_sobre_done_nao_muda_nada() -> None:
    """O primeiro `done` vence, mesmo que o segundo traga outro texto."""
    primeiro = _done_do_kit()
    insight = _insight(InsightStatus.DONE, attempts=1)
    insight.content = primeiro.content.model_dump(mode="json")
    insight.model_id = "anthropic.claude-opus-5-5"
    insight.completed_at = AGORA - timedelta(hours=1)
    service, repository = _service_da_volta(insight)
    segundo = primeiro.model_copy(update={"model_id": "outro-modelo"})

    await service.complete(segundo, max_attempts=5)

    assert insight.model_id == "anthropic.claude-opus-5-5"
    assert insight.completed_at == AGORA - timedelta(hours=1)
    assert insight.content == primeiro.content.model_dump(mode="json")
    repository.database_now.assert_not_awaited()


@pytest.mark.parametrize("retryable", [True, False])
async def test_failed_sobre_done_nao_muda_nada(retryable: bool) -> None:
    insight = _insight(InsightStatus.DONE, attempts=1)
    insight.content = _done_do_kit().content.model_dump(mode="json")
    service, _ = _service_da_volta(insight)

    await service.complete(_failed_do_kit(retryable=retryable), max_attempts=5)

    assert insight.status is InsightStatus.DONE
    assert insight.last_error is None


@pytest.mark.parametrize("retryable", [True, False])
async def test_failed_sobre_failed_nao_muda_nada(retryable: bool) -> None:
    insight = _insight(InsightStatus.FAILED, attempts=5)
    insight.last_error = "erro de antes"
    service, _ = _service_da_volta(insight)

    await service.complete(_failed_do_kit(retryable=retryable), max_attempts=5)

    assert insight.status is InsightStatus.FAILED
    assert insight.last_error == "erro de antes"


@pytest.mark.parametrize("antes", [InsightStatus.PENDING, InsightStatus.DISPATCHED])
@pytest.mark.parametrize(
    ("attempts", "espera"),
    [
        (1, timedelta(seconds=30)),
        (2, timedelta(minutes=1)),
        (4, timedelta(minutes=4)),
    ],
)
async def test_failed_que_pode_repetir_faz_backoff(
    antes: InsightStatus, attempts: int, espera: timedelta
) -> None:
    """A mesma espera de quando o disparo falha: uma regra só para os dois caminhos."""
    insight = _insight(antes, attempts)
    service, _ = _service_da_volta(insight)

    await service.complete(_failed_do_kit(retryable=True), max_attempts=5)

    assert insight.status is InsightStatus.PENDING
    assert insight.next_attempt_at == AGORA + espera
    assert insight.last_error is not None and "bedrock_throttled" in insight.last_error


async def test_failed_que_pode_repetir_vira_failed_no_limite_de_tentativas() -> None:
    insight = _insight(InsightStatus.DISPATCHED, attempts=5)
    service, _ = _service_da_volta(insight)

    await service.complete(_failed_do_kit(retryable=True), max_attempts=5)

    assert insight.status is InsightStatus.FAILED
    assert insight.last_error is not None and "bedrock_throttled" in insight.last_error


@pytest.mark.parametrize("antes", [InsightStatus.PENDING, InsightStatus.DISPATCHED])
async def test_failed_sem_nova_tentativa_vira_failed_direto(
    antes: InsightStatus,
) -> None:
    """Recusa do modelo: a primeira tentativa já encerra, sem gastar as outras."""
    insight = _insight(antes, attempts=1)
    service, _ = _service_da_volta(insight)

    await service.complete(_failed_do_kit(retryable=False), max_attempts=5)

    assert insight.status is InsightStatus.FAILED
    assert insight.last_error is not None and "bedrock_throttled" in insight.last_error


async def test_volta_de_insight_desconhecido_vira_not_found(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, repository = _service_da_volta(None)
    done = _done_do_kit()

    with (
        caplog.at_level(logging.WARNING, logger="app.domains.insights.service"),
        pytest.raises(NotFoundError),
    ):
        await service.complete(done, max_attempts=5)

    assert str(done.insight_id) in caplog.text
    repository.database_now.assert_not_awaited()


# --- A leitura do estado (CREED-805) ----------------------------------------------

CREED_ORG = uuid.uuid4()
OUTRA_ORG = uuid.uuid4()


def _usuario(
    role: str, link_id: uuid.UUID, organization_id: uuid.UUID
) -> AuthenticatedUser:
    return AuthenticatedUser(
        sub="sub",
        email="dev@creed.example.com",
        roles=[role],
        link_id=str(link_id),
        organization_id=str(organization_id),
    )


def _service_da_leitura(
    owner: ResponseOwner | None, insight: Insight | None
) -> tuple[InsightService, AsyncMock]:
    repository = AsyncMock(spec=InsightRepository)
    repository.get_response_owner.return_value = owner
    repository.get_by_form_response.return_value = insight
    return InsightService(repository, AsyncMock(spec=PrismaService)), repository


def _insight_pronto() -> Insight:
    insight = _insight(InsightStatus.DONE, attempts=1)
    insight.content = _done_do_kit().content.model_dump(mode="json")
    insight.completed_at = AGORA
    return insight


async def test_dono_le_o_proprio_insight() -> None:
    dono = uuid.uuid4()
    resposta = uuid.uuid4()
    owner = ResponseOwner(dono, LinkType.EMPREGO, OUTRA_ORG)
    service, repository = _service_da_leitura(owner, _insight_pronto())

    lido = await service.get_status(
        resposta, user=_usuario("respondente", dono, OUTRA_ORG)
    )

    repository.get_by_form_response.assert_awaited_once_with(resposta)
    assert lido.status == "done"
    assert lido.content is not None and len(lido.content.analise) == 2
    assert lido.completed_at == AGORA


@pytest.mark.parametrize(
    ("estado", "visto"),
    [
        (InsightStatus.PENDING, "pending"),
        (InsightStatus.DISPATCHED, "pending"),  # quem lê não vê o `dispatched`
        (InsightStatus.FAILED, "failed"),
    ],
)
async def test_sem_texto_pronto_o_estado_vem_sem_content(
    estado: InsightStatus, visto: str
) -> None:
    dono = uuid.uuid4()
    owner = ResponseOwner(dono, LinkType.EMPREGO, OUTRA_ORG)
    service, _ = _service_da_leitura(owner, _insight(estado, attempts=1))

    lido = await service.get_status(
        uuid.uuid4(), user=_usuario("respondente", dono, OUTRA_ORG)
    )

    assert lido.status == visto
    assert lido.content is None
    assert lido.completed_at is None


async def test_administradora_le_o_insight_de_um_mentorando() -> None:
    """P-048: o mentorando é um vínculo de mentoria na organização da CREED."""
    mentorando = ResponseOwner(uuid.uuid4(), LinkType.MENTORIA, CREED_ORG)
    service, _ = _service_da_leitura(mentorando, _insight_pronto())

    lido = await service.get_status(
        uuid.uuid4(), user=_usuario("admin", uuid.uuid4(), CREED_ORG)
    )

    assert lido.status == "done"


@pytest.mark.parametrize(
    ("papel", "dono_da_resposta"),
    [
        # A administradora não lê o de quem é de empresa: anônimo para a CREED também.
        ("admin", ResponseOwner(uuid.uuid4(), LinkType.EMPREGO, OUTRA_ORG)),
        # Mentoria, mas de outra organização que não a dela.
        ("admin", ResponseOwner(uuid.uuid4(), LinkType.MENTORIA, OUTRA_ORG)),
        # A gestora da mesma organização não lê o de um membro (P-086).
        ("gestor", ResponseOwner(uuid.uuid4(), LinkType.EMPREGO, CREED_ORG)),
        # Nem a gestora lê o de mentorando, por mais que a organização coincida.
        ("gestor", ResponseOwner(uuid.uuid4(), LinkType.MENTORIA, CREED_ORG)),
        # Outro respondente.
        ("respondente", ResponseOwner(uuid.uuid4(), LinkType.EMPREGO, CREED_ORG)),
    ],
)
async def test_outro_vinculo_nao_le_o_insight(
    papel: str, dono_da_resposta: ResponseOwner
) -> None:
    service, repository = _service_da_leitura(dono_da_resposta, _insight_pronto())

    with pytest.raises(ForbiddenError):
        await service.get_status(
            uuid.uuid4(), user=_usuario(papel, uuid.uuid4(), CREED_ORG)
        )

    # O 403 vem antes de abrir o insight: quem não pode ler não descobre nem o estado.
    repository.get_by_form_response.assert_not_awaited()


async def test_resposta_inexistente_e_not_found_e_nao_forbidden() -> None:
    service, repository = _service_da_leitura(None, None)

    with pytest.raises(NotFoundError):
        await service.get_status(
            uuid.uuid4(), user=_usuario("admin", uuid.uuid4(), CREED_ORG)
        )

    repository.get_by_form_response.assert_not_awaited()


async def test_resposta_sem_insight_e_not_found() -> None:
    """Resposta em andamento, ou enviada antes de a esteira existir."""
    dono = uuid.uuid4()
    owner = ResponseOwner(dono, LinkType.EMPREGO, OUTRA_ORG)
    service, _ = _service_da_leitura(owner, None)

    with pytest.raises(NotFoundError):
        await service.get_status(
            uuid.uuid4(), user=_usuario("respondente", dono, OUTRA_ORG)
        )


# --- O insight da empresa: o gatilho no envio (CREED-8013) ------------------------


def _service_do_gatilho(
    enviadas: int, *, individual: bool = False
) -> tuple[InsightService, AsyncMock, FormScope]:
    """`enviadas`: o que o repository conta, já com a resposta que está sendo enviada."""
    escopo = FormScope(uuid.uuid4(), uuid.uuid4(), individual)
    repository = AsyncMock(spec=InsightRepository)
    repository.get_form_scope.return_value = escopo
    repository.count_submitted_with.return_value = enviadas
    repository.schedule_organization.return_value = True
    service = InsightService(repository, AsyncMock(spec=PrismaService))
    return service, repository, escopo


async def test_com_4_enviadas_o_insight_da_empresa_nao_e_agendado() -> None:
    service, repository, escopo = _service_do_gatilho(4)
    resposta = uuid.uuid4()

    await service.request_organization(resposta)

    # A conta inclui a resposta que está sendo enviada: ela só vira `submitted` no
    # commit.
    repository.count_submitted_with.assert_awaited_once_with(escopo.form_id, resposta)
    repository.schedule_organization.assert_not_awaited()


@pytest.mark.parametrize("enviadas", [5, 6, 15])
async def test_do_piso_em_diante_agenda_para_daqui_a_30_minutos(enviadas: int) -> None:
    service, repository, escopo = _service_do_gatilho(enviadas)

    await service.request_organization(uuid.uuid4())

    repository.schedule_organization.assert_awaited_once_with(
        escopo.organization_id, escopo.form_id, timedelta(minutes=30)
    )


async def test_a_trava_do_periodo_vem_antes_da_contagem() -> None:
    """É a trava que faz o segundo de dois envios simultâneos contar o primeiro."""
    service, repository, escopo = _service_do_gatilho(5)

    await service.request_organization(uuid.uuid4())

    repository.lock_period.assert_awaited_once_with(escopo.form_id)
    chamadas = [nome for nome, *_ in repository.mock_calls]
    assert chamadas.index("lock_period") < chamadas.index("count_submitted_with")


async def test_periodo_que_ja_tem_pedido_esperando_segue_sem_erro() -> None:
    """O índice parcial recusa o segundo pedido, e o envio não falha por isso."""
    service, repository, _ = _service_do_gatilho(7)
    repository.schedule_organization.return_value = False

    await service.request_organization(uuid.uuid4())

    repository.schedule_organization.assert_awaited_once()


async def test_questionario_individual_de_mentorando_nunca_agenda() -> None:
    """Formulário de uma pessoa só (P-048): não há grupo para o texto ler."""
    service, repository, _ = _service_do_gatilho(50, individual=True)

    await service.request_organization(uuid.uuid4())

    repository.lock_period.assert_not_awaited()
    repository.count_submitted_with.assert_not_awaited()
    repository.schedule_organization.assert_not_awaited()


async def test_gatilho_de_resposta_inexistente_vira_not_found() -> None:
    service, repository, _ = _service_do_gatilho(5)
    repository.get_form_scope.return_value = None

    with pytest.raises(NotFoundError):
        await service.request_organization(uuid.uuid4())

    repository.schedule_organization.assert_not_awaited()


# --- O insight da empresa: o pedido que vai ao N8N (CREED-8013) -------------------


def _numeros_da_empresa() -> CompanyPeriodNumbers:
    """Seis pessoas no período: Marketing tem o piso; Financeiro, uma pessoa só."""
    return CompanyPeriodNumbers(
        opens_at=datetime(2026, 11, 1, tzinfo=UTC),
        closes_at=datetime(2026, 11, 30, 23, 59, 59, tzinfo=UTC),
        submitted=6,
        invited=10,
        scores=dict.fromkeys(Prisma, 60.0)
        | {Prisma.SEGURANCA_PSICOLOGICA: 71.0, Prisma.ADAPTABILIDADE_COGNITIVA: 49.0},
        dimensions=dict.fromkeys(Dimension, 55.0),
        destaque=Prisma.SEGURANCA_PSICOLOGICA,
        oportunidade=Prisma.ADAPTABILIDADE_COGNITIVA,
        departments=[
            DepartmentRowRead(
                department=DepartmentType.MARKETING,
                respondents=5,
                scores=dict.fromkeys(Prisma, 70.0),
                difference=dict.fromkeys(Prisma, 10.0),
            ),
            DepartmentRowRead(
                department=DepartmentType.FINANCEIRO,
                respondents=1,
                scores=dict.fromkeys(Prisma, 30.0),
                difference=dict.fromkeys(Prisma, -30.0),
            ),
        ],
        alignment={
            prisma: PrismaAlignmentRead(
                bands=AlignmentBandsRead(baixa=1, media=4, alta=1), level="moderado"
            )
            for prisma in Prisma
        },
    )


def _insight_da_empresa(attempts: int = 1) -> Insight:
    return Insight(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        form_id=uuid.uuid4(),
        form_response_id=None,
        status=InsightStatus.PENDING,
        attempts=attempts,
    )


def _dashboards(numeros: CompanyPeriodNumbers | None) -> AsyncMock:
    dashboards = AsyncMock(spec=DashboardService)
    dashboards.company_period_numbers.return_value = numeros
    return dashboards


def _service_da_empresa(
    numeros: CompanyPeriodNumbers | None,
) -> tuple[InsightService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=InsightRepository)
    dashboards = _dashboards(numeros)
    service = InsightService(
        repository, AsyncMock(spec=PrismaService), dashboards=dashboards
    )
    return service, repository, dashboards


async def test_pedido_da_empresa_tem_a_forma_do_exemplo_do_kit() -> None:
    """O ramo da empresa no N8N (CREED-8015) roda com o `exemplo-ida-empresa.json`
    fixado: o back tem que mandar a mesma forma, campo a campo e tipo a tipo."""
    service, _, dashboards = _service_da_empresa(_numeros_da_empresa())
    pedido = _insight_da_empresa()

    payload = await service.build_organization_payload(pedido)

    dashboards.company_period_numbers.assert_awaited_once_with(
        pedido.organization_id, pedido.form_id
    )
    corpo = payload.model_dump(mode="json")
    exemplo = json.loads(
        (CONTRACT_DIR / "exemplo-ida-empresa.json").read_text(encoding="utf-8")
    )
    assert _forma(corpo) == _forma(exemplo)
    assert TypeAdapter(InsightRequest).validate_python(corpo) == payload
    assert payload.insight_id == pedido.id
    assert payload.attempt == 1


async def test_pedido_da_empresa_leva_os_numeros_do_dashboard() -> None:
    numeros = _numeros_da_empresa()
    service, _, _ = _service_da_empresa(numeros)

    payload = await service.build_organization_payload(_insight_da_empresa())

    assert payload.result.prismas.seguranca_psicologica == 71.0
    assert payload.result.prismas.adaptabilidade_cognitiva == 49.0
    assert payload.result.dimensions.S8 == 55.0
    assert payload.result.destaque is Prisma.SEGURANCA_PSICOLOGICA
    assert payload.result.oportunidade is Prisma.ADAPTABILIDADE_COGNITIVA
    assert payload.participation.submitted == 6
    assert payload.participation.invited == 10
    assert payload.period.opens_at == numeros.opens_at
    assert payload.period.closes_at == numeros.closes_at
    assert payload.alignment.neuroinovacao_prisma.bands.media == 4
    assert payload.alignment.neuroinovacao_prisma.level == "moderado"


async def test_pedido_da_empresa_so_leva_setor_com_o_piso() -> None:
    """P-089: o Financeiro, com uma pessoa só, identificaria quem respondeu."""
    service, _, _ = _service_da_empresa(_numeros_da_empresa())

    payload = await service.build_organization_payload(_insight_da_empresa())

    assert [row.department for row in payload.departments] == [DepartmentType.MARKETING]
    assert payload.departments[0].submitted == 5
    assert payload.departments[0].prismas.cultura_empreendedora == 70.0


async def test_pedido_da_empresa_nao_leva_texto_livre() -> None:
    """P-090: nenhuma resposta aberta entra, e o service nem as busca."""
    service, repository, _ = _service_da_empresa(_numeros_da_empresa())

    payload = await service.build_organization_payload(_insight_da_empresa())

    repository.list_descriptive_answers.assert_not_awaited()
    assert "open_answers" not in payload.model_dump()


async def test_periodo_sem_resultado_nao_vira_pedido_da_empresa() -> None:
    service, _, _ = _service_da_empresa(None)

    with pytest.raises(ValidationError, match="não tem resultado"):
        await service.build_organization_payload(_insight_da_empresa())


async def test_insight_de_uma_resposta_nao_tem_pedido_da_empresa() -> None:
    service, _, dashboards = _service_da_empresa(_numeros_da_empresa())

    with pytest.raises(ValueError, match="é de uma resposta"):
        await service.build_organization_payload(_pedido())

    dashboards.company_period_numbers.assert_not_awaited()


async def test_ciclo_monta_cada_pedido_pelo_escopo() -> None:
    individual = _insight(InsightStatus.PENDING)
    da_empresa = _insight_da_empresa(attempts=0)
    service, _, _ = _service_do_ciclo(
        reivindicados=[individual, da_empresa],
        dashboards=_dashboards(_numeros_da_empresa()),
    )

    payloads = await service.claim_due_batch(LIMITES)

    assert [type(payload) for payload in payloads] == [
        IndividualInsightRequest,
        OrganizationInsightRequest,
    ]
    assert payloads[1].insight_id == da_empresa.id
    assert payloads[1].attempt == 1
    assert da_empresa.status is InsightStatus.DISPATCHED


async def test_pedido_da_empresa_sem_resultado_vira_failed_e_nao_trava_a_fila() -> None:
    """Todas as pessoas do período foram excluídas, por exemplo: tentar de novo não
    muda isso."""
    da_empresa, individual = _insight_da_empresa(0), _insight(InsightStatus.PENDING)
    service, _, _ = _service_do_ciclo(
        reivindicados=[da_empresa, individual], dashboards=_dashboards(None)
    )

    payloads = await service.claim_due_batch(LIMITES)

    assert [payload.insight_id for payload in payloads] == [individual.id]
    assert da_empresa.status is InsightStatus.FAILED
    assert da_empresa.last_error is not None
    assert da_empresa.last_error.startswith("pedido não montado:")
