"""Smoke tests do artefato versionado da POC do n8n."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = ROOT / "docker/n8n/workflows/creed-insight-beta.json"
EXAMPLE_PATH = ROOT / "docker/n8n/examples/creed-insight-beta-request.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_workflow_is_importable_and_inactive_by_default() -> None:
    workflow = _read_json(WORKFLOW_PATH)

    assert workflow["id"] == "creed55InsightBeta"
    assert workflow["active"] is False
    assert workflow["settings"]["executionOrder"] == "v1"

    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert nodes["Receber solicitacao"]["parameters"]["path"] == (
        "creed/insights/beta"
    )
    assert nodes["Receber solicitacao"]["parameters"]["responseMode"] == (
        "responseNode"
    )
    condition = nodes["Payload valido?"]["parameters"]["conditions"]["conditions"][0]
    assert condition["operator"] == {
        "type": "boolean",
        "operation": "true",
        "singleValue": True,
    }
    assert nodes["Responder sucesso"]["parameters"]["options"][
        "responseCode"
    ] == 200
    assert nodes["Responder payload invalido"]["parameters"]["options"][
        "responseCode"
    ] == 422


def test_workflow_has_no_credentials_or_external_provider_dependency() -> None:
    workflow = _read_json(WORKFLOW_PATH)
    serialized = json.dumps(workflow).lower()

    assert "credentials" not in serialized
    assert "openai" not in serialized
    assert "anthropic" not in serialized


def test_example_covers_every_product_prism() -> None:
    example = _read_json(EXAMPLE_PATH)
    expected_prisms = {
        "plasticidade_humana",
        "empreendedorismo",
        "multiculturalismo",
        "neuroinovacao",
        "tomada_decisao",
    }

    assert example["contract_version"] == "beta-1"
    assert {answer["prisma"] for answer in example["answers"]} == expected_prisms
    assert all(0 <= answer["score"] <= 5 for answer in example["answers"])
