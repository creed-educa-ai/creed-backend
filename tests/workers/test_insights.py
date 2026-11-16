"""Testes do worker da esteira de insights (CREED-804).

O worker é porta de entrada: os testes conferem que ele abre as unidades de
trabalho na ordem certa, chama o service e para quando pedem. A regra (teto,
espera, limite, varredura) é testada no service, e a concorrência contra Postgres
em `tests/domains/insights/test_insights_postgres.py`.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.domains.insights.service import DispatchLimits
from app.external_services.n8n.client import N8NClient
from app.workers import insights as worker

LIMITES = DispatchLimits(
    batch_size=5, max_in_flight=5, max_attempts=5, dispatch_timeout_seconds=600
)


class ServiceFalso:
    """Anota em que unidade de trabalho cada passo foi chamado."""

    def __init__(self, sessao: int, eventos: list[str], payloads: list[str]) -> None:
        self.sessao = sessao
        self.eventos = eventos
        self.payloads = payloads

    async def claim_due_batch(self, limits: DispatchLimits) -> list[str]:
        self.eventos.append(f"reivindica na {self.sessao}")
        return self.payloads

    async def dispatch(self, payload: str, limits: DispatchLimits) -> None:
        self.eventos.append(f"entrega {payload} na {self.sessao}")


async def test_ciclo_grava_a_reivindicacao_antes_de_entregar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eventos: list[str] = []
    abertas: list[int] = []

    @asynccontextmanager
    async def unidade_falsa() -> AsyncIterator[int]:
        abertas.append(len(abertas) + 1)
        numero = abertas[-1]
        yield numero
        eventos.append(f"grava a {numero}")

    def montar(sessao: int, n8n: Any) -> ServiceFalso:
        return ServiceFalso(sessao, eventos, ["p1", "p2"])

    monkeypatch.setattr(worker, "unit_of_work", unidade_falsa)
    monkeypatch.setattr(worker, "build_dispatch_service", montar)

    async with httpx.AsyncClient() as http:
        await worker.run_cycle(N8NClient(http), LIMITES)

    assert eventos == [
        "reivindica na 1",
        "grava a 1",
        "entrega p1 na 2",
        "grava a 2",
        "entrega p2 na 3",
        "grava a 3",
    ]


async def test_entrega_que_quebra_nao_leva_as_outras_do_lote(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """As outras já foram reivindicadas: se o ciclo parasse aqui, elas ficariam
    `dispatched`, ocupando o teto, até a varredura."""
    entregues: list[str] = []

    @dataclass
    class Pedido:
        insight_id: str

    class ServiceQueQuebraNaPrimeira:
        async def claim_due_batch(self, limits: DispatchLimits) -> list[Pedido]:
            return [Pedido("p1"), Pedido("p2")]

        async def dispatch(self, payload: Pedido, limits: DispatchLimits) -> None:
            if payload.insight_id == "p1":
                raise RuntimeError("erro inesperado na entrega")
            entregues.append(payload.insight_id)

    @asynccontextmanager
    async def unidade_falsa() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(worker, "unit_of_work", unidade_falsa)
    monkeypatch.setattr(
        worker, "build_dispatch_service", lambda *_: ServiceQueQuebraNaPrimeira()
    )

    async with httpx.AsyncClient() as http:
        await worker.run_cycle(N8NClient(http), LIMITES)

    assert entregues == ["p2"]
    assert "Entrega do insight p1 falhou" in caplog.text
    assert "erro inesperado na entrega" in caplog.text


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> list[httpx.AsyncClient]:
    """Os `AsyncClient` que o worker abriu, para conferir que ele os fecha."""
    abertos: list[httpx.AsyncClient] = []

    def fabrica() -> httpx.AsyncClient:
        abertos.append(httpx.AsyncClient())
        return abertos[-1]

    monkeypatch.setattr(worker, "build_http_client", fabrica)
    monkeypatch.setattr(settings, "INSIGHT_WORKER_INTERVAL_SECONDS", 0.01)
    return abertos


async def test_pedido_de_parada_termina_o_ciclo_em_curso_e_fecha_o_client(
    monkeypatch: pytest.MonkeyPatch, clients: list[httpx.AsyncClient]
) -> None:
    stop = asyncio.Event()
    ciclos: list[str] = []

    async def ciclo(n8n: N8NClient, limits: DispatchLimits) -> None:
        ciclos.append("começou")
        stop.set()  # o SIGTERM chega no meio do ciclo
        await asyncio.sleep(0)
        ciclos.append("terminou")

    monkeypatch.setattr(worker, "run_cycle", ciclo)

    await asyncio.wait_for(worker.run(stop), timeout=5)

    assert ciclos == ["começou", "terminou"]
    [client] = clients
    assert client.is_closed


async def test_ciclo_que_falha_nao_derruba_o_worker(
    monkeypatch: pytest.MonkeyPatch,
    clients: list[httpx.AsyncClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()
    ciclos = 0

    async def ciclo(n8n: N8NClient, limits: DispatchLimits) -> None:
        nonlocal ciclos
        ciclos += 1
        if ciclos == 1:
            raise RuntimeError("banco reiniciando")
        stop.set()

    monkeypatch.setattr(worker, "run_cycle", ciclo)

    await asyncio.wait_for(worker.run(stop), timeout=5)

    assert ciclos == 2
    assert "Ciclo do worker de insights falhou" in caplog.text
    assert "banco reiniciando" in caplog.text


async def test_sem_url_o_worker_avisa_que_a_esteira_esta_desligada(
    monkeypatch: pytest.MonkeyPatch,
    clients: list[httpx.AsyncClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "")
    stop = asyncio.Event()

    async def ciclo(n8n: N8NClient, limits: DispatchLimits) -> None:
        stop.set()

    monkeypatch.setattr(worker, "run_cycle", ciclo)

    with caplog.at_level(logging.INFO, logger="app.workers.insights"):
        await asyncio.wait_for(worker.run(stop), timeout=5)

    assert "Esteira de insights desligada" in caplog.text


def test_limites_vem_dos_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INSIGHT_WORKER_BATCH_SIZE", 2)
    monkeypatch.setattr(settings, "INSIGHT_MAX_IN_FLIGHT", 3)
    monkeypatch.setattr(settings, "INSIGHT_MAX_ATTEMPTS", 4)
    monkeypatch.setattr(settings, "INSIGHT_DISPATCH_TIMEOUT_SECONDS", 60)

    assert worker.limits_from_settings() == DispatchLimits(
        batch_size=2, max_in_flight=3, max_attempts=4, dispatch_timeout_seconds=60
    )
