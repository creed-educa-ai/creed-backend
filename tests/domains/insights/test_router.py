"""Testes de app/domains/insights/router.py (CREED-805).

O service é simulado: a regra de cada linha da tabela de idempotência é provada em
`test_service.py`. Aqui se prova a borda HTTP: o que a assinatura deixa passar, o
que vira 401, 404 e 422, e quem pode ler o estado. A assinatura é a de verdade
(`verify_n8n_callback`), montada com a função do kit e o segredo do vetor.
"""

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import compute_webhook_signature
from app.domains.insights.dependencies import get_max_attempts
from app.domains.insights.dependencies import get_service as get_insight_service
from app.domains.insights.router import router
from app.domains.insights.schemas import (
    InsightCallbackDone,
    InsightCallbackFailed,
    InsightStatusRead,
)
from app.domains.insights.service import InsightService
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import ForbiddenError, NotFoundError
from scripts.exportar_contrato_n8n import CONTRACT_DIR

VECTOR = json.loads((CONTRACT_DIR / "vetor-hmac.json").read_text(encoding="utf-8"))
ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TOKEN = {"Authorization": "Bearer valido"}
MAX_ATTEMPTS = 7  # diferente do padrão, para provar que o valor da dependência chega


def _kit(file_name: str) -> bytes:
    return (CONTRACT_DIR / file_name).read_bytes()


def _assinado(body: bytes, *, agora_menos: int = 0) -> dict[str, str]:
    """Os cabeçalhos do N8N, com o segredo do vetor e o envio `agora_menos` s atrás."""
    timestamp = str(int(time.time()) - agora_menos)
    return {
        "X-Creed-Timestamp": timestamp,
        "X-Creed-Signature": compute_webhook_signature(VECTOR["secret"], timestamp, body),
        "Content-Type": "application/json",
    }


@pytest.fixture(autouse=True)
def segredo_do_vetor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "N8N_CALLBACK_SECRET", VECTOR["secret"])


@pytest.fixture
def service() -> AsyncMock:
    return AsyncMock(spec=InsightService)


@pytest.fixture
def app(service: AsyncMock) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    fastapi_app.dependency_overrides[get_insight_service] = lambda: service
    fastapi_app.dependency_overrides[get_max_attempts] = lambda: MAX_ATTEMPTS
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- POST /insights/callback -------------------------------------------------------


def test_done_do_kit_assinado_recebe_204_e_chega_ao_service(
    client: TestClient, service: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def keycloak_nao_e_chamado(token: str) -> dict[str, Any]:
        raise AssertionError("o callback não usa o login do Keycloak")

    monkeypatch.setattr("app.shared.authorization.validate_token", keycloak_nao_e_chamado)
    body = _kit("exemplo-volta-done.json")

    response = client.post("/insights/callback", content=body, headers=_assinado(body))

    assert response.status_code == 204
    assert response.content == b""
    callback, max_attempts = service.complete.await_args.args
    assert isinstance(callback, InsightCallbackDone)
    assert str(callback.insight_id) == "0b4e1f2a-9c3d-4a5b-8e6f-7d8c9b0a1e2f"
    assert max_attempts == MAX_ATTEMPTS


def test_failed_do_kit_assinado_recebe_204_e_chega_ao_service(
    client: TestClient, service: AsyncMock
) -> None:
    body = _kit("exemplo-volta-failed.json")

    response = client.post("/insights/callback", content=body, headers=_assinado(body))

    assert response.status_code == 204
    callback, _ = service.complete.await_args.args
    assert isinstance(callback, InsightCallbackFailed)
    assert callback.retryable is True


def test_limite_de_tentativas_padrao_e_o_do_worker() -> None:
    assert get_max_attempts() == settings.INSIGHT_MAX_ATTEMPTS


def test_sem_assinatura_e_401_e_nada_muda(client: TestClient, service: AsyncMock) -> None:
    body = _kit("exemplo-volta-done.json")

    response = client.post(
        "/insights/callback",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
    service.complete.assert_not_awaited()


def test_sem_assinatura_e_corpo_fora_do_contrato_ainda_e_401(
    client: TestClient, service: AsyncMock
) -> None:
    """Quem não assinou não descobre, pelo 422, o que o contrato aceita."""
    response = client.post(
        "/insights/callback",
        content=b'{"status": "inventado"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
    service.complete.assert_not_awaited()


def test_assinatura_errada_e_401_e_nada_muda(
    client: TestClient, service: AsyncMock
) -> None:
    body = _kit("exemplo-volta-done.json")
    headers = _assinado(body)
    headers["X-Creed-Signature"] = headers["X-Creed-Signature"][:-1] + "0"

    response = client.post("/insights/callback", content=body, headers=headers)

    assert response.status_code == 401
    service.complete.assert_not_awaited()


@pytest.mark.parametrize("deslocamento", [-1, 1])
def test_timestamp_a_mais_de_5_minutos_e_401_e_nada_muda(
    client: TestClient, service: AsyncMock, deslocamento: int
) -> None:
    body = _kit("exemplo-volta-done.json")
    dez_minutos = 10 * 60

    response = client.post(
        "/insights/callback",
        content=body,
        headers=_assinado(body, agora_menos=deslocamento * dez_minutos),
    )

    assert response.status_code == 401
    service.complete.assert_not_awaited()


def _done_com(mudanca: dict[str, Any]) -> bytes:
    corpo = json.loads(_kit("exemplo-volta-done.json"))
    corpo.update(mudanca)
    return json.dumps(corpo).encode("utf-8")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            _done_com(
                {"content": {"analise": ["só um"], "prismas": {}, "recomendacao": []}}
            ),
            id="content fora do InsightContent",
        ),
        pytest.param(_done_com({"status": "inventado"}), id="status desconhecido"),
        pytest.param(_done_com({"contract_version": "insight-v2"}), id="outra versão"),
        pytest.param(_done_com({"campo_a_mais": 1}), id="campo a mais"),
        pytest.param(_done_com({"insight_id": "não-é-uuid"}), id="insight_id inválido"),
        pytest.param(b"{isto nao e json", id="JSON quebrado"),
    ],
)
def test_corpo_fora_do_contrato_assinado_e_422_e_nada_muda(
    client: TestClient, service: AsyncMock, body: bytes
) -> None:
    """A assinatura confere, então o insight segue `dispatched`: a varredura do
    worker o devolve à fila, e o N8N pode tentar de novo."""
    response = client.post("/insights/callback", content=body, headers=_assinado(body))

    assert response.status_code == 422
    service.complete.assert_not_awaited()


