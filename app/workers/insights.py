"""Worker da esteira de insights: `python -m app.workers.insights` (ADR-0010, item 3).

Roda no container `insight-worker`, com a mesma imagem do back e outro comando. A
cada `INSIGHT_WORKER_INTERVAL_SECONDS`, um ciclo: reivindica os pedidos que podem
sair e os entrega ao N8N, um de cada vez. Teto, espera, limite de tentativas e
varredura moram no `InsightService`; aqui só se abre a unidade de trabalho e se
chama o service.

`SIGTERM` (o `docker compose stop`) e `Ctrl+C` encerram o worker depois do ciclo em
curso. Ele fecha o client do N8N e as conexões com o banco ao sair.
"""

import asyncio
import contextlib
import logging
import signal

import httpx

from app.core.config import settings
from app.core.database import engine, unit_of_work
from app.domains.insights.dependencies import build_dispatch_service
from app.domains.insights.service import DispatchLimits
from app.external_services.n8n.client import N8NClient

logger = logging.getLogger(__name__)


def limits_from_settings() -> DispatchLimits:
    return DispatchLimits(
        batch_size=settings.INSIGHT_WORKER_BATCH_SIZE,
        max_in_flight=settings.INSIGHT_MAX_IN_FLIGHT,
        max_attempts=settings.INSIGHT_MAX_ATTEMPTS,
        dispatch_timeout_seconds=settings.INSIGHT_DISPATCH_TIMEOUT_SECONDS,
    )


def build_http_client() -> httpx.AsyncClient:
    """Ponto de troca nos testes, como o do Keycloak. O tempo máximo não vai aqui:
    o `N8NClient` o passa em cada chamada."""
    return httpx.AsyncClient()


async def run_cycle(n8n: N8NClient, limits: DispatchLimits) -> None:
    """Um ciclo: reivindicar e gravar; depois, cada entrega na sua unidade de trabalho.

    A reivindicação é gravada antes de qualquer disparo. Se o worker cair no meio, o
    pedido fica `dispatched` e a varredura o devolve à fila.
    """
    async with unit_of_work() as session:
        payloads = await build_dispatch_service(session, n8n).claim_due_batch(limits)
    for payload in payloads:
        try:
            async with unit_of_work() as session:
                await build_dispatch_service(session, n8n).dispatch(payload, limits)
        except Exception:
            # Uma entrega que falha de um jeito inesperado não leva junto as outras
            # do lote, já reivindicadas: este pedido fica `dispatched`, e a varredura
            # o devolve à fila. O erro fica no log com o traceback.
            logger.exception("Entrega do insight %s falhou", payload.insight_id)


async def run(stop: asyncio.Event) -> None:
    """O laço do worker, até `stop` ser acionado."""
    limits = limits_from_settings()
    async with build_http_client() as http:
        n8n = N8NClient(http)
        if not n8n.is_configured:
            logger.info(
                "Esteira de insights desligada: N8N_WEBHOOK_URL ou "
                "N8N_WEBHOOK_TOKEN vazio. O worker fica parado e não mexe em "
                "nenhum pedido."
            )
        while not stop.is_set():
            try:
                await run_cycle(n8n, limits)
            except Exception:
                # Um ciclo que falha (o banco reiniciando, por exemplo) não derruba o
                # worker: a unidade de trabalho desfez a metade, e o próximo ciclo
                # tenta de novo. O erro fica no log com o traceback.
                logger.exception("Ciclo do worker de insights falhou")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    stop.wait(), timeout=settings.INSIGHT_WORKER_INTERVAL_SECONDS
                )


def _stop_on_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows (dev local): o event loop não tem `add_signal_handler`.
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


async def main() -> None:
    stop = asyncio.Event()
    _stop_on_signals(stop)
    try:
        await run(stop)
    finally:
        await engine.dispose()
    logger.info("Worker de insights encerrado.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    asyncio.run(main())
