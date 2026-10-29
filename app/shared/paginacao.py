"""Envelope de paginação compartilhado (ADR-0004, item 2).

Espelho do `ListaPaginada<T>` do front: os dois lados precisam concordar no
formato, então ele existe uma vez de cada lado e nenhum domínio escreve o seu.
Domínio que lista devolve `PaginaDe[<Entidade>Response]`.
"""

from pydantic import BaseModel


class PaginaDe[T](BaseModel):
    """Uma página de resultados mais o total, que o front usa para paginar."""

    itens: list[T]
    total: int
    pagina: int
    tamanho_pagina: int
