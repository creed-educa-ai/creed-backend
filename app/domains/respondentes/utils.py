"""Funções puras do domínio respondentes.

Puras de propósito (conventions/camadas-do-back.md → "Cálculo puro sai do
service"): sem sessão, sem I/O e sem `settings`. Por isso podem ser usadas tanto
pelo service quanto pelo `schemas.py` na montagem da resposta, e testadas sem
banco.
"""

from datetime import date


def calcular_idade(data_nascimento: date | None, hoje: date | None = None) -> int | None:
    """Idade em anos completos."""
    if data_nascimento is None:
        return None
    referencia = hoje or date.today()
    idade = referencia.year - data_nascimento.year
    if (referencia.month, referencia.day) < (data_nascimento.month, data_nascimento.day):
        idade -= 1
    return idade
