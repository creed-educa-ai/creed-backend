"""Testes de app/shared/validators.py"""

import uuid

import pytest
from pydantic import ValidationError

from app.domains.users.schemas import UserCreate
from app.shared.validators import sem_caractere_de_controle


@pytest.mark.parametrize(
    "texto", ["Pessoa\x00Exemplo", "Pessoa\nExemplo", "Pessoa\tExemplo"]
)
def test_recusa_caractere_de_controle(texto: str) -> None:
    with pytest.raises(ValueError):
        sem_caractere_de_controle(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "Pessoa Exemplo",
        "José da Conceição",
        # Espaço não separável: chega quando alguém cola o nome de outro lugar.
        "Pessoa\xa0Exemplo",
    ],
)
def test_aceita_texto_comum(texto: str) -> None:
    assert sem_caractere_de_controle(texto) == texto


def test_cadastro_de_usuario_usa_a_regra() -> None:
    # users não tem teste de router: a regra é provada no schema de entrada.
    with pytest.raises(ValidationError):
        UserCreate(
            name="Pessoa\x00Exemplo",
            email="pessoa@exemplo.com",
            keycloak_id=uuid.uuid4(),
            link_id=uuid.uuid4(),
        )
