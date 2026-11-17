"""Testes do client do webhook de ida da esteira (CREED-803).

Nenhum teste toca a rede: o `AsyncClient` recebe um `httpx.MockTransport`, que
responde no lugar do N8N.
"""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.external_services import n8n
from app.external_services.n8n.client import N8NClient
from app.external_services.n8n.exceptions import N8NUnavailableError
from app.external_services.n8n.schemas import IndividualInsightRequest
from app.shared.exceptions import ServiceUnavailableError
from scripts.exportar_contrato_n8n import CONTRACT_DIR

URL = "http://n8n.test/webhook/creed/insights/v1"

Responder = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def _settings_previsiveis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", URL)
    monkeypatch.setattr(settings, "N8N_WEBHOOK_TOKEN", "token-de-teste")
    monkeypatch.setattr(settings, "N8N_TIMEOUT_SECONDS", 7)


def _pedido() -> IndividualInsightRequest:
    """O exemplo do kit, o mesmo com que o workflow do N8N é testado."""
    return IndividualInsightRequest.model_validate_json(
        (CONTRACT_DIR / "exemplo-ida-individual.json").read_text(encoding="utf-8")
    )


async def _despachar(responder: Responder) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        await N8NClient(http).dispatch(_pedido())


async def test_entrega_o_pedido_com_token_e_tempo_maximo() -> None:
    recebidos: list[httpx.Request] = []

    def n8n_aceita(request: httpx.Request) -> httpx.Response:
        recebidos.append(request)
        return httpx.Response(202)

    await _despachar(n8n_aceita)

    [request] = recebidos
    assert request.method == "POST"
    assert str(request.url) == URL
    assert request.headers["Authorization"] == "Bearer token-de-teste"
    assert json.loads(request.content) == _pedido().model_dump(mode="json")
    assert request.extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), 7
    )


@pytest.mark.parametrize("status", [200, 202, 204])
async def test_qualquer_2xx_e_sucesso(status: int) -> None:
    await _despachar(lambda request: httpx.Response(status))


@pytest.mark.parametrize("status", [301, 400, 401, 404, 500, 502, 503])
async def test_resposta_fora_de_2xx_vira_n8n_indisponivel(status: int) -> None:
    with pytest.raises(N8NUnavailableError, match=str(status)):
        await _despachar(lambda request: httpx.Response(status, text="erro do N8N"))


@pytest.mark.parametrize(
    "erro",
    [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout],
    ids=["conexao recusada", "tempo esgotado ao conectar", "tempo esgotado na resposta"],
)
async def test_falha_de_rede_vira_n8n_indisponivel(
    erro: type[httpx.TransportError],
) -> None:
    def n8n_fora(request: httpx.Request) -> httpx.Response:
        raise erro("simulado", request=request)

    # `pytest.raises(N8NUnavailableError)` falharia se o erro do httpx vazasse.
    with pytest.raises(N8NUnavailableError, match=erro.__name__) as capturado:
        await _despachar(n8n_fora)

    assert isinstance(capturado.value.__cause__, erro)


async def test_url_malformada_vira_n8n_indisponivel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`InvalidURL` não herda de `httpx.HTTPError`: sem tratamento próprio, vazaria."""
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "http://[::1")

    with pytest.raises(N8NUnavailableError, match="InvalidURL"):
        await _despachar(lambda request: httpx.Response(202))


@pytest.mark.parametrize(
    ("url", "token", "configurado"),
    [(URL, "token-de-teste", True), ("", "token-de-teste", False), (URL, "", False)],
    ids=["url e token", "sem url", "sem token"],
)
def test_esteira_so_esta_configurada_com_url_e_token(
    monkeypatch: pytest.MonkeyPatch, url: str, token: str, configurado: bool
) -> None:
    """Sem token, o webhook recusaria todo pedido, e cada um gastaria as tentativas
    até virar `failed`. Desligada, a esteira só espera."""
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", url)
    monkeypatch.setattr(settings, "N8N_WEBHOOK_TOKEN", token)

    assert N8NClient(httpx.AsyncClient()).is_configured is configurado


def test_n8n_indisponivel_e_servico_indisponivel_do_projeto() -> None:
    """Herdar de `ServiceUnavailableError` mantém o erro no vocabulário do projeto."""
    assert issubclass(N8NUnavailableError, ServiceUnavailableError)


def test_pacote_nao_conhece_dominio_nem_cria_conexao_no_import() -> None:
    """O client só transporta, e o `AsyncClient` vem de quem chama (playbook
    `integrar-servico-externo.md`, "Erros que este playbook existe para evitar")."""
    pacote = Path(n8n.__file__).parent
    for arquivo in sorted(pacote.glob("*.py")):
        codigo = arquivo.read_text(encoding="utf-8")
        assert "app.domains" not in codigo, f"{arquivo.name} importa um domínio"
        assert "AsyncClient(" not in codigo, f"{arquivo.name} cria o AsyncClient"
