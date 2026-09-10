"""Testes do realm versionado (`docker/keycloak/realm-creed.json`).

O realm é arquivo, não clique na UI — é o item que impede dev e produção de
divergirem sem ninguém perceber (spec da CREED-23, seção Riscos). Arquivo JSON,
porém, não tem comentário e não tem compilador: um `directAccessGrantsEnabled`
que vira `false` numa edição só aparece quando o login inteiro para de funcionar.

Estes testes são a leitura de review desse arquivo, em forma de CI. Eles não
sobem o Keycloak: leem o JSON e conferem o que a spec e o contrato decidiram.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings

REALM = json.loads(
    (
        Path(__file__).resolve().parents[1] / "docker" / "keycloak" / "realm-creed.json"
    ).read_text(encoding="utf-8")
)

PAPEIS = {"admin", "gestor", "respondente"}


@pytest.fixture
def client() -> dict[str, Any]:
    """O client confidencial do backend — o único que fala com este realm."""
    return next(c for c in REALM["clients"] if c["clientId"] == "creed-backend")


def test_realm_e_client_batem_com_os_defaults_da_settings(
    monkeypatch: pytest.MonkeyPatch, client: dict[str, Any]
) -> None:
    """Se o arquivo e a Settings divergirem, o setup do time quebra no primeiro login."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "irrelevante")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "irrelevante")
    settings = Settings(_env_file=None)

    assert REALM["realm"] == settings.KEYCLOAK_REALM
    assert client["clientId"] == settings.KEYCLOAK_CLIENT_ID


def test_client_e_confidencial_com_direct_access_grant(
    client: dict[str, Any],
) -> None:
    """Decisão D1: o backend intermedeia o login como confidential client."""
    assert client["publicClient"] is False
    assert client["directAccessGrantsEnabled"] is True


def test_papeis_do_realm_sao_os_da_premissa_p006() -> None:
    nomes = {papel["name"] for papel in REALM["roles"]["realm"]}

    assert nomes == PAPEIS


def test_usuario_de_teste_entra_pelo_token_endpoint() -> None:
    """O `curl` do critério de aceite depende de um usuário vindo do próprio export.

    Sem `requiredActions` vazia e sem `temporary: false`, o Direct Access Grant
    responde `invalid_grant: "Account is not fully set up"` — que na tela vira
    "senha inválida" e manda o time procurar um bug que não existe.
    """
    usuario = next(u for u in REALM["users"] if u.get("username") == "dev@creed.local")

    assert usuario["enabled"] is True
    assert usuario.get("requiredActions") == []
    assert usuario["credentials"][0]["temporary"] is False
    assert set(usuario["realmRoles"]) <= PAPEIS


def test_realm_nao_liga_acao_obrigatoria_por_padrao() -> None:
    """A mesma armadilha do teste acima, mas pela porta do realm.

    `verifyEmail` ou reset de senha ligados anexam ação obrigatória a todo usuário
    novo, e aí `temporary: false` no provisionamento (entrega 3) não salva ninguém.
    Item de review nomeado no `contrato-api.md`; aqui ele para de depender de memória.
    """
    assert REALM["verifyEmail"] is False
    assert REALM["resetPasswordAllowed"] is False
    assert REALM["registrationAllowed"] is False


def test_perfil_nao_exige_nome_para_provisionar() -> None:
    """A armadilha que custou mais caro achar, e que nenhum outro teste pegava.

    O `UserCreate` do contrato manda `{vinculo_id, email, initial_password}` — sem
    nome. O user profile declarativo do Keycloak, porém, nasce exigindo `firstName`
    e `lastName`, e um perfil incompleto dispara `VERIFY_PROFILE` **no login**,
    não na criação. O Direct Access Grant (decisão D1) então responde
    `invalid_grant: "Account is not fully set up"` — que na tela vira "senha
    inválida" para um usuário recém-criado cuja senha está certa.

    Verificado contra o Keycloak 26.0.8: com o perfil padrão, todo usuário
    provisionado só com e-mail fica trancado fora. Quem tem o nome da pessoa é o
    `Participant` no nosso banco; aqui o Keycloak guarda credencial, não cadastro.
    """
    perfil = json.loads(
        REALM["components"]["org.keycloak.userprofile.UserProfileProvider"][0]["config"][
            "kc.user.profile.config"
        ][0]
    )
    obrigatorios = {a["name"] for a in perfil["attributes"] if "required" in a}

    assert "firstName" not in obrigatorios
    assert "lastName" not in obrigatorios


def test_service_account_tem_o_minimo_verificado() -> None:
    """As duas roles que o provisionamento da entrega 3 (decisão D4) exige.

    Verificado contra o Keycloak 26.0.8, tirando uma role por vez do conjunto:

    - `manage-users` — criar e apagar usuário (a compensação da D4). Sem ela,
      `POST /admin/realms/creed/users` responde 403.
    - `view-realm` — **ler a realm role** antes de atribuí-la. Sem ela,
      `GET /admin/realms/creed/roles/gestor` responde 403 e o espelhamento de
      papel morre no meio do provisionamento, com o usuário já criado.

    `view-users` e `query-users` são dispensáveis: `manage-users` já dá leitura,
    e `view-users` é composta — traz `query-users` e `query-groups` de brinde.
    Papel a mais aqui é permissão de admin que ninguém pediu.
    """
    sa = next(
        u for u in REALM["users"] if u.get("serviceAccountClientId") == "creed-backend"
    )

    assert set(sa["clientRoles"]["realm-management"]) == {"manage-users", "view-realm"}


def test_sessao_segue_os_tempos_da_premissa_p010() -> None:
    """P-010: access token de 15 min, refresh de 8 h."""
    assert REALM["accessTokenLifespan"] == 15 * 60
    assert REALM["ssoSessionMaxLifespan"] == 8 * 60 * 60
