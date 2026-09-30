"""Testes de contrato HTTP do domínio participants.

A guarda `require_role("admin")` roda de verdade: só o `validate_token` do
Keycloak e o service de users são trocados por dublês, como em
`tests/shared/test_authorization.py`. Assim 401 e 403 são provados na rota, e não
só na guarda isolada. O service de participants também é dublê: a regra dele está
em `test_service.py`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.participants.dependencies import get_service
from app.domains.participants.models import Participant
from app.domains.participants.router import router
from app.domains.participants.schemas import ParticipantCreate
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.models import User, UserRole
from app.shared.enums import RecordStatus
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError

TOKEN = {"Authorization": "Bearer token-de-teste"}

# Ids que o service falso recusa, para provar a tradução de cada erro em status.
DOCUMENTO_INEXISTENTE = uuid.UUID("00000000-0000-4000-8000-000000000001")
DOCUMENTO_EM_USO = uuid.UUID("00000000-0000-4000-8000-000000000002")


class _FakeParticipantService:
    def __init__(self) -> None:
        self.itens: list[Participant] = []

    async def create_participant(self, request: ParticipantCreate) -> Participant:
        if request.document_id == DOCUMENTO_INEXISTENTE:
            raise ValidationError(f"Documento {request.document_id} não encontrado")
        if request.document_id == DOCUMENTO_EM_USO:
            raise ConflictError(
                f"O documento {request.document_id} já pertence a outro participante"
            )

        participant = Participant(
            id=uuid.uuid4(),
            name=request.name,
            document_id=request.document_id,
            status=RecordStatus.ACTIVE,
            created_at=datetime(2026, 9, 27, tzinfo=UTC),
            updated_at=None,
        )
        self.itens.append(participant)
        return participant

    async def get_participant(self, participant_id: uuid.UUID) -> Participant:
        for participant in self.itens:
            if participant.id == participant_id:
                return participant
        raise NotFoundError(f"Participante {participant_id} não encontrado")


class _FakeUserService:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_active_user_by_email(self, email: str) -> User | None:
        return self._user


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    fastapi_app.dependency_overrides[get_service] = _FakeParticipantService
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def autenticar_como(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, role: UserRole
) -> None:
    """Faz o token de teste valer como um usuário ativo com o papel indicado."""
    email = "dev@creed.example.com"

    async def _fake_validate_token(token: str) -> dict[str, Any]:
        return {"sub": "sub-dev", "email": email, "realm_access": {"roles": [role.value]}}

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    user = User(
        id=uuid.uuid4(),
        keycloak_id=uuid.uuid4(),
        email=email,
        name="Dev CREED",
        status=RecordStatus.ACTIVE,
        role=role,
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(user)


class TestComAdmin:
    @pytest.fixture(autouse=True)
    def _admin(self, app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
        autenticar_como(app, monkeypatch, UserRole.ADMIN)
        # Um service só para a classe inteira: o GET precisa enxergar o que o POST gravou.
        service = _FakeParticipantService()
        app.dependency_overrides[get_service] = lambda: service

    def test_cadastra_e_devolve_201_ativo(self, client: TestClient) -> None:
        response = client.post(
            "/participants", json={"name": "Pessoa Exemplo"}, headers=TOKEN
        )

        assert response.status_code == 201
        corpo = response.json()
        assert corpo["name"] == "Pessoa Exemplo"
        assert corpo["status"] == "active"
        assert corpo["document_id"] is None
        assert corpo["updated_at"] is None

    def test_cadastra_com_documento_e_devolve_o_mesmo_id(
        self, client: TestClient
    ) -> None:
        documento = str(uuid.uuid4())

        response = client.post(
            "/participants",
            json={"name": "Pessoa Exemplo", "document_id": documento},
            headers=TOKEN,
        )

        assert response.status_code == 201
        assert response.json()["document_id"] == documento

    def test_documento_inexistente_devolve_422(self, client: TestClient) -> None:
        response = client.post(
            "/participants",
            json={"name": "Pessoa Exemplo", "document_id": str(DOCUMENTO_INEXISTENTE)},
            headers=TOKEN,
        )

        assert response.status_code == 422
        assert response.json()["detail"].startswith("Documento")

    def test_documento_de_outra_pessoa_devolve_409(self, client: TestClient) -> None:
        response = client.post(
            "/participants",
            json={"name": "Pessoa Exemplo", "document_id": str(DOCUMENTO_EM_USO)},
            headers=TOKEN,
        )

        assert response.status_code == 409

    def test_document_id_malformado_devolve_422(self, client: TestClient) -> None:
        response = client.post(
            "/participants",
            json={"name": "Pessoa Exemplo", "document_id": "nao-e-uuid"},
            headers=TOKEN,
        )

        assert response.status_code == 422
        # Erro do Pydantic: `detail` é lista, não texto como o do service.
        assert response.json()["detail"][0]["loc"] == ["body", "document_id"]

    def test_remove_espacos_das_pontas_do_nome(self, client: TestClient) -> None:
        response = client.post(
            "/participants", json={"name": "  Pessoa Exemplo  "}, headers=TOKEN
        )

        assert response.status_code == 201
        assert response.json()["name"] == "Pessoa Exemplo"

    @pytest.mark.parametrize(
        "nome",
        ["", "   ", "a" * 201, "Pessoa\x00Exemplo", "Pessoa\nExemplo", "Pessoa\tExemplo"],
    )
    def test_nome_invalido_devolve_422(self, client: TestClient, nome: str) -> None:
        response = client.post("/participants", json={"name": nome}, headers=TOKEN)

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "name"]

    def test_consulta_o_participante_cadastrado(self, client: TestClient) -> None:
        criado = client.post(
            "/participants", json={"name": "Pessoa Exemplo"}, headers=TOKEN
        ).json()

        response = client.get(f"/participants/{criado['id']}", headers=TOKEN)

        assert response.status_code == 200
        assert response.json() == criado

    def test_id_inexistente_devolve_404(self, client: TestClient) -> None:
        response = client.get(f"/participants/{uuid.uuid4()}", headers=TOKEN)

        assert response.status_code == 404
        assert response.json()["detail"].startswith("Participante")


class TestSemAcesso:
    def test_sem_token_devolve_401_nas_duas_rotas(self, client: TestClient) -> None:
        assert client.post("/participants", json={"name": "X"}).status_code == 401
        assert client.get(f"/participants/{uuid.uuid4()}").status_code == 401

    @pytest.mark.parametrize("role", [UserRole.GESTOR, UserRole.RESPONDENTE])
    def test_papel_diferente_de_admin_devolve_403_nas_duas_rotas(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        role: UserRole,
    ) -> None:
        """P-022 — só admin cadastra e consulta participante."""
        autenticar_como(app, monkeypatch, role)

        cadastro = client.post("/participants", json={"name": "X"}, headers=TOKEN)
        consulta = client.get(f"/participants/{uuid.uuid4()}", headers=TOKEN)

        assert cadastro.status_code == 403
        assert consulta.status_code == 403
