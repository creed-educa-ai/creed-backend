"""Testes do contrato OpenAPI exibido no Swagger UI."""

from typing import Any

from fastapi.testclient import TestClient

from app.main import app


def _operation(schema: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    operation: dict[str, Any] = schema["paths"][path][method]
    return operation


def test_swagger_ui_is_available_at_the_documented_url() -> None:
    response = TestClient(app).get("/api/v1/docs")

    assert response.status_code == 200
    assert "url: '/api/v1/openapi.json'" in response.text


def test_all_endpoints_have_method_summary_description_and_operation_id() -> None:
    schema = app.openapi()
    expected_operations = {
        ("/health", "get"),
        ("/api/v1/authentication/login", "post"),
        ("/api/v1/authentication/renew", "post"),
        ("/api/v1/authentication/session", "get"),
        ("/api/v1/users", "post"),
        ("/api/v1/users/{user_id}", "delete"),
        ("/api/v1/forms", "post"),
        ("/api/v1/forms/{form_id}", "get"),
        ("/api/v1/form-responses", "post"),
        ("/api/v1/form-responses/{form_response_id}", "patch"),
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
    assert components["UserCreate"]["examples"]
    assert components["FormResponseCreate"]["examples"]
    assert components["SessionResponse"]["examples"]
    assert components["UserResponse"]["examples"]
    assert components["FormResponseResponse"]["examples"]
    assert components["ParticipantCreate"]["examples"]
    assert components["ParticipantResponse"]["examples"]

    for schema_name in (
        "LoginRequest",
        "UserCreate",
        "FormResponseCreate",
        "ParticipantCreate",
    ):
        for field in components[schema_name]["properties"].values():
            assert field["description"]

    delete_user = _operation(schema, "/api/v1/users/{user_id}", "delete")
    user_id = delete_user["parameters"][0]
    assert user_id["name"] == "user_id"
    assert user_id["description"]
    assert user_id["schema"]["examples"]

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

    assert set(
        _operation(schema, "/api/v1/authentication/login", "post")["responses"]
    ) >= {"200", "401", "422"}
    assert set(_operation(schema, "/api/v1/users", "post")["responses"]) >= {
        "201",
        "409",
        "422",
    }
    assert set(_operation(schema, "/api/v1/form-responses", "post")["responses"]) >= {
        "201",
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
        "409",
        "422",
    }
    assert set(
        _operation(schema, "/api/v1/forms/{form_id}/questions", "get")["responses"]
    ) >= {"200", "404"}
    assert set(
        _operation(
            schema,
            "/api/v1/form-responses/{form_response_id}",
            "patch",
        )["responses"]
    ) >= {"200", "404", "409", "422"}
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
