"""Estrutura dos workflows `insight-v1` exportados do N8N da AWS (CREED-806).

Os três JSON de `docker/n8n/workflows/` são baixados do editor e commitados como
registro. O N8N do compose local não roda a esteira (spec da CREED-80, decisão 4),
então aqui não se executa nada: confere-se o que um export não pode trazer (segredo,
URL de volta vinda de fora, dado de execução) e o que a esteira combinou com o back
(rota, autenticação, 202, a volta fixa).
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "docker" / "n8n" / "workflows"

ENTRADA = "insight-v1-entrada.json"
GERAR = "insight-v1-gerar.json"
VOLTA = "insight-v1-volta.json"
TODOS = [ENTRADA, GERAR, VOLTA]

URL_DA_VOLTA = "http://back:8000/api/v1/insights/callback"
# O mantle de Ohio, e não o bedrock-runtime: lá o GPT exige perfil `us.`/`global.`,
# que espalha as chamadas por outras regiões, e a conta só tem Ohio liberada.
URL_DO_MODELO = "https://bedrock-mantle.us-east-2.api.aws/openai/v1/responses"
MODELO = "openai.gpt-5.6-terra"


def _load(file_name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (WORKFLOWS_DIR / file_name).read_text(encoding="utf-8")
    )
    return data


def _nodes(file_name: str, node_type: str | None = None) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = _load(file_name)["nodes"]
    if node_type is None:
        return nodes
    return [node for node in nodes if node["type"] == node_type]


def _only(file_name: str, node_type: str) -> dict[str, Any]:
    nodes = _nodes(file_name, node_type)
    assert len(nodes) == 1, f"{file_name}: esperado um {node_type}, há {len(nodes)}"
    return nodes[0]


# --- O que um export não pode trazer -----------------------------------------


@pytest.mark.parametrize("file_name", TODOS)
def test_export_nao_traz_dado_de_execucao(file_name: str) -> None:
    """Pin data guarda a saída de uma execução, e ela pode ter texto de quem
    respondeu ou o segredo lido da data table."""
    assert not _load(file_name).get("pinData")


@pytest.mark.parametrize("file_name", TODOS)
def test_credencial_vai_so_por_referencia(file_name: str) -> None:
    for node in _nodes(file_name):
        for credential in node.get("credentials", {}).values():
            assert set(credential) <= {"id", "name"}, node["name"]


@pytest.mark.parametrize("file_name", TODOS)
def test_export_nao_traz_segredo_conhecido(file_name: str) -> None:
    text = (WORKFLOWS_DIR / file_name).read_text(encoding="utf-8")

    assert "segredo-de-teste-nao-use" not in text
    # A nota da entrada pode citar `Bearer <N8N_WEBHOOK_TOKEN>`; um token de verdade, não.
    assert not re.search(r"Bearer (?!<)", text)


def test_segredo_da_assinatura_vem_de_expressao() -> None:
    """O segredo mora na data table `segredos-esteira`: no nó, só a referência."""
    crypto = _only(VOLTA, "n8n-nodes-base.crypto")

    assert crypto["parameters"]["secret"].startswith("={{")


def test_segredo_e_lido_da_data_table() -> None:
    tabela = _only(VOLTA, "n8n-nodes-base.dataTable")
    condicoes = tabela["parameters"]["filters"]["conditions"]

    tabela_id = tabela["parameters"]["dataTableId"]
    assert tabela_id["cachedResultName"] == "segredos-esteira"
    assert [c["keyValue"] for c in condicoes] == ["N8N_CALLBACK_SECRET"]


# --- A volta -----------------------------------------------------------------


def test_volta_vai_so_para_a_url_fixa_do_back() -> None:
    """Nenhuma URL de volta vem do payload: a rota é uma só, pela rede interna."""
    requests = _nodes(VOLTA, "n8n-nodes-base.httpRequest")

    assert [r["parameters"]["url"] for r in requests] == [URL_DA_VOLTA]


@pytest.mark.parametrize("file_name", TODOS)
def test_nenhuma_url_de_request_e_expressao(file_name: str) -> None:
    for request in _nodes(file_name, "n8n-nodes-base.httpRequest"):
        assert request["parameters"]["url"] in {URL_DA_VOLTA, URL_DO_MODELO}


def test_volta_assina_com_os_headers_do_contrato() -> None:
    request = _only(VOLTA, "n8n-nodes-base.httpRequest")
    headers = {
        h["name"]: h["value"]
        for h in request["parameters"]["headerParameters"]["parameters"]
    }

    assert set(headers) == {"X-Creed-Timestamp", "X-Creed-Signature"}
    assert headers["X-Creed-Signature"].startswith("=sha256=")


def test_volta_envia_o_corpo_que_assinou() -> None:
    """O corpo vai como texto cru, a mesma string que entrou no HMAC: reserializar
    o JSON mudaria a assinatura."""
    request = _only(VOLTA, "n8n-nodes-base.httpRequest")["parameters"]
    crypto = _only(VOLTA, "n8n-nodes-base.crypto")["parameters"]

    assert request["contentType"] == "raw"
    assert "corpo" in request["body"]
    assert crypto["action"] == "hmac"
    assert crypto["type"] == "SHA256"
    # O export omite parâmetro no valor padrão, e o padrão do Crypto é `hex`.
    assert crypto.get("encoding", "hex") == "hex"


def test_volta_nao_salva_dado_de_execucao() -> None:
    """A saída do nó que lê a data table tem o segredo."""
    settings = _load(VOLTA)["settings"]

    assert settings["saveDataSuccessExecution"] == "none"
    assert settings["saveDataErrorExecution"] == "none"


# --- A entrada ---------------------------------------------------------------


def test_entrada_e_o_webhook_combinado_com_o_back() -> None:
    webhook = _only(ENTRADA, "n8n-nodes-base.webhook")
    params = webhook["parameters"]

    assert params["httpMethod"] == "POST"
    assert params["path"] == "creed/insights/v1"
    assert params["authentication"] == "headerAuth"
    # Omitido no export por ser o padrão: responde antes de rodar o resto.
    assert params.get("responseMode", "onReceived") == "onReceived"
    assert params["options"]["responseCode"]["values"]["customCode"] == 202
    assert "httpHeaderAuth" in webhook["credentials"]


# --- Quem chama quem ---------------------------------------------------------


def _chamados(file_name: str) -> set[str]:
    return {
        node["parameters"]["workflowId"]["cachedResultName"]
        for node in _nodes(file_name, "n8n-nodes-base.executeWorkflow")
    }


def test_entrada_chama_o_gerar_e_o_volta() -> None:
    assert _chamados(ENTRADA) == {"insight-v1 gerar", "insight-v1 volta"}


def test_gerar_devolve_pelo_volta() -> None:
    assert _chamados(GERAR) == {"insight-v1 volta"}


def test_falha_inesperada_do_gerar_vira_failed() -> None:
    """No lugar de um error workflow: a saída de erro do nó que chama o gerar."""
    gerar = next(
        node
        for node in _nodes(ENTRADA, "n8n-nodes-base.executeWorkflow")
        if node["parameters"]["workflowId"]["cachedResultName"] == "insight-v1 gerar"
    )

    assert gerar["onError"] == "continueErrorOutput"
    assert "n8n_error" in (WORKFLOWS_DIR / ENTRADA).read_text(encoding="utf-8")


# --- O modelo ----------------------------------------------------------------


def _codigo(nome: str) -> str:
    return str(
        next(
            node["parameters"]["jsCode"]
            for node in _nodes(GERAR, "n8n-nodes-base.code")
            if node["name"] == nome
        )
    )


def test_gerar_chama_o_gpt_no_mantle_de_ohio_com_a_credencial_aws() -> None:
    request = _only(GERAR, "n8n-nodes-base.httpRequest")
    headers = {
        h["name"]: h["value"]
        for h in request["parameters"]["headerParameters"]["parameters"]
    }

    assert request["parameters"]["url"] == URL_DO_MODELO
    assert request["parameters"]["nodeCredentialType"] == "aws"
    # A assinatura SigV4 do N8N não põe o Content-Type: sem ele, a Responses API dá 400.
    assert headers == {"Content-Type": "application/json"}
    assert request["retryOnFail"] is True
    assert request["onError"] == "continueErrorOutput"


def test_gerar_pede_saida_estruturada_sem_guardar_o_pedido() -> None:
    codigo = _codigo("Montar chamada ao modelo")

    assert f"const MODELO = '{MODELO}';" in codigo
    assert "type: 'json_schema'" in codigo
    assert "strict: true" in codigo
    # Dado pessoal: sem `store: false` o Bedrock guarda pedido e resposta por 30 dias.
    assert "store: false" in codigo


def test_gerar_escreve_nos_tres_idiomas_da_tela() -> None:
    codigo = _codigo("Montar chamada ao modelo")

    for idioma in ("'pt-BR': {", "en: {", "es: {"):
        assert idioma in codigo


def test_gerar_tem_os_dois_ramos_com_a_versao_do_prompt() -> None:
    codigo = _codigo("Montar chamada ao modelo")

    assert "pedido.scope === 'organization'" in codigo
    assert "'individual-v0-provisorio'" in codigo
    assert "'empresa-v0-provisorio'" in codigo


def test_gerar_devolve_o_modelo_e_o_prompt_que_usou() -> None:
    codigo = _codigo("Interpretar resposta")

    assert "model_id: pedido.modelo" in codigo
    assert "prompt_version: pedido.prompt_version" in codigo


def test_entrada_aceita_os_dois_escopos_e_os_tres_idiomas() -> None:
    codigo = next(
        node["parameters"]["jsCode"]
        for node in _nodes(ENTRADA, "n8n-nodes-base.code")
        if node["name"] == "Validar pedido"
    )

    assert "const IDIOMAS = ['pt-BR', 'en', 'es'];" in codigo
    assert "p.scope === 'organization'" in codigo
    assert "organization_not_supported" not in codigo
