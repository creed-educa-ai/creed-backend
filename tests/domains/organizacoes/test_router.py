"""Testes de app/domains/organizacoes/router.py

A guarda roda de verdade: só o `validate_token` e o `UserService` são dublês, como
em `tests/domains/forms/test_router.py`. A regra de organização do `gestor` é
provada em `test_service.py`; aqui se prova a guarda de papel, a tradução das
exceções do service em status HTTP e o formato da saída.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.organizacoes.dependencies import get_service
from app.domains.organizacoes.models import Organization
from app.domains.organizacoes.router import router
from app.domains.organizacoes.schemas import OrganizationCreate, OrganizationUpdate
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.enums import RecordStatus
from app.shared.exceptions import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DOCUMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")

FAKE_ORGANIZATION = Organization(
    id=ORGANIZATION_ID,
    name="Organização Exemplo",
    address="Av. Ipiranga, 6681",
    document_id=DOCUMENT_ID,
    status=RecordStatus.ACTIVE,
    created_at=datetime(2026, 10, 15, tzinfo=UTC),
    updated_at=None,
)

CHAVES_DA_SAIDA = {
    "id",
    "name",
    "address",
    "document_id",
    "status",
    "created_at",
    "updated_at",
}
TOKEN = {"Authorization": "Bearer valido"}
PAYLOAD = {"name": "Organização Exemplo", "address": "Av. Ipiranga, 6681"}
URL = "/organizacoes"
URL_DA_ORGANIZACAO = f"{URL}/{ORGANIZATION_ID}"


class _FakeService:
    """Dublê: devolve o que for configurado, sem reimplementar a regra.

    `erro` faz qualquer operação levantar aquela exceção, como o service real
    faria. `chamadas` guarda o que o router passou, para conferir.
    """

    def __init__(self, *, erro: DomainError | None = None) -> None:
        self.erro = erro
        self.chamadas: list[tuple[str, Any]] = []

    def _talvez_falhar(self) -> None:
        if self.erro is not None:
            raise self.erro

    async def create(self, request: OrganizationCreate) -> Organization:
        self.chamadas.append(("create", request))
        self._talvez_falhar()
        return FAKE_ORGANIZATION

    async def get(
        self, organization_id: uuid.UUID, *, role: str, own_organization_id: uuid.UUID
    ) -> Organization:
        self.chamadas.append(("get", (organization_id, role, own_organization_id)))
        self._talvez_falhar()
        return FAKE_ORGANIZATION

    async def list_page(
        self, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Organization], int]:
        self.chamadas.append(("list_page", (pagina, tamanho_pagina)))
        self._talvez_falhar()
        return [FAKE_ORGANIZATION], 1

    async def update(
        self, organization_id: uuid.UUID, request: OrganizationUpdate
    ) -> Organization:
        self.chamadas.append(("update", (organization_id, request)))
        self._talvez_falhar()
        return FAKE_ORGANIZATION


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def autenticar_como(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    organization_id: uuid.UUID = ORGANIZATION_ID,
) -> None:
    """Faz o token de teste valer como um usuário ativo com o papel indicado."""
    email = "dev@creed.example.com"

    async def _fake_validate_token(token: str) -> dict[str, Any]:
        return {"sub": "sub-dev", "email": email, "realm_access": {"roles": [role]}}

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=role,
        link_id=uuid.uuid4(),
        organization_id=organization_id,
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)


def usar_service(app: FastAPI, service: _FakeService) -> _FakeService:
    app.dependency_overrides[get_service] = lambda: service
    return service


def _payload_de_criacao() -> dict[str, str]:
    return {**PAYLOAD, "document_id": str(DOCUMENT_ID)}


class TestSemToken:
    @pytest.mark.parametrize(
        ("metodo", "url"),
        [
            ("POST", URL),
            ("GET", URL),
            ("GET", URL_DA_ORGANIZACAO),
            ("PATCH", URL_DA_ORGANIZACAO),
        ],
        ids=["criar", "listar", "consultar", "alterar"],
    )
    def test_devolve_401(
        self, app: FastAPI, client: TestClient, metodo: str, url: str
    ) -> None:
        usar_service(app, _FakeService())

        assert client.request(metodo, url, json={}).status_code == 401


class TestSoAdmin:
    """Cadastro, listagem e alteração são só do `admin`, e a guarda barra antes."""

    @pytest.mark.parametrize("role", ["gestor", "respondente"])
    @pytest.mark.parametrize(
        ("metodo", "url", "corpo"),
        [
            ("POST", URL, _payload_de_criacao()),
            ("GET", URL, None),
            ("PATCH", URL_DA_ORGANIZACAO, {"name": "Novo nome"}),
        ],
        ids=["criar", "listar", "alterar"],
    )
    def test_outro_papel_devolve_403_sem_chegar_ao_service(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        role: str,
        metodo: str,
        url: str,
        corpo: dict[str, str] | None,
    ) -> None:
        autenticar_como(app, monkeypatch, role)
        service = usar_service(app, _FakeService())

        response = client.request(metodo, url, json=corpo, headers=TOKEN)

        assert response.status_code == 403
        assert service.chamadas == []


class TestCriar:
    def test_admin_com_payload_valido_devolve_201_no_formato_do_contrato(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        usar_service(app, _FakeService())

        response = client.post(URL, json=_payload_de_criacao(), headers=TOKEN)

        assert response.status_code == 201
        body = response.json()
        assert set(body) == CHAVES_DA_SAIDA
        assert body["status"] == "active"
        assert body["document_id"] == str(DOCUMENT_ID)

    def test_documento_inexistente_devolve_422(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        erro = ValidationError(f"Documento {DOCUMENT_ID} não encontrado")
        usar_service(app, _FakeService(erro=erro))

        response = client.post(URL, json=_payload_de_criacao(), headers=TOKEN)

        assert response.status_code == 422
        assert response.json()["detail"] == erro.message

    def test_documento_em_uso_devolve_409(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        erro = ConflictError(f"O documento {DOCUMENT_ID} já pertence a outra organização")
        usar_service(app, _FakeService(erro=erro))

        response = client.post(URL, json=_payload_de_criacao(), headers=TOKEN)

        assert response.status_code == 409
        assert response.json()["detail"] == erro.message

    @pytest.mark.parametrize(
        "payload",
        [
            {"address": "Rua A", "document_id": str(DOCUMENT_ID)},
            {"name": "", "address": "Rua A", "document_id": str(DOCUMENT_ID)},
            {"name": "Org", "document_id": str(DOCUMENT_ID)},
            {"name": "Org", "address": "Rua A"},
            {"name": "Org", "address": "Rua A", "document_id": "não-é-um-uuid"},
        ],
        ids=[
            "sem_nome",
            "nome_vazio",
            "sem_endereco",
            "sem_documento",
            "documento_nao_uuid",
        ],
    )
    def test_payload_invalido_devolve_422_sem_chegar_ao_service(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        payload: dict[str, str],
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service = usar_service(app, _FakeService())

        response = client.post(URL, json=payload, headers=TOKEN)

        assert response.status_code == 422
        assert service.chamadas == []


class TestListar:
    def test_admin_recebe_a_pagina_no_envelope_compartilhado(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service = usar_service(app, _FakeService())

        response = client.get(
            URL, params={"pagina": 2, "tamanho_pagina": 10}, headers=TOKEN
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"itens", "total", "pagina", "tamanho_pagina"}
        assert (body["total"], body["pagina"], body["tamanho_pagina"]) == (1, 2, 10)
        assert set(body["itens"][0]) == CHAVES_DA_SAIDA
        assert service.chamadas == [("list_page", (2, 10))]

    def test_sem_query_usa_a_primeira_pagina_com_50(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service = usar_service(app, _FakeService())

        assert client.get(URL, headers=TOKEN).status_code == 200
        assert service.chamadas == [("list_page", (1, 50))]

    @pytest.mark.parametrize(
        "params",
        [{"pagina": 0}, {"tamanho_pagina": 0}, {"tamanho_pagina": 201}],
        ids=["pagina_zero", "tamanho_zero", "tamanho_acima_de_200"],
    )
    def test_query_fora_dos_limites_devolve_422(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        params: dict[str, int],
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service = usar_service(app, _FakeService())

        assert client.get(URL, params=params, headers=TOKEN).status_code == 422
        assert service.chamadas == []


class TestConsultar:
    @pytest.mark.parametrize("role", ["admin", "gestor"])
    def test_admin_e_gestor_chegam_ao_service_com_papel_e_organizacao(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        role: str,
    ) -> None:
        autenticar_como(app, monkeypatch, role)
        service = usar_service(app, _FakeService())

        response = client.get(URL_DA_ORGANIZACAO, headers=TOKEN)

        assert response.status_code == 200
        assert set(response.json()) == CHAVES_DA_SAIDA
        assert service.chamadas == [("get", (ORGANIZATION_ID, role, ORGANIZATION_ID))]

    def test_respondente_devolve_403_pela_guarda(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A spec não dá esta rota ao respondente, nem para a própria organização."""
        autenticar_como(app, monkeypatch, "respondente")
        service = usar_service(app, _FakeService())

        response = client.get(URL_DA_ORGANIZACAO, headers=TOKEN)

        assert response.status_code == 403
        assert service.chamadas == []

    def test_organizacao_alheia_devolve_403_pelo_service(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "gestor")
        erro = ForbiddenError("Sem acesso a organização de outro vínculo")
        usar_service(app, _FakeService(erro=erro))

        response = client.get(URL_DA_ORGANIZACAO, headers=TOKEN)

        assert response.status_code == 403
        assert response.json()["detail"] == erro.message

    def test_inexistente_devolve_404(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        usar_service(app, _FakeService(erro=NotFoundError("não encontrada")))

        assert client.get(URL_DA_ORGANIZACAO, headers=TOKEN).status_code == 404


class TestAlterar:
    def test_admin_altera_e_o_service_recebe_so_o_que_veio(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service = usar_service(app, _FakeService())

        response = client.patch(
            URL_DA_ORGANIZACAO, json={"status": "inactive"}, headers=TOKEN
        )

        assert response.status_code == 200
        assert set(response.json()) == CHAVES_DA_SAIDA
        [(operacao, (organization_id, request))] = service.chamadas
        assert (operacao, organization_id) == ("update", ORGANIZATION_ID)
        assert request.model_dump(exclude_unset=True) == {"status": RecordStatus.INACTIVE}

    def test_inexistente_devolve_404(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        usar_service(app, _FakeService(erro=NotFoundError("não encontrada")))

        response = client.patch(URL_DA_ORGANIZACAO, json={"name": "X"}, headers=TOKEN)

        assert response.status_code == 404

    @pytest.mark.parametrize("campo", ["name", "address", "status"])
    def test_null_explicito_devolve_422_sem_chegar_ao_service(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        campo: str,
    ) -> None:
        """Os três são obrigatórios no banco: `null` gravado virava 500 no `flush()`."""
        autenticar_como(app, monkeypatch, "admin")
        service = usar_service(app, _FakeService())

        response = client.patch(URL_DA_ORGANIZACAO, json={campo: None}, headers=TOKEN)

        assert response.status_code == 422
        assert service.chamadas == []

    def test_corpo_vazio_chega_ao_service_sem_campo_algum(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Omitir não é o mesmo que mandar `null`: omitido, nada muda."""
        autenticar_como(app, monkeypatch, "admin")
        service = usar_service(app, _FakeService())

        assert client.patch(URL_DA_ORGANIZACAO, json={}, headers=TOKEN).status_code == 200
        [(_, (_, request))] = service.chamadas
        assert request.model_dump(exclude_unset=True) == {}

    def test_document_id_nao_e_campo_do_patch(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Trocar o documento não está no contrato: o campo é ignorado."""
        autenticar_como(app, monkeypatch, "admin")
        service = usar_service(app, _FakeService())

        client.patch(
            URL_DA_ORGANIZACAO,
            json={"document_id": str(uuid.uuid4())},
            headers=TOKEN,
        )

        [(_, (_, request))] = service.chamadas
        assert request.model_dump(exclude_unset=True) == {}
