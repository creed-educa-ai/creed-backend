"""Testes da leitura de configuração (`app/core/config.py`).

CORS_ORIGINS é o único campo de tipo complexo da Settings. O pydantic-settings
trata campo complexo dando `json.loads` no valor do ambiente ANTES de qualquer
validator — o que faz a lista separada por vírgula do `.env.example` estourar na
leitura da config. O `NoDecode` desliga esse parse; estes testes seguram isso.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


class TestCorsOrigins:
    def test_aceita_lista_separada_por_virgula(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,https://creed.app")

        assert Settings().CORS_ORIGINS == ["http://localhost:5173", "https://creed.app"]

    def test_aceita_origem_unica(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """O formato exato do `.env.example` — o que todo mundo herda no setup."""
        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")

        assert Settings().CORS_ORIGINS == ["http://localhost:5173"]

    def test_descarta_espacos_e_itens_vazios(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ORIGINS", " http://a , ,http://b ,")

        assert Settings().CORS_ORIGINS == ["http://a", "http://b"]

    def test_usa_o_default_quando_a_variavel_nao_existe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        # sem o .env, os campos que não têm default precisam vir do ambiente
        monkeypatch.setenv("POSTGRES_PASSWORD", "irrelevante")
        monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "irrelevante")

        assert Settings(_env_file=None).CORS_ORIGINS == ["http://localhost:5173"]


class TestKeycloak:
    """As settings do Keycloak (CREED-23, entrega 2).

    O que estes testes seguram é a regra do `KEYCLOAK_CLIENT_SECRET` sem default:
    igual ao `POSTGRES_PASSWORD`, a aplicação tem que falhar no boot quando o
    segredo não chega, em vez de subir com o valor conhecido do realm local.
    """

    def test_client_secret_nao_tem_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POSTGRES_PASSWORD", "irrelevante")
        monkeypatch.delenv("KEYCLOAK_CLIENT_SECRET", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_defaults_apontam_para_o_realm_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Os defaults têm que casar com o docker-compose, senão o setup não sobe."""
        monkeypatch.setenv("POSTGRES_PASSWORD", "irrelevante")
        monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "irrelevante")

        settings = Settings(_env_file=None)

        assert settings.KEYCLOAK_SERVER_URL == "http://localhost:8080"
        # Vazio: no local o endereço público é o mesmo do KEYCLOAK_SERVER_URL.
        assert settings.KEYCLOAK_PUBLIC_URL == ""
        assert settings.KEYCLOAK_REALM == "creed"
        assert settings.KEYCLOAK_CLIENT_ID == "creed-backend"

    def test_link_do_convite_vale_72_horas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """P-049. O padrão do Keycloak, 12 h, vence de um dia para o outro."""
        monkeypatch.setenv("POSTGRES_PASSWORD", "irrelevante")
        monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "irrelevante")
        monkeypatch.delenv("KEYCLOAK_INVITE_LIFESPAN_SECONDS", raising=False)

        assert Settings(_env_file=None).KEYCLOAK_INVITE_LIFESPAN_SECONDS == 259200

    def test_link_de_volta_nasce_desligado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """P-051: `FRONTEND_URL` vazia manda o convite sem o link "voltar".

        Vazia, e não `http://localhost:5173`, porque o Keycloak recusa redirect fora
        da lista do client: um ambiente que esquecesse a variável mandaria um link
        para localhost, e pela D7 todo convite falharia.
        """
        monkeypatch.setenv("POSTGRES_PASSWORD", "irrelevante")
        monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "irrelevante")
        monkeypatch.delenv("FRONTEND_URL", raising=False)

        assert Settings(_env_file=None).FRONTEND_URL == ""
