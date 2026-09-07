"""Testes das funções puras do domínio respondentes.

Exemplo de FORMA, vindo do scaffold: é assim que se testa cálculo puro, sem
banco e sem HTTP. Não é cobertura conquistada por task nenhuma, e não prova nada
sobre o resto do domínio.
"""

from datetime import date

import pytest

from app.domains.respondentes.utils import calcular_idade


class TestCalcularIdade:
    def test_retorna_none_sem_data(self) -> None:
        assert calcular_idade(None) is None

    def test_idade_apos_aniversario(self) -> None:
        assert calcular_idade(date(1990, 1, 15), hoje=date(2026, 6, 10)) == 36

    def test_idade_antes_do_aniversario(self) -> None:
        assert calcular_idade(date(1990, 12, 15), hoje=date(2026, 6, 10)) == 35

    def test_idade_no_dia_do_aniversario(self) -> None:
        assert calcular_idade(date(1990, 6, 10), hoje=date(2026, 6, 10)) == 36

    @pytest.mark.parametrize(
        ("nascimento", "hoje", "esperado"),
        [
            (date(2000, 2, 29), date(2026, 2, 28), 25),
            (date(2000, 2, 29), date(2026, 3, 1), 26),
        ],
    )
    def test_ano_bissexto(self, nascimento: date, hoje: date, esperado: int) -> None:
        assert calcular_idade(nascimento, hoje=hoje) == esperado
