"""Testes da leitura de configuração (`app/core/config.py`).

CORS_ORIGINS é o único campo de tipo complexo da Settings. O pydantic-settings
trata campo complexo dando `json.loads` no valor do ambiente ANTES de qualquer
validator — o que faz a lista separada por vírgula do `.env.example` estourar na
leitura da config. O `NoDecode` desliga esse parse; estes testes seguram isso.
"""

import pytest

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
        # sem o .env, POSTGRES_PASSWORD (que não tem default) precisa vir do ambiente
        monkeypatch.setenv("POSTGRES_PASSWORD", "irrelevante")

        assert Settings(_env_file=None).CORS_ORIGINS == ["http://localhost:5173"]
