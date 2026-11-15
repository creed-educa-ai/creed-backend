"""Testes da conferência de assinatura do callback (`app/core/security.py`, CREED-805).

Uma aplicação mínima com uma rota protegida pelo `Depends`: assim a conferência é
provada sozinha, sem o domínio de insights. A assinatura é montada aqui com
`compute_webhook_signature` e o segredo do vetor do kit, nunca com o segredo de outro
ambiente. Que a rota de insights usa o `Depends` é provado em
`tests/domains/insights/test_router.py`.
"""

import hmac
import json
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import (
    MAX_TIMESTAMP_SKEW_SECONDS,
    compute_webhook_signature,
    verify_n8n_callback,
)
from scripts.exportar_contrato_n8n import CONTRACT_DIR

VECTOR = json.loads((CONTRACT_DIR / "vetor-hmac.json").read_text(encoding="utf-8"))
SECRET: str = VECTOR["secret"]
CHAVE_ERRADA = "outra-chave"  # qualquer texto que não seja o segredo do vetor
BODY = b'{"insight_id":"0b4e1f2a-9c3d-4a5b-8e6f-7d8c9b0a1e2f"}'


@pytest.fixture(autouse=True)
def secret_do_vetor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "N8N_CALLBACK_SECRET", SECRET)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.post("/protegida", dependencies=[Depends(verify_n8n_callback)])
    async def protegida(corpo: dict[str, Any]) -> dict[str, str]:
        return {"ok": "sim"}

    return TestClient(app)


def _assinado(
    *, secret: str = SECRET, agora_menos: int = 0, body: bytes = BODY
) -> dict[str, str]:
    """Os cabeçalhos que o N8N mandaria, com o envio `agora_menos` segundos atrás."""
    timestamp = str(int(time.time()) - agora_menos)
    return {
        "X-Creed-Timestamp": timestamp,
        "X-Creed-Signature": compute_webhook_signature(secret, timestamp, body),
    }


def _post(client: TestClient, headers: dict[str, str], body: bytes = BODY) -> Any:
    return client.post(
        "/protegida",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )


def test_chamada_assinada_passa(client: TestClient) -> None:
    resposta = _post(client, _assinado())

    assert resposta.status_code == 200


def test_sem_cabecalhos_de_assinatura_e_401(client: TestClient) -> None:
    assert _post(client, {}).status_code == 401


@pytest.mark.parametrize("faltando", ["X-Creed-Timestamp", "X-Creed-Signature"])
def test_so_um_dos_cabecalhos_e_401(client: TestClient, faltando: str) -> None:
    cabecalhos = _assinado()
    del cabecalhos[faltando]

    assert _post(client, cabecalhos).status_code == 401


def test_assinatura_com_outro_segredo_e_401(client: TestClient) -> None:
    assert _post(client, _assinado(secret=CHAVE_ERRADA)).status_code == 401


def test_corpo_alterado_depois_de_assinado_e_401(client: TestClient) -> None:
    cabecalhos = _assinado()

    resposta = _post(client, cabecalhos, body=BODY.replace(b"0b4e", b"ffff"))

    assert resposta.status_code == 401


def test_timestamp_trocado_sem_reassinar_e_401(client: TestClient) -> None:
    cabecalhos = _assinado()
    cabecalhos["X-Creed-Timestamp"] = str(int(cabecalhos["X-Creed-Timestamp"]) + 1)

    assert _post(client, cabecalhos).status_code == 401


def test_timestamp_dentro_da_janela_passa(client: TestClient) -> None:
    quatro_minutos = 4 * 60

    assert _post(client, _assinado(agora_menos=quatro_minutos)).status_code == 200


@pytest.mark.parametrize("deslocamento", [-1, 1])
def test_timestamp_fora_da_janela_e_401_mesmo_bem_assinado(
    client: TestClient, deslocamento: int
) -> None:
    """Velho (uma cópia gravada, reenviada tarde) ou do futuro: nos dois sentidos."""
    fora = deslocamento * (MAX_TIMESTAMP_SKEW_SECONDS + 60)

    assert _post(client, _assinado(agora_menos=fora)).status_code == 401


def test_timestamp_que_nao_e_numero_e_401(client: TestClient) -> None:
    cabecalhos = {
        "X-Creed-Timestamp": "ontem",
        "X-Creed-Signature": compute_webhook_signature(SECRET, "ontem", BODY),
    }

    assert _post(client, cabecalhos).status_code == 401


def test_assinatura_com_acento_e_401_e_nao_erro_do_servidor(
    client: TestClient,
) -> None:
    """`hmac.compare_digest` com texto só aceita ASCII: sem converter para bytes, isto
    seria um 500."""
    timestamp = _assinado()["X-Creed-Timestamp"]

    resposta = client.post(
        "/protegida",
        content=BODY,
        headers={
            "Content-Type": "application/json",
            "X-Creed-Timestamp": timestamp,
            # Os bytes de "çççç" em latin-1: o httpx não envia texto fora do ASCII.
            "X-Creed-Signature": b"sha256=" + "çççç".encode("latin-1"),
        },
    )

    assert resposta.status_code == 401


def test_segredo_vazio_no_ambiente_fecha_a_rota(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Com chave vazia, qualquer um calcula uma assinatura que confere."""
    monkeypatch.setattr(settings, "N8N_CALLBACK_SECRET", "")

    assert _post(client, _assinado(secret="")).status_code == 401


def test_401_nao_diz_o_que_errou(client: TestClient) -> None:
    """Quem chama sem direito não aprende se errou o segredo, o corpo ou a hora."""
    sem_assinatura = _post(client, {})
    assinatura_errada = _post(client, _assinado(secret=CHAVE_ERRADA))
    velha = _post(client, _assinado(agora_menos=3600))

    assert sem_assinatura.json() == assinatura_errada.json() == velha.json()


def test_a_assinatura_e_comparada_com_compare_digest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    chamadas: list[tuple[bytes, bytes]] = []
    original: Callable[[bytes, bytes], bool] = hmac.compare_digest

    def espiao(a: bytes, b: bytes) -> bool:
        chamadas.append((a, b))
        return original(a, b)

    monkeypatch.setattr("app.core.security.hmac.compare_digest", espiao)

    _post(client, _assinado())

    assert len(chamadas) == 1
