"""Testes do cliente do token endpoint do Keycloak.

Sem Keycloak de verdade: o transporte do httpx é substituído por um dublê. O que
se prova aqui é o contrato do módulo — a forma da requisição que sai, e como
cada resposta do realm vira exceção nossa. Que o Keycloak de verdade responde
assim é o que o teste de fumaça com `docker compose` prova, não este arquivo.
"""

from collections.abc import Callable

import httpx
import pytest

from app.core.config import settings
from app.external_services.keycloak import client as keycloak_client

TOKENS = {
    "access_token": "access-fake",
    "refresh_token": "refresh-fake",
    "expires_in": 900,
}


@pytest.fixture(autouse=True)
def _settings_previsiveis(monkeypatch: pytest.MonkeyPatch) -> None:
    # Barra no fim de propósito: o módulo tem que normalizar a URL.
    monkeypatch.setattr(settings, "KEYCLOAK_SERVER_URL", "http://kc.local:8080/")
    monkeypatch.setattr(settings, "KEYCLOAK_REALM", "creed")
    monkeypatch.setattr(settings, "KEYCLOAK_CLIENT_ID", "creed-backend")
    monkeypatch.setattr(settings, "KEYCLOAK_CLIENT_SECRET", "segredo-local")


def _responder_com(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    def _fabrica() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(keycloak_client, "build_http_client", _fabrica)


class TestLogin:
    async def test_monta_a_requisicao_do_direct_access_grant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        capturada: dict[str, object] = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            capturada["url"] = str(request.url)
            capturada["corpo"] = request.content.decode()
            return httpx.Response(200, json=TOKENS)

        _responder_com(monkeypatch, _handler)

        assert await keycloak_client.login("dev@creed.example.com", "senha") == TOKENS

        assert capturada["url"] == (
            "http://kc.local:8080/realms/creed/protocol/openid-connect/token"
        )
        corpo = str(capturada["corpo"])
        assert "grant_type=password" in corpo
        assert "username=dev%40creed.example.com" in corpo
        assert "client_id=creed-backend" in corpo
        assert "client_secret=segredo-local" in corpo

    @pytest.mark.parametrize("status", [400, 401])
    async def test_credencial_recusada(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        """400 `invalid_grant` cobre senha errada, conta desabilitada e usuário
        inexistente — os três precisam sair pela mesma porta."""
        _responder_com(
            monkeypatch,
            lambda _r: httpx.Response(status, json={"error": "invalid_grant"}),
        )

        with pytest.raises(keycloak_client.InvalidCredentialsError):
            await keycloak_client.login("dev@creed.example.com", "errada")

    async def test_erro_do_servidor_nao_e_credencial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Se isto virar InvalidCredentials, Keycloak fora do ar mostra
        'senha inválida' e o usuário troca a senha que estava certa."""
        _responder_com(monkeypatch, lambda _r: httpx.Response(503, text="down"))

        with pytest.raises(keycloak_client.KeycloakUnavailableError):
            await keycloak_client.login("dev@creed.example.com", "senha")

    async def test_keycloak_inalcancavel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("sem resposta", request=request)

        _responder_com(monkeypatch, _handler)

        with pytest.raises(keycloak_client.KeycloakUnavailableError):
            await keycloak_client.login("dev@creed.example.com", "senha")


class TestRefresh:
    async def test_troca_o_refresh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        capturado: dict[str, str] = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            capturado["corpo"] = request.content.decode()
            return httpx.Response(200, json=TOKENS)

        _responder_com(monkeypatch, _handler)

        assert await keycloak_client.refresh("refresh-antigo") == TOKENS
        assert "grant_type=refresh_token" in capturado["corpo"]
        assert "refresh_token=refresh-antigo" in capturado["corpo"]

    async def test_refresh_expirado_e_credencial_recusada(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _responder_com(
            monkeypatch,
            lambda _r: httpx.Response(400, json={"error": "invalid_grant"}),
        )

        with pytest.raises(keycloak_client.InvalidCredentialsError):
            await keycloak_client.refresh("expirado")
