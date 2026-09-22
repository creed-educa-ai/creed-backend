"""Testes do contrato OpenAPI exibido no Swagger UI."""

from typing import Any

from fastapi.testclient import TestClient

from app.main import app


def _operation(schema: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    return schema["paths"][path][method]


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
        ("/api/v1/form-responses", "post"),
        ("/api/v1/form-responses/{form_response_id}", "patch"),
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


def test_request_fields_path_parameters_and_examples_are_documented() -> None:
    schema = app.openapi()
    components = schema["components"]["schemas"]

    assert components["LoginRequest"]["examples"]
    assert components["UserCreate"]["examples"]
    assert components["FormResponseCreate"]["examples"]
    assert components["SessionResponse"]["examples"]
    assert components["UserResponse"]["examples"]
    assert components["FormResponseResponse"]["examples"]

    for schema_name in ("LoginRequest", "UserCreate", "FormResponseCreate"):
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
    assert set(
        _operation(
            schema,
            "/api/v1/form-responses/{form_response_id}",
            "patch",
        )["responses"]
    ) >= {"200", "404", "409", "422"}

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