def test_insight_desconhecido_e_404(client: TestClient, service: AsyncMock) -> None:
    service.complete.side_effect = NotFoundError("Insight 0b4e… não encontrado")
    body = _kit("exemplo-volta-done.json")

    response = client.post("/insights/callback", content=body, headers=_assinado(body))

    assert response.status_code == 404
    assert response.json() == {"detail": "Insight 0b4e… não encontrado"}


# --- GET /form-responses/{form_response_id}/insight --------------------------------


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


def autenticar_como(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, role: str
) -> uuid.UUID:
    email = "dev@creed.example.com"
    link_id = uuid.uuid4()

    async def _fake_validate_token(token: str) -> dict[str, Any]:
        return {"sub": "sub-dev", "email": email, "realm_access": {"roles": [role]}}

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=role,
        link_id=link_id,
        organization_id=ORGANIZATION_ID,
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)
    return link_id


def test_ler_o_estado_exige_login(client: TestClient, service: AsyncMock) -> None:
    response = client.get(f"/form-responses/{uuid.uuid4()}/insight")

    assert response.status_code == 401
    service.get_status.assert_not_awaited()


def test_ler_o_estado_devolve_status_content_e_data(
    app: FastAPI,
    client: TestClient,
    service: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link_id = autenticar_como(app, monkeypatch, "respondente")
    form_response_id = uuid.uuid4()
    pronto = InsightCallbackDone.model_validate_json(_kit("exemplo-volta-done.json"))
    service.get_status.return_value = InsightStatusRead(
        status="done",
        content=pronto.content,
        completed_at=datetime(2026, 11, 15, 12, 0, tzinfo=UTC),
    )

    response = client.get(f"/form-responses/{form_response_id}/insight", headers=TOKEN)

    assert response.status_code == 200
    corpo = response.json()
    assert set(corpo) == {"status", "content", "completed_at"}
    assert corpo["status"] == "done"
    assert corpo["content"]["recomendacao"] == pronto.content.recomendacao
    assert corpo["completed_at"] == "2026-11-15T12:00:00Z"
    # O service recebe quem pede: é ele que decide quem lê.
    assert service.get_status.await_args.args == (form_response_id,)
    assert service.get_status.await_args.kwargs["user"].link_uuid == link_id


def test_ler_o_estado_em_preparo_vem_sem_texto(
    app: FastAPI,
    client: TestClient,
    service: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    autenticar_como(app, monkeypatch, "respondente")
    service.get_status.return_value = InsightStatusRead(
        status="pending", content=None, completed_at=None
    )

    response = client.get(f"/form-responses/{uuid.uuid4()}/insight", headers=TOKEN)

    assert response.status_code == 200
    assert response.json() == {"status": "pending", "content": None, "completed_at": None}


def test_ler_o_estado_de_resposta_inexistente_e_404(
    app: FastAPI,
    client: TestClient,
    service: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    autenticar_como(app, monkeypatch, "respondente")
    service.get_status.side_effect = NotFoundError("Resposta não encontrada")

    response = client.get(f"/form-responses/{uuid.uuid4()}/insight", headers=TOKEN)

    assert response.status_code == 404


def test_ler_o_estado_de_outro_vinculo_e_403(
    app: FastAPI,
    client: TestClient,
    service: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    service.get_status.side_effect = ForbiddenError(
        "Sem acesso ao insight de outro respondente"
    )

    response = client.get(f"/form-responses/{uuid.uuid4()}/insight", headers=TOKEN)

    assert response.status_code == 403
    assert response.json() == {"detail": "Sem acesso ao insight de outro respondente"}


def test_ler_o_estado_com_id_que_nao_e_uuid_e_422(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "respondente")

    response = client.get("/form-responses/nao-e-uuid/insight", headers=TOKEN)

    assert response.status_code == 422
