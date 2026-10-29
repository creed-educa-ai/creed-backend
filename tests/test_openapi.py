"""Testes do contrato OpenAPI exibido no Swagger UI."""

import importlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
from app.core.config import settings
from app.main import app


def _operation(schema: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    operation: dict[str, Any] = schema["paths"][path][method]
    return operation


def test_swagger_ui_is_available_at_the_documented_url() -> None:
    response = TestClient(app).get("/api/v1/docs")

    assert response.status_code == 200
    assert "url: '/api/v1/openapi.json'" in response.text


def test_swagger_is_not_published_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    # O `app` é montado quando o módulo é importado: para ver a versão de produção,
    # o módulo roda de novo com o ambiente trocado — e de novo no fim, para os
    # outros testes não herdarem o app de produção.
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    try:
        client = TestClient(importlib.reload(main).app)

        assert client.get("/api/v1/docs").status_code == 404
        assert client.get("/api/v1/openapi.json").status_code == 404
        assert client.get("/health").status_code == 200
    finally:
        monkeypatch.undo()
        importlib.reload(main)


def test_all_endpoints_have_method_summary_description_and_operation_id() -> None:
    schema = app.openapi()
    expected_operations = {
        ("/health", "get"),
        ("/api/v1/authentication/login", "post"),
        ("/api/v1/authentication/renew", "post"),
        ("/api/v1/authentication/session", "get"),
        ("/api/v1/authentication/password-reset", "post"),
        ("/api/v1/users", "post"),
        ("/api/v1/users/{user_id}", "delete"),
        ("/api/v1/users/{user_id}/invitation", "post"),
        ("/api/v1/organizations/{organization_id}/members", "post"),
        ("/api/v1/forms", "post"),
        ("/api/v1/forms/{form_id}", "get"),
        ("/api/v1/form-responses", "post"),
        ("/api/v1/form-responses/{form_response_id}", "patch"),
        ("/api/v1/form-responses/{form_response_id}/answers", "post"),
        ("/api/v1/form-responses/{form_response_id}/answers", "get"),
        ("/api/v1/participants", "post"),
        ("/api/v1/participants/{participant_id}", "get"),
        ("/api/v1/questions", "post"),
        ("/api/v1/forms/{form_id}/questions", "get"),
    }

    documented_operations = {
        (path, method)
        for path, path_item in schema["paths"].items()
        for method in path_item
    }

    assert expected_operations <= documented_operations
    for path, method in documented_operations:
        operation = _operation(schema, path, method)
        assert operation["summary"]
        assert operation["description"]
        assert operation["operationId"]


def test_every_tag_used_by_a_route_has_a_description() -> None:
    # Domínio novo sem entrada em `OPENAPI_TAGS` aparece no Swagger sem texto.
    schema = app.openapi()
    used_tags = {
        tag
        for path_item in schema["paths"].values()
        for operation in path_item.values()
        for tag in operation.get("tags", [])
    }
    described_tags = {tag["name"] for tag in schema["tags"] if tag["description"]}

    assert used_tags <= described_tags


def test_request_fields_path_parameters_and_examples_are_documented() -> None:
    schema = app.openapi()
    components = schema["components"]["schemas"]

    assert components["LoginRequest"]["examples"]
    assert components["PasswordResetRequest"]["examples"]
    assert components["UserCreate"]["examples"]
    assert components["MemberInvite"]["examples"]
    assert components["FormResponseCreate"]["examples"]
    assert components["SessionResponse"]["examples"]
    assert components["UserResponse"]["examples"]
    assert components["FormResponseResponse"]["examples"]
    assert components["ParticipantCreate"]["examples"]
    assert components["ParticipantResponse"]["examples"]
    assert components["QuestionCreate"]["examples"][0]["dimensao"] == "S2"
    assert components["QuestionResponse"]["examples"][0]["dimensao"] == "S2"
    assert components["QuestionCreate"]["properties"]["dimensao"]["description"]
    assert components["QuestionResponse"]["properties"]["dimensao"]["description"]

    for schema_name in (
        "LoginRequest",
        "PasswordResetRequest",
        "UserCreate",
        "MemberInvite",
        "FormResponseCreate",
        "ParticipantCreate",
        "QuestionCreate",
    ):
        for field in components[schema_name]["properties"].values():
            assert field["description"]

    delete_user = _operation(schema, "/api/v1/users/{user_id}", "delete")
    user_id = delete_user["parameters"][0]
    assert user_id["name"] == "user_id"
    assert user_id["description"]
    assert user_id["schema"]["examples"]

    resend_invitation = _operation(schema, "/api/v1/users/{user_id}/invitation", "post")
    invited_user_id = resend_invitation["parameters"][0]
    assert invited_user_id["name"] == "user_id"
    assert invited_user_id["description"]
    assert invited_user_id["schema"]["examples"]

    submit_response = _operation(
        schema,
        "/api/v1/form-responses/{form_response_id}",
        "patch",
    )
    form_response_id = submit_response["parameters"][0]
    assert form_response_id["name"] == "form_response_id"
    assert form_response_id["description"]
    assert form_response_id["schema"]["examples"]

    get_participant = _operation(schema, "/api/v1/participants/{participant_id}", "get")
    participant_id = get_participant["parameters"][0]
    assert participant_id["name"] == "participant_id"
    assert participant_id["description"]
    assert participant_id["schema"]["examples"]


def test_success_error_and_bearer_authentication_responses_are_documented() -> None:
    schema = app.openapi()

    # Keycloak fora do ar é 503, não 401 de senha errada (CREED-23.8).
    assert set(
        _operation(schema, "/api/v1/authentication/login", "post")["responses"]
    ) >= {"200", "401", "422", "503"}
    assert set(
        _operation(schema, "/api/v1/authentication/renew", "post")["responses"]
    ) >= {"200", "401", "422", "503"}
    # Cadastro e remoção falam com o Keycloak: indisponível é 503 (D7).
    assert set(_operation(schema, "/api/v1/users", "post")["responses"]) >= {
        "201",
        "409",
        "422",
        "503",
    }
    # Remover usuário exige admin, como o cadastro.
    assert set(_operation(schema, "/api/v1/users/{user_id}", "delete")["responses"]) >= {
        "204",
        "401",
        "403",
        "404",
        "503",
    }
    # Reenvio de convite: usuário de outra organização é 404, não 403, para não vazar
    # cadastro alheio; o e-mail do Keycloak fora do ar é 503 (CREED-23.8).
    assert set(
        _operation(schema, "/api/v1/users/{user_id}/invitation", "post")["responses"]
    ) >= {"204", "401", "403", "404", "422", "503"}
    # Esqueci minha senha: rota pública, sem 401 nem 404, porque a resposta não pode
    # dizer se o e-mail tem acesso (CREED-23.8).
    password_reset = _operation(schema, "/api/v1/authentication/password-reset", "post")
    assert set(password_reset["responses"]) >= {"204", "422", "503"}
    assert not {"401", "404"} & set(password_reset["responses"])
    assert "security" not in password_reset
    # Convite de membro: o recorte do gestor é 403, a organização inexistente é 404,
    # e o Keycloak ou o SMTP fora do ar é 503, como no cadastro (D7, D8).
    assert set(
        _operation(schema, "/api/v1/organizations/{organization_id}/members", "post")[
            "responses"
        ]
    ) >= {"201", "401", "403", "404", "409", "422", "503"}
    # O vínculo de quem responde vem do login desde a CREED-47 (P-031).
    assert set(_operation(schema, "/api/v1/form-responses", "post")["responses"]) >= {
        "201",
        "401",
        "403",
        "409",
        "422",
    }
    # Referência inexistente no corpo é 422; no caminho, 404 (CREED-47).
    assert set(
        _operation(schema, "/api/v1/organizations/{organization_id}/links", "post")[
            "responses"
        ]
    ) >= {"201", "422"}
    assert set(_operation(schema, "/api/v1/questions", "post")["responses"]) >= {
        "201",
        "401",
        "403",
        "409",
        "422",
    }
    assert set(
        _operation(schema, "/api/v1/forms/{form_id}/questions", "get")["responses"]
    ) >= {"200", "401", "403", "404"}
    # Formulário e pergunta exigem login desde a CREED-47 (P-033).
    assert set(_operation(schema, "/api/v1/forms", "post")["responses"]) >= {
        "201",
        "401",
        "403",
        "422",
    }
    assert set(_operation(schema, "/api/v1/forms/{form_id}", "get")["responses"]) >= {
        "200",
        "401",
        "403",
        "404",
    }
    assert set(
        _operation(
            schema,
            "/api/v1/form-responses/{form_response_id}",
            "patch",
        )["responses"]
    ) >= {"200", "401", "403", "404", "409", "422"}
    # Gravar e ler respostas: só o dono da resposta de formulário (CREED-47).
    answers = "/api/v1/form-responses/{form_response_id}/answers"
    assert set(_operation(schema, answers, "post")["responses"]) >= {
        "201",
        "401",
        "403",
        "404",
        "409",
        "422",
    }
    assert set(_operation(schema, answers, "get")["responses"]) >= {
        "200",
        "401",
        "403",
        "404",
    }
    assert set(_operation(schema, "/api/v1/participants", "post")["responses"]) >= {
        "201",
        "401",
        "403",
        "409",
        "422",
    }
    assert set(
        _operation(schema, "/api/v1/participants/{participant_id}", "get")["responses"]
    ) >= {"200", "401", "403", "404", "422"}

    # O 422 do cadastro sai em dois formatos: texto (documento inexistente, vindo
    # do service) e lista (validação do Pydantic). Os dois precisam estar no schema.
    participant_422 = _operation(schema, "/api/v1/participants", "post")["responses"][
        "422"
    ]["content"]["application/json"]
    assert {ref["$ref"] for ref in participant_422["schema"]["anyOf"]} == {
        "#/components/schemas/ErrorResponse",
        "#/components/schemas/ValidationErrorResponse",
    }
    assert set(participant_422["examples"]) == {"documento_inexistente", "nome_vazio"}

    security_schemes = schema["components"]["securitySchemes"]
    assert security_schemes["BearerAuth"] == {
        "type": "http",
        "description": (
            "Token JWT retornado pelos endpoints de login ou renovação de sessão."
        ),
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    assert _operation(
        schema,
        "/api/v1/authentication/session",
        "get",
    )["security"] == [{"BearerAuth": []}]

    conflict_response = _operation(
        schema,
        "/api/v1/form-responses/{form_response_id}",
        "patch",
    )["responses"]["409"]
    assert conflict_response["description"]
    assert conflict_response["content"]["application/json"]["example"]
