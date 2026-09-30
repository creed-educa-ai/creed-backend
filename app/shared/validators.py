"""Regras de validação de texto usadas pelos schemas de mais de um domínio."""

import unicodedata


def sem_caractere_de_controle(texto: str) -> str:
    """Recusa caracteres de controle (`\\x00`, quebra de linha, tab...) no texto.

    O Postgres não grava `\\x00` em `varchar`: sem esta checagem, o erro sai do
    banco como 500 em vez de 422. Quebra de linha e tab também não fazem sentido
    num nome. Categoria `Cc` do Unicode = caractere de controle.

    Levanta `ValueError`, que o Pydantic transforma em 422 quando a função é
    chamada de um `field_validator`.
    """
    if any(unicodedata.category(letra) == "Cc" for letra in texto):
        raise ValueError("Não pode ter caracteres de controle")
    return texto
