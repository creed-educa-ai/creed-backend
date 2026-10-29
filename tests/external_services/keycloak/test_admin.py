"""Testes do cliente da Admin API do Keycloak.

Sem Keycloak de verdade: o transporte do httpx é substituído por um realm falso, como
em `test_client.py`. O que se prova aqui é o contrato do módulo — a forma de cada
requisição que sai e como cada resposta vira exceção nossa. Que o Keycloak de verdade
responde assim foi conferido à mão contra o realm local (task 1 da CREED-23.8).
"""

import json
import uuid
from collections.abc import Callable

import httpx
import pytest

from app.core.config import settings
from app.external_services.keycloak import admin as keycloak_admin
from app.external_services.keycloak.client import KeycloakUnavailableError

# É uma URL, não um segredo: o S105 só reage ao "TOKEN" do nome.
TOKEN_URL = "http://kc.local:8080/realms/creed/protocol/openid-connect/token"  # noqa: S105
ADMIN_URL = "http://kc.local:8080/admin/realms/creed"
SERVICE_ACCOUNT_TOKEN = "token-do-service-account"  # noqa: S105
KEYCLOAK_ID = uuid.UUID("e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339")
EMAIL = "pessoa@creed.example.com"
GESTOR_ROLE = {
    "id": "0b6c1f7e-6a1d-4c51-9a55-3d1f3b0c2a11",
    "name": "gestor",
    "composite": False,
    "clientRole": False,
    "containerId": "creed",
}


@pytest.fixture(autouse=True)
def _settings_previsiveis(monkeypatch: pytest.MonkeyPatch) -> None:
    # Barra no fim de propósito: o módulo tem que normalizar as duas URLs.
    monkeypatch.setattr(settings, "KEYCLOAK_SERVER_URL", "http://kc.local:8080/")
    monkeypatch.setattr(settings, "KEYCLOAK_REALM", "creed")
    monkeypatch.setattr(settings, "KEYCLOAK_CLIENT_ID", "creed-backend")
    monkeypatch.setattr(settings, "KEYCLOAK_CLIENT_SECRET", "segredo-local")
    monkeypatch.setattr(settings, "KEYCLOAK_INVITE_LIFESPAN_SECONDS", 259200)
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173/")


def _issued_token(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"access_token": SERVICE_ACCOUNT_TOKEN})


class FakeRealm:
    """Responde o token endpoint com `token` e a Admin API com `admin`.

    Guarda as requisições, separadas em token e Admin API, para o teste conferir a
    forma de cada uma, e conta os clientes HTTP abertos (`clients_built`).
    """

    def __init__(
        self,
        admin: Callable[[httpx.Request], httpx.Response],
        token: Callable[[httpx.Request], httpx.Response],
    ) -> None:
        self.admin = admin
        self.token = token
        self.token_requests: list[httpx.Request] = []
        self.admin_requests: list[httpx.Request] = []
        self.clients_built = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            self.token_requests.append(request)
            return self.token(request)

        self.admin_requests.append(request)
        return self.admin(request)


def _realm(
    monkeypatch: pytest.MonkeyPatch,
    admin: Callable[[httpx.Request], httpx.Response],
    token: Callable[[httpx.Request], httpx.Response] = _issued_token,
) -> FakeRealm:
    realm = FakeRealm(admin, token)

    def _fabrica() -> httpx.AsyncClient:
        realm.clients_built += 1
        return httpx.AsyncClient(transport=httpx.MockTransport(realm))

    monkeypatch.setattr(keycloak_admin, "build_http_client", _fabrica)
    return realm


def _role_then_mapping(request: httpx.Request) -> httpx.Response:
    """O GET do papel devolve a representação dele; o POST do mapeamento, 204."""
    if request.method == "GET":
        return httpx.Response(200, json=GESTOR_ROLE)
    return httpx.Response(204)


def _created(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, headers={"Location": f"{ADMIN_URL}/users/{KEYCLOAK_ID}"})


def _no_content(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(204)


def _server_error(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"errorMessage": "unknown_error"})


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("sem resposta", request=request)


