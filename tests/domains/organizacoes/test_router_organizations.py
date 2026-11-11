"""Testes de app/domains/organizacoes/router_organizations.py

O cadastro é público: não há guarda, então não há dublê de `validate_token`. O
service é um dublê; a regra (documento repetido, status `pending`, e-mail em
minúsculas) é provada em `test_service.py`. Aqui se prova a validação do corpo, a
limpeza do documento antes de chegar ao service, a tradução do 409 e o formato da
saída, com o documento que o `with_documents` junta.

A exclusão tem guarda, que roda de verdade: só o `validate_token` e o `UserService`
são dublês (`autenticar_como`, como em `test_router.py`). O
`OrganizationRemovalService` é um dublê; a ordem do que sai é provada em
`tests/domains/users/test_organization_removal_service.py`.

A aprovação tem a mesma guarda e o mesmo `autenticar_como`. O
`OrganizationApprovalService` é um dublê; o status e o convite são provados em
`tests/domains/users/test_organization_approval_service.py`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.organizacoes.dependencies import get_service
from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.domains.organizacoes.router_organizations import router
from app.domains.organizacoes.schemas import OrganizationSignUp
from app.domains.organizacoes.service import OrganizationWithDocument
from app.domains.users.dependencies import (
    get_organization_approval_service,
    get_organization_removal_service,
)
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    ServiceUnavailableError,
)

URL = "/organizations/sign-up"

PENDING_ORGANIZATION = Organization(
    id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    name="Empresa Teste",
    address="[A informar]",
    document_id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
    status=OrganizationStatus.PENDING,
    email="gestora@empresa.com.br",
    contact_name="Gestora Teste",
    phone="51 99999-0000",
    created_at=datetime(2026, 11, 10, tzinfo=UTC),
    updated_at=None,
)

CHAVES_DA_SAIDA = {
    "id",
    "name",
    "address",
    "document_id",
    "status",
    "email",
    "contact_name",
    "phone",
    "document",
    "created_at",
    "updated_at",
}

CORPO = {
    "name": "Empresa Teste",
    "document": "12.345.678/0001-90",
    "email": "Gestora@Empresa.com.br",
    "contact_name": "Gestora Teste",
    "phone": "51 99999-0000",
}


class _FakeService:
    """Dublê: devolve a organização pendente, ou levanta o `erro` configurado.

    `pedidos` guarda o corpo já validado que o router passou ao `sign_up`.
    """

    def __init__(self, *, erro: ConflictError | None = None) -> None:
        self.erro = erro
        self.pedidos: list[OrganizationSignUp] = []

    async def sign_up(self, request: OrganizationSignUp) -> Organization:
        self.pedidos.append(request)
        if self.erro is not None:
            raise self.erro
        return PENDING_ORGANIZATION

    async def with_documents(
        self, organizations: list[Organization]
    ) -> list[OrganizationWithDocument]:
        return [
            OrganizationWithDocument(
                organization=organization,
                document_type="cnpj",
                document_value="12345678000190",
            )
            for organization in organizations
        ]


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def usar_service(app: FastAPI, service: _FakeService) -> _FakeService:
    app.dependency_overrides[get_service] = lambda: service
    return service


def _campos_recusados(response: Any) -> set[str]:
    return {erro["loc"][-1] for erro in response.json()["detail"]}


class TestCadastro:
    def test_sem_token_devolve_201_pendente_no_formato_do_contrato(
        self, app: FastAPI, client: TestClient
    ) -> None:
        usar_service(app, _FakeService())

        response = client.post(URL, json=CORPO)

        assert response.status_code == 201
        body = response.json()
        assert set(body) == CHAVES_DA_SAIDA
        assert body["status"] == "pending"
        assert body["address"] == "[A informar]"
        assert body["document"] == {"type": "cnpj", "value": "12345678000190"}
        assert (body["email"], body["contact_name"], body["phone"]) == (
            "gestora@empresa.com.br",
            "Gestora Teste",
            "51 99999-0000",
        )

    @pytest.mark.parametrize(
        "cabecalho",
        [
            {"Authorization": "Bearer qualquer-coisa"},
            {"Authorization": "Basic nao-e-bearer"},
        ],
        ids=["bearer_invalido", "outro_esquema"],
    )
    def test_com_token_se_comporta_igual(
        self, app: FastAPI, client: TestClient, cabecalho: dict[str, str]
    ) -> None:
        """A rota não olha o token: um token qualquer não vira 401 nem 403."""
        service = usar_service(app, _FakeService())

        response = client.post(URL, json=CORPO, headers=cabecalho)

        assert response.status_code == 201
        assert len(service.pedidos) == 1

    def test_espacos_nas_pontas_saem_antes_de_chegar_ao_service(
        self, app: FastAPI, client: TestClient
    ) -> None:
        service = usar_service(app, _FakeService())

        client.post(URL, json={**CORPO, "name": "  Empresa Teste  ", "phone": " 51 "})

        [pedido] = service.pedidos
        assert (pedido.name, pedido.phone) == ("Empresa Teste", "51")

    def test_documento_repetido_devolve_409(
        self, app: FastAPI, client: TestClient
    ) -> None:
        erro = ConflictError("Já existe um cadastro com este documento")
        usar_service(app, _FakeService(erro=erro))

        response = client.post(URL, json=CORPO)

        assert response.status_code == 409
        assert response.json()["detail"] == erro.message


class TestDocumento:
    """🟡 P-076: o service recebe só os dígitos, e só com 11 ou 14 deles."""

    @pytest.mark.parametrize(
        ("digitado", "guardado"),
        [
            ("12.345.678/0001-90", "12345678000190"),
            ("12345678000190", "12345678000190"),
            ("123.456.789-09", "12345678909"),
            ("12_345_678\t0001 90", "12345678000190"),
        ],
        ids=["cnpj_pontuado", "cnpj_limpo", "cpf_pontuado", "sublinhado_e_tab"],
    )
    def test_chega_ao_service_so_com_os_digitos(
        self, app: FastAPI, client: TestClient, digitado: str, guardado: str
    ) -> None:
        service = usar_service(app, _FakeService())

        response = client.post(URL, json={**CORPO, "document": digitado})

        assert response.status_code == 201
        assert [pedido.document for pedido in service.pedidos] == [guardado]

    @pytest.mark.parametrize(
        "documento",
        [
            "123",
            "1234567890",
            "123456789012",
            "1234567800019a",
            "".join(chr(0xFF10 + int(c)) for c in "12345678000190"),
            "...",
        ],
        ids=[
            "tres_digitos",
            "dez_digitos",
            "doze_digitos",
            "letra_no_meio",
            "digitos_de_largura_cheia",
            "so_pontuacao",
        ],
    )
    def test_sem_11_nem_14_digitos_devolve_422_sem_chegar_ao_service(
        self, app: FastAPI, client: TestClient, documento: str
    ) -> None:
        service = usar_service(app, _FakeService())

        response = client.post(URL, json={**CORPO, "document": documento})

        assert response.status_code == 422
        assert _campos_recusados(response) == {"document"}
        assert service.pedidos == []


class TestCorpoInvalido:
    @pytest.mark.parametrize("campo", list(CORPO))
    def test_campo_ausente_devolve_422_com_o_nome_do_campo(
        self, app: FastAPI, client: TestClient, campo: str
    ) -> None:
        service = usar_service(app, _FakeService())
        corpo = {chave: valor for chave, valor in CORPO.items() if chave != campo}

        response = client.post(URL, json=corpo)

        assert response.status_code == 422
        assert _campos_recusados(response) == {campo}
        assert service.pedidos == []

    @pytest.mark.parametrize("campo", list(CORPO))
    def test_campo_vazio_ou_so_espaco_devolve_422_com_o_nome_do_campo(
        self, app: FastAPI, client: TestClient, campo: str
    ) -> None:
        service = usar_service(app, _FakeService())

        response = client.post(URL, json={**CORPO, campo: "   "})

        assert response.status_code == 422
        assert _campos_recusados(response) == {campo}
        assert service.pedidos == []

    def test_corpo_vazio_devolve_um_item_por_campo(
        self, app: FastAPI, client: TestClient
    ) -> None:
        usar_service(app, _FakeService())

        response = client.post(URL, json={})

        assert response.status_code == 422
        assert _campos_recusados(response) == set(CORPO)
        assert len(response.json()["detail"]) == len(CORPO)

    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("name", "x" * 201),
            ("contact_name", "x" * 201),
            ("phone", "1" * 31),
            ("document", "1" * 101),
        ],
        ids=["nome", "responsavel", "telefone", "documento"],
    )
    def test_longo_demais_devolve_422(
        self, app: FastAPI, client: TestClient, campo: str, valor: str
    ) -> None:
        service = usar_service(app, _FakeService())

        response = client.post(URL, json={**CORPO, campo: valor})

        assert response.status_code == 422
        assert _campos_recusados(response) == {campo}
        assert service.pedidos == []

    def test_responsavel_com_um_caractere_devolve_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """🟡 P-082: o convite da aprovação exige nome com 2 ou mais."""
        service = usar_service(app, _FakeService())

        response = client.post(URL, json={**CORPO, "contact_name": "A"})

        assert response.status_code == 422
        assert _campos_recusados(response) == {"contact_name"}
        assert service.pedidos == []

    @pytest.mark.parametrize("campo", ["name", "contact_name", "phone"])
    def test_caractere_de_controle_devolve_422(
        self, app: FastAPI, client: TestClient, campo: str
    ) -> None:
        """O `\\x00` dava 500 no Postgres; quebra de linha não faz sentido aqui."""
        service = usar_service(app, _FakeService())

        response = client.post(URL, json={**CORPO, campo: "Antes\x00depois"})

        assert response.status_code == 422
        assert _campos_recusados(response) == {campo}
        assert service.pedidos == []

    @pytest.mark.parametrize(
        "email", ["sem-arroba", "pessoa@", "pessoa@dominio", "a b@empresa.com.br"]
    )
    def test_email_mal_formado_devolve_422(
        self, app: FastAPI, client: TestClient, email: str
    ) -> None:
        service = usar_service(app, _FakeService())

        response = client.post(URL, json={**CORPO, "email": email})

        assert response.status_code == 422
        assert _campos_recusados(response) == {"email"}
        assert service.pedidos == []


# --- Exclusão de empresa (E-6) -----------------------------------------------

# A organização do caminho e a de quem pede são diferentes de propósito: o teste
# prova que a de quem pede sai do token, e não do endereço.
TARGET_ID = uuid.UUID("8f14e45f-ceea-467e-adde-3f81905dbc1c")
OWN_ORGANIZATION_ID = uuid.UUID("3f2b8c1e-7a4d-4e9b-9c0a-5d6e7f8a9b0c")
URL_DA_EMPRESA = f"/organizations/{TARGET_ID}"
TOKEN = {"Authorization": "Bearer valido"}


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


def autenticar_como(app: FastAPI, monkeypatch: pytest.MonkeyPatch, role: str) -> None:
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
        organization_id=OWN_ORGANIZATION_ID,
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)


class _FakeRemovalService:
    """Dublê do `OrganizationRemovalService`: guarda o que recebeu, ou levanta `erro`."""

    def __init__(self, *, erro: DomainError | None = None) -> None:
        self.erro = erro
        self.calls: list[dict[str, uuid.UUID]] = []

    async def remove_organization(
        self, organization_id: uuid.UUID, *, own_organization_id: uuid.UUID
    ) -> None:
        self.calls.append(
            {
                "organization_id": organization_id,
                "own_organization_id": own_organization_id,
            }
        )
        if self.erro is not None:
            raise self.erro


def usar_removal_service(
    app: FastAPI, service: _FakeRemovalService
) -> _FakeRemovalService:
    app.dependency_overrides[get_organization_removal_service] = lambda: service
    return service


class TestExclusao:
    def test_admin_devolve_204_sem_corpo(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service = usar_removal_service(app, _FakeRemovalService())

        response = client.delete(URL_DA_EMPRESA, headers=TOKEN)

        assert response.status_code == 204
        assert response.content == b""
        assert service.calls == [
            {"organization_id": TARGET_ID, "own_organization_id": OWN_ORGANIZATION_ID}
        ]

    def test_sem_token_devolve_401(self, app: FastAPI, client: TestClient) -> None:
        service = usar_removal_service(app, _FakeRemovalService())

        response = client.delete(URL_DA_EMPRESA)

        assert response.status_code == 401
        assert service.calls == []

    @pytest.mark.parametrize("role", ["gestor", "respondente"])
    def test_outro_papel_devolve_403_sem_chegar_ao_service(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        role: str,
    ) -> None:
        """🟡 P-079: o service não confere o papel; quem barra é a guarda."""
        autenticar_como(app, monkeypatch, role)
        service = usar_removal_service(app, _FakeRemovalService())

        response = client.delete(URL_DA_EMPRESA, headers=TOKEN)

        assert response.status_code == 403
        assert service.calls == []

    @pytest.mark.parametrize(
        ("erro", "status_esperado"),
        [
            (NotFoundError(f"Organização {TARGET_ID} não encontrada"), 404),
            (ConflictError("Não é possível excluir a própria organização"), 409),
            (
                ServiceUnavailableError(
                    "Não foi possível remover o acesso agora. Tente de novo."
                ),
                503,
            ),
        ],
        ids=["inexistente", "propria_organizacao", "keycloak_fora"],
    )
    def test_traduz_os_erros_do_service(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        erro: DomainError,
        status_esperado: int,
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        usar_removal_service(app, _FakeRemovalService(erro=erro))

        response = client.delete(URL_DA_EMPRESA, headers=TOKEN)

        assert response.status_code == status_esperado
        assert response.json() == {"detail": erro.message}

    def test_id_que_nao_e_uuid_devolve_422_sem_chegar_ao_service(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service = usar_removal_service(app, _FakeRemovalService())

        response = client.delete("/organizations/nao-e-uuid", headers=TOKEN)

        assert response.status_code == 422
        assert service.calls == []


# --- Aprovação de empresa (E-3) ----------------------------------------------

URL_DA_APROVACAO = f"/organizations/{TARGET_ID}/approval"

APPROVED_ORGANIZATION = Organization(
    id=TARGET_ID,
    name="Empresa Teste",
    address="[A informar]",
    document_id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
    status=OrganizationStatus.ACTIVE,
    email="gestora@empresa.com.br",
    contact_name="Gestora Teste",
    phone="51 99999-0000",
    created_at=datetime(2026, 11, 10, tzinfo=UTC),
    updated_at=None,
)


class _FakeApprovalService:
    """Dublê do `OrganizationApprovalService`: guarda o que recebeu, ou levanta `erro`."""

    def __init__(self, *, erro: DomainError | None = None) -> None:
        self.erro = erro
        self.calls: list[dict[str, uuid.UUID]] = []

    async def approve(
        self, organization_id: uuid.UUID, *, own_organization_id: uuid.UUID
    ) -> OrganizationWithDocument:
        self.calls.append(
            {
                "organization_id": organization_id,
                "own_organization_id": own_organization_id,
            }
        )
        if self.erro is not None:
            raise self.erro
        return OrganizationWithDocument(
            organization=APPROVED_ORGANIZATION,
            document_type="cnpj",
            document_value="12345678000190",
        )


def usar_approval_service(
    app: FastAPI, service: _FakeApprovalService
) -> _FakeApprovalService:
    app.dependency_overrides[get_organization_approval_service] = lambda: service
    return service


class TestAprovacao:
    def test_admin_devolve_200_com_a_empresa_ativa(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service = usar_approval_service(app, _FakeApprovalService())

        response = client.post(URL_DA_APROVACAO, headers=TOKEN)

        assert response.status_code == 200
        body = response.json()
        assert set(body) == CHAVES_DA_SAIDA
        assert body["id"] == str(TARGET_ID)
        assert body["status"] == "active"
        assert body["document"] == {"type": "cnpj", "value": "12345678000190"}
        assert service.calls == [
            {"organization_id": TARGET_ID, "own_organization_id": OWN_ORGANIZATION_ID}
        ]

    def test_sem_token_devolve_401(self, app: FastAPI, client: TestClient) -> None:
        service = usar_approval_service(app, _FakeApprovalService())

        response = client.post(URL_DA_APROVACAO)

        assert response.status_code == 401
        assert service.calls == []

    @pytest.mark.parametrize("role", ["gestor", "respondente"])
    def test_outro_papel_devolve_403_sem_chegar_ao_service(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        role: str,
    ) -> None:
        """🟡 P-079: o service não confere o papel; quem barra é a guarda."""
        autenticar_como(app, monkeypatch, role)
        service = usar_approval_service(app, _FakeApprovalService())

        response = client.post(URL_DA_APROVACAO, headers=TOKEN)

        assert response.status_code == 403
        assert service.calls == []

    @pytest.mark.parametrize(
        ("erro", "status_esperado"),
        [
            (NotFoundError(f"Organização {TARGET_ID} não encontrada"), 404),
            (ConflictError(f"A empresa {TARGET_ID} não está pendente"), 409),
            (
                ConflictError("Já existe usuário com o e-mail gestora@empresa.com.br"),
                409,
            ),
            (
                ServiceUnavailableError(
                    "Não foi possível criar o acesso agora. Tente de novo."
                ),
                503,
            ),
        ],
        ids=["inexistente", "nao_pendente", "email_com_acesso", "convite_fora"],
    )
    def test_traduz_os_erros_do_service(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        erro: DomainError,
        status_esperado: int,
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        usar_approval_service(app, _FakeApprovalService(erro=erro))

        response = client.post(URL_DA_APROVACAO, headers=TOKEN)

        assert response.status_code == status_esperado
        assert response.json() == {"detail": erro.message}

    def test_id_que_nao_e_uuid_devolve_422_sem_chegar_ao_service(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service = usar_approval_service(app, _FakeApprovalService())

        response = client.post("/organizations/nao-e-uuid/approval", headers=TOKEN)

        assert response.status_code == 422
        assert service.calls == []
