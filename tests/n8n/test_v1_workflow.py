"""Smoke tests do artefato versionado do fluxo v1 assíncrono do n8n."""

import json
from pathlib import Path
from typing import Any

from app.shared.enums import Dimension, Prisma

ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = ROOT / "docker/n8n/workflows/creed-insight-v1.json"
EXAMPLE_PATH = ROOT / "docker/n8n/examples/creed-insight-v1-request.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v1_workflow_is_importable_and_inactive_by_default() -> None:
    workflow = _read_json(WORKFLOW_PATH)

    assert workflow["id"] == "creedInsightV1Async"
    assert workflow["active"] is False
    assert workflow["settings"]["executionOrder"] == "v1"

    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert nodes["Receber solicitacao"]["parameters"]["path"] == "creed/insights/v1"
    assert (
        nodes["Responder 202 Aceito (Assincrono)"]["parameters"]["options"][
            "responseCode"
        ]
        == 202
    )
    assert (
        nodes["Responder 422 Invalido"]["parameters"]["options"]["responseCode"] == 422
    )
    assert nodes["Enviar Callback para o Backend"]["parameters"]["method"] == "POST"


def test_v1_workflow_has_no_hardcoded_credentials() -> None:
    workflow = _read_json(WORKFLOW_PATH)
    serialized = json.dumps(workflow).lower()

    assert "credentials" not in serialized
    assert "openai" not in serialized
    assert "anthropic" not in serialized


def test_v1_example_covers_all_matrix_dimensions() -> None:
    example = _read_json(EXAMPLE_PATH)
    expected_dimensions = {dimension.value for dimension in Dimension}

    assert example["contract_version"] == "v1"
    assert {answer["dimensao"] for answer in example["answers"]} == expected_dimensions
    assert all(1 <= answer["score"] <= 5 for answer in example["answers"])


def test_v1_example_uses_valid_prisms() -> None:
    example = _read_json(EXAMPLE_PATH)
    valid_prisms = {prisma.value for prisma in Prisma}

    for answer in example["answers"]:
        if "prisma" in answer:
            assert answer["prisma"] in valid_prisms
