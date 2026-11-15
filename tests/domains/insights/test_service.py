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

from app.domains.insights.models import Insight, InsightPrisma, InsightStatus
from app.domains.insights.repository import (
    DescriptiveAnswer,
    FormScope,
    InsightPrismaRepository,
    InsightRepository,
)
from app.domains.insights.service import (
    DispatchLimits,
    InsightPrismaService,
    InsightService,
)
from app.domains.prismas.service import PrismaService
from app.external_services.n8n.client import N8NClient
from app.external_services.n8n.exceptions import N8NUnavailableError
from app.external_services.n8n.schemas import IndividualInsightRequest, OpenAnswer
from app.shared.enums import Dimension, Prisma
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError
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
    repository.get_form_scope.return_value = FormScope(organizacao, formulario)
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
    repository.get_form_scope.return_value = FormScope(uuid.uuid4(), uuid.uuid4())
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
) -> tuple[InsightService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=InsightRepository)
    repository.list_stale.return_value = esquecidos or []
    repository.count_dispatched.return_value = em_voo
    repository.claim_due.return_value = reivindicados or []
    repository.list_descriptive_answers.return_value = []
    prismas = AsyncMock(spec=PrismaService)
    prismas.calculate_for_dispatch.return_value = _notas()
    return InsightService(repository, prismas, n8n or _n8n()), repository, prismas


def _payload_do_kit() -> IndividualInsightRequest:
    return IndividualInsightRequest.model_validate_json(
        (CONTRACT_DIR / "exemplo-ida-individual.json").read_text(encoding="utf-8")
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
    assert novo.dispatched_at is not None
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


async def test_varredura_solta_o_esquecido_antes_de_contar() -> None:
    esquecido = _insight(InsightStatus.DISPATCHED, attempts=2)
    service, repository, _ = _service_do_ciclo(esquecidos=[esquecido])
    antes = datetime.now(UTC)

    await service.claim_due_batch(LIMITES)

    repository.list_stale.assert_awaited_once_with(600)
    assert esquecido.status is InsightStatus.PENDING
    assert esquecido.last_error == "sem volta do N8N em 600 s"
    assert esquecido.next_attempt_at >= antes + timedelta(minutes=1)
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
    antes = datetime.now(UTC)

    await service.dispatch(_payload_do_kit(), LIMITES)

    depois = datetime.now(UTC)
    assert insight.status is InsightStatus.PENDING
    assert insight.last_error == "N8N respondeu 503: fora"
    assert antes + espera <= insight.next_attempt_at <= depois + espera


async def test_quinta_falha_na_entrega_vira_failed() -> None:
    insight = _insight(InsightStatus.DISPATCHED, attempts=5)
    n8n = _n8n()
    n8n.dispatch.side_effect = N8NUnavailableError("N8N não respondeu: ReadTimeout")
    service, repository, _ = _service_do_ciclo(n8n=n8n)
    repository.get_for_update.return_value = insight

    await service.dispatch(_payload_do_kit(), LIMITES)

    assert insight.status is InsightStatus.FAILED
    assert insight.last_error == "N8N não respondeu: ReadTimeout"


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