class TestServiceAccountToken:
    async def test_pede_token_por_client_credentials_e_usa_na_chamada(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        realm = _realm(monkeypatch, _created)

        await keycloak_admin.create_user(EMAIL)

        corpo = realm.token_requests[0].content.decode()
        assert "grant_type=client_credentials" in corpo
        assert "client_id=creed-backend" in corpo
        assert "client_secret=segredo-local" in corpo
        assert realm.admin_requests[0].headers["Authorization"] == (
            f"Bearer {SERVICE_ACCOUNT_TOKEN}"
        )

    async def test_token_recusado_e_indisponivel_e_nao_chama_a_admin_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Segredo errado é back mal configurado, não credencial de quem pediu."""
        realm = _realm(
            monkeypatch,
            _created,
            token=lambda _r: httpx.Response(401, json={"error": "unauthorized_client"}),
        )

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.create_user(EMAIL)

        assert realm.admin_requests == []

    async def test_token_endpoint_inalcancavel_e_indisponivel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        realm = _realm(monkeypatch, _created, token=_unreachable)

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.create_user(EMAIL)

        assert realm.admin_requests == []

    @pytest.mark.parametrize(
        "token",
        [
            lambda _r: httpx.Response(200, text="<html>502 Bad Gateway</html>"),
            lambda _r: httpx.Response(200, json={"token_type": "Bearer"}),
            lambda _r: httpx.Response(200, json=["access_token"]),
        ],
        ids=["sem-json", "sem-access-token", "json-que-nao-e-objeto"],
    )
    async def test_token_200_malformado_e_indisponivel(
        self,
        monkeypatch: pytest.MonkeyPatch,
        token: Callable[[httpx.Request], httpx.Response],
    ) -> None:
        """Pelo `delete_user`, que é a compensação do service.

        Lá, só `KeycloakUnavailableError` é capturada. Um `ValueError` ou `KeyError`
        escapando daqui trocaria o erro original e tiraria o id do log.
        """
        realm = _realm(monkeypatch, _no_content, token=token)

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.delete_user(KEYCLOAK_ID)

        assert realm.admin_requests == []

    async def test_uma_operacao_com_duas_chamadas_pede_um_token_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D9: token por operação, não por chamada HTTP. O papel é a que faz duas."""
        realm = _realm(monkeypatch, _role_then_mapping)

        await keycloak_admin.assign_realm_role(KEYCLOAK_ID, "gestor")

        assert realm.clients_built == 1
        assert len(realm.token_requests) == 1
        leitura, mapeamento = realm.admin_requests
        assert leitura.headers["Authorization"] == f"Bearer {SERVICE_ACCOUNT_TOKEN}"
        assert mapeamento.headers["Authorization"] == f"Bearer {SERVICE_ACCOUNT_TOKEN}"

    async def test_cada_operacao_pede_o_proprio_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem cache entre operações (D9): duas operações, dois tokens."""
        realm = _realm(monkeypatch, _no_content)

        await keycloak_admin.delete_user(KEYCLOAK_ID)
        await keycloak_admin.delete_user(KEYCLOAK_ID)

        assert realm.clients_built == 2
        assert len(realm.token_requests) == 2


class TestCreateUser:
    async def test_cria_sem_senha_e_sem_nome_e_devolve_o_id_do_location(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        realm = _realm(monkeypatch, _created)

        keycloak_id = await keycloak_admin.create_user(EMAIL)

        assert keycloak_id == KEYCLOAK_ID
        request = realm.admin_requests[0]
        assert request.method == "POST"
        assert str(request.url) == f"{ADMIN_URL}/users"
        # Igualdade exata: `credentials`, `firstName` ou `lastName` a mais quebram.
        assert json.loads(request.content) == {
            "username": EMAIL,
            "email": EMAIL,
            "enabled": True,
            "requiredActions": [],
        }

    async def test_409_vira_conflito(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _realm(
            monkeypatch,
            lambda _r: httpx.Response(409, json={"errorMessage": "User exists"}),
        )

        with pytest.raises(keycloak_admin.KeycloakConflictError):
            await keycloak_admin.create_user(EMAIL)

    async def test_resposta_sem_location_e_indisponivel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem o id não há como gravar o `keycloak_id`, nem como desfazer depois."""
        _realm(monkeypatch, lambda _r: httpx.Response(201))

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.create_user(EMAIL)

    async def test_erro_do_servidor_e_indisponivel_com_o_corpo_no_log(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _realm(monkeypatch, _server_error)

        with (
            caplog.at_level("ERROR"),
            pytest.raises(KeycloakUnavailableError),
        ):
            await keycloak_admin.create_user(EMAIL)

        assert "unknown_error" in caplog.text

    async def test_keycloak_inalcancavel_e_indisponivel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _realm(monkeypatch, _unreachable)

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.create_user(EMAIL)


class TestAssignRealmRole:
    async def test_le_o_papel_e_o_mapeia_no_usuario(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        realm = _realm(monkeypatch, _role_then_mapping)

        await keycloak_admin.assign_realm_role(KEYCLOAK_ID, "gestor")

        leitura, mapeamento = realm.admin_requests
        assert leitura.method == "GET"
        assert str(leitura.url) == f"{ADMIN_URL}/roles/gestor"
        assert mapeamento.method == "POST"
        assert str(mapeamento.url) == (
            f"{ADMIN_URL}/users/{KEYCLOAK_ID}/role-mappings/realm"
        )
        assert json.loads(mapeamento.content) == [GESTOR_ROLE]

    async def test_papel_que_o_realm_nao_tem_e_indisponivel_e_nao_mapeia(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        realm = _realm(
            monkeypatch,
            lambda _r: httpx.Response(404, json={"error": "Could not find role"}),
        )

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.assign_realm_role(KEYCLOAK_ID, "gestor")

        assert len(realm.admin_requests) == 1

    async def test_papel_200_sem_json_e_indisponivel_e_nao_mapeia(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        realm = _realm(
            monkeypatch, lambda _r: httpx.Response(200, text="<html>proxy</html>")
        )

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.assign_realm_role(KEYCLOAK_ID, "gestor")

        assert len(realm.admin_requests) == 1

    async def test_mapeamento_recusado_e_indisponivel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _admin(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json=GESTOR_ROLE)
            return httpx.Response(500, text="erro")

        _realm(monkeypatch, _admin)

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.assign_realm_role(KEYCLOAK_ID, "gestor")


class TestSendUpdatePasswordEmail:
    async def test_pede_update_password_com_validade_e_link_de_volta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        realm = _realm(monkeypatch, _no_content)

        await keycloak_admin.send_update_password_email(KEYCLOAK_ID)

        request = realm.admin_requests[0]
        assert request.method == "PUT"
        assert request.url.path == (
            f"/admin/realms/creed/users/{KEYCLOAK_ID}/execute-actions-email"
        )
        assert json.loads(request.content) == ["UPDATE_PASSWORD"]
        # A barra no fim da FRONTEND_URL não pode virar "//login".
        assert dict(request.url.params) == {
            "lifespan": "259200",
            "client_id": "creed-backend",
            "redirect_uri": "http://localhost:5173/login",
        }

    async def test_sem_frontend_url_manda_so_a_validade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P-051: `FRONTEND_URL` vazia desliga o link de volta."""
        monkeypatch.setattr(settings, "FRONTEND_URL", "")
        realm = _realm(monkeypatch, _no_content)

        await keycloak_admin.send_update_password_email(KEYCLOAK_ID)

        assert dict(realm.admin_requests[0].url.params) == {"lifespan": "259200"}

    async def test_smtp_fora_do_ar_e_indisponivel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Quem fala SMTP é o Keycloak: a falha chega como erro da Admin API."""
        _realm(monkeypatch, _server_error)

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.send_update_password_email(KEYCLOAK_ID)


class TestDeleteUser:
    async def test_apaga_o_usuario(self, monkeypatch: pytest.MonkeyPatch) -> None:
        realm = _realm(monkeypatch, _no_content)

        await keycloak_admin.delete_user(KEYCLOAK_ID)

        request = realm.admin_requests[0]
        assert request.method == "DELETE"
        assert str(request.url) == f"{ADMIN_URL}/users/{KEYCLOAK_ID}"

    async def test_usuario_que_ja_nao_existe_e_sucesso(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _realm(monkeypatch, lambda _r: httpx.Response(404))

        await keycloak_admin.delete_user(KEYCLOAK_ID)

    async def test_erro_do_servidor_e_indisponivel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _realm(monkeypatch, _server_error)

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.delete_user(KEYCLOAK_ID)

    async def test_keycloak_inalcancavel_e_indisponivel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _realm(monkeypatch, _unreachable)

        with pytest.raises(KeycloakUnavailableError):
            await keycloak_admin.delete_user(KEYCLOAK_ID)
